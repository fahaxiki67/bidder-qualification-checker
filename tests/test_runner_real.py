"""runner 真实数据源链路测试：全部注入传输层（get），不访问真实政府网站。

覆盖：真实链路按注册表逐源执行并落库真实查询状态（PASS/MANUAL/TIMEOUT…）、
源失败状态折算进总体结论（绝不归约 PASS）、nightly_mock_only 门控拒绝真实查询、
mock 链路 query_error 场景总体结论=ERROR（不再被吞成 NO_DATA）。
"""
import json
from pathlib import Path

import pytest
import yaml

from app.core import runner
from app.core.db import connect, init_db
from app.core.runner import run_check
from app.sources.national.base import TransportTimeout

REGISTRY = {
    "sources": [
        {"id": "creditchina", "name": "信用中国", "level": "national",
         "automation_mode": "auto",
         "official_home": "https://www.creditchina.gov.cn/",
         "query_url": "https://www.creditchina.gov.cn/q",
         "adapter": "app.sources.national.creditchina"},
        {"id": "zxgk", "name": "执行信息公开网", "level": "national",
         "automation_mode": "auto_fill_manual_verify",
         "official_home": "https://zxgk.court.gov.cn/",
         "adapter": "app.sources.national.zxgk"},
    ]
}

SUBJ = {"subject_name": "测试公司", "subject_uscc": "91510000TEST0000XX"}
FIXTURE = {"result": [{**SUBJ, "penalty_content": "省级住建主管部门限制投标一年",
                       "authority_level": "province",
                       "start_date": "2026-08-05", "end_date": "2027-08-05"}]}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    reg = tmp_path / "sources_registry.yaml"
    reg.write_text(yaml.safe_dump(REGISTRY, allow_unicode=True), encoding="utf-8")
    app_yaml = tmp_path / "app.yaml"
    app_yaml.write_text("nightly_mock_only: false\n", encoding="utf-8")
    monkeypatch.setattr(runner, "REGISTRY_YAML", reg)
    monkeypatch.setattr(runner, "APP_YAML", app_yaml)
    db = tmp_path / "t.sqlite3"
    init_db(db)
    conn = connect(db)
    cur = conn.execute(
        "INSERT INTO projects (name, base_date, years_back, terms) VALUES ('p','2026-09-04',3,'条款1')")
    pid = cur.lastrowid
    cur = conn.execute("INSERT INTO companies (name, uscc) VALUES ('测试公司','91510000TEST0000XX')")
    cid = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO project_companies (project_id, company_id, status) VALUES (?,?, 'running')",
        (pid, cid))
    pcid = cur.lastrowid
    conn.commit()
    conn.close()
    return db, pcid


def _query_rows(db, pcid):
    conn = connect(db)
    conn.row_factory = __import__("sqlite3").Row
    try:
        return [dict(r) for r in conn.execute(
            "SELECT source_id, status, raw_json FROM source_queries ORDER BY id")]
    finally:
        conn.close()


def test_real_sources_query_success_and_manual(env):
    db, pcid = env
    overall = run_check(db, pcid, real_sources=True,
                        get=lambda url, t: (200, json.dumps(FIXTURE)))
    assert overall == "FAIL"  # A 级省级限制投标在有效期内 → 条款1 FAIL
    rows = {r["source_id"]: r for r in _query_rows(db, pcid)}
    assert rows["creditchina"]["status"] == "PASS"
    assert rows["zxgk"]["status"] == "MANUAL"  # query_url 未复核（auto_fill_manual_verify）
    payload = json.loads(rows["creditchina"]["raw_json"])
    assert [f["kind"] for f in payload["findings"]] == ["penalty_bid_restriction"]


