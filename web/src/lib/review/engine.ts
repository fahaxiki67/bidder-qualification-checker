import { bidderNameFromFile, parseFile } from "./parse.ts";
import { collectSignals, ENABLED_RULE_IDS } from "./rules.ts";
import { dedupeItems, dedupeQuotes, mergeMetadata, primaryQuote } from "./extract.ts";
import { fieldName, normLabel } from "./extract.ts";
import {
  MAX_INPUT_FILES,
  SUPPORTED_EXTENSIONS,
  THRESHOLDS,
  type Bidder,
  type RelationClue,
  type ReviewResult,
} from "./types.ts";
import { relativePath } from "@/lib/utils";

export type IncomingFile = {
  file: File;
  bidder: string;
};

function parseRelationsText(text: string, source: string): RelationClue[] {
  const clues: RelationClue[] = [];
  const trimmed = text.trim();
  if (!trimmed) return clues;
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      const data = JSON.parse(trimmed) as unknown;
      const rows = Array.isArray(data) ? data : [data];
      for (const [i, row] of rows.entries()) {
        if (!row || typeof row !== "object") continue;
        const rec = row as Record<string, unknown>;
        const str = (keys: string[]) => {
          for (const k of Object.keys(rec)) {
            if (keys.includes(normLabel(k))) return String(rec[k] ?? "").trim();
          }
          return "";
        };
        clues.push({
          bidder_a: str(["biddera", "companya", "partya", "投标人a", "企业a", "甲方", "namea"]),
          bidder_b: str(["bidderb", "companyb", "partyb", "投标人b", "企业b", "乙方", "nameb"]),
          relation: str(["relation", "关系", "备注"]),
          source,
          row: i + 1,
          raw: Object.fromEntries(Object.entries(rec).map(([k, v]) => [k, String(v ?? "")])),
        });
      }
      return clues;
    } catch {
      /* fall through to csv */
    }
  }
  const lines = trimmed.split(/\r?\n/).filter((l) => l.trim());
  if (!lines.length) return clues;
  const headers = lines[0]!.split(/[,，\t;；]/).map((h) => h.trim());
  for (let i = 1; i < lines.length; i++) {
    const cells = lines[i]!.split(/[,，\t;；]/);
    const rec: Record<string, string> = {};
    headers.forEach((h, idx) => {
      rec[h] = (cells[idx] ?? "").trim();
    });
    const pick = (aliases: string[]) => {
      for (const [k, v] of Object.entries(rec)) {
        if (aliases.includes(normLabel(k))) return v;
      }
      return "";
    };
    clues.push({
      bidder_a: pick(["biddera", "companya", "投标人a", "企业a", "甲方"]),
      bidder_b: pick(["bidderb", "companyb", "投标人b", "企业b", "乙方"]),
      relation: pick(["relation", "关系", "备注"]),
      source,
      row: i + 1,
      raw: rec,
    });
  }
  void fieldName;
  return clues;
}

export async function reviewFiles(
  incoming: IncomingFile[],
  options: { project?: string; relationsText?: string; relationsName?: string } = {},
): Promise<ReviewResult> {
  const files = incoming.slice(0, MAX_INPUT_FILES);
  const grouped = new Map<string, IncomingFile[]>();
  for (const item of files) {
    const name = item.bidder.trim() || bidderNameFromFile(item.file);
    grouped.set(name, [...(grouped.get(name) ?? []), item]);
  }

  const parseErrors: ReviewResult["parse_errors"] = [];
  const parseWarnings: ReviewResult["parse_warnings"] = [];
  const unsupported: ReviewResult["unsupported_files"] = [];
  const bidders: Bidder[] = [];

  for (const name of [...grouped.keys()].sort((a, b) => a.localeCompare(b, "zh-CN"))) {
    const publicFiles = [];
    const internal = [];
    let quotes = [] as Bidder["quotes"];
    let items = [] as Bidder["line_items"];
    const metadata: Bidder["metadata"] = {};
    for (const item of grouped.get(name) ?? []) {
      const source = relativePath(item.file);
      const parsed = await parseFile(item.file, source);
      publicFiles.push(parsed.public);
      for (const w of parsed.public.parse_warnings ?? []) {
        parseWarnings.push({ path: source, bidder: name, locator: w.locator, error: w.reason, raw: w.raw });
      }
      if (parsed.public.parse_status === "UNSUPPORTED") unsupported.push(parsed.public);
      if (parsed.error && parsed.public.parse_status !== "UNSUPPORTED") {
        parseErrors.push({ path: source, bidder: name, error: parsed.error });
      }
      if (parsed.public.parse_status === "OK" || parsed.public.parse_status === "PARTIAL") {
        if (parsed.public.parse_status === "OK") {
          internal.push({ public: parsed.public, text: parsed.text });
        }
        quotes.push(...parsed.quotes);
        items.push(...parsed.items);
        mergeMetadata(metadata, parsed.metadata);
      }
    }
    quotes = dedupeQuotes(quotes);
    items = dedupeItems(items);
    bidders.push({
      name,
      files: publicFiles,
      quotes,
      primary_quote: primaryQuote(quotes),
      line_items: items,
      line_item_count: items.length,
      comparable_line_item_count: items.filter((i) => i.comparability_status === "COMPARABLE").length,
      insufficient_line_item_count: items.filter((i) => i.comparability_status !== "COMPARABLE").length,
      metadata,
      _internal_files: internal,
    });
  }

  const clues = options.relationsText
    ? parseRelationsText(options.relationsText, options.relationsName || "relations")
    : [];
  const signals = collectSignals(bidders, clues);
  signals.forEach((s, i) => {
    s.id = `S${String(i + 1).padStart(3, "0")}`;
  });

  const publicBidders = bidders.map((b) => {
    const { _internal_files, ...rest } = b;
    void _internal_files;
    return {
      ...rest,
      metadata: Object.fromEntries(
        Object.entries(rest.metadata).filter(([field]) => field !== "bank_account"),
      ),
    };
  });

  return {
    product: "投标审查器",
    review_type: "offline_multi_bidder_file_review",
    project: options.project?.trim() || "",
    generated_at: new Date().toISOString(),
    config: {
      supported_extensions: [...SUPPORTED_EXTENSIONS],
      thresholds: THRESHOLDS,
      enabled_rule_ids: ENABLED_RULE_IDS,
    },
    legal_notice: {
      conclusion: "仅输出风险预警和人工复核线索，不构成串通投标、违法、资格不合格或投标无效认定。",
      scope: "文件仅在本机浏览器内存中解析，不上传、不联网、不修改原文件。检测结果受资料完整性、版本和口径影响。",
    },
    bidders: publicBidders,
    signals,
    relation_clues: clues,
    unsupported_files: unsupported,
    parse_errors: parseErrors,
    parse_warnings: parseWarnings,
    summary: {
      bidder_count: bidders.length,
      file_count: bidders.reduce((s, b) => s + b.files.length, 0),
      parsed_file_count: bidders.reduce((s, b) => s + b.files.filter((f) => f.parse_status === "OK").length, 0),
      partial_file_count: bidders.reduce((s, b) => s + b.files.filter((f) => f.parse_status === "PARTIAL").length, 0),
      quote_count: bidders.reduce((s, b) => s + b.quotes.length, 0),
      signal_count: signals.length,
      high_signal_count: signals.filter((s) => s.level === "高").length,
      unsupported_file_count: unsupported.length,
      parse_error_count: parseErrors.length,
    },
    auto_conclusion: false,
    manual_review_required: true,
  };
}

export { bidderNameFromFile };
