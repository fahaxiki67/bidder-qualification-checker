"""P3 全国数据源 adapter 骨架测试：全部 fixture/mock，不访问真实政府网站。

覆盖：注册表 adapter 路径可加载、query_url 缺失→MANUAL、传输异常→TIMEOUT/ERROR/
BLOCKED（绝不 PASS）、空结果→NO_DATA、解析失败→ERROR、SSRF 拦截且不发请求、
抽取的 Finding 能被 RuleEngine 正确评判、gsxt 验证码源一律 MANUAL。
"""
import json
from datetime import date
from pathlib import Path

import pytest

import app
from app.core.models import Company, Project, SourceRef
from app.core.registry import SourceRegistry
from app.core.rules import RuleEngine
from app.core.status import NEVER_PASS, Status
from app.sources.national.base import (
    TransportError,
    TransportStatus,
    TransportTimeout,
    fetch,
    load_adapter,
    query_source,
)

REGISTRY = SourceRegistry.from_yaml(
    Path(app.__file__).resolve().parent / "config" / "sources_registry.yaml")
NATIONAL = REGISTRY.filter(level="national")
COMPANY = Company(name="测试建筑有限公司", uscc="91510000TEST0000XX")
SUBJ = {"subject_name": "测试建筑有限公司", "subject_uscc": "91510000TEST0000XX"}

PROJECT = Project(name="测试项目", base_date=date(2026, 9, 4))


def source_with(sid: str, query_url: str | None = None, **kw) -> SourceRef:
    base = next(e for e in NATIONAL if e.id == sid)
    return SourceRef(**{**base.__dict__, "query_url": query_url, **kw})


def get_ok(payload) -> object:
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return lambda url, timeout: (200, body)


def rule_status(rule_id: str, findings) -> Status:
    result = next(r for r in RuleEngine().run_all(findings, PROJECT, COMPANY)
                  if r.rule_id == rule_id)
    return Status(result.status)


# ── 注册表与骨架约定 ────────────────────────────────────────────────

def test_registry_national_adapter_paths_resolve():
    assert {e.id for e in NATIONAL} == {
        "gsxt", "creditchina", "zxgk", "mem_safety_credit", "jzsc", "pcczdc"}
    for e in NATIONAL:
        assert load_adapter(e).source_id == e.id


def test_adapter_source_id_mismatch_rejected():
    bogus = SourceRef(**{**source_with("creditchina").__dict__, "id": "zxgk"})
    with pytest.raises(ValueError, match="不一致"):
        load_adapter(bogus)


def test_missing_query_url_is_manual_for_all_national_sources():
    """查询接口未人工复核（query_url 空）一律 MANUAL，绝不假装能查。"""
    for e in NATIONAL:
        out = query_source(e, COMPANY)
        assert out.status is Status.MANUAL and not out.findings


def test_gsxt_manual_even_with_query_url():
    out = query_source(
        source_with("gsxt", "https://www.gsxt.gov.cn/x"), COMPANY, get=get_ok({}))
    assert out.status is Status.MANUAL
    assert "验证码" in out.note


# ── 传输层状态映射：失败绝不归约 PASS ───────────────────────────────

def _query_zxgk_with(getter):
    """zxgk 注册表为 auto_fill_manual_verify（有验证码，另测）；
    传输层/解析用 auto 假设态（复核联调后的形态）单测管线本身。"""
    return query_source(
        source_with("zxgk", "https://zxgk.court.gov.cn/q", automation_mode="auto"),
        COMPANY, get=getter)


@pytest.mark.parametrize("exc,expected", [
    (TransportTimeout(), Status.TIMEOUT),
    (TransportStatus(403, "waf"), Status.BLOCKED),
    (TransportStatus(429), Status.BLOCKED),
    (TransportStatus(500), Status.ERROR),
    (TransportError("connection refused"), Status.ERROR),
])
def test_transport_failures_map_and_never_pass(exc, expected):
    def broken(url, timeout):
        raise exc
    out = _query_zxgk_with(broken)
    assert out.status is expected
    assert out.status in NEVER_PASS


def test_http_204_counts_as_success_but_no_data():
    out = _query_zxgk_with(lambda url, timeout: (200, json.dumps({})))
    assert out.status is Status.NO_DATA  # 查询成功但未检索到记录 ≠ PASS


def test_parse_failure_is_error_not_success():
    out = query_source(
        source_with("creditchina", "https://www.creditchina.gov.cn/q"),
        COMPANY, get=lambda url, timeout: (200, "<html>not json</html>"))
    assert out.status is Status.ERROR
    assert "解析失败" in out.note


