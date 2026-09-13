import * as XLSX from "xlsx";
import { sha256Hex } from "@/lib/utils";
import { parseAmount } from "./amount.ts";
import {
  dedupeItems,
  dedupeQuotes,
  makeQuote,
  metadataFromPairs,
  mergeMetadata,
  quoteKind,
  quoteParseWarnings,
  rowsToQuotesAndItems,
  textQuotes,
} from "./extract.ts";
import {
  MAX_FILE_BYTES,
  MAX_PDF_FILE_BYTES,
  MAX_PDF_PAGES,
  MAX_PDF_TEXT_CHARS,
  MAX_TEXT_FOR_COMPARE,
  SUPPORTED_EXTENSIONS,
  type ParsedFile,
} from "./types.ts";

function extOf(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i).toLowerCase() : "";
}

function decodeBytes(raw: Uint8Array): string {
  const encodings: string[] = ["utf-8", "utf-16le", "gb18030"];
  for (const enc of encodings) {
    try {
      const text = new TextDecoder(enc, { fatal: enc !== "gb18030" }).decode(raw);
      if (enc === "utf-8" && text.includes("\uFFFD") && raw.some((b) => b >= 0x80)) continue;
      return text.replace(/^\uFEFF/, "");
    } catch {
      /* try next */
    }
  }
  return new TextDecoder("utf-8", { fatal: false }).decode(raw);
}

function parseCsv(text: string): unknown[][] {
  const rows: unknown[][] = [];
  let row: string[] = [];
  let cell = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]!;
    if (inQuotes) {
      if (ch === '"' && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (ch === '"') inQuotes = false;
      else cell += ch;
    } else if (ch === '"') inQuotes = true;
    else if (ch === "," || ch === "\t" || ch === ";" || ch === "，") {
      row.push(cell);
      cell = "";
    } else if (ch === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (ch !== "\r") cell += ch;
  }
  if (cell.length || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows.filter((r) => r.some((c) => String(c).trim()));
}

function parseJsonValue(value: unknown, depth: number, nodes: { n: number }, acc: string[], quotes: ReturnType<typeof makeQuote>[], source: string): void {
  if (nodes.n > 100000 || depth > 100) return;
  nodes.n += 1;
  if (value == null) return;
  if (typeof value === "string" || typeof value === "number") {
    acc.push(String(value));
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((v) => parseJsonValue(v, depth + 1, nodes, acc, quotes, source));
    return;
  }
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    for (const [k, v] of Object.entries(obj)) {
      acc.push(`${k}: ${typeof v === "object" ? "" : String(v)}`);
      const kind = quoteKind(k);
      const amountSource = obj.total ?? obj.bid_price ?? obj.amount ?? v;
      const prefer = obj.total ?? obj.bid_price ?? v;
      const amt = parseAmount(prefer);
      if (amt != null && /报价|总价|amount|price|total|控制价/i.test(k)) {
        quotes.push(makeQuote(k, amt, source, k, `${k}=${prefer}`, kind));
      }
      parseJsonValue(v, depth + 1, nodes, acc, quotes, source);
      void amountSource;
    }
  }
}

async function parsePdf(buffer: ArrayBuffer, source: string): Promise<{ text: string; partial: boolean; warning?: string }> {
  const pdfjs = await import("pdfjs-dist");
  const worker = await import("pdfjs-dist/build/pdf.worker.min.mjs?url");
  pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
  const doc = await pdfjs.getDocument({ data: buffer }).promise;
  const pages = Math.min(doc.numPages, MAX_PDF_PAGES);
  const parts: string[] = [];
  let chars = 0;
  for (let i = 1; i <= pages; i++) {
    const page = await doc.getPage(i);
    const content = await page.getTextContent();
    const text = content.items.map((item) => ("str" in item ? item.str : "")).join(" ");
    parts.push(`--- 第${i}页 ---\n${text}`);
    chars += text.length;
    if (chars > MAX_PDF_TEXT_CHARS) break;
  }
  const text = parts.join("\n");
  const partial = doc.numPages > pages || chars > MAX_PDF_TEXT_CHARS || text.replace(/\s/g, "").length < 40;
  const warning = partial
    ? "PDF 仅提取文本层；扫描件无法在浏览器内 OCR，未识别页不参与全文相似比较。"
    : undefined;
  return { text, partial, warning };
}

async function parseDocx(buffer: ArrayBuffer): Promise<string> {
  const mammoth = await import("mammoth");
  const result = await mammoth.extractRawText({ arrayBuffer: buffer });
  return result.value || "";
}

