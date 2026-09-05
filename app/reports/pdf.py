"""PDF 核查报告（P7）：汇总 + 条款结论及判定依据 + 查询日志 + 发现/证据 + 状态口径与声明。

中文字体使用 reportlab 内置 CID 字体 STSong-Light（无需外部字体文件，Windows/macOS
PDF 阅读器均可显示）。状态用语统一走 report_label——"查询失败"绝不写成"无异常"。

排版纪律（审计整改）：所有单元格一律经 Paragraph 渲染——
1. 长中文（企业名称/项目名/处罚描述）必须自动折行，纯字符串单元格在 reportlab
   Table 里不折行、会横向溢出到页面外被裁掉；
2. 内容来自第三方页面，可能含 & < > 等字符，必须 XML 转义后再进 Paragraph，
   否则 reportlab 解析失败或吞字。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from .. import __version__
from ..core.status import Status, report_label

_FONT = "STSong-Light"
_FONT_READY = False


def _ensure_font() -> None:
    """字体注册幂等：重复导出不得重复注册（reportlab 允许覆盖但无必要）。"""
    global _FONT_READY
    if not _FONT_READY:
        pdfmetrics.registerFont(UnicodeCIDFont(_FONT))
        _FONT_READY = True


def _styles():
    _ensure_font()
    body = ParagraphStyle("body", fontName=_FONT, fontSize=10.5, leading=16)
    h1 = ParagraphStyle("h1", fontName=_FONT, fontSize=16, leading=22, spaceAfter=6)
    h2 = ParagraphStyle("h2", fontName=_FONT, fontSize=12.5, leading=18,
                        spaceBefore=10, spaceAfter=4)
    small = ParagraphStyle("small", fontName=_FONT, fontSize=9, leading=13,
                           textColor=colors.HexColor("#555555"))
    cell = ParagraphStyle("cell", fontName=_FONT, fontSize=9, leading=12.5)
    cell_head = ParagraphStyle("cell_head", parent=cell, fontSize=9.5,
                               textColor=colors.HexColor("#1f2d3d"))
    return body, h1, h2, small, cell, cell_head


def _p(text, style) -> Paragraph:
    """文本 → 可折行、已转义的段落（长文本不再溢出，特殊字符不再破坏解析）。"""
    s = "" if text is None else str(text)
    return Paragraph(escape(s).replace("\n", "<br/>") or "&nbsp;", style)


def _table(rows, widths, cell_style, head_style) -> Table:
    data = [[_p(c, head_style) for c in rows[0]]]
    for r in rows[1:]:
        data.append([_p(c, cell_style) for c in r])
    t = Table(data, colWidths=widths, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFF3F8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _source_provenance(run) -> str:
    """数据来源口径：mock 演示链路绝不能被当成真实官方查询结果使用。"""
    if not run:
        return "尚无完整核查运行"
    if run["scenario"] == "real_sources":
        return "真实官方数据源查询（real_sources）"
    return (f"mock 演示链路（场景 {run['scenario']}）：非真实官方查询，"
            "仅用于流程演示，不得作为核查结论使用")


def _label(status: str) -> str:
    """状态 → 报告用语；NOT_APPLICABLE 不属于九态，不入 Status 枚举。"""
    if status == "NOT_APPLICABLE":
        return "不适用（未启用条款）"
    return report_label(Status(status))


def export_pdf(db_path: str | Path, pc_id: int, out_path: str | Path) -> Path:
    _ensure_font()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        pc = conn.execute("SELECT * FROM project_companies WHERE id = ?", (pc_id,)).fetchone()
        if pc is None:
            raise ValueError(f"project_companies id={pc_id} 不存在")
        run = conn.execute(
            "SELECT * FROM check_runs WHERE project_id = ? AND company_id = ? "
            "AND finished_at IS NOT NULL ORDER BY id DESC LIMIT 1",
            (pc["project_id"], pc["company_id"])).fetchone()
        project = conn.execute("SELECT * FROM projects WHERE id = ?",
                               (pc["project_id"],)).fetchone()
        company = conn.execute("SELECT * FROM companies WHERE id = ?",
                               (pc["company_id"],)).fetchone()
        rules = [dict(r) for r in conn.execute(
            "SELECT rule_id, status, reasons_json FROM rule_results WHERE run_id = ? ORDER BY id",
            (run["run_id"],))] if run else []
        queries = [dict(q) for q in conn.execute(
            "SELECT source_id, status, query_url, queried_at, raw_json FROM source_queries "
            "WHERE run_id = ? ORDER BY id", (run["run_id"],))] if run else []
        findings = [dict(f) for f in conn.execute(
            "SELECT sq.source_id, f.kind, f.grade, f.description FROM findings f "
            "JOIN source_queries sq ON f.query_id = sq.id WHERE sq.run_id = ? ORDER BY f.id",
            (run["run_id"],))] if run else []
        evidences = [dict(e) for e in conn.execute(
            "SELECT id, source_id, sha256, captured_at, key_text FROM evidence "
            "WHERE query_id IN (SELECT id FROM source_queries WHERE run_id = ?) ORDER BY id",
            (run["run_id"],))] if run else []
        n_reviews = conn.execute(
            "SELECT COUNT(*) FROM manual_reviews WHERE run_id = ?",
            (run["run_id"],)).fetchone()[0] if run else 0
    finally:
        conn.close()

    body, h1, h2, small, cell, cell_head = _styles()
    story = []
    story.append(Paragraph("投标人资格核查报告", h1))
    story.append(Paragraph(
        f"bqc {__version__} · 本报告为机器核查结论，'待人工核查/查询失败'绝不代表'无异常'",
        small))
    story.append(Spacer(1, 6 * mm))

    company_disp = company["name"] + (f"（{company['uscc']}）" if company["uscc"] else "")
    overall = run["overall_status"] if run else None
    summary = [
        ["项目", project["name"]],
        ["企业", company_disp],
        ["数据来源", _source_provenance(run)],
        ["核查基准日", project["base_date"]],
        ["近几年范围", f"近 {project['years_back']} 年（自 {_window_start(project)} 起）"],
        ["总体结论", f'{overall} · {report_label(Status(overall))}' if overall else "尚无完整核查运行"],
        ["业务判断", run["decision_status"] if run else "—"],
        ["数据获取", f'{run["data_status"]} · {report_label(Status(run["data_status"]))}'
         if run and run["data_status"] else "—"],
        ["需人工复核", "是" if run and run["manual_required"] else "否"],
        ["发现/证据/复核", f"{len(findings)} 条 / {len(evidences)} 份 / {n_reviews} 次"],
        ["批次 run_id", run["run_id"] if run else "—"],
    ]
    story.append(Paragraph("一、核查汇总", h2))
    story.append(_table(summary, [35 * mm, 139 * mm], cell, cell_head))

    story.append(Paragraph("二、条款核查结论与判定依据", h2))
    rule_rows = [["规则", "状态", "结论用语", "判定依据"]]
    for r in rules:
        reasons = json.loads(r["reasons_json"] or "[]")
        rule_rows.append([r["rule_id"], r["status"], _label(r["status"]), "；".join(reasons)])
    if len(rule_rows) == 1:
        rule_rows.append(["—", "—", "—", "尚无条款结论"])
    story.append(_table(rule_rows, [46 * mm, 22 * mm, 26 * mm, 80 * mm], cell, cell_head))

    story.append(Paragraph("三、数据源查询日志", h2))
    q_rows = [["数据源", "状态", "结论用语", "查询时间", "备注"]]
    for q in queries:
        note = json.loads(q["raw_json"] or "{}").get("note", "")
        q_rows.append([q["source_id"], q["status"], _label(q["status"]), q["queried_at"], note])
    if len(q_rows) == 1:
        q_rows.append(["—", "—", "—", "—", "尚无查询记录"])
    story.append(_table(q_rows, [32 * mm, 24 * mm, 30 * mm, 30 * mm, 58 * mm], cell, cell_head))

    story.append(Paragraph("四、发现明细", h2))
    f_rows = [["数据源", "类型", "等级", "描述"]]
    for f in findings:
        f_rows.append([f["source_id"], f["kind"], f["grade"], f["description"]])
    if len(f_rows) == 1:
        f_rows.append(["—", "—", "—", "本次核查未发现相关记录（NO_DATA ≠ 确认不存在）"])
    story.append(_table(f_rows, [30 * mm, 34 * mm, 14 * mm, 96 * mm], cell, cell_head))

    story.append(Paragraph("五、证据清单（SHA-256，原件存本地证据目录）", h2))
    e_rows = [["id", "数据源", "SHA-256（前 16 位）", "采集时间", "摘要"]]
    for e in evidences:
        e_rows.append([str(e["id"]), e["source_id"], (e["sha256"] or "")[:16],
                       e["captured_at"], e["key_text"] or ""])
    if len(e_rows) == 1:
        e_rows.append(["—", "—", "—", "—", "本次核查无落盘证据（演示链路不落盘证据）"])
    story.append(_table(e_rows, [12 * mm, 32 * mm, 44 * mm, 32 * mm, 54 * mm], cell, cell_head))

    story.append(Paragraph("六、状态口径与声明", h2))
    for line in (
        "ERROR / TIMEOUT / BLOCKED / MANUAL / UNKNOWN 永不自动算作 PASS；"
        "本报告任何位置都不把失败状态表述为'正常/无异常'。",
        "'未查到'（NO_DATA）与'确认不存在'严格区分；C/D 级线索不得作否决结论。",
        "本工具仅做公开信息的自动查询与整理；遇验证码/风控即转人工，不伪造查询成功。",
        "机器结论不替代人工复核与招标文件条款解释；证据原件（SHA-256）存本地证据目录。",
    ):
        story.append(Paragraph(f"· {line}", body))

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(out), pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"投标人资格核查报告 - {company['name']}",
                            author=f"bqc {__version__}")
    doc.build(story)
    return out


def _window_start(project) -> str:
    """核查窗口起始日（近 N 年）：与 Project.window_start 同口径，供报告展示。"""
    from datetime import date

    base = date.fromisoformat(project["base_date"])
    n = int(project["years_back"] or 3)
    try:
        return base.replace(year=base.year - n).isoformat()
    except ValueError:  # 2 月 29 日
        return base.replace(year=base.year - n, day=28).isoformat()
