import { amountRegex, isAmbiguousDecimal, isForeignCurrency, parseAmount } from "./amount.ts";
import type { LineItem, Quote, QuoteKind } from "./types.ts";

const CJK_SPACE_RE = /(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])/g;
const CONTROL_LABEL_RE = /招标控制价|最高限价|控制价|control(?:\s*price)?|ceiling(?:\s*price)?/i;
const EXPLICIT_TOTAL_LABEL_RE =
  /投标总价|投标报价|总报价|含税报价|不含税报价|报价金额|报价合计|含税总价|不含税总价|合同总价|项目总价|total(?:\s*price)?|bid[_ -]?price/i;
const GENERIC_TOTAL_LABEL_RE = /合计|金额|amount|price/i;
const LABEL_RE =
  /(招标控制价|最高限价|控制价|投标总价|投标报价|总报价|含税报价|不含税报价|报价金额|报价合计|含税总价|不含税总价|合同总价|项目总价|合计|金额|total(?:\s*price)?|bid[_ -]?price|amount|price)/i;
const TOTAL_LABEL_RE =
  /招标控制价|最高限价|控制价|投标总价|投标报价|总报价|含税报价|不含税报价|报价金额|报价合计|含税总价|不含税总价|合同总价|项目总价|合计|金额|total|bid[_ -]?price|amount|price/i;
const NOTE_LINE_RE = /^\s*注\s*[:：]/;
const NEGATIVE_AMOUNT_RE = /(?<![\w.])[-−]\s*\d/;
const ACCOUNT_LABEL_RE =
  /银行账号|保证金账户|保证金账号|开户账号|银行账户|退款账户|bank[_ -]?account|payment[_ -]?account/i;
const ACCOUNT_TOKEN_RE = /(?<![0-9A-Za-z])[0-9][0-9\s-]{7,30}[0-9](?![0-9A-Za-z])/g;

const ITEM_NAME_ALIASES = new Set(["项目名称", "清单名称", "项目", "名称", "name", "item", "description", "清单项目"]);
const ITEM_UNIT_ALIASES = new Set(["单位", "计量单位", "unit", "uom"]);
const ITEM_SPEC_ALIASES = new Set(["规格", "规格型号", "规格特征", "项目特征", "特征", "spec", "specification", "feature"]);
const ITEM_AMOUNT_ALIASES = new Set(["合价", "金额", "小计", "总价", "amount", "total", "合计"]);
const ITEM_UNIT_PRICE_ALIASES = new Set(["单价", "unitprice", "price"]);
const ITEM_QUANTITY_ALIASES = new Set(["数量", "工程量", "quantity", "qty"]);

const FIELD_ALIASES: Record<string, string[]> = {
  author: ["author", "作者", "创建者", "creator", "lastmodifiedby", "最后修改者"],
  machine_id: ["机器码", "制作机器码", "machinecode", "machine_id", "creator_machine"],
  mac: ["mac", "mac地址", "mac_address", "网卡mac", "网卡mac地址"],
  ip: ["ip", "ip地址", "ip_address", "上传ip", "下载ip", "网络地址"],
  disk_serial: ["硬盘序列号", "硬盘号", "diskserial", "disk_serial"],
  certificate: ["数字证书", "电子证书", "certificate", "证书编号", "ca证书"],
  contact: ["联系人", "contact", "contactperson"],
  contact_phone: ["电话", "联系电话", "联系人电话", "phone", "mobile", "手机号"],
  legal_representative: ["法定代表人", "法人", "legalrepresentative", "legal_representative"],
  registered_address: ["注册地址", "注册地", "address", "registeredaddress"],
  project_manager: ["项目经理", "项目负责人", "projectmanager", "project_manager"],
  company_uscc: ["统一社会信用代码", "社会信用代码", "uscc", "creditcode"],
  bank_account: [
    "银行账号", "保证金账户", "保证金账号", "开户账号", "银行账户",
    "退款账户", "bankaccount", "bank_account", "paymentaccount",
  ],
};

const CANONICAL_FIELD = new Map<string, string>();
for (const [field, aliases] of Object.entries(FIELD_ALIASES)) {
  for (const alias of aliases) CANONICAL_FIELD.set(normLabel(alias), field);
}