export async function parseFile(file: File, source: string): Promise<ParsedFile> {
  const extension = extOf(file.name);
  const limit = extension === ".pdf" ? MAX_PDF_FILE_BYTES : MAX_FILE_BYTES;
  const empty = async (status: ParsedFile["public"]["parse_status"], error?: string): Promise<ParsedFile> => {
    const buf = await file.arrayBuffer().catch(() => new ArrayBuffer(0));
    return {
      public: {
        path: source,
        extension,
        size_bytes: file.size,
        sha256: buf.byteLength ? await sha256Hex(buf) : "",
        parse_status: status,
      },
      text: "",
      quotes: [],
      items: [],
      metadata: {},
      error,
    };
  };

  if (!(SUPPORTED_EXTENSIONS as readonly string[]).includes(extension)) {
    return empty("UNSUPPORTED", `不支持的文件类型：${extension || "无扩展名"}（当前可解析 txt/md/csv/json/xlsx/xls/pdf/docx）`);
  }
  if (file.size > limit) {
    return empty("ERROR", `文件超过 ${Math.floor(limit / 1024 / 1024)} MB 限制`);
  }

  const buffer = await file.arrayBuffer();
  const digest = await sha256Hex(buffer);
  const raw = new Uint8Array(buffer);
  let text = "";
  let quotes = [] as ReturnType<typeof textQuotes>["quotes"];
  let items = [] as ReturnType<typeof textQuotes>["items"];
  const metadata: ParsedFile["metadata"] = {};
  const warnings: { locator: string; reason: string; raw: string }[] = [];
  let parse_status: ParsedFile["public"]["parse_status"] = "OK";
  let error: string | undefined;

  try {
    if (extension === ".txt" || extension === ".md" || extension === ".csv") {
      text = decodeBytes(raw);
      if (extension === ".csv") {
        const extracted = rowsToQuotesAndItems(parseCsv(text), source);
        quotes = extracted.quotes;
        items = extracted.items;
        mergeMetadata(metadata, extracted.metadata);
      } else {
        const extracted = textQuotes(text, source);
        quotes = extracted.quotes;
        items = extracted.items;
      }
      warnings.push(...quoteParseWarnings(text));
    } else if (extension === ".json") {
      text = decodeBytes(raw);
      try {
        const data = JSON.parse(text) as unknown;
        const acc: string[] = [];
        parseJsonValue(data, 0, { n: 0 }, acc, quotes, source);
        text = acc.join("\n");
        const extracted = textQuotes(text, source);
        quotes = [...quotes, ...extracted.quotes];
        items = extracted.items;
      } catch (err) {
        error = `JSON 解析失败：${err instanceof Error ? err.message : String(err)}`;
        parse_status = "ERROR";
      }
    } else if (extension === ".xlsx" || extension === ".xls") {
      const wb = XLSX.read(buffer, { type: "array", cellDates: true });
      const parts: string[] = [];
      for (const name of wb.SheetNames) {
        const sheet = wb.Sheets[name];
        if (!sheet) continue;
        const rows = XLSX.utils.sheet_to_json<(string | number | boolean | null)[]>(sheet, {
          header: 1,
          raw: true,
          defval: "",
        });
        parts.push(`# ${name}`);
        parts.push(rows.map((r) => r.map((c) => String(c ?? "")).join("\t")).join("\n"));
        const extracted = rowsToQuotesAndItems(rows, `${source} / ${name}`);
        quotes.push(...extracted.quotes);
        items.push(...extracted.items);
        mergeMetadata(metadata, extracted.metadata);
      }
      const props = wb.Props ?? {};
      mergeMetadata(metadata, metadataFromPairs([
        ["author", (props as { Author?: string }).Author ?? ""],
        ["lastModifiedBy", (props as { LastAuthor?: string }).LastAuthor ?? ""],
      ]));
      text = parts.join("\n");
      warnings.push(...quoteParseWarnings(text));
    } else if (extension === ".pdf") {
      const pdf = await parsePdf(buffer, source);
      text = pdf.text;
      if (pdf.partial) {
        parse_status = "PARTIAL";
        if (pdf.warning) warnings.push({ locator: "PDF", reason: pdf.warning, raw: "" });
      }
      const extracted = textQuotes(text, source);
      quotes = extracted.quotes.map((q) => ({ ...q, extraction_method: "text" as const }));
      items = extracted.items;
      warnings.push(...quoteParseWarnings(text));
    } else if (extension === ".docx") {
      text = await parseDocx(buffer);
      const extracted = textQuotes(text, source);
      quotes = extracted.quotes;
      items = extracted.items;
      warnings.push(...quoteParseWarnings(text));
    }
  } catch (err) {
    error = err instanceof Error ? err.message : String(err);
    parse_status = parse_status === "OK" ? "ERROR" : parse_status;
  }

  quotes = dedupeQuotes(quotes);
  items = dedupeItems(items);
  const compare = text.slice(0, MAX_TEXT_FOR_COMPARE);
  const normalized = compare.replace(/\s+/g, "").toLowerCase();
  const publicFile: ParsedFile["public"] = {
    path: source,
    extension,
    size_bytes: file.size,
    sha256: digest,
    normalized_sha256: await sha256Hex(new TextEncoder().encode(normalized)),
    parse_status,
    text_chars: text.length,
    quote_count: quotes.length,
    line_item_count: items.length,
    parse_warnings: warnings.length ? warnings : undefined,
  };
  return { public: publicFile, text: compare, quotes, items, metadata, error };
}

export function bidderNameFromFile(file: File): string {
  const rel = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
  const parts = rel.split(/[/\\]/).filter(Boolean);
  if (parts.length >= 2) return parts[0]!.trim() || "未命名投标人";
  const stem = file.name.replace(/\.[^.]+$/, "");
  if (stem.includes("__")) return stem.split("__")[0]!.trim() || "未命名投标人";
  return "未分组";
}
