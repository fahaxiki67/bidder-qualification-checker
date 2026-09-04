"""核查执行器：路由数据源 → 采集（当前为 mock）→ 规则评判 → 结果落库。

SQL 一律单表参数化查询（? 占位符），避免复杂拼接（也是 Mimosa 门禁的偏好）。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from ..sources.mock import findings_for
from .db import connect
from .models import Company, Finding, Project
from .registry import SourceRegistry
from .router import plan
from .rules import RuleEngine

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_YAML = REPO_ROOT / "config" / "sources_registry.yaml"


def _load_check_target(conn: sqlite3.Connection, pc_id: int):
    """读取 project_companies 及其关联的 project / company（分三步单表查询）。"""
    conn.row_factory = sqlite3.Row
    pc = conn.execute(
        "SELECT project_id, company_id, overall_status FROM project_companies WHERE id = ?",
        (pc_id,),
    ).fetchone()
    if pc is None:
        raise ValueError(f"project_companies id={pc_id} 不存在")
    proj = conn.execute(
        "SELECT id, name, province, industry, owner_group, base_date, years_back "
        "FROM projects WHERE id = ?",
        (pc["project_id"],),
    ).fetchone()
    comp = conn.execute(
        "SELECT id, name, uscc, registered_province FROM companies WHERE id = ?",
        (pc["company_id"],),
    ).fetchone()
    return pc, proj, comp


def run_check(db_path: str | Path, pc_id: int, scenario: str = "clean") -> str:
    """对一条 project_companies 记录跑完整核查链，返回总体结论（Status 值）。"""
    conn = connect(db_path)
    try:
        pc, proj, comp = _load_check_target(conn, pc_id)
        project = Project(
            name=proj["name"], province=proj["province"], industry=proj["industry"],
            owner_group=proj["owner_group"],
            base_date=date.fromisoformat(proj["base_date"]), years_back=proj["years_back"],
        )
        company = Company(name=comp["name"], uscc=comp["uscc"],
                          registered_province=comp["registered_province"])

        sources = plan(company, project, SourceRegistry.from_yaml(REGISTRY_YAML))
        findings: list[Finding] = findings_for(scenario, company, project)

        # 记录每个源的查询日志：mock 下查询本身恒为成功（PASS）；
        # 真实 adapter 接入后由 adapter 返回真实查询状态（含 ERROR/TIMEOUT/BLOCKED/MANUAL）。
        primary = sources[0].id if sources else "mock"
        for e in sources:
            fnd = findings if e.id == primary else []
            cur = conn.execute(
                "INSERT INTO source_queries (project_id, company_id, source_id, status, query_url, raw_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (proj["id"], comp["id"], e.id, "PASS",
                 e.query_url or e.official_home,
                 json.dumps([x.__dict__ for x in fnd], ensure_ascii=False, default=str)),
            )
            qid = cur.lastrowid
            for x in fnd:
                conn.execute(
                    "INSERT INTO findings (query_id, company_id, kind, grade, description, start_date, end_date, attrs_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (qid, comp["id"], x.kind, x.grade, x.description,
                     x.start_date.isoformat() if x.start_date else None,
                     x.end_date.isoformat() if x.end_date else None,
                     json.dumps(x.attrs, ensure_ascii=False)),
                )

        engine = RuleEngine()
        results = engine.run_all(findings, project, company)
        for r in results:
            conn.execute(
                "INSERT INTO rule_results (project_id, company_id, rule_id, status, reasons_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (proj["id"], comp["id"], r.rule_id, r.status,
                 json.dumps(r.reasons, ensure_ascii=False)),
            )
        overall = engine.overall(results)
        conn.execute(
            "UPDATE project_companies SET overall_status = ?, status = 'done' WHERE id = ?",
            (overall, pc_id),
        )
        conn.commit()
        return overall
    finally:
        conn.close()
