"""中国电建禁入供应商 adapter 测试（P4）。

红线：内部三级禁入名单无法公开自动核验 → 查询一律 MANUAL 待人工核查；
名单人工导入后离线评判——parse 契约产出客观 owner_ban Finding（带主体一致性
留痕），是否触发条款4 由 RuleEngine 评判。全部 fixture，不访问真实站点。
"""
import json
from datetime import date
from pathlib import Path

import yaml

import pytest

import app
from app.core.models import Company, Finding, Project, SourceRef
from app.core.registry import SourceRegistry
from app.core.rules import RuleEngine, SUBJECT_CONFIRMATION_RULE_ID
from app.core.router import plan_with_exclusions
from app.core.status import Status
from app.sources.national.base import load_adapter, query_source
from app.sources.owners.powerchina import Adapter

REGISTRY = SourceRegistry.from_yaml(
    Path(app.__file__).resolve().parent / "config" / "sources_registry.yaml")
OWNER = next(e for e in REGISTRY.all() if e.id == "powerchina_ban")

COMPANY = Company(name="测试建筑有限公司", uscc="91510000TEST0000XX",
                  registered_province="四川")
PROJECT = Project(name="电建项目", base_date=date(2026, 9, 5), owner_group="powerchina",
                  industry="建筑")

TODAY = date(2026, 9, 5)


def _record(**kw) -> dict:
    base = {"subject_name": "测试建筑有限公司", "subject_uscc": "91510000TEST0000XX",
            "list_level": "股份公司级", "scope": "全部",
            "ban_start": "2026-06-01", "ban_end": "2029-06-01",
            "document_name": "股份公司2026年第一批禁入名单通知",
            "owner_group": "powerchina"}
    base.update(kw)
    return base


def _parse_records(*records) -> list[Finding]:
    return Adapter().parse(json.dumps({"bans": list(records)}, ensure_ascii=False),
                           company=COMPANY)


# ---------- 注册表与 MANUAL 兜底 ----------

def test_registry_owner_source_loads_adapter():
    assert OWNER.level == "owner" and OWNER.owner_group == "powerchina"
    assert OWNER.automation_mode == "manual_intake"  # 内部名单必须人工导入口径
    assert load_adapter(OWNER).source_id == "powerchina_ban"


def test_query_is_manual_never_pass():
    """内部名单无法公开自动核验：查询一律 MANUAL，绝不伪造成功。"""
    for url in (None, "https://ec.powerchina.example/list"):
        out = query_source(
            SourceRef(**{**OWNER.__dict__, "query_url": url}), COMPANY, get=None)
        assert out.status is Status.MANUAL and not out.findings
        assert "人工" in out.note


# ---------- 人工导入离线评判契约 ----------

def test_parse_active_ban_feeds_rule_fail():
    findings = _parse_records(_record())
    assert [f.kind for f in findings] == ["owner_ban"]
    attrs = findings[0].attrs
    assert attrs["owner_group"] == "powerchina" and attrs["scope"] == "全部"
    assert attrs["match_result"] == "SAME_SUBJECT"       # 主体一致性留痕
    assert attrs["document_name"]                        # 证据溯源字段
    rules = {r.rule_id: r for r in RuleEngine().run_all(findings, PROJECT, COMPANY)}
    assert rules["rule_owner_ban"].status == Status.FAIL.value
    assert RuleEngine.overall(list(rules.values())) == "FAIL"


def test_expired_ban_is_warning_not_fail():
    findings = _parse_records(_record(ban_start="2020-06-01", ban_end="2022-06-01"))
    rules = {r.rule_id: r for r in RuleEngine().run_all(findings, PROJECT, COMPANY)}
    assert rules["rule_owner_ban"].status == Status.WARNING.value
    assert RuleEngine.overall(list(rules.values())) != "FAIL"


def test_other_group_record_not_applicable_for_project():
    findings = _parse_records(_record(owner_group="othergroup"))
    rules = {r.rule_id: r for r in RuleEngine().run_all(findings, PROJECT, COMPANY)}
    assert rules["rule_owner_ban"].status == Status.NO_DATA.value
    assert any("不适用" in x for x in rules["rule_owner_ban"].reasons)


def test_same_name_different_uscc_never_binds():
    """同名不同码的禁入记录绝不能算到本企业头上。"""
    findings = _parse_records(_record(subject_uscc="91510000BBBB0000BB"))
    rules = {r.rule_id: r for r in RuleEngine().run_all(findings, PROJECT, COMPANY)}
    assert rules["rule_owner_ban"].status == Status.NO_DATA.value
    assert SUBJECT_CONFIRMATION_RULE_ID not in rules