export function norm(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, "").trim().toLowerCase();
}

export function normLabel(value: unknown): string {
  return String(value ?? "").replace(/[\s_\-]/g, "").toLowerCase();
}

export function maskAccount(value: string): string {
  const text = String(value ?? "").replace(/\s+/g, "");
  if (text.length <= 8) return "*".repeat(text.length);
  return `${text.slice(0, 4)}${"*".repeat(text.length - 8)}${text.slice(-4)}`;
}

export function redactAccountText(value: unknown): string {
  let text = String(value ?? "");
  const replacements: { start: number; end: number; repl: string }[] = [];
  const labelRe = new RegExp(ACCOUNT_LABEL_RE.source, "gi");
  let label: RegExpExecArray | null;
  while ((label = labelRe.exec(text))) {
    const window = text.slice(label.index + label[0].length);
    const tokenRe = new RegExp(ACCOUNT_TOKEN_RE.source, "g");
    let match: RegExpExecArray | null;
    while ((match = tokenRe.exec(window))) {
      const digits = match[0].replace(/[\s-]/g, "");
      if (digits.length >= 9 && digits.length <= 24) {
        const start = label.index + label[0].length + match.index;
        replacements.push({ start, end: start + match[0].length, repl: maskAccount(digits) });
      }
    }
  }
  for (const item of replacements.reverse()) {
    text = text.slice(0, item.start) + item.repl + text.slice(item.end);
  }
  return text;
}

export function fieldName(key: unknown): string | null {
  return CANONICAL_FIELD.get(normLabel(key)) ?? null;
}

export function quoteKind(label: unknown): QuoteKind {
  const text = String(label ?? "");
  if (CONTROL_LABEL_RE.test(text)) return "control";
  if (EXPLICIT_TOTAL_LABEL_RE.test(text)) return text.includes("不含税") ? "untaxed_total" : "explicit_total";
  return "generic_total";
}

export function quoteRank(quote: Quote): number {
  if (quote.kind === "control" || CONTROL_LABEL_RE.test(quote.label)) return -1;
  if (quote.label.includes("不含税")) return 1;
  if (quote.label.includes("含税")) return 4;
  if (EXPLICIT_TOTAL_LABEL_RE.test(quote.label)) return 3;
  return 0;
}

export function makeQuote(
  label: string,
  value: number,
  source: string,
  locator: string,
  raw: unknown,
  kind: QuoteKind = "explicit_total",
): Quote {
  return {
    label: label || "报价",
    value: Math.round(value * 1e6) / 1e6,
    source,
    locator,
    raw: redactAccountText(String(raw).slice(0, 500)),
    kind,
  };
}

export function makeLineItem(
  name: unknown,
  amount: unknown,
  source: string,
  locator: string,
  raw?: unknown,
  unit?: unknown,
  specification?: unknown,
  feature?: unknown,
): LineItem | null {
  const itemName = String(name ?? "").trim();
  const value = parseAmount(amount);
  if (!itemName || value === null || value === 0) return null;
  const unitText = String(unit ?? "").trim();
  const specText = String(specification ?? "").trim() || String(feature ?? "").trim();
  const missing: string[] = [];
  if (!unitText) missing.push("unit");
  if (!specText) missing.push("specification_or_feature");
  const comparison_key = missing.length
    ? null
    : [norm(itemName), norm(unitText), norm(specText)].join("|");
  return {
    name: itemName.slice(0, 300),
    name_key: norm(itemName),
    unit: unitText.slice(0, 100) || null,
    specification: String(specification ?? "").trim().slice(0, 300) || null,
    feature: String(feature ?? "").trim().slice(0, 500) || null,
    comparison_key,
    comparability_status: comparison_key ? "COMPARABLE" : "INSUFFICIENT_DATA",
    comparability_missing: missing,
    amount: Math.round(value * 1e6) / 1e6,
    source,
    locator,
    raw: redactAccountText(String(raw ?? itemName).slice(0, 500)),
  };
}

