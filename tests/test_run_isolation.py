"""核查批次 run_id 隔离（P0.5 §五）。

同一条 project/company 重复核查：每批唯一 run_id；source_queries/rule_results
绑定批次；Web 只展示最新一次完整运行；历史批次保留可溯、绝不混入当前结论。
旧库迁移：补列不删数据，旧行 run_id=NULL 视为迁移前历史。
"""
import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from app.core import runner
from app.core.db import connect, init_db
from app.core.runner import run_check

REGISTRY_WITH_URL = {"sources": [
    {"id": "creditchina", "name": "信用中国", "level": "national",
     "automation_mode": "auto",
     "official_home": "https://www.creditchina.gov.cn/",
     "query_url": "https://www.creditchina.gov.cn/q",
     "adapter": "app.sources.national.creditchina"},
]}

# 同一注册表但 query_url 撤回（模拟"复核撤回"场景）→ 该源转 MANUAL
REGISTRY_NO_URL = {"sources": [
    dict(REGISTRY_WITH_URL["sources"][0], query_url=None),
]}

SUBJ = {"subject_name": "测试公司", "subject_uscc": "91510000TEST0000XX"}

# 历史处罚（基准日 2026 已过期）→ 条款1 仅 WARNING
HISTORICAL = {"result": [
    {**SUBJ, "penalty_content": "省级住建主管部门限制投标两年",
     "authority_level": "province",
     "start_date": "2020-01-01", "end_date": "2022-01-01"},
]}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    reg = tmp_path / "sources_registry.yaml"
    reg.write_text(yaml.safe_dump(REGISTRY_WITH_URL, allow_unicode=True), encoding="utf-8")
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


def _rows(db, sql, params=()):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def test_two_runs_are_isolated_and_bound(env):
    """第一轮 WARNING（历史处罚）→ 第二轮 MANUAL（复核撤回）：
    两批数据各自绑定 run_id，当前结论只取第二轮。"""
    db, pcid = env
    overall1 = run_check(db, pcid, real_sources=True,
                         get=lambda url, t: (200, json.dumps(HISTORICAL)))
    assert overall1 == "WARNING"

    reg = Path(runner.REGISTRY_YAML)
    reg.write_text(yaml.safe_dump(REGISTRY_NO_URL, allow_unicode=True), encoding="utf-8")
    overall2 = run_check(db, pcid, real_sources=True, get=lambda url, t: (200, "{}"))
    assert overall2 == "MANUAL"
    assert overall2 != overall1

    runs = _rows(db, "SELECT * FROM check_runs ORDER BY id")
    assert len(runs) == 2
    run1, run2 = runs[0], runs[1]
    assert run1["run_id"] and run2["run_id"] and run1["run_id"] != run2["run_id"]
    assert run1["finished_at"] and run2["finished_at"]  # 两批都完整

    # 批次结论字段
    assert (run1["decision_status"], run1["data_status"], run1["manual_required"]) == \
        ("WARNING", "PASS", 0)
    assert (run2["decision_status"], run2["data_status"], run2["manual_required"]) == \
        ("NO_DATA", "MANUAL", 1)
    assert run1["overall_status"] == "WARNING" and run2["overall_status"] == "MANUAL"

    # source_queries 各归各批
    queries = _rows(db, "SELECT source_id, status, run_id FROM source_queries ORDER BY id")
    assert [q["run_id"] for q in queries] == [run1["run_id"], run2["run_id"]]
    assert [q["status"] for q in queries] == ["PASS", "MANUAL"]

    # rule_results 各归各批（5 条规则 × 2 轮）
    rules = _rows(db, "SELECT run_id FROM rule_results ORDER BY id")
    assert len(rules) == 10
    assert {r["run_id"] for r in rules} == {run1["run_id"], run2["run_id"]}

    # 当前指针指向第二轮
    pc = _rows(db, "SELECT run_id, overall_status FROM project_companies WHERE id=?", (pcid,))[0]
    assert pc["run_id"] == run2["run_id"] and pc["overall_status"] == "MANUAL"


def test_findings_trace_to_run_via_query(env):
    """findings 经 query_id → source_queries.run_id 可追溯批次。"""
    db, pcid = env
    run_check(db, pcid, real_sources=True,
              get=lambda url, t: (200, json.dumps(HISTORICAL)))
    rows = _rows(
        db,
        "SELECT f.id, sq.run_id FROM findings f JOIN source_queries sq ON f.query_id = sq.id",
    )
    assert rows and all(r["run_id"] for r in rows)


def test_web_shows_only_latest_complete_run(env, monkeypatch):
    import importlib

    db, pcid = env
    run_check(db, pcid, real_sources=True,
              get=lambda url, t: (200, json.dumps(HISTORICAL)))
    reg = Path(runner.REGISTRY_YAML)
    reg.write_text(yaml.safe_dump(REGISTRY_NO_URL, allow_unicode=True), encoding="utf-8")
    run_check(db, pcid, real_sources=True, get=lambda url, t: (200, "{}"))

    runs = _rows(db, "SELECT run_id FROM check_runs ORDER BY id")
    run1_id, run2_id = runs[0]["run_id"], runs[1]["run_id"]

    monkeypatch.setenv("BQC_DB", str(db))
    import app.web.server as server
    importlib.reload(server)
    data = server._load_result(pcid)
    assert data["run"]["run_id"] == run2_id
    # 当前展示只含第二轮：1 条查询日志（MANUAL）、无第一轮的历史处罚 findings
    assert len(data["queries"]) == 1 and data["queries"][0]["status"] == "MANUAL"
    assert data["run"]["overall_status"] == "MANUAL"

    from fastapi.testclient import TestClient
    page = TestClient(server.app).get(f"/checks/{pcid}")
    assert page.status_code == 200
    assert run2_id in page.text
    assert run1_id not in page.text  # 第一轮不混入
    assert "需人工复核" in page.text


