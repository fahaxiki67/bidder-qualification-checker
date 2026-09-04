"""本地 Web UI 服务器：项目创建 → 企业录入 → mock 核查 → 结果与证据入口。

仅监听 127.0.0.1。数据库路径可用环境变量 BQC_DB 覆盖（默认 当前工作目录/data/bqc.sqlite3）。
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .. import __version__
from ..core.db import connect, init_db
from ..core.evidence import evidence_dir_for
from ..core.runner import run_check
from ..core.status import Status, report_label

# 数据库默认落在当前工作目录 data/（与 CLI init-db 默认一致），
# 安装版不再往 site-packages 写数据。
DB_PATH = Path(os.environ.get("BQC_DB") or Path("data/bqc.sqlite3"))
init_db(DB_PATH)

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
BADGE = {
    Status.FAIL.value: "badge-fail",
    Status.WARNING.value: "badge-warn",
    Status.MANUAL.value: "badge-warn",
    Status.UNKNOWN.value: "badge-warn",
    Status.ERROR.value: "badge-err",
    Status.TIMEOUT.value: "badge-err",
    Status.BLOCKED.value: "badge-err",
    Status.NO_DATA.value: "badge-muted",
    Status.PASS.value: "badge-ok",
}

app = FastAPI(title="投标人资格智能核查系统", version=__version__)


@app.get("/")
def index(request: Request):
    return TEMPLATES.TemplateResponse(
        request, "index.html",
        {"today": date.today().isoformat(), "version": __version__},
    )


@app.post("/projects")
def create_and_run(
    project_name: str = Form(...),
    province: str = Form(""),
    industry: str = Form(""),
    owner_group: str = Form(""),
    base_date: str = Form(""),
    years_back: int = Form(3),
    company_name: str = Form(...),
    uscc: str = Form(""),
    registered_province: str = Form(""),
    scenario: str = Form("clean"),
    terms: list[str] = Form([]),   # 本项目启用的资格条款（结构化勾选，P0.5 §八）
):
    if not base_date:
        base_date = date.today().isoformat()
    try:
        base = date.fromisoformat(base_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="核查基准日格式应为 YYYY-MM-DD")

    conn = connect(DB_PATH)
    try:
        cur = conn.execute(
            "INSERT INTO projects (name, province, industry, owner_group, base_date, years_back, terms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_name, province or None, industry or None, owner_group or None,
             base.isoformat(), years_back,
             ",".join(t for t in terms if t) or None),
        )
        project_id = cur.lastrowid
        company_id = None
        if uscc:
            row = conn.execute(
                "SELECT id FROM companies WHERE uscc = ?", (uscc,)
            ).fetchone()
            company_id = row[0] if row else None
        if company_id is None:
            cur = conn.execute(
                "INSERT INTO companies (name, uscc, registered_province) VALUES (?, ?, ?)",
                (company_name, uscc or None, registered_province or None),
            )
            company_id = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO project_companies (project_id, company_id, status) "
            "VALUES (?, ?, 'running')",
            (project_id, company_id),
        )
        pc_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    run_check(DB_PATH, pc_id, scenario=scenario)
    return RedirectResponse(f"/checks/{pc_id}", status_code=303)


def _load_result(pc_id: int):
    conn = connect(DB_PATH)
    conn.row_factory = __import__("sqlite3").Row
    try:
        pc = conn.execute(
            "SELECT project_id, company_id, overall_status, status FROM project_companies WHERE id = ?",
            (pc_id,),
        ).fetchone()
        if pc is None:
            return None
        # 只取最新一次【完整】运行（P0.5 §五）：历史批次保留可溯，但不混入当前展示
        run = conn.execute(
            "SELECT run_id, scenario, decision_status, data_status, manual_required, "
            "overall_status, started_at, finished_at FROM check_runs "
            "WHERE project_id = ? AND company_id = ? AND finished_at IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (pc["project_id"], pc["company_id"]),
        ).fetchone()
        run_id = run["run_id"] if run else None
        project = conn.execute(
            "SELECT name, province, industry, owner_group, base_date FROM projects WHERE id = ?",
            (pc["project_id"],),
        ).fetchone()
        company = conn.execute(
            "SELECT name, uscc, registered_province FROM companies WHERE id = ?",
            (pc["company_id"],),
        ).fetchone()
        rules = [
            dict(r) for r in conn.execute(
                "SELECT rule_id, status, reasons_json FROM rule_results "
                "WHERE project_id = ? AND company_id = ? AND run_id = ? ORDER BY id",
                (pc["project_id"], pc["company_id"], run_id),
            ).fetchall()
        ] if run_id else []
        queries = [
            dict(q) for q in conn.execute(
                "SELECT id, source_id, status, queried_at, query_url FROM source_queries "
                "WHERE project_id = ? AND company_id = ? AND run_id = ? ORDER BY id",
                (pc["project_id"], pc["company_id"], run_id),
            ).fetchall()
        ] if run_id else []
        ev_by_query: dict[int, list[dict]] = {}
        reviews: list[dict] = []
        if run_id:
            for ev in conn.execute(
                "SELECT id, query_id, source_id, kind, sha256, captured_at, key_text "
                "FROM evidence WHERE query_id IN (SELECT id FROM source_queries WHERE run_id = ?) "
                "ORDER BY id", (run_id,)).fetchall():
                ev_by_query.setdefault(ev["query_id"], []).append(dict(ev))
            reviews = [dict(r) for r in conn.execute(
                "SELECT mr.query_id, mr.reviewer, mr.decision, mr.note, mr.reviewed_at "
                "FROM manual_reviews mr WHERE mr.run_id = ? ORDER BY mr.id", (run_id,)).fetchall()]
        for q in queries:
            q["evidence"] = ev_by_query.get(q["id"], [])
        import json
        for r in rules:
            r["reasons"] = json.loads(r.pop("reasons_json") or "[]")
        return {"pc": dict(pc), "project": dict(project), "company": dict(company),
                "rules": rules, "queries": queries, "reviews": reviews,
                "run": dict(run) if run else None}
    finally:
        conn.close()


@app.get("/checks/{pc_id}")
def result(request: Request, pc_id: int):
    data = _load_result(pc_id)
    if data is None:
        raise HTTPException(status_code=404, detail="核查记录不存在")
    import json
    for r in data["rules"]:
        r["badge"] = BADGE.get(r["status"], "badge-muted")
        if r["status"] == "NOT_APPLICABLE":
            r["label"] = "不适用（本项目未启用该条款）"
        else:
            r["label"] = report_label(Status(r["status"]))
    run = data["run"]
    overall = run["overall_status"] if run else None
    data_status = run["data_status"] if run else None
    manual_required = bool(run["manual_required"]) if run else False
    return TEMPLATES.TemplateResponse(
        request, "result.html",
        {
            "d": data, "overall": overall,
            "overall_label": report_label(Status(overall)) if overall else "待核查",
            "overall_badge": BADGE.get(overall, "badge-muted"),
            "data_status": data_status,
            "data_label": report_label(Status(data_status)) if data_status else None,
            "data_badge": BADGE.get(data_status, "badge-muted"),
            "manual_required": manual_required,
            "evidence_total": sum(len(q["evidence"]) for q in data["queries"]),
            "version": __version__,
        },
    )


@app.get("/evidence/{evidence_id}")
def view_evidence(evidence_id: int):
    """证据原文查看（仅本地 UI）。路径必须落在证据目录内，防目录穿越。"""
    conn = connect(DB_PATH)
    conn.row_factory = __import__("sqlite3").Row
    try:
        row = conn.execute(
            "SELECT file_path, sha256 FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="证据不存在")
    fp = Path(row["file_path"])
    allowed_root = (evidence_dir_for(DB_PATH)).resolve()
    if not str(fp.resolve()).startswith(str(allowed_root)):
        raise HTTPException(status_code=400, detail="证据路径非法")
    if not fp.is_file():
        raise HTTPException(status_code=404, detail="证据文件缺失（可运行哈希校验定位）")
    return PlainTextResponse(fp.read_text(encoding="utf-8", errors="replace"))


@app.post("/checks/{pc_id}/review")
def submit_review(pc_id: int, query_id: int = Form(...), reviewer: str = Form(...),
                  decision: str = Form(...), note: str = Form("")):
    """人工复核：结论是审计记录，不自动改判机器结论（P6 人工复核流）。"""
    data = _load_result(pc_id)
    if data is None or not data["run"]:
        raise HTTPException(status_code=404, detail="核查记录不存在")
    valid = {q["id"] for q in data["queries"]}
    if query_id not in valid:
        raise HTTPException(status_code=400, detail="query_id 不属于本次核查")
    if decision not in ("确认无误", "记录非本企业", "证据不足再查", "其他（见备注）"):
        raise HTTPException(status_code=400, detail="decision 非法")
    conn = connect(DB_PATH)
    try:
        conn.execute(
            "INSERT INTO manual_reviews (query_id, run_id, reviewer, decision, note) "
            "VALUES (?, ?, ?, ?, ?)",
            (query_id, data["run"]["run_id"], reviewer.strip(), decision, note.strip()),
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(f"/checks/{pc_id}", status_code=303)


@app.post("/checks/{pc_id}/run")
def rerun(pc_id: int, scenario: str = Form("clean")):
    run_check(DB_PATH, pc_id, scenario=scenario)
    return RedirectResponse(f"/checks/{pc_id}", status_code=303)