def test_real_sources_timeout_folds_into_overall(env, monkeypatch):
    db, pcid = env
    one = {"sources": [REGISTRY["sources"][0]]}  # 单源隔离：只有 creditchina（auto）
    reg = Path(runner.REGISTRY_YAML)
    reg.write_text(yaml.safe_dump(one, allow_unicode=True), encoding="utf-8")

    def slow(url, t):
        raise TransportTimeout()
    overall = run_check(db, pcid, real_sources=True, get=slow)
    assert overall == "TIMEOUT"  # 规则层全 NO_DATA，但源失败必须顶上来，绝不 PASS
    rows = {r["source_id"]: r for r in _query_rows(db, pcid)}
    assert rows["creditchina"]["status"] == "TIMEOUT"


def test_real_sources_failure_states_combine_by_severity(env):
    """双源：creditchina TIMEOUT + zxgk MANUAL → 总体取最严重 MANUAL（待人工核查）。"""
    db, pcid = env

    def slow(url, t):
        raise TransportTimeout()
    overall = run_check(db, pcid, real_sources=True, get=slow)
    assert overall == "MANUAL"
    rows = {r["source_id"]: r for r in _query_rows(db, pcid)}
    assert rows["creditchina"]["status"] == "TIMEOUT"
    assert rows["zxgk"]["status"] == "MANUAL"


def test_real_sources_refused_under_nightly_mock_only(env, monkeypatch):
    db, pcid = env
    app_yaml = Path(runner.APP_YAML).parent / "app.yaml"
    app_yaml.write_text("nightly_mock_only: true\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="nightly_mock_only"):
        run_check(db, pcid, real_sources=True, get=lambda url, t: (200, "{}"))


def test_real_sources_app_yaml_explicit_override(env, monkeypatch):
    """app_yaml 显式覆盖：白天人工复核场景可越过全局夜间门控，但必须明示传入。"""
    db, pcid = env
    app_yaml = Path(runner.APP_YAML).parent / "app.yaml"
    app_yaml.write_text("nightly_mock_only: true\n", encoding="utf-8")  # 全局=禁
    override = Path(runner.APP_YAML).parent / "app_daytime.yaml"
    override.write_text("nightly_mock_only: false\n", encoding="utf-8")
    # 不传 override → 拒绝；显式传白天配置 → 放行
    with pytest.raises(RuntimeError, match="nightly_mock_only"):
        run_check(db, pcid, real_sources=True, get=lambda url, t: (200, "{}"))
    overall = run_check(db, pcid, real_sources=True, get=lambda url, t: (200, "{}"),
                        app_yaml=override)
    assert overall == "MANUAL"  # query_url 未复核 → 全源 MANUAL，红线语义不变


def test_mock_query_error_overall_is_error(env):
    """修复：查询失败演示场景总体结论=ERROR，不再是 NO_DATA（红线：失败≠无异常）。"""
    db, pcid = env
    assert run_check(db, pcid, scenario="query_error") == "ERROR"
    rows = _query_rows(db, pcid)
    primary = next(r for r in rows if r["source_id"] == "creditchina")
    assert primary["status"] == "ERROR"
    assert run_check(db, pcid, scenario="clean") == "NO_DATA"


# ---------- 0.18.1 复核修复：逐源证据隔离 / 异常兜底（外部复核建议） ----------

TWO_AUTO_REGISTRY = {
    "sources": [
        {"id": "creditchina", "name": "信用中国", "level": "national",
         "automation_mode": "auto",
         "official_home": "https://www.creditchina.gov.cn/",
         "query_url": "https://www.creditchina.gov.cn/q",
         "adapter": "app.sources.national.creditchina"},
        {"id": "mem_safety_credit", "name": "应急部安全信用", "level": "national",
         "automation_mode": "auto",
         "official_home": "https://www.mem.gov.cn/",
         "query_url": "https://www.mem.gov.cn/q",
         "adapter": "app.sources.national.mem"},
    ]
}

BODY_A = json.dumps({"result": []})  # creditchina 契约：无记录
BODY_B = json.dumps({"penalties": [  # mem 契约：一条省级限制投标
    {**SUBJ, "content": "省级住建主管部门限制投标一年",
     "authority_level": "province", "start_date": "2026-08-05",
     "end_date": "2027-08-05"}]})


@pytest.fixture()
def two_auto_env(tmp_path, monkeypatch):
    reg = tmp_path / "sources_registry.yaml"
    reg.write_text(yaml.safe_dump(TWO_AUTO_REGISTRY, allow_unicode=True), encoding="utf-8")
    app_yaml = tmp_path / "app.yaml"
    app_yaml.write_text("nightly_mock_only: false\n", encoding="utf-8")
    monkeypatch.setattr(runner, "REGISTRY_YAML", reg)
    monkeypatch.setattr(runner, "APP_YAML", app_yaml)
    db = tmp_path / "t.sqlite3"
    init_db(db)
    conn = connect(db)
    cur = conn.execute(
        "INSERT INTO projects (name, base_date, years_back, terms) VALUES ('p','2026-09-05',3,'条款1')")
    pid = cur.lastrowid
    cur = conn.execute("INSERT INTO companies (name, uscc) VALUES ('测试公司','91510000TEST0000XX')")
    cid = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO project_companies (project_id, company_id, status) VALUES (?,?, 'running')",
        (pid, cid))
    pcid = cur.lastrowid
    conn.commit()
    conn.close()
    return db, pcid