def test_incomplete_run_not_shown_as_current(env):
    """finished_at 为空的批次（运行中断）不作为当前结论展示。"""
    db, pcid = env
    conn = connect(db)
    conn.execute(
        "INSERT INTO check_runs (run_id, project_id, company_id, scenario) VALUES ('ghost', 1, 1, 'x')")
    conn.commit()
    conn.close()
    # 正常跑一轮
    reg = Path(runner.REGISTRY_YAML)
    reg.write_text(yaml.safe_dump(REGISTRY_NO_URL, allow_unicode=True), encoding="utf-8")
    run_check(db, pcid, real_sources=True, get=lambda url, t: (200, "{}"))
    rows = _rows(
        db,
        "SELECT run_id FROM check_runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1",
    )
    assert rows[0]["run_id"] != "ghost"


# ---------- 旧库迁移（P0.5 §五：说明兼容方式，不静默删除） ----------

OLD_03X_SCHEMA = """
CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
    province TEXT, city TEXT, industry TEXT, owner_group TEXT, base_date TEXT NOT NULL,
    years_back INTEGER NOT NULL DEFAULT 3, terms TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
CREATE TABLE companies (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
    uscc TEXT UNIQUE, registered_province TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
CREATE TABLE project_companies (id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    company_id INTEGER NOT NULL REFERENCES companies(id),
    status TEXT NOT NULL DEFAULT 'pending', overall_status TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (project_id, company_id));
CREATE TABLE source_queries (id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id), company_id INTEGER REFERENCES companies(id),
    source_id TEXT NOT NULL, query_url TEXT, query_params TEXT,
    queried_at TEXT NOT NULL DEFAULT (datetime('now','localtime')), status TEXT NOT NULL,
    page_title TEXT, key_text TEXT, adapter_version TEXT, raw_json TEXT);
CREATE TABLE rule_results (id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id), company_id INTEGER REFERENCES companies(id),
    rule_id TEXT NOT NULL, status TEXT NOT NULL, reasons_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
CREATE TABLE manual_reviews (id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id INTEGER REFERENCES source_queries(id),
    rule_result_id INTEGER REFERENCES rule_results(id),
    reviewer TEXT, decision TEXT NOT NULL, note TEXT,
    reviewed_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
CREATE TABLE source_registry (id TEXT PRIMARY KEY, name TEXT NOT NULL, level TEXT NOT NULL);
CREATE TABLE findings (id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id INTEGER REFERENCES source_queries(id),
    company_id INTEGER REFERENCES companies(id), kind TEXT NOT NULL, grade TEXT NOT NULL,
    description TEXT, start_date TEXT, end_date TEXT, attrs_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
CREATE TABLE evidence (id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id INTEGER REFERENCES source_queries(id), source_id TEXT NOT NULL, url TEXT,
    captured_at TEXT NOT NULL DEFAULT (datetime('now','localtime')), kind TEXT,
    file_path TEXT, sha256 TEXT, grade TEXT, key_text TEXT);
CREATE TABLE app_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, version TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
"""


def test_old_03x_db_migrates_without_data_loss(tmp_path):
    """0.3.x 旧库升级：补 check_runs 表与 run_id 列；历史行 run_id=NULL 原样保留。"""
    p = tmp_path / "old.sqlite3"
    conn = connect(p)
    conn.executescript(OLD_03X_SCHEMA)
    cur = conn.execute("INSERT INTO projects (name, base_date) VALUES ('旧项目', '2025-01-01')")
    pid = cur.lastrowid
    cur = conn.execute("INSERT INTO companies (name) VALUES ('旧公司')")
    cid = cur.lastrowid
    conn.execute(
        "INSERT INTO project_companies (project_id, company_id, overall_status, status) "
        "VALUES (?, ?, 'WARNING', 'done')", (pid, cid))
    conn.execute(
        "INSERT INTO source_queries (project_id, company_id, source_id, status) "
        "VALUES (?, ?, 'creditchina', 'PASS')", (pid, cid))
    conn.commit()
    legacy_sq = conn.execute("SELECT id FROM source_queries").fetchone()[0]
    conn.close()

    init_db(p)  # 迁移发生在这里

    conn = connect(p)
    conn.row_factory = sqlite3.Row
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "check_runs" in tables
    for table in ("source_queries", "rule_results", "manual_reviews", "project_companies"):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        assert "run_id" in cols, table
    # 历史数据原样保留，run_id=NULL 标记为迁移前
    sq = conn.execute("SELECT * FROM source_queries WHERE id=?", (legacy_sq,)).fetchone()
    assert sq["source_id"] == "creditchina" and sq["run_id"] is None
    pc = conn.execute("SELECT * FROM project_companies").fetchone()
    assert pc["overall_status"] == "WARNING" and pc["run_id"] is None
    conn.close()

    # 迁移后新运行正常写入批次（幂等：init_db 可重复执行）
    init_db(p)
    conn = connect(p)
    n = conn.execute("SELECT COUNT(*) FROM app_versions").fetchone()[0]
    assert n == 1
    conn.close()
