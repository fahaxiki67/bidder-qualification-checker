const AMOUNT_RE =
  /(?<![\w.])[-+]?(?:(?:\d{1,3}(?:[.,，]\d{3})+)(?:[.,，]\d+)?|\d+(?:[.,，]\d+)?)(?:\s*(?:亿元|亿|万元|万|元))?(?![\w.,])/gi;
const AMBIGUOUS_DECIMAL_RE = /(?<![\w.,，])\d{1,3}\.\d{3}(?!\d)/;
const FOREIGN_CURRENCY_RE =
  /(?:[$€£]|\b(?:usd|eur|gbp|jpy|hkd|aud|cad|sgd|krw|inr|rub)\b|美元|欧元|英镑|日元|港币|港元|澳元|加元|新加坡元|韩元|卢布)/i;

export function relativeDiff(a: number, b: number): number {
  return Math.abs(a - b) / Math.max(Math.abs(a), Math.abs(b), 1);
}

export function mean(values: number[]): number {
  return values.reduce((s, v) => s + v, 0) / values.length;
}

export function pstdev(values: number[]): number {
  if (values.length === 0) return 0;
  const m = mean(values);
  const variance = values.reduce((s, v) => s + (v - m) ** 2, 0) / values.length;
  return Math.sqrt(variance);
}

export function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2;
}

export function parseAmount(value: unknown): number | null {
  if (value === null || value === undefined || typeof value === "boolean") return null;
  if (typeof value === "object") return null;
  if (typeof value === "number") {
    return Number.isFinite(value) && value >= 0 ? value : null;
  }
  let text = String(value).trim();
  if (FOREIGN_CURRENCY_RE.test(text)) return null;
  text = text.replace(/￥|¥|人民币/g, "");
  AMOUNT_RE.lastIndex = 0;
  const match = AMOUNT_RE.exec(text);
  if (!match) return null;
  let token = match[0].replace(/\s+/g, "");
  let multiplier = 1;
  for (const [suffix, factor] of [
    ["亿元", 100_000_000],
    ["亿", 100_000_000],
    ["万元", 10_000],
    ["万", 10_000],
    ["元", 1],
  ] as const) {
    if (token.toLowerCase().endsWith(suffix)) {
      token = token.slice(0, -suffix.length);
      multiplier = factor;
      break;
    }
  }
  const sign = token.startsWith("-") ? "-" : "";
  const unsigned = token.replace(/^[+-]/, "");
  const separators = [...unsigned]
    .map((ch, i) => (".，,".includes(ch) ? i : -1))
    .filter((i) => i >= 0);
  let normalized: string;
  if (separators.length) {
    const last = separators[separators.length - 1]!;
    const lastSeparator = unsigned[last]!;
    const fraction = unsigned.slice(last + 1);
    if (unsigned.includes(".") && (unsigned.includes(",") || unsigned.includes("，"))) {
      const integer = unsigned.slice(0, last).replace(/[.,，]/g, "");
      normalized = `${sign}${integer}.${fraction}`;
    } else if (
      separators.length > 1 &&
      new Set(separators.map((i) => unsigned[i])).size === 1 &&
      fraction.length === 3 &&
      unsigned.split(/[.,，]/).slice(1).every((part) => part.length === 3)
    ) {
      normalized = sign + unsigned.replace(/[.,，]/g, "");
    } else if (separators.length > 1) {
      const integer = unsigned.slice(0, last).replace(/[.,，]/g, "");
      normalized = `${sign}${integer}.${fraction}`;
    } else if ((lastSeparator === "," || lastSeparator === "，") && fraction.length === 3) {
      normalized = sign + unsigned.replace(lastSeparator, "");
    } else if (lastSeparator === "." && fraction.length === 3 && !unsigned.startsWith("0")) {
      return null;
    } else {
      normalized = `${sign}${unsigned.slice(0, last).replace(/[,，]/g, "")}.${fraction}`;
    }
  } else {
    normalized = sign + unsigned;
  }
  const number = Number(normalized) * multiplier;
  return Number.isFinite(number) && number >= 0 ? number : null;
}

export function amountRegex(): RegExp {
  return new RegExp(AMOUNT_RE.source, "gi");
}

export function isAmbiguousDecimal(text: string): boolean {
  return AMBIGUOUS_DECIMAL_RE.test(text);
}

export function isForeignCurrency(text: string): boolean {
  return FOREIGN_CURRENCY_RE.test(text);
}
