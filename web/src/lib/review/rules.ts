import { mean, pstdev, relativeDiff, median } from "./amount.ts";
import { maskAccount, norm } from "./extract.ts";
import { THRESHOLDS, type Bidder, type RelationClue, type Signal, type SignalLevel } from "./types.ts";

const RULE_IDS: Record<string, string> = {
  QUOTE_NEAR_MATCH: "F-01",
  QUOTE_LOW_DISPERSION: "F-02",
  QUOTE_OUTLIER: "F-03",
  SYNCHRONIZED_LINE_ITEMS: "F-04",
  QUOTE_ARITHMETIC_PATTERN: "F-05",
  UNIFORM_DISCOUNT_RATE: "F-06",
  QUOTE_NEAR_BAND: "F-07",
  METADATA_MATCH: "E-01",
  PAYMENT_ACCOUNT_MATCH: "E-02",
  TEXT_EXACT_MATCH: "S-01",
  TEXT_HIGH_SIMILARITY: "S-02",
  STRUCTURE_SIMILARITY: "S-03",
  LINE_ITEM_SET_MATCH: "S-04",
  SHARED_TEXT_BLOCKS: "S-05",
  LOCAL_RELATION_CLUE: "P-01",
  PERSON_OVERLAP: "P-02",
  KINSHIP_RELATION: "P-03",
  PERSON_TABLE_OVERLAP: "P-04",
};

const LEGAL: Record<string, string> = {
  QUOTE_NEAR_MATCH: "《招标投标法实施条例》第40条第4项关联线索；相对差异阈值为工具筛选参数",
  QUOTE_LOW_DISPERSION: "《招标投标法实施条例》第40条第4项关联线索；离散度阈值为工具筛选参数",
  QUOTE_OUTLIER: "发改法规规〔2022〕1117号关于异常低价/严重不平衡报价研判的政策背景；不作法定推定",
  SYNCHRONIZED_LINE_ITEMS: "《招标投标法实施条例》第40条第4项关联线索；清单匹配阈值为工具筛选参数",
  QUOTE_ARITHMETIC_PATTERN: "《招标投标法实施条例》第40条第4项关于投标报价呈规律性差异的关联线索",
  UNIFORM_DISCOUNT_RATE: "《招标投标法实施条例》第40条第4项关联线索；控制价口径仍须人工核验",
  QUOTE_NEAR_BAND: "《招标投标法实施条例》第40条第4项关联线索；接近带为工具筛查参数，不构成推定",
  METADATA_MATCH: "《招标投标法实施条例》第40条第1、4项及《电子招标投标办法》电子留痕要求的辅助线索",
  PAYMENT_ACCOUNT_MATCH: "《招标投标法实施条例》第40条第6项关于保证金从同一账户转出的法定边界；资料字段相同不等同转出事实",
  TEXT_EXACT_MATCH: "《招标投标法实施条例》第40条第4项关于投标文件异常一致的关联线索",
  TEXT_HIGH_SIMILARITY: "《招标投标法实施条例》第40条第4项关于投标文件异常一致的关联线索",
  STRUCTURE_SIMILARITY: "《招标投标法实施条例》第40条第4项关于投标文件异常一致的关联线索",
  LINE_ITEM_SET_MATCH: "《招标投标法实施条例》第40条第4项关于投标文件异常一致的关联线索",
  SHARED_TEXT_BLOCKS: "《招标投标法实施条例》第40条第4项关于投标文件异常一致的关联线索",
  LOCAL_RELATION_CLUE: "《招标投标法实施条例》第34、39—40条涉及主体关系的法定边界；本地线索不等同认定",
  PERSON_OVERLAP: "《招标投标法实施条例》第40条第3项关于项目管理成员同一人的法定边界；扩展人员字段仅作线索",
  KINSHIP_RELATION: "《招标投标法实施条例》第34条关于单位负责人同一/控股或管理关系的边界",
  PERSON_TABLE_OVERLAP: "《招标投标法实施条例》第34条第2款；人员任职重合仅作关联线索",
};

const ELECTRONIC_FIELDS = new Set(["author", "machine_id", "mac", "ip", "disk_serial", "certificate"]);
const PERSON_FIELDS = new Set(["legal_representative", "contact", "contact_phone", "project_manager"]);
const KINSHIP_RE = /夫妻|配偶|父子|母子|父女|母女|兄弟|姐妹|兄妹|姐弟|弟兄|亲属|近亲属|直系|堂兄|堂弟|堂姐|堂妹|表兄|表弟|表姐|表妹|叔侄|翁婿|婆媳|连襟|妯娌/;

