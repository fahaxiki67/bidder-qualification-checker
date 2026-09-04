"""SourceRouter 行业门控测试（P0.5 §七）。

数据源限定行业时只对适用行业计划查询；不适用源显式记 NOT_APPLICABLE（含原因），
绝不冒充"查询无数据"，也不被强行查询；owner_group/注册省/项目省原逻辑不变。
"""
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
import yaml

from app.core import runner
from app.core.db import connect, init_db
from app.core.models import Company, Project, SourceRef
from app.core.registry import SourceRegistry
from app.core.router import industry_applicable, plan, plan_with_exclusions
from app.core.runner import run_check

COMPANY = Company(name="测试公司", uscc="91510000TEST0000XX", registered_province="四川")

REGISTRY_YAML = {
    "sources": [
        {"id": "creditchina", "name": "信用中国", "level": "national",
         "automation_mode": "auto", "official_home": "https://www.creditchina.gov.cn/",
         "adapter": "app.sources.national.creditchina"},
        {"id": "jzsc", "name": "全国建筑市场监管平台", "level": "national",
         "automation_mode": "auto", "official_home": "https://jzsc.mohurd.gov.cn/",
         "industry": "建筑",
         "adapter": "app.sources.national.jzsc"},
        {"id": "powerchina_ban", "name": "中国电建禁入名单", "level": "owner",
         "automation_mode": "auto", "official_home": "https://ec.powerchina.cn/",
         "owner_group": "powerchina",
         "adapter": "app.sources.national.creditchina"},
        {"id": "sc_credit", "name": "四川信用", "level": "province", "province": "四川",
         "automation_mode": "auto", "official_home": "https://scexample.cn/",
         "adapter": "app.sources.national.creditchina"},
    ]
}


@pytest.fixture()
def registry(tmp_path) -> SourceRegistry:
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.safe_dump(REGISTRY_YAML, allow_unicode=True), encoding="utf-8")
    return SourceRegistry.from_yaml(p)


def test_industry_applicable_unit():
    assert industry_applicable(None, "建筑") is True          # 未限定行业 → 恒适用
    assert industry_applicable("", "建筑") is True
    assert industry_applicable("建筑", "建筑") is True
    assert industry_applicable("建筑,市政", "水利") is False
    assert industry_applicable("建筑、市政", "市政") is True   # 分隔符容错
    assert industry_applicable("建筑", "") is False           # 项目未填行业 → 不适用
    assert industry_applicable("建筑", None) is False


def test_plan_with_exclusions_industry_gate(registry):
    proj_build = Project(name="房建项目", industry="建筑", base_date=date(2026, 9, 5),
                         owner_group="powerchina")
    route = plan_with_exclusions(COMPANY, proj_build, registry)
    ids = {e.id for e in route.planned}
    assert {"creditchina", "jzsc", "powerchina_ban", "sc_credit"} == ids
    assert route.not_applicable == []

    proj_water = Project(name="水利项目", industry="水利", base_date=date(2026, 9, 5),
                         owner_group="powerchina")
    route2 = plan_with_exclusions(COMPANY, proj_water, registry)
    ids2 = {e.id for e in route2.planned}
    assert "jzsc" not in ids2 and "creditchina" in ids2 and "sc_credit" in ids2
    assert [e.id for e, _ in route2.not_applicable] == ["jzsc"]
    assert "行业不适用" in route2.not_applicable[0][1]

    # 项目未填行业：行业限定源不适用（宁可不查转人工，不得硬查）
    proj_none = Project(name="项目", base_date=date(2026, 9, 5))
    route3 = plan_with_exclusions(COMPANY, proj_none, registry)
    assert [e.id for e, _ in route3.not_applicable] == ["jzsc"]


def test_plan_compat_returns_planned_only(registry):
    proj = Project(name="项目", industry="水利", base_date=date(2026, 9, 5))
    assert {e.id for e in plan(COMPANY, proj, registry)} == {"creditchina", "sc_credit"}


def test_other_routing_logic_unchanged(registry):
    """集团不匹配不查；省级源按注册地/项目地命中，同省只查一次（原行为不回归）。"""
    proj_gd = Project(name="项目", base_date=date(2026, 9, 5),
                      owner_group="othergroup", province="广东")
    ids_gd = {e.id for e in plan(COMPANY, proj_gd, registry)}
    assert "powerchina_ban" not in ids_gd   # 集团不匹配 → 不查
    assert "sc_credit" in ids_gd            # 企业注册地四川 → 发证地核查仍要查（原逻辑）

    proj_hebei = Project(name="项目", base_date=date(2026, 9, 5), province="四川")
    picked = [e.id for e in plan(
        Company(name="测试公司", uscc=None, registered_province="河北"), proj_hebei, registry)]
    assert picked.count("sc_credit") == 1   # 仅项目地命中，只查一次

    # 行业不符的省级/集团源同样不硬查（门控在层级判断之前）
    proj_jz_owner = Project(name="项目", industry="水利", base_date=date(2026, 9, 5),
                            owner_group="powerchina", province="四川")
    route = plan_with_exclusions(COMPANY, proj_jz_owner, registry)
    assert {e.id for e, _ in route.not_applicable} == {"jzsc"}
    assert "powerchina_ban" in {e.id for e in route.planned}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    reg = tmp_path / "sources_registry.yaml"
    reg.write_text(yaml.safe_dump(REGISTRY_YAML, allow_unicode=True), encoding="utf-8")
    app_yaml = tmp_path / "app.yaml"
    app_yaml.write_text("nightly_mock_only: false\n", encoding="utf-8")
    monkeypatch.setattr(runner, "REGISTRY_YAML", reg)
    monkeypatch.setattr(runner, "APP_YAML", app_yaml)
    db = tmp_path / "t.sqlite3"
    init_db(db)
    conn = connect(db)
    cur = conn.execute("INSERT INTO projects (name, industry, base_date, years_back, terms) "
                       "VALUES ('水利项目','水利','2026-09-05',3,'条款1')")
    pid = cur.lastrowid
    cur = conn.execute("INSERT INTO companies (name, uscc) VALUES ('测试公司','91510000TEST0000XX')")
    cid = cur.lastrowid
    cur = conn.execute("INSERT INTO project_companies (project_id, company_id, status) "
                       "VALUES (?,?, 'running')", (pid, cid))
    pcid = cur.lastrowid
    conn.commit()
    conn.close()
    return db, pcid


def test_runner_records_not_applicable(env):
    """行业不适用源落 NOT_APPLICABLE 行（含原因），不参与数据层合并、不算无数据。"""
    db, pcid = env
    overall = run_check(db, pcid, real_sources=True,
                        get=lambda url, t: (200, json.dumps({"result": []})))
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = {r["source_id"]: r for r in conn.execute(
            "SELECT source_id, status, raw_json FROM source_queries")}
    finally:
        conn.close()
    assert rows["jzsc"]["status"] == "NOT_APPLICABLE"
    assert "行业不适用" in rows["jzsc"]["raw_json"]
    # 计划内源正常执行：creditchina 无 query_url（未人工复核）→ MANUAL（红线行为）
    assert rows["creditchina"]["status"] == "MANUAL"
    assert overall == "MANUAL"  # NA 不参与合并；总体由计划内源的 MANUAL 顶上来，绝不 PASS
