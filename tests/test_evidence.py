"""P6 证据系统测试：落盘+SHA-256 回环、篡改检出、结论回链、人工复核流、名单导入闭环。"""
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
import yaml

import app
from app.core import runner
from app.core.db import connect, init_db
from app.core.evidence import evidence_dir_for, save_evidence, sha256_text, verify_evidence
from app.core.runner import run_check

SUBJ = {"subject_name": "测试建筑有限公司", "subject_uscc": "91510000TEST0000XX"}

REGISTRY = {"sources": [
    {"id": "creditchina", "name": "信用中国", "level": "national",
     "automation_mode": "auto",
     "official_home": "https://www.creditchina.gov.cn/",
     "query_url": "https://www.creditchina.gov.cn/q",
     "adapter": "app.sources.national.creditchina"}]}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    reg = tmp_path / "sources_registry.yaml"
    reg.write_text(yaml.safe_dump(REGISTRY, allow_unicode=True), encoding="utf-8")
    app_yaml = tmp_path / "app.yaml"
    app_yaml.write_text("nightly_mock_only: false\n", encoding="utf-8")
    monkeypatch.setattr(runner, "REGISTRY_YAML", reg)
    monkeypatch.setattr(runner, "APP_YAML", app_yaml)
    db = tmp_path / "data" / "t.sqlite3"
    init_db(db)
    conn = connect(db)
    cur = conn.execute("INSERT INTO projects (name, owner_group, industry, base_date, years_back, terms) "
                       "VALUES ('p','powerchina','建筑','2026-09-05',3,'条款1,条款2,条款3,条款4')")
    pid = cur.lastrowid
    cur = conn.execute("INSERT INTO companies (name, uscc) VALUES ('测试建筑有限公司','91510000TEST0000XX')")
    cid = cur.lastrowid
    cur = conn.execute("INSERT INTO project_companies (project_id, company_id, status) "
                       "VALUES (?,?, 'running')", (pid, cid))
    pcid = cur.lastrowid
    conn.commit()
    conn.close()
    return db, pcid, tmp_path


# ---------- 落盘 + 哈希回环 + 篡改检出 ----------

def test_save_and_verify_roundtrip(tmp_path):
    db = tmp_path / "d" / "t.sqlite3"
    init_db(db)
    eid, fpath, digest = save_evidence(
        db, source_id="creditchina", url="https://x.example/", raw_text="响应原文ABC",
        kind="raw_response", key_text="k")
    assert fpath.is_file() and fpath.parent == evidence_dir_for(db)
    assert digest == sha256_text("响应原文ABC")
    ok, broken = verify_evidence(db, eid)
    assert ok == 1 and broken == []


def test_tamper_is_detected(tmp_path):
    db = tmp_path / "d" / "t.sqlite3"
    init_db(db)
    eid, fpath, _ = save_evidence(db, source_id="creditchina", url=None,
                                  raw_text="原文", kind="raw_response")
    fpath.write_text("被篡改的内容", encoding="utf-8")
    ok, broken = verify_evidence(db, eid)
    assert ok == 0 and broken and broken[0][0] == eid and "哈希不符" in broken[0][1]


def test_missing_file_is_detected(tmp_path):
    db = tmp_path / "d" / "t.sqlite3"
    init_db(db)
    eid, fpath, _ = save_evidence(db, source_id="s", url=None, raw_text="x", kind="k")
    fpath.unlink()
    ok, broken = verify_evidence(db, eid)
    assert ok == 0 and "不可读" in broken[0][1]


# ---------- runner 真实链路落证据 + 结论回链 + 查看器 + 复核流 ----------

FIXTURE = {"result": [{**SUBJ, "penalty_content": "省级住建主管部门限制投标一年",
                       "authority_level": "province",
                       "start_date": "2026-08-05", "end_date": "2027-08-05"}]}


def test_runner_captures_evidence_and_result_links(env, monkeypatch):
    db, pcid, tmp_path = env
    overall = run_check(db, pcid, real_sources=True,
                        get=lambda url, t: (200, json.dumps(FIXTURE)))
    assert overall == "FAIL"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        ev = conn.execute("SELECT id, query_id, source_id, sha256, file_path, kind "
                          "FROM evidence WHERE kind='raw_response'").fetchall()
        assert len(ev) == 1
        sq = conn.execute("SELECT id FROM source_queries").fetchone()
        assert ev[0]["query_id"] == sq["id"]  # 证据绑定产生它的那次查询
        assert Path(ev[0]["file_path"]).is_file()
        assert ev[0]["sha256"] == sha256_text(
            Path(ev[0]["file_path"]).read_text(encoding="utf-8"))
    finally:
        conn.close()

    # 结果页回链 + 查看器
    monkeypatch.setenv("BQC_DB", str(db))
    import importlib
    import app.web.server as server
    importlib.reload(server)
    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    page = c.get(f"/checks/{pcid}")
    assert page.status_code == 200 and "证据回链" in page.text and "raw_response" in page.text
    raw = c.get(f"/evidence/{ev[0]['id']}")
    # 证据原文必须逐字保留（原始响应是什么就存什么，不美化不转码）
    assert raw.status_code == 200 and '"result"' in raw.text
    assert c.get("/evidence/99999").status_code == 404