export const ENABLED_RULE_IDS = [...new Set(Object.values(RULE_IDS))].sort();

function signal(
  code: string,
  title: string,
  scope: string,
  description: string,
  evidence: unknown[],
  level: SignalLevel = "中",
): Signal {
  return {
    code,
    rule_id: RULE_IDS[code],
    kind: code.toLowerCase(),
    level,
    title,
    scope,
    description,
    legal_basis: LEGAL[code] ?? "规则说明中的法规/政策背景；本信号仅供人工复核",
    evidence,
    manual_action: "人工复核原始文件、电子投标平台日志及业务口径后再作判断",
    auto_conclusion: false,
  };
}

function pairwise<T>(values: T[]): [T, T][] {
  const out: [T, T][] = [];
  for (let i = 0; i < values.length; i++) {
    for (let j = i + 1; j < values.length; j++) out.push([values[i]!, values[j]!]);
  }
  return out;
}

function dice(a: string, b: string): number {
  if (!a && !b) return 1;
  if (!a || !b) return 0;
  if (a === b) return 1;
  const grams = (s: string) => {
    const g = new Map<string, number>();
    for (let i = 0; i < s.length - 1; i++) {
      const k = s.slice(i, i + 2);
      g.set(k, (g.get(k) ?? 0) + 1);
    }
    return g;
  };
  const ga = grams(a);
  const gb = grams(b);
  let overlap = 0;
  for (const [k, n] of ga) overlap += Math.min(n, gb.get(k) ?? 0);
  const total = [...ga.values()].reduce((s, n) => s + n, 0) + [...gb.values()].reduce((s, n) => s + n, 0);
  return total ? (2 * overlap) / total : 0;
}

function fnv(text: string): string {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(16);
}

