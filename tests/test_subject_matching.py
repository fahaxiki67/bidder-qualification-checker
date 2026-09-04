"""主体一致性校验测试（P0.5 §六）。

matching.check_subject 七条判定规则、base.subject_attrs 可追溯字段、
adapter 层 DIFFERENT 剔除、engine 层 UNCONFIRMED 转人工兜底——
同名不同码绝不误并，缺码绝不自动认定，无法确认绝不作确定性结论。
"""
import json

import pytest

from app.core.matching import (
    DIFFERENT_SUBJECT,
    SAME_SUBJECT,
    UNCONFIRMED,
    check_subject,
)
from app.core.models import Company, Project
from app.core.rules import RuleEngine, SUBJECT_CONFIRMATION_RULE_ID
from app.core.status import Status
from app.sources.national.base import subject_attrs
from datetime import date

COMPANY = Company(name="测试建筑有限公司", uscc="91510000TEST0000XX")
PROJECT = Project(name="测试项目", base_date=date(2026, 9, 5))


# ---------- §六 七条判定规则 ----------

def test_rule1_both_uscc_must_match():
    m = check_subject("甲公司", "91510000AAAA0000AA", "乙公司", "91510000AAAA0000AA")
    assert m.match_result is SAME_SUBJECT and m.matched_by == "USCC"


def test_rule2_same_uscc_different_name_is_same_subject():
    m = check_subject("测试建筑有限公司", "91510000TEST0000XX",
                      "测试建筑有限公司（曾用名：旧称公司）", "91510000TEST0000XX")
    assert m.match_result is SAME_SUBJECT and m.matched_by == "USCC"
    assert "名称写法不同" in m.reason  # 依据留痕


def test_rule3_same_name_different_uscc_is_different():
    m = check_subject("同名建筑公司", "91510000TEST0000XX",
                      "同名建筑公司", "91510000BBBB0000BB")
    assert m.match_result is DIFFERENT_SUBJECT
    assert "不是同一主体" in m.reason


def test_rule4_one_side_uscc_never_auto_match():
    m = check_subject("测试建筑有限公司", "91510000TEST0000XX", "测试建筑有限公司", "")
    assert m.match_result is UNCONFIRMED and m.matched_by == "NONE"
    m2 = check_subject("测试建筑有限公司", "", "测试建筑有限公司", "91510000TEST0000XX")
    assert m2.match_result is UNCONFIRMED


def test_rule5_both_no_uscc_normalized_name():
    """双方均无 USCC：仅空白差异经规范化后一致 → 同一主体（并提示补录 USCC）。"""
    m = check_subject("测试 建筑有限公司", "", "测试建筑有限公司", "")
    assert m.match_result is SAME_SUBJECT and m.matched_by == "NORMALIZED_NAME"
    m2 = check_subject("测试建筑有限公司", "", "测试建筑（有限公司）", "")
    assert m2.match_result is UNCONFIRMED  # 括号注记形态不同不算精确一致，转人工


def test_rule6_fuzzy_or_abbreviated_name_never_confirmed():
    """简称/模糊包含/部分相似不得作确定性认定。"""
    for src in ("测试公司", "测试建筑", "建筑有限公司", "测试建筑有限公司四川分公司"):
        m = check_subject("测试建筑有限公司", "", src, "")
        assert m.match_result is UNCONFIRMED, src


def test_rule7_missing_identity_unconfirmed():
    m = check_subject("测试建筑有限公司", "91510000TEST0000XX", "", "")
    assert m.match_result is UNCONFIRMED  # 来源记录缺主体字段 → 不得默认同主体


# ---------- 可追溯字段（§六 要求字段不缺失） ----------

def test_subject_attrs_traceability_fields():
    attrs = subject_attrs(COMPANY, {"subject_name": "测试建筑有限公司",
                                    "subject_uscc": "91510000TEST0000XX"})
    for key in ("requested_company_name", "requested_company_uscc",
                "source_subject_name", "source_subject_uscc",
                "matched_by", "match_result"):
        assert key in attrs
    assert attrs["match_result"] == SAME_SUBJECT


