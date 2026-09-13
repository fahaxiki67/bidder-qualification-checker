import { formatYuan } from "@/lib/utils";
import type { ReviewResult } from "./types.ts";

export function toMarkdown(result: ReviewResult): string {
  const lines = [
    `# 投标文件离线审查报告`,
    "",
    result.project ? `项目：${result.project}` : "项目：未填写",
    `生成时间：${result.generated_at}`,
    `投标人 ${result.summary.bidder_count} 家 · 文件 ${result.summary.file_count} 份 · 信号 ${result.summary.signal_count} 条`,
    "",
    `> ${result.legal_notice.conclusion}`,
    "",
    "## 投标人报价",
    "",
    "| 投标人 | 主报价（元） | 文件 | 清单项 |",
    "|---|---:|---:|---:|",
  ];
  for (const b of result.bidders) {
    lines.push(
      `| ${b.name} | ${b.primary_quote ? formatYuan(b.primary_quote.value) : "未识别"} | ${b.files.length} | ${b.line_item_count} |`,
    );
  }
  lines.push("", "## 风险信号（全部需人工复核）", "");
  if (!result.signals.length) {
    lines.push("未触发预警信号。这不代表不存在风险，只说明当前资料未命中已启用规则。");
  }
  for (const s of result.signals) {
    lines.push(`### ${s.id ?? ""} ${s.rule_id} ${s.title}（${s.level}）`);
    lines.push("");
    lines.push(`范围：${s.scope}`);
    lines.push("");
    lines.push(s.description);
    lines.push("");
    lines.push(`法律背景：${s.legal_basis}`);
    lines.push("");
    lines.push(`下一步：${s.manual_action}`);
    lines.push("");
  }
  if (result.parse_warnings.length || result.parse_errors.length || result.unsupported_files.length) {
    lines.push("## 解析缺口", "");
    for (const e of result.parse_errors) lines.push(`- 错误 ${e.path}：${e.error}`);
    for (const w of result.parse_warnings) lines.push(`- 提示 ${w.path} ${w.locator}：${w.error}`);
    for (const f of result.unsupported_files) lines.push(`- 未解析 ${f.path}`);
  }
  lines.push("", "自动结论：否。整份结果须人工复核。");
  return lines.join("\n");
}

export function downloadText(filename: string, text: string, mime: string) {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
