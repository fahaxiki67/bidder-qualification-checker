"""Project.terms 控制规则引擎测试（P0.5 §八）。

三层区分：通用背景风险（background，恒评估不否决）/ 本项目资格条款
（term，按勾选启用）/ 本项目正式资格判断（仅启用条款参与合并）。
相同企业、相同 Finding：启用条款不同 → 正式资格判断必须不同。
"""
from datetime import date

import pytest

from app.core.models import Company, Finding, Project
from app.core.rules import (
    DEFAULT_RULES,
    SUBJECT_CONFIRMATION_RULE_ID,
    RuleEngine,
    engine_for_terms,
    load_rule_specs,
    normalize_terms,
)
from app.core.status import Status

COMPANY = Company(name="测试公司", uscc="91510000TEST0000XX")
BID_BAN = Finding(kind="penalty_bid_restriction", source_id="creditchina", grade="A",
                  description="省级限制投标一年",
                  start_date=date(2026, 8, 5), end_date=date(2027, 8, 5),
                  attrs={"authority_level": "province"})
LICENSE_DEAD = Finding(kind="license_authority_status", source_id="jzsc", grade="A",
                       description="施工总承包一级",
                       attrs={"status": "吊销"})


def test_rules_yaml_specs_load_with_scope():
    specs = load_rule_specs()
    assert {s.id for s in specs.values()} == {r.id for r in DEFAULT_RULES}
    by_id = {s.id: s for s in specs.values()}
    assert by_id["rule_bid_restriction"].clause == "条款1"
    assert by_id["rule_bid_restriction"].scope == "term"
    assert by_id["rule_license_validity"].scope == "background"
    assert by_id["rule_license_validity"].clause == "§6"


def test_normalize_terms():
    assert normalize_terms(None) is None                       # 未指定 → 全启用
    assert normalize_terms("") == set()                        # 明确不启用任何条款
    assert normalize_terms("条款1,条款4") == {"条款1", "条款4"}
    assert normalize_terms(("条款2", "§6")) == {"条款2", "§6"}


def test_terms_enable_only_selected_term_rules():
    engine = engine_for_terms({"条款2"})
    # 仅启用的 term 规则 + 恒评估的 background 规则
    assert [r.id for r in engine.rules] == ["rule_business_status", "rule_license_validity"]
    results = {r.rule_id: r for r in engine.run_all([BID_BAN], Project(
        name="p", base_date=date(2026, 9, 5), terms=("条款2",)), COMPANY)}
    # 启用条款正常评判；未启用条款显式 NOT_APPLICABLE 留痕
    assert results["rule_business_status"].status == Status.NO_DATA.value  # 无相关 findings
    assert results["rule_bid_restriction"].status == "NOT_APPLICABLE"
    assert "未启用" in results["rule_bid_restriction"].reasons[0]
    # background 规则始终评估
    assert results["rule_license_validity"].scope == "background"
    assert SUBJECT_CONFIRMATION_RULE_ID not in results


def test_same_findings_different_terms_different_decision():
    """§八 验收：相同企业、相同 Finding，启用条款不同 → 正式资格判断不同。"""
    proj_a = Project(name="项目A", base_date=date(2026, 9, 5), terms=("条款1",))
    proj_b = Project(name="项目B", base_date=date(2026, 9, 5), terms=("条款2", "条款3"))
    overall_a = RuleEngine.overall(engine_for_terms(proj_a.terms).run_all([BID_BAN], proj_a, COMPANY))
    overall_b = RuleEngine.overall(engine_for_terms(proj_b.terms).run_all([BID_BAN], proj_b, COMPANY))
    assert overall_a == "FAIL"      # 项目A 启用条款1 → 否决成立
    assert overall_b == "NO_DATA"   # 项目B 未启用条款1 → 同一记录不得否决


def test_background_never_vetoes_qualification():
    """通用背景风险（§6 证照吊销）恒评估、可出 FAIL 结论，但不得单独否决项目资格。"""
    proj = Project(name="项目", base_date=date(2026, 9, 5), terms=("条款1",))
    engine = engine_for_terms(proj.terms)
    results = {r.rule_id: r for r in engine.run_all([LICENSE_DEAD], proj, COMPANY)}
    assert results["rule_license_validity"].status == Status.FAIL.value
    assert results["rule_license_validity"].scope == "background"
    # 正式资格判断不受 background FAIL 影响
    assert RuleEngine.overall(list(results.values())) == "NO_DATA"


def test_terms_none_keeps_legacy_all_rules():
    """terms=None（旧调用/mock 演示）→ 全部规则启用且全部参与判断。"""
    engine = engine_for_terms(None)
    assert len(engine.rules) == len(DEFAULT_RULES)
    proj = Project(name="p", base_date=date(2026, 9, 5))
    results = engine.run_all([BID_BAN], proj, COMPANY)
    assert not [r for r in results if r.status == "NOT_APPLICABLE"]
    assert RuleEngine.overall(results) == "FAIL"
