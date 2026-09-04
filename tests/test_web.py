import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BQC_DB", str(tmp_path / "b.sqlite3"))
    import app.web.server as server
    importlib.reload(server)  # 以 tmp 数据库路径重建 app
    from fastapi.testclient import TestClient
    return TestClient(server.app)


def test_index_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "投标人资格智能核查系统" in r.text
    assert "开始核查" in r.text


def test_full_check_flow_fail(client):
    """建项目 → mock 核查（省级限制投标）→ 结果页 FAIL。"""
    r = client.post("/projects", data={
        "project_name": "广东某电建项目", "province": "广东", "industry": "建筑",
        "owner_group": "powerchina", "base_date": "2026-09-04", "years_back": "3",
        "company_name": "四川某建筑公司", "uscc": "91510112MACD5CDJ9F",
        "registered_province": "四川", "scenario": "bid_ban",
    }, follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("/checks/")
    page = client.get(loc).text
    assert "FAIL" in page
    assert "触发否决条款" in page
    assert "creditchina" in page  # 查询日志可见


def test_check_flow_clean_is_not_fake_pass(client):
    """无记录场景：总体 NO_DATA（未检索到记录），绝不显示“正常”。"""
    r = client.post("/projects", data={
        "project_name": "某项目", "base_date": "2026-09-04", "years_back": "3",
        "company_name": "某公司", "scenario": "clean",
    }, follow_redirects=True)
    assert r.status_code == 200
    assert "NO_DATA" in r.text
    assert "未检索到记录" in r.text
    # 汇总行不允许出现"正常"
    assert ">正常" not in r.text


def test_error_scenario_shown_as_failure(client):
    r = client.post("/projects", data={
        "project_name": "某项目", "base_date": "2026-09-04",
        "company_name": "某公司", "scenario": "clean",
    }, follow_redirects=False)
    pc = r.headers["location"]
    r2 = client.post(pc + "/run", data={"scenario": "query_error"}, follow_redirects=True)
    assert "ERROR" in r2.text
    assert "查询失败" in r2.text
    # ERROR 不得显示为正常
    assert ">正常" not in r2.text


def test_rerun_overwrites_overall(client):
    r = client.post("/projects", data={
        "project_name": "某项目", "base_date": "2026-09-04",
        "company_name": "某公司", "scenario": "clean",
    }, follow_redirects=False)
    pc = r.headers["location"]
    r2 = client.post(pc + "/run", data={"scenario": "bid_ban"}, follow_redirects=True)
    assert "FAIL" in r2.text


def test_duplicate_submit_is_idempotent(client):
    """同项目同企业重复提交（双击/重试）→ 复用记录 303，绝不 500。"""
    data = {"project_name": "重复项目", "base_date": "2026-09-05", "years_back": "3",
            "company_name": "同一公司", "uscc": "91510112MACD5CDJ9F",
            "scenario": "clean"}
    r1 = client.post("/projects", data=data, follow_redirects=False)
    r2 = client.post("/projects", data=data, follow_redirects=False)
    assert r1.status_code == 303 and r2.status_code == 303


def test_years_back_clamped_server_side(monkeypatch, tmp_path):
    """years_back 越界值（99）被服务端钳制到 10（前端 min/max 不可信）。"""
    import sqlite3
    monkeypatch.setenv("BQC_DB", str(tmp_path / "b.sqlite3"))
    importlib.reload(server) if False else None
    import app.web.server as server_mod
    importlib.reload(server_mod)
    from fastapi.testclient import TestClient
    c = TestClient(server_mod.app)
    r = c.post("/projects", data={"project_name": "钳制", "base_date": "2026-09-05",
                                  "years_back": "99", "company_name": "某公司",
                                  "scenario": "clean"}, follow_redirects=False)
    assert r.status_code == 303
    conn = sqlite3.connect(server_mod.DB_PATH)
    v = conn.execute("SELECT years_back FROM projects").fetchone()[0]
    conn.close()
    assert v == 10