export function collectSignals(bidders: Bidder[], clues: RelationClue[]): Signal[] {
  const signals: Signal[] = [];
  const quotes = Object.fromEntries(
    bidders.filter((b) => b.primary_quote).map((b) => [b.name, b.primary_quote!]),
  );
  const names = Object.keys(quotes);

  for (const [left, right] of pairwise(names)) {
    const a = quotes[left]!;
    const b = quotes[right]!;
    const diff = relativeDiff(a.value, b.value);
    if (diff <= THRESHOLDS.near_quote_relative_diff) {
      signals.push(signal(
        "QUOTE_NEAR_MATCH", "投标总报价高度接近", `${left} ↔ ${right}`,
        `两份投标资料主报价分别为 ${a.value.toFixed(2)} 与 ${b.value.toFixed(2)}，相对差异约 ${(diff * 100).toFixed(2)}%。该数值模式可能有正常报价口径解释，不能单独认定违法。`,
        [a, b], "高",
      ));
    } else if (diff <= THRESHOLDS.near_quote_secondary_relative_diff) {
      signals.push(signal(
        "QUOTE_NEAR_BAND", "投标总报价落入接近带", `${left} ↔ ${right}`,
        `两份投标资料主报价分别为 ${a.value.toFixed(2)} 与 ${b.value.toFixed(2)}，相对差异约 ${(diff * 100).toFixed(2)}%（接近带 0.5%~2%）。须结合清单构成与控制价口径复核。`,
        [a, b], "中",
      ));
    }
  }

  if (names.length >= 3) {
    const numbers = names.map((n) => quotes[n]!.value);
    const average = mean(numbers);
    const cv = average ? pstdev(numbers) / average : 0;
    if (cv <= THRESHOLDS.low_dispersion_cv) {
      signals.push(signal(
        "QUOTE_LOW_DISPERSION", "多家投标报价离散度偏低", "项目全部已识别报价",
        `${numbers.length} 家主报价变异系数约 ${(cv * 100).toFixed(2)}%，低于预警阈值 ${(THRESHOLDS.low_dispersion_cv * 100).toFixed(2)}%。`,
        Object.values(quotes), "中",
      ));
    }
    const middle = median(numbers);
    for (const name of names) {
      const quote = quotes[name]!;
      const deviation = relativeDiff(quote.value, middle);
      if (deviation >= THRESHOLDS.outlier_relative_diff) {
        signals.push(signal(
          "QUOTE_OUTLIER", "单家投标报价相对中位数离群", name,
          `主报价 ${quote.value.toFixed(2)} 与项目报价中位数 ${middle.toFixed(2)} 的相对差异约 ${(deviation * 100).toFixed(2)}%。`,
          [quote], "中",
        ));
      }
    }
    const ordered = [...numbers].sort((a, b) => a - b);
    const diffs = ordered.slice(1).map((v, i) => v - ordered[i]!);
    const ratios = ordered.slice(1).map((v, i) => v / ordered[i]!);
    const md = mean(diffs);
    if (md > 0 && pstdev(diffs) / md <= THRESHOLDS.arithmetic_step_cv) {
      signals.push(signal(
        "QUOTE_ARITHMETIC_PATTERN", "多家投标总报价呈等差排列", "项目全部已识别主报价",
        `${numbers.length} 家主报价排序后相邻差值变异系数约 ${((pstdev(diffs) / md) * 100).toFixed(2)}%。`,
        names.map((n) => ({ bidder: n, value: quotes[n]!.value })), "高",
      ));
    } else {
      const mr = mean(ratios);
      if (mr > 0 && pstdev(ratios) / mr <= THRESHOLDS.geometric_ratio_cv) {
        signals.push(signal(
          "QUOTE_ARITHMETIC_PATTERN", "多家投标总报价呈等比排列", "项目全部已识别主报价",
          `${numbers.length} 家主报价排序后相邻比值变异系数约 ${((pstdev(ratios) / mr) * 100).toFixed(2)}%。`,
          names.map((n) => ({ bidder: n, value: quotes[n]!.value })), "高",
        ));
      }
    }
  }

  const rates: Record<string, { bidder: string; quote: number; control: number; discount_rate: number }> = {};
  for (const bidder of bidders) {
    const primary = bidder.primary_quote;
    if (!primary || primary.kind === "control") continue;
    const controls = bidder.quotes.filter((q) => q.kind === "control");
    const unique = new Set(controls.map((q) => q.value));
    if (unique.size !== 1) continue;
    const control = controls[0]!;
    if (primary.value === control.value) continue;
    rates[bidder.name] = {
      bidder: bidder.name,
      quote: primary.value,
      control: control.value,
      discount_rate: Math.round((1 - primary.value / control.value) * 1e6) / 1e6,
    };
  }
  const rateList = Object.values(rates);
  if (rateList.length >= 2) {
    const band = Math.max(...rateList.map((r) => r.discount_rate)) - Math.min(...rateList.map((r) => r.discount_rate));
    if (band <= THRESHOLDS.discount_rate_band) {
      signals.push(signal(
        "UNIFORM_DISCOUNT_RATE", "多家投标相对控制价的下浮率几乎一致", "项目已识别控制价与主报价",
        `${rateList.length} 家相对控制价下浮率极差约 ${(band * 100).toFixed(4)}%。`,
        rateList, "高",
      ));
    }
  }

  for (const [left, right] of pairwise(bidders.map((b) => b.name))) {
    const a = bidders.find((b) => b.name === left)!;
    const b = bidders.find((b) => b.name === right)!;
    const group = (bidder: Bidder) => {
      const g: Record<string, typeof bidder.line_items> = {};
      for (const item of bidder.line_items) {
        if (item.comparison_key && item.comparability_status === "COMPARABLE") {
          (g[item.comparison_key] ??= []).push(item);
        }
      }
      return g;
    };
    const ga = group(a);
    const gb = group(b);
    const common = Object.keys(ga).filter((k) => ga[k]!.length === 1 && gb[k]?.length === 1);
    if (common.length >= THRESHOLDS.min_common_line_items) {
      const matched = common.filter((k) => relativeDiff(ga[k]![0]!.amount, gb[k]![0]!.amount) <= THRESHOLDS.line_item_match_relative_diff);
      const ratios = common.map((k) => ga[k]![0]!.amount / (gb[k]![0]!.amount || 1));
      const ratioCv = ratios.length >= 3 && mean(ratios) ? pstdev(ratios) / mean(ratios) : null;
      const enough = matched.length >= Math.max(THRESHOLDS.min_common_line_items, Math.ceil(common.length * 0.6));
      const sameScale = ratioCv != null && ratioCv <= THRESHOLDS.low_dispersion_cv;
      if (enough || sameScale) {
        signals.push(signal(
          "SYNCHRONIZED_LINE_ITEMS", "多个清单项报价呈同步或同尺度变化", `${left} ↔ ${right}`,
          `两家共有 ${common.length} 个可比清单项，其中 ${matched.length} 个金额高度接近。`,
          common.slice(0, 12).flatMap((k) => [ga[k]![0], gb[k]![0]]), "高",
        ));
      }
    }
    const setA = new Set(a.line_items.filter((i) => i.comparison_key && i.comparability_status === "COMPARABLE").map((i) => i.comparison_key!));
    const setB = new Set(b.line_items.filter((i) => i.comparison_key && i.comparability_status === "COMPARABLE").map((i) => i.comparison_key!));
    const union = new Set([...setA, ...setB]);
    const inter = [...setA].filter((k) => setB.has(k));
    if (union.size && inter.length / union.size >= THRESHOLDS.line_item_jaccard && inter.length >= THRESHOLDS.min_line_item_set_common) {
      signals.push(signal(
        "LINE_ITEM_SET_MATCH", "清单项目构成高度一致", `${left} ↔ ${right}`,
        `两家清单项目名称集合交并比约 ${((inter.length / union.size) * 100).toFixed(2)}%（共有 ${inter.length} 项）。`,
        [{ bidder: left, item_count: setA.size }, { bidder: right, item_count: setB.size }], "中",
      ));
    }

    const structA = new Set(a.files.map((f) => `${f.extension}|${f.path.split(/[/\\]/).pop()?.toLowerCase()}`));
    const structB = new Set(b.files.map((f) => `${f.extension}|${f.path.split(/[/\\]/).pop()?.toLowerCase()}`));
    const shared = [...structA].filter((x) => structB.has(x));
    const sUnion = new Set([...structA, ...structB]);
    const sScore = sUnion.size ? shared.length / sUnion.size : 0;
    if (sScore >= THRESHOLDS.structure_similarity && shared.length >= 2) {
      signals.push(signal(
        "STRUCTURE_SIMILARITY", "投标文件结构/文件名组合高度相似", `${left} ↔ ${right}`,
        `两家文件结构组合交并比约 ${(sScore * 100).toFixed(2)}%。`,
        [{ bidder: left, files: a.files }, { bidder: right, files: b.files }], "中",
      ));
    }

    let best = 0;
    let bestPair: [{ public: Bidder["_internal_files"][number]["public"] }, { public: Bidder["_internal_files"][number]["public"] }] | null = null;
    for (const fa of a._internal_files) {
      for (const fb of b._internal_files) {
        const minLen = Math.min(fa.text.length, fb.text.length);
        if (minLen < THRESHOLDS.min_text_chars) continue;
        if (fa.public.sha256 && fa.public.sha256 === fb.public.sha256) {
          signals.push(signal(
            "TEXT_EXACT_MATCH", "投标文件字节内容完全一致", `${left} ↔ ${right}`,
            "两份文件 SHA-256 一致，表明字节内容相同；仍需核对模板及合法共享来源。",
            [{ bidder: left, ...fa.public }, { bidder: right, ...fb.public }], "高",
          ));
        } else if (fa.public.normalized_sha256 && fa.public.normalized_sha256 === fb.public.normalized_sha256) {
          signals.push(signal(
            "TEXT_EXACT_MATCH", "投标文件去空白文本内容一致", `${left} ↔ ${right}`,
            "两份文件去除空白后的文本摘要一致。",
            [{ bidder: left, ...fa.public }, { bidder: right, ...fb.public }], "高",
          ));
        } else if (fa.public.extension === fb.public.extension) {
          const score = dice(fa.text, fb.text);
          if (score > best) {
            best = score;
            bestPair = [fa, fb];
          }
        }
      }
    }
    if (bestPair && best >= THRESHOLDS.text_similarity) {
      signals.push(signal(
        "TEXT_HIGH_SIMILARITY", "投标文件文本相似度较高", `${left} ↔ ${right}`,
        `同类型文件文本相似度约 ${(best * 100).toFixed(2)}%。`,
        [{ bidder: left, ...bestPair[0].public }, { bidder: right, ...bestPair[1].public }], "中",
      ));
    }

    const size = THRESHOLDS.shared_block_size;
    const blocks = (bidder: Bidder) => {
      const set = new Set<string>();
      for (const file of bidder._internal_files) {
        const t = file.text.replace(/\s+/g, "").toLowerCase();
        for (let i = 0; i <= t.length - size; i += size) set.add(fnv(t.slice(i, i + size)));
      }
      return set;
    };
    const ba = blocks(a);
    const bb = blocks(b);
    const sharedBlocks = [...ba].filter((x) => bb.has(x));
    const smaller = Math.min(ba.size, bb.size);
    if (smaller && sharedBlocks.length >= THRESHOLDS.min_shared_blocks && sharedBlocks.length / smaller >= THRESHOLDS.shared_block_coverage) {
      signals.push(signal(
        "SHARED_TEXT_BLOCKS", "投标文件存在大段共用文本", `${left} ↔ ${right}`,
        `按 ${size} 字定长分块后，两家文件共有 ${sharedBlocks.length} 个相同文本块，占较小一方约 ${((sharedBlocks.length / smaller) * 100).toFixed(1)}%。`,
        [{ bidder: left, block_count: ba.size }, { bidder: right, block_count: bb.size }], "中",
      ));
    }

    const meta = (bidder: Bidder, fields: Set<string>) => {
      const m: Record<string, Set<string>> = {};
      for (const [field, values] of Object.entries(bidder.metadata)) {
        if (!fields.has(field)) continue;
        m[field] = new Set(values.map((v) => norm(v.value)).filter(Boolean));
      }
      return m;
    };
    const ma = meta(a, ELECTRONIC_FIELDS);
    const mb = meta(b, ELECTRONIC_FIELDS);
    for (const field of Object.keys(ma)) {
      const sharedVals = [...(ma[field] ?? [])].filter((v) => mb[field]?.has(v));
      if (sharedVals.length) {
        signals.push(signal(
          "METADATA_MATCH", "投标资料元数据存在相同值", `${left} ↔ ${right}`,
          `字段 ${field} 出现相同值；单个作者、IP、MAC 相同均不能单独作出违法判断。`,
          [{ bidder: left, field, values: sharedVals }, { bidder: right, field, values: sharedVals }], "中",
        ));
      }
    }
    const pa = meta(a, PERSON_FIELDS);
    const pb = meta(b, PERSON_FIELDS);
    for (const field of Object.keys(pa)) {
      const sharedVals = [...(pa[field] ?? [])].filter((v) => pb[field]?.has(v));
      if (sharedVals.length) {
        signals.push(signal(
          "PERSON_OVERLAP", "投标资料所载人员信息重合", `${left} ↔ ${right}`,
          `人员字段 ${field} 出现相同值，须核对登记信息与人员真实身份。`,
          [{ bidder: left, field }, { bidder: right, field }], "高",
        ));
      }
    }
    const accountsA = new Set((a.metadata.bank_account ?? []).map((v) => norm(v.value)).filter(Boolean));
    const accountsB = new Set((b.metadata.bank_account ?? []).map((v) => norm(v.value)).filter(Boolean));
    const sharedAcc = [...accountsA].filter((v) => accountsB.has(v));
    if (sharedAcc.length) {
      signals.push(signal(
        "PAYMENT_ACCOUNT_MATCH", "投标资料所载银行/保证金账户相同", `${left} ↔ ${right}`,
        "账户字段出现相同账号（证据中已脱敏）；须以银行流水与保证金收退凭证核实。",
        [
          { bidder: left, accounts: sharedAcc.map(maskAccount) },
          { bidder: right, accounts: sharedAcc.map(maskAccount) },
        ], "高",
      ));
    }
  }

  const bidderNames = new Set(bidders.map((b) => b.name));
  for (const clue of clues) {
    const hitA = bidderNames.has(clue.bidder_a);
    const hitB = bidderNames.has(clue.bidder_b);
    if (!hitA && !hitB) continue;
    signals.push(signal(
      "LOCAL_RELATION_CLUE", "本地关联线索命中已扫描投标人", `${clue.bidder_a} ↔ ${clue.bidder_b}`,
      `用户提供的关联线索：${clue.relation || "未注明关系"}。线索本身不构成认定。`,
      [clue], "中",
    ));
    if (KINSHIP_RE.test(clue.relation)) {
      signals.push(signal(
        "KINSHIP_RELATION", "关联线索涉及投标人之间亲属关系", `${clue.bidder_a} ↔ ${clue.bidder_b}`,
        `本地线索描述了亲属关系（${clue.relation}）；须以有权登记资料核实。`,
        [clue], "高",
      ));
    }
  }

  const byPerson: Record<string, Record<string, Set<string>>> = {};
  for (const clue of clues) {
    const raw = clue.raw;
    if (!raw) continue;
    const person = raw["人员"] || raw["姓名"] || raw["name"] || raw["person"];
    const company = raw["企业"] || raw["公司"] || raw["企业名称"] || raw["company"];
    const role = raw["职务"] || raw["职位"] || raw["role"] || "";
    if (!person || !company || person.length < 2) continue;
    if (raw.bidder_a || raw.投标人a) continue;
    ((byPerson[person] ??= {})[company] ??= new Set()).add(role);
  }
  for (const [person, companies] of Object.entries(byPerson)) {
    const hit = Object.keys(companies).filter((c) => bidderNames.has(c));
    if (hit.length >= 2) {
      signals.push(signal(
        "PERSON_TABLE_OVERLAP", "人员长表显示同一人任职多家投标人", person,
        `${person} 同时出现在 ${hit.join("、")} 的任职记录里，须以工商登记、社保等核实。`,
        [{ person, companies: hit }], "高",
      ));
    }
  }

  return signals;
}