def test_subject_attrs_missing_record_identity_unconfirmed():
    attrs = subject_attrs(COMPANY, {"penalty_content": "罚款"})
    assert attrs["match_result"] == UNCONFIRMED
    assert attrs["source_subject_name"] == "" and attrs["source_subject_uscc"] == ""


# ---------- 链路强制：adapter 剔除 DIFFERENT；engine 拦截 UNCONFIRMED ----------

def _engine_result(findings):
    return {r.rule_id: r for r in RuleEngine().run_all(findings, PROJECT, COMPANY)}


def test_unconfirmed_findings_never_reach_business_rules():
    """UNCONFIRMED 记录不得形成业务条款结论（防同名/缺码错并成 FAIL）。"""
    from app.core.models import Finding
    f = Finding(kind="penalty_bid_restriction", source_id="creditchina", grade="A",
                description="省级限制投标", attrs={"match_result": UNCONFIRMED})
    rules = _engine_result([f])
    # 业务条款看不到这条记录
    assert rules["rule_bid_restriction"].status == Status.NO_DATA.value
    # 转人工兜底条款出现且为 MANUAL
    assert rules[SUBJECT_CONFIRMATION_RULE_ID].status == Status.MANUAL.value


def test_unannotated_findings_pass_through():
    """mock/演示 findings（无主体字段标注）不受拦截——演示链路行为不变。"""
    from app.core.models import Finding
    f = Finding(kind="penalty_bid_restriction", source_id="mock", grade="A",
                description="省级限制投标", attrs={"authority_level": "province"})
    rules = _engine_result([f])
    assert rules["rule_bid_restriction"].status == Status.FAIL.value
    assert SUBJECT_CONFIRMATION_RULE_ID not in rules


def test_runner_end_to_end_same_name_different_uscc(tmp_path, monkeypatch):
    """端到端：来源返回同名不同码记录 → 剔除 → 本企业 NO_DATA，绝不把他家处罚算到本企业头上。"""
    import sqlite3
    import yaml

    from app.core import runner
    from app.core.db import connect, init_db
    from app.core.runner import run_check

    REG = {"sources": [{"id": "creditchina", "name": "信用中国", "level": "national",
                        "automation_mode": "auto",
                        "official_home": "https://www.creditchina.gov.cn/",
                        "query_url": "https://www.creditchina.gov.cn/q",
                        "adapter": "app.sources.national.creditchina"}]}
    reg = tmp_path / "reg.yaml"
    reg.write_text(yaml.safe_dump(REG, allow_unicode=True), encoding="utf-8")
    app_yaml = tmp_path / "app.yaml"
    app_yaml.write_text("nightly_mock_only: false\n", encoding="utf-8")
    monkeypatch.setattr(runner, "REGISTRY_YAML", reg)
    monkeypatch.setattr(runner, "APP_YAML", app_yaml)
    db = tmp_path / "t.sqlite3"
    init_db(db)
    conn = connect(db)
    cur = conn.execute("INSERT INTO projects (name, base_date, years_back, terms) "
                       "VALUES ('p','2026-09-05',3,'条款1')")
    pid = cur.lastrowid
    cur = conn.execute("INSERT INTO companies (name, uscc) VALUES ('测试公司','91510000TEST0000XX')")
    cid = cur.lastrowid
    cur = conn.execute("INSERT INTO project_companies (project_id, company_id, status) "
                       "VALUES (?,?, 'running')", (pid, cid))
    pcid = cur.lastrowid
    conn.commit()
    conn.close()

    # 来源记录：名称完全相同、USCC 不同——绝不能错并
    body = {"result": [{**{"subject_name": "测试公司", "subject_uscc": "91510000BBBB0000BB"},
                        "penalty_content": "省级住建主管部门限制投标一年",
                        "authority_level": "province",
                        "start_date": "2026-08-05", "end_date": "2027-08-05"}]}
    overall = run_check(db, pcid, real_sources=True,
                        get=lambda url, t: (200, json.dumps(body)))
    assert overall == "NO_DATA"  # 剔除后本企业无记录，绝不 FAIL
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        sq = conn.execute("SELECT status, raw_json FROM source_queries").fetchone()
        assert sq["status"] == "NO_DATA"
        assert "剔除" in sq["raw_json"]  # 剔除留痕
        # findings 不落任何记录
        assert conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0] == 0
    finally:
        conn.close()