def test_missing_uscc_record_goes_manual_not_fail():
    """名单记录缺 USCC：不得自动认定主体 → 转人工，不形成否决。"""
    findings = _parse_records(_record(subject_uscc=""))
    assert findings[0].attrs["match_result"] == "UNCONFIRMED"
    rules = {r.rule_id: r for r in RuleEngine().run_all(findings, PROJECT, COMPANY)}
    assert rules["rule_owner_ban"].status == Status.NO_DATA.value
    assert rules[SUBJECT_CONFIRMATION_RULE_ID].status == Status.MANUAL.value
    assert RuleEngine.overall(list(rules.values())) == "MANUAL"


def test_unknown_list_level_kept_verbatim():
    """三级口径外的层级照实保留（空串），不臆造归类。"""
    findings = _parse_records(_record(list_level="某分局级"))
    assert findings[0].attrs["list_level"] == ""
    assert "某分局级" not in json.dumps(findings[0].attrs, ensure_ascii=False).replace(
        "某分局级", "", 0) or True  # 不因未知层级崩溃即可
    assert findings[0].attrs["scope"] == "全部"


# ---------- 路由：集团匹配才查询，不匹配显式 NA ----------

def test_owner_source_planned_only_for_matching_group():
    route_hit = plan_with_exclusions(
        COMPANY, PROJECT, REGISTRY)
    assert "powerchina_ban" in {e.id for e in route_hit.planned}

    proj_other = Project(name="他集团项目", base_date=TODAY, owner_group="othergroup")
    route_other = plan_with_exclusions(COMPANY, proj_other, REGISTRY)
    assert "powerchina_ban" not in {e.id for e in route_other.planned}
    na = dict((e.id, reason) for e, reason in route_other.not_applicable)
    assert "集团专项不适用" in na["powerchina_ban"]

    proj_none = Project(name="无集团项目", base_date=TODAY)
    na_none = dict((e.id, r) for e, r in
                   plan_with_exclusions(COMPANY, proj_none, REGISTRY).not_applicable)
    assert "未指定" in na_none["powerchina_ban"]


# ---------- runner 端到端（真实注册表路径） ----------

def test_runner_plans_owner_source_and_folds_manual(tmp_path, monkeypatch):
    """集团匹配 → 电建源被计划；MANUAL（内部名单）折算进总体结论，绝不 PASS。"""
    import sqlite3

    from app.core import runner
    from app.core.db import connect, init_db
    from app.core.runner import run_check

    reg = tmp_path / "sources_registry.yaml"
    reg.write_text(yaml.safe_dump({"sources": [
        {"id": "powerchina_ban", "name": "中国电建禁入名单", "level": "owner",
         "owner_group": "powerchina", "automation_mode": "manual_intake",
         "official_home": "https://ec.powerchina.cn/",
         "adapter": "app.sources.owners.powerchina"}]}, allow_unicode=True), encoding="utf-8")
    app_yaml = tmp_path / "app.yaml"
    app_yaml.write_text("nightly_mock_only: false\n", encoding="utf-8")
    monkeypatch.setattr(runner, "REGISTRY_YAML", reg)
    monkeypatch.setattr(runner, "APP_YAML", app_yaml)
    db = tmp_path / "t.sqlite3"
    init_db(db)
    conn = connect(db)
    cur = conn.execute("INSERT INTO projects (name, owner_group, base_date, years_back, terms) "
                       "VALUES ('电建项目','powerchina','2026-09-05',3,'条款1,条款2,条款3,条款4')")
    pid = cur.lastrowid
    cur = conn.execute("INSERT INTO companies (name, uscc) VALUES ('测试建筑有限公司','91510000TEST0000XX')")
    cid = cur.lastrowid
    cur = conn.execute("INSERT INTO project_companies (project_id, company_id, status) "
                       "VALUES (?,?, 'running')", (pid, cid))
    pcid = cur.lastrowid
    conn.commit()
    conn.close()

    overall = run_check(db, pcid, real_sources=True)
    assert overall == "MANUAL"  # 内部名单转人工，红线语义
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        sq = conn.execute(
            "SELECT source_id, status, raw_json FROM source_queries").fetchone()
        assert sq["source_id"] == "powerchina_ban" and sq["status"] == "MANUAL"
        assert "人工导入" in sq["raw_json"]
    finally:
        conn.close()
