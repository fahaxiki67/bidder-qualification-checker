import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { parseAmount, relativeDiff } from "./amount.ts";
import { collectSignals } from "./rules.ts";
import { primaryQuote, quoteKind, textQuotes } from "./extract.ts";
import type { Bidder } from "./types.ts";

describe("parseAmount", () => {
  it("parses wan and yuan", () => {
    assert.equal(parseAmount("1.2万元"), 12000);
    assert.equal(parseAmount("10040000"), 10040000);
  });
  it("skips ambiguous 123.456", () => {
    assert.equal(parseAmount("123.456"), null);
  });
  it("skips foreign currency", () => {
    assert.equal(parseAmount("USD 1000"), null);
  });
});

describe("quotes", () => {
  it("reads labeled bid price and control price", () => {
    const { quotes } = textQuotes("投标报价：10040000元\n招标控制价：12000000元", "a.txt");
    assert.equal(quotes.length, 2);
    assert.equal(quoteKind("招标控制价"), "control");
    const primary = primaryQuote(quotes);
    assert.equal(primary?.value, 10040000);
  });
  it("skips 注 lines", () => {
    const { quotes } = textQuotes("注：本表适用于招标控制价 2.0", "a.txt");
    assert.equal(quotes.length, 0);
  });
});

describe("F-01 / F-07", () => {
  function bidder(name: string, value: number): Bidder {
    const q = { label: "投标报价", value, source: name, locator: "1", raw: "", kind: "explicit_total" as const };
    return {
      name,
      files: [],
      quotes: [q],
      primary_quote: q,
      line_items: [],
      line_item_count: 0,
      comparable_line_item_count: 0,
      insufficient_line_item_count: 0,
      metadata: {},
      _internal_files: [],
    };
  }
  it("flags 0.4% as F-01 and 1.5% as F-07", () => {
    const signals = collectSignals([
      bidder("甲", 10_000_000),
      bidder("乙", 10_040_000),
      bidder("丙", 10_150_000),
    ], []);
    assert.ok(signals.some((s) => s.rule_id === "F-01"));
    assert.ok(signals.some((s) => s.rule_id === "F-07"));
    assert.ok(relativeDiff(10_000_000, 10_040_000) <= 0.005);
  });
});