def test_ssrf_blocked_url_never_requests():
    called = []

    def spy(url, timeout):
        called.append(url)
        return 200, "{}"

    out = query_source(
        source_with("creditchina", "http://169.254.169.254/latest/meta-data/"),
        COMPANY, get=spy)
    assert out.status is Status.BLOCKED
    assert "SSRF" in out.note
    assert called == []  # 拦截发生在请求前


def test_fetch_non2xx_without_risk_code_is_error():
    res = fetch("https://www.creditchina.gov.cn/q", get=lambda url, t: (502, ""))
    assert res.status is Status.ERROR and res.http_status == 502


# ── 抽取 → RuleEngine 评判联动 ──────────────────────────────────────

def test_creditchina_extracts_penalty_kinds_and_rule_fails():
    payload = {"result": [
        {**SUBJ, "penalty_content": "省级住建主管部门限制投标一年", "authority_level": "province",
         "start_date": "2026-08-05", "end_date": "2027-08-05"},
        {**SUBJ, "penalty_content": "吊销营业执照", "current": True},
        {**SUBJ, "penalty_content": "罚款 5 万元", "start_date": "2026-01-01"},
    ]}
    out = query_source(source_with("creditchina", "https://www.creditchina.gov.cn/q"),
                       COMPANY, get=get_ok(payload))
    assert out.status is Status.PASS
    kinds = [f.kind for f in out.findings]
    assert kinds == ["penalty_bid_restriction", "penalty_business", "penalty_other"]
    assert rule_status("rule_bid_restriction", out.findings) is Status.FAIL
    assert rule_status("rule_business_status", out.findings) is Status.FAIL


def test_creditchina_expired_restriction_is_only_warning():
    payload = {"result": [{**SUBJ, "penalty_content": "限制投标一年", "authority_level": "province",
                           "start_date": "2024-01-01", "end_date": "2025-01-01"}]}
    out = query_source(source_with("creditchina", "https://www.creditchina.gov.cn/q"),
                       COMPANY, get=get_ok(payload))
    assert rule_status("rule_bid_restriction", out.findings) is Status.WARNING


def test_zxgk_extracts_court_records():
    payload = {"dishonest": [{**SUBJ, "case_code": "(2026)川01执100", "court": "成都中院",
                              "file_date": "2026-05-01", "case_note": "有履行能力而拒不履行"}],
               "executed": [{**SUBJ, "case_code": "(2026)川01执200", "amount": "50万元"}]}
    out = _query_zxgk_with(get_ok(payload))
    assert out.status is Status.PASS and len(out.findings) == 2
    assert {f.kind for f in out.findings} == {"court_dishonesty", "court_executed"}


def test_mem_safety_penalty_and_bid_restriction():
    payload = {"penalties": [{**SUBJ, "content": "安全生产许可证被暂扣并限制投标半年",
                              "authority_level": "national",
                              "start_date": "2026-07-01", "end_date": "2026-12-31"}]}
    out = query_source(source_with("mem_safety_credit", "https://www.mem.gov.cn/q"),
                       COMPANY, get=get_ok(payload))
    assert {f.kind for f in out.findings} == {"penalty_safety", "penalty_bid_restriction"}
    assert rule_status("rule_bid_restriction", out.findings) is Status.FAIL


def test_jzsc_license_status_feeds_validity_rule():
    url = "https://jzsc.mohurd.gov.cn/q"
    ok = query_source(source_with("jzsc", url), COMPANY,
                      get=get_ok({"qualifications": [{**SUBJ, "cert_name": "施工总承包一级", "status": "正常"}]}))
    revoked = query_source(source_with("jzsc", url), COMPANY,
                           get=get_ok({"qualifications": [{**SUBJ, "cert_name": "施工总承包一级", "status": "吊销"}]}))
    assert rule_status("rule_license_validity", ok.findings) is Status.NO_DATA
    assert rule_status("rule_license_validity", revoked.findings) is Status.FAIL


def test_pcczdc_bankruptcy_fails_rule():
    payload = {"cases": [{**SUBJ, "state": "宣告破产", "current": True,
                          "case_code": "(2026)川01破5号", "court": "成都中院"}]}
    out = query_source(source_with("pcczdc", "https://pccz.court.gov.cn/q"),
                       COMPANY, get=get_ok(payload))
    assert rule_status("rule_bankruptcy", out.findings) is Status.FAIL
    overall = RuleEngine.overall(RuleEngine().run_all(out.findings, PROJECT, COMPANY))
    assert overall == "FAIL"