def test_manual_review_flow_records_with_run_id(env, monkeypatch):
    db, pcid, _ = env
    run_check(db, pcid, real_sources=True, get=lambda url, t: (200, json.dumps(FIXTURE)))
    conn = sqlite3.connect(db)
    qid = conn.execute("SELECT id FROM source_queries").fetchone()[0]
    run_id = conn.execute("SELECT run_id FROM check_runs ORDER BY id DESC LIMIT 1").fetchone()[0]
    conn.close()

    monkeypatch.setenv("BQC_DB", str(db))
    import importlib
    import app.web.server as server
    importlib.reload(server)
    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    r = c.post(f"/checks/{pcid}/review", data={
        "query_id": str(qid), "reviewer": "张工", "decision": "确认无误", "note": "与官网一致"},
        follow_redirects=False)
    assert r.status_code == 303
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM manual_reviews").fetchone()
    conn.close()
    assert row["query_id"] == qid and row["run_id"] == run_id  # 复核绑定核查批次
    assert row["reviewer"] == "张工" and row["decision"] == "确认无误"
    page = c.get(f"/checks/{pcid}")
    assert "张工" in page.text and "确认无误" in page.text
    # 非法 decision 拒绝
    r2 = c.post(f"/checks/{pcid}/review", data={
        "query_id": str(qid), "reviewer": "x", "decision": "随便写"})
    assert r2.status_code == 400


# ---------- 名单导入闭环（P4 承诺的入口） ----------

def _setup_owner_env(tmp_path, monkeypatch):
    reg = tmp_path / "sources_registry.yaml"
    reg.write_text(yaml.safe_dump({"sources": [
        {"id": "powerchina_ban", "name": "中国电建禁入名单", "level": "owner",
         "owner_group": "powerchina", "automation_mode": "manual_intake",
         "official_home": "https://ec.powerchina.cn/",
         "adapter": "app.sources.owners.powerchina"}]}, allow_unicode=True), encoding="utf-8")
    app_yaml = tmp_path / "app.yaml"
    app_yaml.write_text("nightly_mock_only: false\n", encoding="utf-8")
    monkeypatch.setattr(runner, "REGISTRY_YAML", reg)
    monkeypatch.setattr(runner, "APP_YAML", app_yaml)
    db = tmp_path / "data" / "t.sqlite3"
    init_db(db)
    conn = connect(db)
    cur = conn.execute("INSERT INTO projects (name, owner_group, base_date, years_back, terms) "
                       "VALUES ('p','powerchina','2026-09-05',3,'条款1,条款2,条款3,条款4')")
    pid = cur.lastrowid
    cur = conn.execute("INSERT INTO companies (name, uscc) VALUES ('测试建筑有限公司','91510000TEST0000XX')")
    cid = cur.lastrowid
    cur = conn.execute("INSERT INTO project_companies (project_id, company_id, status) "
                       "VALUES (?,?, 'running')", (pid, cid))
    pcid = cur.lastrowid
    conn.commit()
    conn.close()
    return db, pcid, tmp_path


def test_import_bans_then_run_adjudicates_offline(tmp_path, monkeypatch):
    """导入有效期内名单 → 核查：条款4 FAIL（decision）+ MANUAL 保留（data/manual）+ 证据回链。"""
    db, pcid, tmp_path = _setup_owner_env(tmp_path, monkeypatch)
    bans = {"bans": [{**SUBJ, "list_level": "股份公司级", "scope": "全部",
                      "ban_start": "2026-06-01", "ban_end": "2029-06-01",
                      "document_name": "2026年第一批禁入名单"}]}
    ban_file = tmp_path / "bans.json"
    ban_file.write_text(json.dumps(bans, ensure_ascii=False), encoding="utf-8")

    from app.main import main as cli
    rc = cli(["import-bans", str(ban_file), "--db", str(db)])
    assert rc == 0

    overall = run_check(db, pcid, real_sources=True)
    # 人工证据触发条款4 → decision FAIL；源状态保持 MANUAL（人工确认语义）
    assert overall == "FAIL"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        run = conn.execute("SELECT decision_status, data_status, manual_required "
                           "FROM check_runs ORDER BY id DESC LIMIT 1").fetchone()
        assert run["decision_status"] == "FAIL" and run["data_status"] == "MANUAL"
        assert run["manual_required"] == 1
        rule = conn.execute("SELECT status FROM rule_results WHERE rule_id='rule_owner_ban'").fetchone()
        assert rule["status"] == "FAIL"
    finally:
        conn.close()


def test_import_bans_wrong_subject_never_binds(tmp_path, monkeypatch):
    """导入同名不同码名单 → 不得形成证据（引擎双拦截）。"""
    db, pcid, tmp_path = _setup_owner_env(tmp_path, monkeypatch)
    bans = {"bans": [{"subject_name": "测试建筑有限公司", "subject_uscc": "91510000BBBB0000BB",
                      "list_level": "股份公司级", "scope": "全部",
                      "ban_start": "2026-06-01", "ban_end": "2029-06-01"}]}
    f = tmp_path / "bans.json"
    f.write_text(json.dumps(bans, ensure_ascii=False), encoding="utf-8")
    from app.main import main as cli
    assert cli(["import-bans", str(f), "--db", str(db)]) == 0
    overall = run_check(db, pcid, real_sources=True)
    conn = sqlite3.connect(db)
    try:
        n = conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
        assert n == 0  # 非同一主体的名单记录不产生任何 Finding
    finally:
        conn.close()
    assert overall == "MANUAL"
