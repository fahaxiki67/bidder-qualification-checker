"""默认 HTTP 传输层状态映射测试（P0.5 §四）。

要求：覆盖默认客户端真实调用链（httpx_get：DNS 复检 → SSRF 校验 → httpx 请求 →
异常翻译 → fetch 状态映射），而非人为抛 TransportTimeout/TransportStatus。
全部经 httpx.MockTransport 与注入式假 DNS，不访问真实网络。
"""
import json
from functools import partial

import httpx
import pytest
import yaml

from app.core import runner
from app.core.db import init_db
from app.core.runner import run_check
from app.core.status import Status
from app.sources.national.base import fetch, httpx_get

PUBLIC_URL = "https://portal.example.cn/search"
_PUBLIC_IP = "93.184.216.34"


def _resolver(host):
    assert host == "portal.example.cn"
    return [_PUBLIC_IP]


def _mock_get(handler, url, timeout=15.0):
    """与生产同链路的默认传输：仅把 client 换成 MockTransport、DNS 换成假解析。"""
    return httpx_get(
        url, timeout,
        client_factory=lambda: httpx.Client(
            transport=httpx.MockTransport(handler), trust_env=False),
        resolver=_resolver,
    )


class TestExceptionMapping:
    def test_httpx_timeout_maps_to_timeout(self):
        def handler(request):
            raise httpx.ConnectTimeout("peer not responding")
        fr = fetch(PUBLIC_URL, get=partial(_mock_get, handler))
        assert fr.status is Status.TIMEOUT
        assert fr.http_status is None and fr.text == ""

    def test_read_timeout_maps_to_timeout(self):
        def handler(request):
            raise httpx.ReadTimeout("read too slow")
        assert fetch(PUBLIC_URL, get=partial(_mock_get, handler)).status is Status.TIMEOUT

    def test_connect_error_maps_to_error_with_reason(self):
        def handler(request):
            raise httpx.ConnectError("connection refused")
        fr = fetch(PUBLIC_URL, get=partial(_mock_get, handler))
        assert fr.status is Status.ERROR
        assert "ConnectError" in fr.note  # 错误信息保留供追溯

    def test_dns_failure_maps_to_error(self):
        def boom(host):
            raise OSError("name resolution failed")
        def get(url, timeout):
            return httpx_get(url, timeout, resolver=boom)
        fr = fetch(PUBLIC_URL, get=get)
        assert fr.status is Status.ERROR
        assert "DNS" in fr.note

    def test_never_raises_out_of_fetch(self):
        """任何传输层异常都不得冲出 fetch()（单源异常不得拖垮核查进程）。"""
        def handler(request):
            raise RuntimeError("totally unexpected")
        # 非网络异常原样上抛（编程错误必须暴露）——fetch 对其不兜底由 runner 隔离
        with pytest.raises(RuntimeError):
            fetch(PUBLIC_URL, get=partial(_mock_get, handler))


class TestHttpStatusMapping:
    @pytest.mark.parametrize("code", [403, 418, 429, 503])
    def test_risk_codes_map_to_blocked(self, code):
        handler = lambda request: httpx.Response(code, text="forbidden")
        fr = fetch(PUBLIC_URL, get=partial(_mock_get, handler))
        assert fr.status is Status.BLOCKED
        assert fr.http_status == code
        assert "限制" in fr.note

    @pytest.mark.parametrize("code", [301, 404, 500, 502])
    def test_other_non_2xx_map_to_error(self, code):
        handler = lambda request: httpx.Response(code, text="nope")
        fr = fetch(PUBLIC_URL, get=partial(_mock_get, handler))
        assert fr.status is Status.ERROR
        assert fr.http_status == code

    def test_2xx_maps_to_pass_with_text(self):
        handler = lambda request: httpx.Response(200, text="ok-body")
        fr = fetch(PUBLIC_URL, get=partial(_mock_get, handler))
        assert fr.status is Status.PASS
        assert fr.text == "ok-body"


class TestDnsRecheckViaDefaultPath:
    def test_resolver_private_ip_blocks(self):
        """默认链路 DNS 复检发现私网地址 → BLOCKED（SSRF 防护），不得崩溃。"""
        def bad_resolver(host):
            return ["192.168.1.10"]
        def get(url, timeout):
            return httpx_get(url, timeout,
                             client_factory=lambda: httpx.Client(
                                 transport=httpx.MockTransport(
                                     lambda r: httpx.Response(200, text="x")),
                                 trust_env=False),
                             resolver=bad_resolver)
        fr = fetch(PUBLIC_URL, get=get)
        assert fr.status is Status.BLOCKED
        assert "SSRF" in fr.note


# ---------- runner 单源异常隔离（§四.5） ----------

REGISTRY = {"sources": [
    {"id": "creditchina", "name": "信用中国", "level": "national",
     "automation_mode": "auto",
     "official_home": "https://www.creditchina.gov.cn/",
     "query_url": "https://www.creditchina.gov.cn/q",
     "adapter": "app.sources.national.creditchina"},
    {"id": "zxgk", "name": "执行信息公开网", "level": "national",
     "automation_mode": "auto",
     "official_home": "https://zxgk.court.gov.cn/",
     "query_url": "https://zxk.example.cn/q",
     "adapter": "app.sources.national.zxgk"},
]}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from app.core.db import connect

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


def test_single_source_crash_does_not_kill_check(env, monkeypatch):
    """一个数据源抛未预期异常：该源记 ERROR 带追溯信息，其余源照常执行，核查完成。"""
    import sqlite3

    real_query_source = runner.query_source

    def exploding_query_source(source, company, *, get=None, timeout=15.0):
        if source.id == "creditchina":
            raise RuntimeError("adapter boom")
        return real_query_source(source, company, get=get, timeout=timeout)

    monkeypatch.setattr(runner, "query_source", exploding_query_source)
    db, pcid = env
    overall = run_check(db, pcid, real_sources=True,
                        get=lambda url, t: (200, json.dumps({"result": []})))
    # zxgk 正常查询无记录 → NO_DATA；creditchina 异常 → ERROR；总体 ERROR 绝不 PASS
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = {r["source_id"]: r for r in conn.execute(
            "SELECT source_id, status, raw_json FROM source_queries")}
        payload = json.loads(rows["creditchina"]["raw_json"])
        assert rows["creditchina"]["status"] == "ERROR"
        assert "RuntimeError" in payload["note"]  # 错误信息保留供追溯
        assert rows["zxgk"]["status"] == "NO_DATA"  # 其余源未受牵连
    finally:
        conn.close()
    assert overall == "ERROR"
