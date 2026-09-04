"""核查执行器：路由数据源 → 采集（mock 或真实 adapter）→ 规则评判 → 结果落库。

SQL 一律单表参数化查询（? 占位符），避免复杂拼接（也是 Mimosa 门禁的偏好）。
数据源失败状态（TIMEOUT/ERROR/BLOCKED/MANUAL）折算进总体结论，绝不归约为 PASS；
真实链路受 config/app.yaml nightly_mock_only 门控（夜间/演示模式禁用真实查询）。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import yaml

from ..sources.mock import findings_for
from ..sources.national.base import query_source
from .db import connect
from .models import Company, Finding, Project
from .registry import SourceRegistry
from .router import plan
from .rules import RuleEngine
from .status import NEVER_PASS, Status, combine

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_YAML = REPO_ROOT / "config" / "sources_registry.yaml"
APP_YAML = REPO_ROOT / "config" / "app.yaml"


def _nightly_mock_only(path: Path | None = None) -> bool:
    data = yaml.safe_load((path or APP_YAML).read_text(encoding="utf-8")) or {}
    return bool(data.get("nightly_mock_only", True))


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


def run_check(db_path: str | Path, pc_id: int, scenario: str = "clean",
              real_sources: bool = False, get=None) -> str:
    """对一条 project_companies 记录跑完整核查链，返回总体结论（Status 值）。

    real_sources=False：mock 演示链路（夜间默认）；
    real_sources=True：按注册表逐源调用真实 adapter（get 可注入用于测试；
    nightly_mock_only=true 时拒绝执行）。query_url 未复核的源返回 MANUAL。
    """
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

        # 逐源执行，得到每源查询状态与客观事实；失败状态绝不伪造成功。
        source_status: dict[str, Status] = {}
        per_source: dict[str, list[Finding]] = {}
        notes: dict[str, str] = {}
        if real_sources:
            if _nightly_mock_only():
                raise RuntimeError(
                    "nightly_mock_only=true：夜间/演示模式禁用真实数据源查询（任务书 §18）")
            for e in sources:
                out = query_source(e, company, get=get)
                source_status[e.id] = Status(out.status.value)
                per_source[e.id] = list(out.findings)
                notes[e.id] = out.note
        else:
            findings = findings_for(scenario, company, project)
            primary = sources[0] if sources else None
            for e in sources:
                source_status[e.id] = Status.PASS
                per_source[e.id] = []
            if primary is not None:
                per_source[primary.id] = list(findings)
                if scenario == "query_error":
                    source_status[primary.id] = Status.ERROR
                    notes[primary.id] = "演示：数据源查询失败"

        engine = RuleEngine()
        all_findings = [f for lst in per_source.values() for f in lst]
        results = engine.run_all(all_findings, project, company)

        for e in sources:
            st = source_status[e.id]
            fnd = per_source.get(e.id, [])
            payload = json.dumps(
                {"note": notes.get(e.id, ""),
                 "findings": [x.__dict__ for x in fnd]},
                ensure_ascii=False, default=str)
            cur = conn.execute(
                "INSERT INTO source_queries (project_id, company_id, source_id, status, query_url, raw_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (proj["id"], comp["id"], e.id, st.value,
                 e.query_url or e.official_home, payload),
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

        for r in results:
            conn.execute(
                "INSERT INTO rule_results (project_id, company_id, rule_id, status, reasons_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (proj["id"], comp["id"], r.rule_id, r.status,
                 json.dumps(r.reasons, ensure_ascii=False)),
            )
        overall = engine.overall(results)
        failed = [s for s in source_status.values() if s in NEVER_PASS]
        if failed:
            overall = combine([Status(overall), *failed]).value
        conn.execute(
            "UPDATE project_companies SET overall_status = ?, status = 'done' WHERE id = ?",
            (overall, pc_id),
        )
        conn.commit()
        return overall
    finally:
        conn.close()
