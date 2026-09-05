"""Web 表单输入校验（0.18.1 复核修复）：非法输入显式 400，绝不静默降级。

背景（外部复核）：Web 接口曾直接信任 scenario 等表单字符串——未知场景落到
mock 兜底分支返回空列表，效果近似"无异常"，手工构造 scenario=anything 会被
静默当作干净场景出结论。本轮锁死：场景白名单、名称非空、USCC 归一化+校验位、
条款白名单、复核人必填。
"""
import importlib
import sqlite3

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "data" / "t.sqlite3"
    monkeypatch.setenv("BQC_DB", str(db))
    import app.web.server as server
    importlib.reload(server)
    from fastapi.testclient import TestClient
    return TestClient(server.app), db


def _post(client, **overrides):
    data = {"project_name": "某项目", "base_date": "2026-09-05",
            "company_name": "某公司", "scenario": "clean"}
    data.update(overrides)
    return client.post("/projects", data=data, follow_redirects=False)


def test_unknown_scenario_returns_400(client):
    c, _ = client
    r = _post(c, scenario="anything")  # 手工构造的非法场景
    assert r.status_code == 400 and "未知测试场景" in r.text


def test_blank_company_name_returns_400(client):
    c, _ = client
    assert _post(c, company_name="   ").status_code == 400
    assert _post(c, project_name="   ").status_code == 400
    # 全空字符串被 FastAPI 必填校验先拦下（422 同属拒绝，语义一致）
    assert _post(c, project_name="").status_code == 422


def test_uscc_is_normalized_before_lookup(client):
    """USCC 去空格转大写后落库/查重：小写+空格录入与规范录入必须是同一家企业。"""
    c, db = client
    r1 = _post(c, uscc=" 91510112macd5cdj9f ")  # 故意小写+首尾空格
    assert r1.status_code == 303
    r2 = _post(c, uscc="91510112MACD5CDJ9F")  # 规范写法
    assert r2.status_code == 303
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT uscc FROM companies").fetchall()
    finally:
        conn.close()
    assert rows == [("91510112MACD5CDJ9F",)]  # 归一化后唯一，不得产生重复企业


def test_invalid_uscc_returns_400(client):
    c, _ = client
    # 校验位不符（末位应为 F）
    r = _post(c, uscc="91510112MACD5CDJ9E")
    assert r.status_code == 400 and "校验位" in r.text
    # 字符集非法（S 不在 GB 32100 字符集）
    r2 = _post(c, uscc="91510000TEST0000XX")
    assert r2.status_code == 400


def test_terms_outside_whitelist_returns_400(client):
    """terms 必须来自规则白名单（rules.yaml 条款号），白名单外拒绝。"""
    c, _ = client
    r = _post(c, terms=["条款1", "自创条款X"])
    assert r.status_code == 400 and "未知资格条款" in r.text
    ok = _post(c, terms=["条款1"])
    assert ok.status_code == 303


def test_blank_reviewer_returns_400(client):
    """人工复核：复核人 strip 后不得为空。"""
    c, db = client
    r = _post(c)  # 先建一条核查
    assert r.status_code == 303
    conn = sqlite3.connect(db)
    try:
        qid = conn.execute("SELECT id FROM source_queries").fetchone()[0]
        pcid = conn.execute("SELECT id FROM project_companies").fetchone()[0]
    finally:
        conn.close()
    bad = c.post(f"/checks/{pcid}/review", data={
        "query_id": str(qid), "reviewer": "  ", "decision": "确认无误"})
    assert bad.status_code == 400
    ok = c.post(f"/checks/{pcid}/review", data={
        "query_id": str(qid), "reviewer": " 张工 ", "decision": "确认无误"},
        follow_redirects=False)
    assert ok.status_code == 303
