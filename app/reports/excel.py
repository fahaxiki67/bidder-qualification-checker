"""Excel 核查明细表（11 sheet，任务书 §16 表结构一一对应 + 汇总封面）。

数据口径：最新一次【完整】核查运行（check_runs.finished_at 非空），与 Web 结果页一致；
历史批次不混入。全部状态经 report_label 输出——"查询失败"绝不写成"无异常"。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from .. import __version__
from ..core.status import Status, report_label

HEADER_FONT = Font(bold=True)

_SHEET_TITLES = (
    "封面与汇总", "项目信息", "企业信息", "条款核查结论", "数据源查询日志",
    "发现明细", "证据清单", "人工复核记录", "数据源注册表", "状态口径说明", "免责与合规声明",
)


def _connect(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _latest_run(conn, pc_id):
    pc = conn.execute(
        "SELECT * FROM project_companies WHERE id = ?", (pc_id,)).fetchone()
    if pc is None:
        raise ValueError(f"project_companies id={pc_id} 不存在")
    run = conn.execute(
        "SELECT * FROM check_runs WHERE project_id = ? AND company_id = ? "
        "AND finished_at IS NOT NULL ORDER BY id DESC LIMIT 1",
        (pc["project_id"], pc["company_id"])).fetchone()
    project = conn.execute("SELECT * FROM projects WHERE id = ?", (pc["project_id"],)).fetchone()
    company = conn.execute("SELECT * FROM companies WHERE id = ?", (pc["company_id"],)).fetchone()
    return pc, run, project, company


def _write_table(ws, headers, rows):
    ws.append(headers)
    for c in ws[1]:
        c.font = HEADER_FONT
    for r in rows:
        ws.append(list(r))


def export_excel(db_path: str | Path, pc_id: int, out_path: str | Path) -> Path:
    conn = _connect(db_path)
    try:
        pc, run, project, company = _latest_run(conn, pc_id)
        run_id = run["run_id"] if run else None

        rules = [dict(r) for r in conn.execute(
            "SELECT rule_id, scope, status, reasons_json FROM rule_results "
            "WHERE run_id = ? ORDER BY id", (run_id,))] if run_id else []
        queries = [dict(q) for q in conn.execute(
            "SELECT id, source_id, status, query_url, queried_at, raw_json FROM source_queries "
            "WHERE run_id = ? ORDER BY id", (run_id,))] if run_id else []
        findings = [dict(f) for f in conn.execute(
            "SELECT sq.source_id, f.kind, f.grade, f.description, f.start_date, f.end_date, "
            "f.attrs_json FROM findings f JOIN source_queries sq ON f.query_id = sq.id "
            "WHERE sq.run_id = ? ORDER BY f.id", (run_id,))] if run_id else []
        evidences = [dict(e) for e in conn.execute(
            "SELECT id, source_id, url, kind, sha256, captured_at, key_text FROM evidence "
            "WHERE query_id IN (SELECT id FROM source_queries WHERE run_id = ?) ORDER BY id",
            (run_id,))] if run_id else []
        reviews = [dict(r) for r in conn.execute(
            "SELECT reviewer, decision, note, reviewed_at FROM manual_reviews "
            "WHERE run_id = ? ORDER BY id", (run_id,))] if run_id else []
        registry = [dict(r) for r in conn.execute(
            "SELECT id, name, level, province, owner_group, official_home, query_url, "
            "automation_mode, enabled FROM source_registry ORDER BY id")]
    finally:
        conn.close()

    import json as _json
    for r in rules:
        r["reasons"] = _json.loads(r.pop("reasons_json") or "[]")

    wb = Workbook()
    ws = wb.active

    # 1 封面与汇总
    ws.title = _SHEET_TITLES[0]
    rows = [
        ("报告", "投标人资格核查明细表"),
        ("生成版本", f"bqc {__version__}"),
        ("项目", project["name"]),
        ("企业", f'{company["name"]}' + (f'（{company["uscc"]}）' if company["uscc"] else "")),
        ("核查基准日", project["base_date"]),
        ("总体结论", f'{run["overall_status"]} · {report_label(Status(run["overall_status"]))}'
         if run and run["overall_status"] else "尚无完整核查运行"),
        ("业务判断（decision）", run["decision_status"] if run else None),
        ("数据获取（data）", f'{run["data_status"]} · {report_label(Status(run["data_status"]))}'
         if run and run["data_status"] else None),
        ("需人工复核", "是" if run and run["manual_required"] else "否"),
        ("本次批次 run_id", run["run_id"] if run else None),
        ("批次开始/完成", f'{run["started_at"]} / {run["finished_at"]}' if run else None),
        ("声明", "本表为机器核查明细；'查询失败/超时/待人工'绝不代表'无异常'；"
               "'未查到'≠'确认不存在'。"),
    ]
    _write_table(ws, ["项目", "内容"], rows)

    # 2 项目信息
    ws = wb.create_sheet(_SHEET_TITLES[1])
    _write_table(ws, ["id", "名称", "省", "市", "行业", "招标人集团", "基准日", "近几年", "启用条款"],
                 [(project["id"], project["name"], project["province"], project["city"],
                   project["industry"], project["owner_group"], project["base_date"],
                   project["years_back"], project["terms"])])

    # 3 企业信息
    ws = wb.create_sheet(_SHEET_TITLES[2])
    _write_table(ws, ["id", "企业名称", "统一社会信用代码", "注册地省", "本次核查状态", "总体结论"],
                 [(company["id"], company["name"], company["uscc"],
                   company["registered_province"], pc["status"], pc["overall_status"])])

    # 4 条款核查结论
    ws = wb.create_sheet(_SHEET_TITLES[3])
    rule_rows = []
    for r in rules:
        label = ("不适用（未启用条款）" if r["status"] == "NOT_APPLICABLE"
                 else report_label(Status(r["status"])))
        rule_rows.append((r["rule_id"], r.get("scope"), r["status"], label,
                          "；".join(r["reasons"])))
    _write_table(ws, ["规则", "层级", "状态", "结论用语", "判定依据"], rule_rows)

    # 5 数据源查询日志
    ws = wb.create_sheet(_SHEET_TITLES[4])
    q_rows = []
    for q in queries:
        label = ("不适用（行业/集团不匹配）" if q["status"] == "NOT_APPLICABLE"
                 else report_label(Status(q["status"])))
        q_rows.append((q["source_id"], q["status"], label, q["queried_at"],
                       q["query_url"], _json.loads(q["raw_json"] or "{}").get("note", "")))
    _write_table(ws, ["数据源", "状态", "结论用语", "查询时间", "入口", "备注"], q_rows)

    # 6 发现明细
    ws = wb.create_sheet(_SHEET_TITLES[5])
    _write_table(ws, ["数据源", "类型", "证据等级", "描述", "起始日", "截止日", "属性"],
                 [(f["source_id"], f["kind"], f["grade"], f["description"],
                   f["start_date"], f["end_date"], f["attrs_json"]) for f in findings])

    # 7 证据清单
    ws = wb.create_sheet(_SHEET_TITLES[6])
    _write_table(ws, ["id", "数据源", "URL", "类型", "SHA-256", "采集时间", "摘要"],
                 [(e["id"], e["source_id"], e["url"], e["kind"], e["sha256"],
                   e["captured_at"], e["key_text"]) for e in evidences])

    # 8 人工复核记录
    ws = wb.create_sheet(_SHEET_TITLES[7])
    _write_table(ws, ["复核人", "结论", "备注", "时间"],
                 [(r["reviewer"], r["decision"], r["note"], r["reviewed_at"]) for r in reviews])

    # 9 数据源注册表
    ws = wb.create_sheet(_SHEET_TITLES[8])
    _write_table(ws, ["id", "名称", "层级", "省", "集团", "官方入口", "查询接口",
                      "自动化模式", "启用"],
                 [(r["id"], r["name"], r["level"], r["province"], r["owner_group"],
                   r["official_home"], r["query_url"], r["automation_mode"],
                   "是" if r["enabled"] else "否") for r in registry])

    # 10 状态口径说明（红线：失败绝不写成无异常）
    ws = wb.create_sheet(_SHEET_TITLES[9])
    legend = [
        ("PASS", report_label(Status.PASS), "查询成功且未发现触发记录"),
        ("WARNING", report_label(Status.WARNING), "发现风险，不足以否决"),
        ("FAIL", report_label(Status.FAIL), "存在 A/B 级官方证据触发否决条款"),
        ("MANUAL", report_label(Status.MANUAL), "需人工验证码/登录/复核——不是正常"),
        ("NO_DATA", report_label(Status.NO_DATA), "查询成功但未检索到记录——不是'确认不存在'"),
        ("ERROR", report_label(Status.ERROR), "查询失败——绝不是'无异常'"),
        ("TIMEOUT", report_label(Status.TIMEOUT), "查询超时——绝不是'无异常'"),
        ("BLOCKED", report_label(Status.BLOCKED), "访问被限制——绝不是'无异常'"),
        ("UNKNOWN", report_label(Status.UNKNOWN), "证据不足无法确认——绝不是'正常'"),
        ("NOT_APPLICABLE", "不适用", "数据源与本项目行业/集团不匹配，未查询（不是查询结果）"),
    ]
    _write_table(ws, ["状态", "报告用语", "含义"], legend)
    ws.append([])
    ws.append(["硬规则", "ERROR / TIMEOUT / BLOCKED / MANUAL / UNKNOWN 永不自动算作 PASS；"
               "本表任何单元格都不把失败状态表述为'正常/无异常'。"])

    # 11 免责与合规声明
    ws = wb.create_sheet(_SHEET_TITLES[10])
    _write_table(ws, ["声明"], [
        ("本工具仅做公开信息的自动查询与整理，不破解验证码、不绕过反自动化、不伪造身份。"),
        ("'未查到'与'确认不存在'严格区分；机器结论不替代人工复核与招标文件条款解释。"),
        ("遇到 MANUAL/ERROR/TIMEOUT/BLOCKED/UNKNOWN 状态的，必须人工核实后方可使用本表结论。"),
        ("本表不含任何企业内部受限名单、用户查询记录与登录凭证；证据原件存本地证据目录。"),
    ])

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out
