from datetime import date

from app.core.models import Finding, Project
from app.core.rules import BankruptcyRule, BidRestrictionRule, BusinessStatusRule, LicenseValidityRule, OwnerBanRule, RuleEngine
from app.core.status import Status

BASE = date(2026, 9, 4)
PROJECT = Project(name="某项目", base_date=BASE)


def f(**kw):
    return Finding(source_id="test", grade="A", **kw)


def test_rule1_effective_province_bid_ban_fails():
    r = BidRestrictionRule().evaluate(
        [f(kind="penalty_bid_restriction", description="暂停投标一年",
           start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
           attrs={"authority_level": "province"})],
        PROJECT,
    )
    assert r.status == Status.FAIL.value


def test_rule1_expired_penalty_is_warning_not_fail():
    r = BidRestrictionRule().evaluate(
        [f(kind="penalty_bid_restriction", description="已到期",
           start_date=date(2024, 1, 1), end_date=date(2025, 1, 1),
           attrs={"authority_level": "national"})],
        PROJECT,
    )
    assert r.status == Status.WARNING.value


def test_rule1_municipal_authority_not_fail():
    r = BidRestrictionRule().evaluate(
        [f(kind="penalty_bid_restriction", description="区级处罚",
           attrs={"authority_level": "city"})],
        PROJECT,
    )
    assert r.status == Status.WARNING.value


def test_rule1_cd_grade_only_cannot_fail():
    f_cd = Finding(source_id="news", grade="C", kind="penalty_bid_restriction",
                   description="媒体称被限制投标", attrs={"authority_level": "province"})
    r = BidRestrictionRule().evaluate([f_cd], PROJECT)
    assert r.status == Status.UNKNOWN.value


def test_rule1_ordinary_fine_is_no_data_for_this_rule():
    r = BidRestrictionRule().evaluate(
        [f(kind="penalty_fine", description="普通罚款三万元")], PROJECT
    )
    assert r.status == Status.NO_DATA.value


def test_rule2_current_revocation_fails():
    r = BusinessStatusRule().evaluate(
        [f(kind="penalty_business", description="吊销执照",
           attrs={"current": True, "status": "吊销营业执照"})],
        PROJECT,
    )
    assert r.status == Status.FAIL.value


def test_rule2_historical_revocation_resolved_is_warning():
    r = BusinessStatusRule().evaluate(
        [f(kind="penalty_business", description="曾吊销后恢复",
           attrs={"current": False, "status": "吊销营业执照"})],
        PROJECT,
    )
    assert r.status == Status.WARNING.value


def test_rule3_current_bankruptcy_fails():
    r = BankruptcyRule().evaluate(
        [f(kind="bankruptcy_status", description="已宣告破产",
           attrs={"current": True, "state": "宣告破产"})],
        PROJECT,
    )
    assert r.status == Status.FAIL.value


def test_rule3_vague_loss_of_capacity_goes_manual():
    r = BankruptcyRule().evaluate(
        [f(kind="loss_of_capacity_other", description="被认定为其他丧失履约能力")], PROJECT
    )
    assert r.status == Status.MANUAL.value


def test_rule4_owner_ban_effective_fails():
    r = OwnerBanRule().evaluate(
        [f(kind="owner_ban", description="禁入三年",
           start_date=date(2025, 1, 1), end_date=date(2028, 1, 1),
           attrs={"owner_group": "powerchina", "scope": "股份公司级"})],
        Project(name="电建项目", owner_group="powerchina", base_date=BASE),
    )
    assert r.status == Status.FAIL.value


def test_rule4_expired_owner_ban_is_warning():
    r = OwnerBanRule().evaluate(
        [f(kind="owner_ban", description="已解除",
           start_date=date(2023, 1, 1), end_date=date(2024, 1, 1),
           attrs={"owner_group": "powerchina"})],
        Project(name="电建项目", owner_group="powerchina", base_date=BASE),
    )
    assert r.status == Status.WARNING.value


def test_rule4_other_group_ban_not_applicable():
    r = OwnerBanRule().evaluate(
        [f(kind="owner_ban", description="别家集团的禁入",
           attrs={"owner_group": "somewhere_else"})],
        Project(name="电建项目", owner_group="powerchina", base_date=BASE),
    )
    assert r.status == Status.NO_DATA.value


def test_rule5_surface_expired_alone_never_fails():
    r = LicenseValidityRule().evaluate(
        [f(kind="license_surface_expired", description="(川)JZ安许证字〔2023〕007346 载明至2026-04-17")],
        PROJECT,
    )
    assert r.status == Status.WARNING.value


def test_rule5_surface_expired_but_authority_extended_no_fail():
    r = LicenseValidityRule().evaluate(
        [f(kind="license_surface_expired", description="扫描件过期"),
         f(kind="license_authority_status", description="官方已延期",
           attrs={"status": "延期"})],
        PROJECT,
    )
    assert r.status == Status.WARNING.value
    assert any("不能判企业无证" in x for x in r.reasons)


def test_rule5_authority_revoked_fails():
    r = LicenseValidityRule().evaluate(
        [f(kind="license_authority_status", description="主管部门显示吊销",
           attrs={"status": "吊销"})],
        PROJECT,
    )
    assert r.status == Status.FAIL.value


def test_engine_overall_never_promotes_failure_to_pass():
    engine = RuleEngine()
    results = engine.run_all(
        [f(kind="bankruptcy_status", description="破产",
           attrs={"current": True, "state": "宣告破产"})],
        PROJECT,
    )
    assert engine.overall(results) == Status.FAIL.value
