export type Status =
  | "PASS"
  | "WARNING"
  | "FAIL"
  | "MANUAL"
  | "NO_DATA"
  | "ERROR"
  | "TIMEOUT"
  | "BLOCKED"
  | "UNKNOWN";

export const STATUS_LABEL: Record<Status, string> = {
  PASS: "未见异常",
  WARNING: "提示关注",
  FAIL: "触发否决条款",
  MANUAL: "待人工核查",
  NO_DATA: "未检索到记录",
  ERROR: "查询失败",
  TIMEOUT: "查询超时",
  BLOCKED: "访问被拦截",
  UNKNOWN: "状态不明",
};

export const NEVER_PASS: Status[] = ["ERROR", "TIMEOUT", "BLOCKED", "MANUAL", "UNKNOWN"];

export type SourceRow = {
  id: string;
  name: string;
  level: string;
  status: Status;
  note: string;
};

export const SOURCES: Omit<SourceRow, "status" | "note">[] = [
  { id: "gsxt", name: "国家企业信用信息公示系统", level: "全国" },
  { id: "creditchina", name: "信用中国", level: "全国" },
  { id: "zxgk", name: "中国执行信息公开网", level: "全国" },
  { id: "mem", name: "应急管理部安全生产信用", level: "全国" },
  { id: "jzsc", name: "全国建筑市场监管平台", level: "全国" },
  { id: "pcczdc", name: "全国破产重整案件信息网", level: "全国" },
  { id: "sc_construction", name: "四川建筑市场监管平台", level: "地区" },
  { id: "gd_construction", name: "广东建筑市场监管平台", level: "地区" },
  { id: "powerchina_ban", name: "中国电建禁入名单", level: "集团" },
];

export type TermId = "条款1" | "条款2" | "条款3" | "条款4";

export type ScenarioId =
  | "clean"
  | "bid_ban"
  | "bid_ban_expired"
  | "revoked"
  | "bankruptcy"
  | "owner_ban"
  | "license_surface_expired"
  | "query_error";

export const SCENARIOS: { id: ScenarioId; label: string }[] = [
  { id: "clean", label: "无异常记录（演示）" },
  { id: "bid_ban", label: "省级限制投标且有效期内（条款1 FAIL）" },
  { id: "bid_ban_expired", label: "限制投标已解除（仅提示）" },
  { id: "revoked", label: "当前吊销营业执照（条款2 FAIL）" },
  { id: "bankruptcy", label: "已宣告破产（条款3 FAIL）" },
  { id: "owner_ban", label: "中国电建集团禁入（条款4 FAIL）" },
  { id: "license_surface_expired", label: "安许表面过期但官方已延期（WARNING）" },
  { id: "query_error", label: "数据源查询失败（ERROR 不算通过）" },
];

export type Finding = {
  term: string;
  title: string;
  status: Status;
  basis: string;
};

export type QualifyInput = {
  project: string;
  company: string;
  uscc: string;
  province: string;
  industry: string;
  ownerGroup: string;
  terms: TermId[];
  scenario: ScenarioId;
  yearsBack: number;
};

export type QualifyResult = {
  overall: Status;
  dataStatus: Status;
  mode: "mock";
  findings: Finding[];
  sources: SourceRow[];
  notice: string;
};

function mergeStatus(a: Status, b: Status): Status {
  const rank: Status[] = ["FAIL", "ERROR", "TIMEOUT", "BLOCKED", "MANUAL", "UNKNOWN", "WARNING", "NO_DATA", "PASS"];
  return rank.indexOf(a) <= rank.indexOf(b) ? a : b;
}

export function runQualify(input: QualifyInput): QualifyResult {
  const sources: SourceRow[] = SOURCES.map((s) => ({
    ...s,
    status: "MANUAL" as Status,
    note: "官方 query_url 尚未人工复核回填，真实查询一律待人工核查，绝不伪造成功。",
  }));
  if (input.scenario === "query_error") {
    sources[1] = { ...sources[1]!, status: "ERROR", note: "演示：信用中国查询失败。失败不得写成无异常。" };
  }

  const findings: Finding[] = [];
  const terms = new Set(input.terms);
  const add = (term: string, title: string, status: Status, basis: string) => {
    if (term.startsWith("条款") && !terms.has(term as TermId) && term !== "§6") return;
    findings.push({ term, title, status, basis });
  };

  switch (input.scenario) {
    case "bid_ban":
      add("条款1", "存在有效期内的限制投标记录", "FAIL", "演示数据：省级限制投标决定仍在有效期。正式判断须核对处罚文书与解除文件。");
      break;
    case "bid_ban_expired":
      add("条款1", "限制投标记录已过有效期", "WARNING", "历史限制已解除，不作为本项目否决；仍建议在报告中留痕。");
      break;
    case "revoked":
      add("条款2", "营业执照被吊销", "FAIL", "演示数据：市场主体登记显示吊销。须以国家企业信用信息公示系统原文为准。");
      break;
    case "bankruptcy":
      add("条款3", "已宣告破产", "FAIL", "演示数据：破产重整案件信息。须核对立案/终结状态。");
      break;
    case "owner_ban":
      add("条款4", "列入招标人集团禁入名单", "FAIL", "演示：中国电建三级禁入有效期内。真实名单只能人工导入后离线评判。");
      break;
    case "license_surface_expired":
      add("§6", "安全生产许可证表面过期", "WARNING", "表面日期过期，但演示数据注明主管部门已办理延期。证照有效期不单独形成本项目否决。");
      break;
    case "query_error":
      add("数据源", "关键数据源查询失败", "ERROR", "查询失败 ≠ 无异常。总体结论不得归约为通过。");
      break;
    default:
      add("演示", "当前演示源未返回否决记录", "NO_DATA", "未检索到记录不等于确认不存在。真实官方源全部仍为待人工核查。");
  }

  let overall: Status = findings.reduce((acc, f) => mergeStatus(acc, f.status), "PASS" as Status);
  const dataStatus = sources.reduce((acc, s) => mergeStatus(acc, s.status), "PASS" as Status);
  if (NEVER_PASS.includes(dataStatus) && overall === "PASS") overall = dataStatus;
  if (input.scenario === "clean") overall = "NO_DATA";
  if (input.scenario === "query_error") overall = "ERROR";
  if (["bid_ban", "revoked", "bankruptcy", "owner_ban"].includes(input.scenario) && findings.some((f) => f.status === "FAIL")) {
    overall = "FAIL";
  }

  return {
    overall,
    dataStatus,
    mode: "mock",
    findings,
    sources,
    notice:
      "本页只跑演示数据。全国官方平台真实自动查询尚未完成：验证码、反自动化令牌、加密响应体均存在。不得把 MANUAL / ERROR 显示成正常。",
  };
}

export function checkUscc(raw: string): { ok: boolean; value: string; message?: string } {
  const value = raw.replace(/\s/g, "").toUpperCase();
  if (!value) return { ok: true, value };
  if (!/^[0-9A-Z]{18}$/.test(value)) return { ok: false, value, message: "统一社会信用代码应为 18 位数字或大写字母" };
  const charset = "0123456789ABCDEFGHJKLMNPQRTUWXY";
  const weights = [1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28];
  let sum = 0;
  for (let i = 0; i < 17; i++) {
    const idx = charset.indexOf(value[i]!);
    if (idx < 0) return { ok: false, value, message: "信用代码含非法字符" };
    sum += idx * weights[i]!;
  }
  const check = charset[(31 - (sum % 31)) % 31];
  if (check !== value[17]) return { ok: false, value, message: "信用代码校验位不正确" };
  return { ok: true, value };
}