def _evidence_rows(db):
    conn = connect(db)
    conn.row_factory = __import__("sqlite3").Row
    try:
        return [dict(r) for r in conn.execute(
            "SELECT source_id, query_id, file_path, sha256 FROM evidence WHERE kind='raw_response'")]
    finally:
        conn.close()


def test_each_source_saves_its_own_raw_response(two_auto_env):
    """两个源返回不同正文，证据文件必须分别对应各自正文（串源=证据链不可信）。"""
    db, pcid = two_auto_env

    def get(url, t):
        return (200, BODY_B if "mem.gov.cn" in url else BODY_A)

    run_check(db, pcid, real_sources=True, get=get)
    rows = {r["source_id"]: r for r in _evidence_rows(db)}
    assert set(rows) == {"creditchina", "mem_safety_credit"}
    from pathlib import Path as _P
    assert _P(rows["creditchina"]["file_path"]).read_text(encoding="utf-8") == BODY_A
    assert _P(rows["mem_safety_credit"]["file_path"]).read_text(encoding="utf-8") == BODY_B


def test_last_manual_source_does_not_discard_previous_evidence(env):
    """尾源（manual 无原文）不得让前面成功源的证据全部丢失（旧实现落证 0 份）。"""
    db, pcid = env
    run_check(db, pcid, real_sources=True, get=lambda url, t: (200, json.dumps(FIXTURE)))
    rows = _evidence_rows(db)
    assert [r["source_id"] for r in rows] == ["creditchina"]
    from pathlib import Path as _P
    assert _P(rows[0]["file_path"]).read_text(encoding="utf-8") == json.dumps(FIXTURE)


def test_all_source_exceptions_do_not_crash_persistence(two_auto_env):
    """全部源传输层异常时应正常落 ERROR，不应出现 UnboundLocalError。"""
    db, pcid = two_auto_env

    def boom(url, t):
        raise RuntimeError("网络不可达")
    overall = run_check(db, pcid, real_sources=True, get=boom)
    rows = {r["source_id"]: r for r in _query_rows(db, pcid)}
    assert rows["creditchina"]["status"] == "ERROR"
    assert rows["mem_safety_credit"]["status"] == "ERROR"
    assert "数据源执行异常" in json.loads(rows["creditchina"]["raw_json"])["note"]
    assert overall == "ERROR"  # 源失败必须顶进总体结论，绝不静默成功
    conn = connect(db)
    try:
        finished = conn.execute(
            "SELECT finished_at, overall_status FROM check_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert finished[0] is not None and finished[1] == "ERROR"
    finally:
        conn.close()
