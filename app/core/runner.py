"""核查执行器：路由数据源 → 采集（mock 或真实 adapter）→ 规则评判 → 结果落库。

SQL 一律单表参数化查询（? 占位符），避免复杂拼接（也是 Mimosa 门禁的偏好）。
数据源失败状态（TIMEOUT/ERROR/BLOCKED/MANUAL）折算进总体结论，绝不归约为 PASS；
真实链路受 app/config/app.yaml nightly_mock_only 门控（夜间/演示模式禁用真实查询）。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date
from pathlib import Path

import yaml

from ..sources.mock import findings_for
from ..sources.national.base import AdapterOutcome, load_adapter, query_source
from .db import connect
from .evidence import save_evidence
from .models import Company, Finding, Project
from .registry import SourceRegistry
from .router import plan_with_exclusions
from .rules import RuleEngine, engine_for_terms, normalize_terms
from .status import (
    Status,
    combine_data,
    combine_decision,
    needs_manual,
    overall as overall_status,
)

# 配置随包分发（app/config/ 进入 wheel），源码运行与安装运行读到同一份
APP_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_YAML = APP_ROOT / "config" / "sources_registry.yaml"
APP_YAML = APP_ROOT / "config" / "app.yaml"


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
        "SELECT id, name, province, industry, owner_group, base_date, years_back, terms "
        "FROM projects WHERE id = ?",
        (pc["project_id"],),
    ).fetchone()
    comp = conn.execute(
        "SELECT id, name, uscc, registered_province FROM companies WHERE id = ?",
        (pc["company_id"],),
    ).fetchone()
    return pc, proj, comp


def _load_imported_findings(source, company, db_path: str | Path):
    """读取人工导入的名单证据文件，经 adapter.parse（含主体一致性）产出 Finding。

    证据来自 evidence 表（kind=owner_ban, query_id IS NULL, 文件在盘且哈希可复核）。
    文件缺失/损坏/解析失败 → 返回 None（维持原 MANUAL 结论，绝不伪造评判成功）。
    """
    import json as _json
    import sqlite3 as _sqlite3

    from .evidence import evidence_dir_for, verify_evidence

    conn = _sqlite3.connect(str(db_path))
    conn.row_factory = _sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, file_path FROM evidence "
            "WHERE source_id = ? AND kind = ? AND query_id IS NULL",
            (source.id, "owner_ban"),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return None
    edir = evidence_dir_for(db_path)
    texts: list[str] = []
    for r in rows:
        ok, broken = verify_evidence(db_path, r["id"])
        if broken:
            continue  # 已篡改/损坏的证据不得作为评判依据
        fp = Path(r["file_path"])
        if not fp.is_absolute():
            fp = edir / fp.name
        try:
            texts.append(fp.read_text(encoding="utf-8"))
        except OSError:
            continue
    if not texts:
        return None
    adapter = load_adapter(source)
    findings = []
    for t in texts:
        try:
            findings.extend(adapter.parse(t, company=company))
        except Exception:
            continue  # 单文件格式坏不拖垮整批导入
    # 非同一主体（同名不同码）的导入记录在落库前剔除，对齐 adapter 层语义
    findings = [f for f in findings
                if f.attrs.get("match_result") != "DIFFERENT_SUBJECT"]
    if not findings:
        return None
    from .status import Status
    return AdapterOutcome(
        source.id, Status.MANUAL, findings, source.query_url or source.official_home,
        note=f"人工导入名单 {len(rows)} 份，经主体一致性检查后离线评判 "
             f"{len(findings)} 条记录（状态保持 MANUAL 待人工确认）",
    )


def run_check(db_path: str | Path, pc_id: int, scenario: str = "clean",
              real_sources: bool = False, get=None,
              app_yaml: str | Path | None = None) -> str:
    """对一条 project_companies 记录跑完整核查链，返回总体结论（Status 值）。

    real_sources=False：mock 演示链路（夜间默认）；
    real_sources=True：按注册表逐源调用真实 adapter（get 可注入用于测试；
    nightly_mock_only=true 时拒绝执行，app_yaml 可显式传入另一份配置用于
    白天人工复核场景——覆盖必须由调用方明示并留痕）。query_url 未复核的源返回 MANUAL。
    """
    conn = connect(db_path)
    run_id = uuid.uuid4().hex  # 核查批次隔离（P0.5 §五）：每次运行唯一，历史不混入
    try:
        pc, proj, comp = _load_check_target(conn, pc_id)
        conn.execute(
            "INSERT INTO check_runs (run_id, project_id, company_id, scenario, started_at) "
            "VALUES (?, ?, ?, ?, datetime('now', 'localtime'))",
            (run_id, proj["id"], comp["id"], "real_sources" if real_sources else scenario),
        )
        conn.commit()
        # DB terms：NULL=未指定（全部条款启用，兼容旧项目）；串=本项目勾选
        enabled_terms = normalize_terms(proj["terms"])
        project = Project(
            name=proj["name"], province=proj["province"], industry=proj["industry"],
            owner_group=proj["owner_group"],
            base_date=date.fromisoformat(proj["base_date"]), years_back=proj["years_back"],
            terms=tuple(sorted(enabled_terms)) if enabled_terms else (),
        )
        company = Company(name=comp["name"], uscc=comp["uscc"],
                          registered_province=comp["registered_province"])

        route = plan_with_exclusions(company, project, SourceRegistry.from_yaml(REGISTRY_YAML))
        sources = route.planned

        # 逐源执行，得到每源查询状态与客观事实；失败状态绝不伪造成功。
        source_status: dict[str, Status] = {}
        per_source: dict[str, list[Finding]] = {}
        notes: dict[str, str] = {}
        if real_sources:
            if _nightly_mock_only(Path(app_yaml) if app_yaml else None):
                raise RuntimeError(
                    "nightly_mock_only=true：夜间/演示模式禁用真实数据源查询（任务书 §18）")
            for e in sources:
                try:
                    out = query_source(e, company, get=get)
                    # P6：manual_intake 源（内部名单）读取人工导入的证据文件离线评判
                    if e.automation_mode == "manual_intake" and not out.findings:
                        imp = _load_imported_findings(e, company, db_path)
                        if imp is not None:
                            out = imp
                except Exception as exc:
                    # 单个数据源异常不得拖垮整个项目核查（P0.5 §四）；
                    # 错误信息保留进 note 供追溯，状态=ERROR 绝不伪造成功
                    source_status[e.id] = Status.ERROR
                    per_source[e.id] = []
                    notes[e.id] = f"数据源执行异常：{exc.__class__.__name__}: {exc}"
                    continue
                source_status[e.id] = Status(out.status.value)
                per_source[e.id] = list(out.findings)
                notes[e.id] = out.note
        else:
            out = None
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

        engine = engine_for_terms(enabled_terms)  # Project.terms 真正控制规则（P0.5 §八）
        all_findings = [f for lst in per_source.values() for f in lst]
        results = engine.run_all(all_findings, project, company)

        # 行业不适用源显式留痕（P0.5 §七）：NOT_APPLICABLE ≠ 查询无数据，
        # 不参与数据层状态合并
        for e, reason in route.not_applicable:
            conn.execute(
                "INSERT INTO source_queries (project_id, company_id, source_id, status, query_url, raw_json, run_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (proj["id"], comp["id"], e.id, "NOT_APPLICABLE",
                 e.query_url or e.official_home,
                 json.dumps({"note": reason}, ensure_ascii=False), run_id),
            )
        for e in sources:
            st = source_status[e.id]
            fnd = per_source.get(e.id, [])
            payload = json.dumps(
                {"note": notes.get(e.id, ""),
                 "findings": [x.__dict__ for x in fnd]},
                ensure_ascii=False, default=str)
            cur = conn.execute(
                "INSERT INTO source_queries (project_id, company_id, source_id, status, query_url, raw_json, run_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (proj["id"], comp["id"], e.id, st.value,
                 e.query_url or e.official_home, payload, run_id),
            )
            qid = cur.lastrowid
            # P6 证据系统：真实响应原文落盘（SHA-256），结论可回链（mock 演示不落盘）
            if out is not None and getattr(out, "raw_text", ""):
                save_evidence(
                    db_path, conn=conn, source_id=e.id, query_id=qid,
                    url=e.query_url or e.official_home,
                    raw_text=out.raw_text,
                    kind="raw_response",
                    key_text=f"HTTP {out.http_status} · {len(out.raw_text)} 字符",
                )
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
                "INSERT INTO rule_results (project_id, company_id, rule_id, status, reasons_json, run_id, scope) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (proj["id"], comp["id"], r.rule_id, r.status,
                 json.dumps(r.reasons, ensure_ascii=False), run_id, r.scope),
            )
        # 正式资格判断：仅启用条款（term/meta）；background=通用背景风险不否决，
        # NOT_APPLICABLE=未启用条款不入统计（P0.5 §八）
        decision = combine_decision(
            r.status for r in results
            if r.status != "NOT_APPLICABLE" and r.scope != "background")
        data = combine_data(source_status.values())
        manual_required = needs_manual((r.status for r in results), source_status.values())
        overall = overall_status(decision, data).value
        # 批次收口：结论绑定本批次；历史批次永久保留，绝不混入当前展示
        conn.execute(
            "UPDATE check_runs SET decision_status = ?, data_status = ?, manual_required = ?, "
            "overall_status = ?, finished_at = datetime('now', 'localtime') WHERE run_id = ?",
            (decision.value, data.value, int(manual_required), overall, run_id),
        )
        conn.execute(
            "UPDATE project_companies SET overall_status = ?, status = 'done', run_id = ? WHERE id = ?",
            (overall, run_id, pc_id),
        )
        conn.commit()
        return overall
    finally:
        conn.close()