export function textQuotes(text: string, source: string): { quotes: Quote[]; items: LineItem[] } {
  const quotes: Quote[] = [];
  const items: LineItem[] = [];
  text.split(/\r?\n/).forEach((line, idx) => {
    const index = idx + 1;
    if (!line.trim() || NOTE_LINE_RE.test(line)) return;
    const compact = line.replace(CJK_SPACE_RE, "");
    const labelMatch = LABEL_RE.exec(compact);
    if (labelMatch) {
      const tail = compact.slice(labelMatch.index + labelMatch[0].length);
      const matches = [...tail.matchAll(amountRegex())];
      const candidates = matches.map((m) => parseAmount(m[0]));
      if (matches.length === 1 && candidates[0] != null && !isAmbiguousDecimal(tail)) {
        const label = labelMatch[1] || "报价";
        quotes.push(makeQuote(label, candidates[0], source, `第${index}行`, line, quoteKind(label)));
      }
    }
    if (/[\t|,，;；]/.test(line)) {
      const cells = line.split(/[\t|,，;；]/).map((c) => c.trim());
      const first = cells[0] || "";
      if (cells.length >= 2 && !TOTAL_LABEL_RE.test(first)) {
        const nums = cells.slice(1).map(parseAmount).filter((n): n is number => n != null);
        if (nums.length >= 1 && !/^\d/.test(first.replace(/\s/g, ""))) {
          const item = makeLineItem(first, nums[nums.length - 1], source, `第${index}行`, line);
          if (item) items.push(item);
        }
      }
    }
  });
  return { quotes, items };
}

export function quoteParseWarnings(text: string): { locator: string; reason: string; raw: string }[] {
  const warnings: { locator: string; reason: string; raw: string }[] = [];
  text.split(/\r?\n/).forEach((line, idx) => {
    if (NOTE_LINE_RE.test(line)) return;
    const labelMatch = LABEL_RE.exec(line);
    if (!labelMatch) return;
    const tail = line.slice(labelMatch.index + labelMatch[0].length);
    if (NEGATIVE_AMOUNT_RE.test(tail)) {
      warnings.push({ locator: `第${idx + 1}行`, reason: "报价金额为负值，未纳入报价比较", raw: redactAccountText(line.slice(0, 500)) });
    } else if (isForeignCurrency(tail) && amountRegex().test(tail)) {
      warnings.push({ locator: `第${idx + 1}行`, reason: "报价币种疑似为非人民币，未纳入报价比较", raw: redactAccountText(line.slice(0, 500)) });
    } else if (isAmbiguousDecimal(tail)) {
      warnings.push({ locator: `第${idx + 1}行`, reason: "报价数字分隔格式存在歧义，未纳入报价比较", raw: redactAccountText(line.slice(0, 500)) });
    }
  });
  return warnings;
}

export function metadataFromPairs(pairs: [unknown, unknown][]): Record<string, { key: string; value: string }[]> {
  const out: Record<string, { key: string; value: string }[]> = {};
  for (const [key, value] of pairs) {
    const field = fieldName(key);
    if (!field || value == null || value === "") continue;
    const text = String(value).trim();
    if (!text) continue;
    (out[field] ??= []).push({ key: String(key), value: text.slice(0, 500) });
  }
  return out;
}

export function mergeMetadata(
  target: Record<string, { key: string; value: string }[]>,
  source: Record<string, { key: string; value: string }[]>,
) {
  for (const [field, values] of Object.entries(source)) {
    (target[field] ??= []).push(...values);
  }
}

export function aliasMatches(label: string, alias: string): boolean {
  if (alias === label) return true;
  if (["unit", "item", "项目"].includes(alias) && /price|特征|feature|spec/.test(label)) return false;
  return label.includes(alias);
}

export function columnKind(header: string): "name" | "unit" | "spec" | "amount" | "unit_price" | "qty" | "meta" | null {
  const n = normLabel(header);
  const hit = (aliases: Set<string>) => [...aliases].some((a) => aliasMatches(n, normLabel(a)));
  if (hit(ITEM_NAME_ALIASES)) return "name";
  if (hit(ITEM_UNIT_ALIASES)) return "unit";
  if (hit(ITEM_SPEC_ALIASES)) return "spec";
  if (hit(ITEM_AMOUNT_ALIASES)) return "amount";
  if (hit(ITEM_UNIT_PRICE_ALIASES)) return "unit_price";
  if (hit(ITEM_QUANTITY_ALIASES)) return "qty";
  if (fieldName(header)) return "meta";
  return null;
}

