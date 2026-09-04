"""PDF 核查报告（P7）：汇总 + 条款结论 + 查询日志 + 证据/复核计数 + 声明。

中文字体使用 reportlab 内置 CID 字体 STSong-Light（无需外部字体文件，Windows/macOS
PDF 阅读器均可显示）。状态用语统一走 report_label——"查询失败"绝不写成"无异常"。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

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


def _styles():
    body = ParagraphStyle("body", fontName=_FONT, fontSize=10.5, leading=16)
    h1 = ParagraphStyle("h1", fontName=_FONT, fontSize=16, leading=22, spaceAfter=6)
    h2 = ParagraphStyle("h2", fontName=_FONT, fontSize=12.5, leading=18,
                        spaceBefore=10, spaceAfter=4)
    small = ParagraphStyle("small", fontName=_FONT, fontSize=9, leading=13,
                           textColor=colors.HexColor("#555555"))
    return body, h1, h2, small


def _table(data, widths=None):
    t = Table(data, colWidths=widths, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFF3F8")),
        ("FONTNAME", (0, 0), (-1, -1), _FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def export_pdf(db_path: str | Path, pc_id: int, out_path: str | Path) -> Path:
    pdfmetrics.registerFont(UnicodeCIDFont(_FONT))
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
            "SELECT source_id, status, query_url, queried_at FROM source_queries "
            "WHERE run_id = ? ORDER BY id", (run["run_id"],))] if run else []
        n_findings = conn.execute(
            "SELECT COUNT(*) FROM findings f JOIN source_queries sq ON f.query_id = sq.id "
            "WHERE sq.run_id = ?", (run["run_id"],)).fetchone()[0] if run else 0
        n_evidence = conn.execute(
            "SELECT COUNT(*) FROM evidence WHERE query_id IN "
            "(SELECT id FROM source_queries WHERE run_id = ?)",
            (run["run_id"],)).fetchone()[0] if run else 0
        n_reviews = conn.execute(
            "SELECT COUNT(*) FROM manual_reviews WHERE run_id = ?",
            (run["run_id"],)).fetchone()[0] if run else 0
    finally:
        conn.close()

    body, h1, h2, small = _styles()
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
        ["核查基准日", project["base_date"]],
        ["总体结论", f'{overall} · {report_label(Status(overall))}' if overall else "尚无完整核查运行"],
        ["业务判断", run["decision_status"] if run else "—"],
        ["数据获取", f'{run["data_status"]} · {report_label(Status(run["data_status"]))}'
         if run and run["data_status"] else "—"],
        ["需人工复核", "是" if run and run["manual_required"] else "否"],
        ["发现/证据/复核", f"{n_findings} 条 / {n_evidence} 份 / {n_reviews} 次"],
        ["批次 run_id", run["run_id"] if run else "—"],
    ]
    story.append(Paragraph("一、核查汇总", h2))
    story.append(_table(summary, widths=[35 * mm, 130 * mm]))

    story.append(Paragraph("二、条款核查结论", h2))
    rule_rows = [["规则", "状态", "结论用语"]]
    for r in rules:
        label = ("不适用（未启用条款）" if r["status"] == "NOT_APPLICABLE"
                 else report_label(Status(r["status"])))
        rule_rows.append([r["rule_id"], r["status"], label])
    story.append(_table(rule_rows, widths=[70 * mm, 30 * mm, 65 * mm]))

    story.append(Paragraph("三、数据源查询日志", h2))
    q_rows = [["数据源", "状态", "结论用语", "查询时间"]]
    for q in queries:
        label = ("不适用（行业/集团不匹配）" if q["status"] == "NOT_APPLICABLE"
                 else report_label(Status(q["status"])))
        q_rows.append([q["source_id"], q["status"], label, q["queried_at"]])
    story.append(_table(q_rows, widths=[40 * mm, 30 * mm, 60 * mm, 35 * mm]))

    story.append(Paragraph("四、状态口径与声明", h2))
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