export function rowsToQuotesAndItems(
  rows: unknown[][],
  source: string,
): { quotes: Quote[]; items: LineItem[]; metadata: Record<string, { key: string; value: string }[]> } {
  const quotes: Quote[] = [];
  const items: LineItem[] = [];
  const metadata: Record<string, { key: string; value: string }[]> = {};
  if (!rows.length) return { quotes, items, metadata };
  const header = rows[0]!.map((c) => String(c ?? "").trim());
  const kinds = header.map(columnKind);
  const hasHeader = kinds.some((k) => k === "name" || k === "amount" || k === "meta");
  const start = hasHeader ? 1 : 0;
  if (hasHeader) {
    mergeMetadata(metadata, metadataFromPairs(header.map((h, i) => [h, ""] as [unknown, unknown]).filter((_, i) => kinds[i] === "meta") as [unknown, unknown][]));
  }
  for (let r = start; r < rows.length; r++) {
    const row = rows[r] ?? [];
    const locator = `第${r + 1}行`;
    if (hasHeader) {
      const byKind: Record<string, unknown> = {};
      const metaPairs: [unknown, unknown][] = [];
      header.forEach((h, i) => {
        const k = kinds[i];
        const v = row[i];
        if (k) byKind[k] = v;
        if (k === "meta") metaPairs.push([h, v]);
        if (!k && typeof v === "string" && LABEL_RE.test(String(h))) {
          const amt = parseAmount(v);
          if (amt != null) quotes.push(makeQuote(h, amt, source, locator, `${h}=${v}`, quoteKind(h)));
        }
      });
      mergeMetadata(metadata, metadataFromPairs(metaPairs));
      if (byKind.name != null && byKind.amount != null) {
        const item = makeLineItem(byKind.name, byKind.amount, source, locator, row.join(" | "), byKind.unit, byKind.spec);
        if (item) items.push(item);
      }
      for (let i = 0; i < header.length; i++) {
        const label = header[i] || "";
        if (!LABEL_RE.test(label)) continue;
        const amt = parseAmount(row[i]);
        if (amt != null) quotes.push(makeQuote(label, amt, source, locator, `${label}=${row[i]}`, quoteKind(label)));
      }
    } else {
      const text = row.map((c) => String(c ?? "")).join("\t");
      const extracted = textQuotes(text, source);
      quotes.push(...extracted.quotes.map((q) => ({ ...q, locator })));
      items.push(...extracted.items);
    }
  }
  return { quotes, items, metadata };
}

export function dedupeQuotes(quotes: Quote[]): Quote[] {
  const seen = new Set<string>();
  const out: Quote[] = [];
  for (const q of quotes) {
    const key = `${q.source}|${q.locator}|${q.value}|${q.label}`;
    if (!seen.has(key)) {
      seen.add(key);
      out.push(q);
    }
  }
  return out;
}

export function dedupeItems(items: LineItem[]): LineItem[] {
  const seen = new Set<string>();
  const out: LineItem[] = [];
  for (const item of items) {
    const key = [item.source, item.locator, item.name_key, item.unit, item.specification, item.feature, item.amount].join("|");
    if (!seen.has(key)) {
      seen.add(key);
      out.push(item);
    }
  }
  return out;
}

export function primaryQuote(quotes: Quote[]): Quote | null {
  const candidates = quotes.filter((q) => quoteRank(q) >= 0);
  if (!candidates.length) return null;
  const bestRank = Math.max(...candidates.map(quoteRank));
  let best = candidates.filter((q) => quoteRank(q) === bestRank);
  const textLayer = best.filter((q) => q.extraction_method === "text");
  if (textLayer.length) best = textLayer;
  const values = new Set(best.map((q) => q.value));
  return values.size === 1 ? best[0]! : null;
}

export { CONTROL_LABEL_RE, EXPLICIT_TOTAL_LABEL_RE, GENERIC_TOTAL_LABEL_RE, LABEL_RE };
