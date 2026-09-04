"""单源联调诊断测试（P3R 准备）：门控、未知源、MANUAL 输出、注入查询。

不在测试中访问任何真实站点；真实查询仅由人工白天显式触发。
"""
import json
from pathlib import Path

import pytest
import yaml

from app import diagnostics
from app.core import runner
from app.sources.national.base import query_source


@pytest.fixture()
def reg(tmp_path, monkeypatch):
    reg_path = tmp_path / "sources_registry.yaml"
    reg_path.write_text(yaml.safe_dump({"sources": [
        {"id": "creditchina", "name": "信用中国", "level": "national",
         "automation_mode": "auto",
         "official_home": "https://www.creditchina.gov.cn/",
         "query_url": "https://www.creditchina.gov.cn/q",
         "adapter": "app.sources.national.creditchina"},
        {"id": "sc_construction", "name": "四川建筑市场监管", "level": "province",
         "province": "四川", "automation_mode": "manual",
         "official_home": None,
         "adapter": "app.sources.regions.sichuan.construction"},
    ]}, allow_unicode=True), encoding="utf-8")
    app_yaml = tmp_path / "app.yaml"
    app_yaml.write_text("nightly_mock_only: true\n", encoding="utf-8")
    return reg_path, app_yaml


def test_nightly_gate_refuses_without_override(reg):
    reg_path, app_yaml = reg
    with pytest.raises(RuntimeError, match="daytime-override"):
        diagnostics.check_source("creditchina", "某公司", registry_yaml=reg_path, app_yaml=app_yaml)


def test_unknown_source_rejected(reg):
    reg_path, app_yaml = reg
    with pytest.raises(ValueError, match="不存在"):
        diagnostics.check_source("nope", "某公司", registry_yaml=reg_path,
                                 app_yaml=app_yaml, allow_daytime=True)


def test_manual_mode_outcome(reg):
    reg_path, app_yaml = reg
    src, out = diagnostics.check_source("sc_construction", "某公司",
                                        registry_yaml=reg_path, app_yaml=app_yaml,
                                        allow_daytime=True)
    assert out.status.value == "MANUAL"
    text = diagnostics.format_outcome(src, out)
    assert "MANUAL" in text and "人工" in text


def test_injected_query_reports_findings(reg):
    """真实链路注入（联调时的等价预演）：状态/发现/主体匹配如实呈现。"""
    reg_path, app_yaml = reg
    fixture = {"result": [
        {"subject_name": "测试公司", "subject_uscc": "91510000TEST0000XX",
         "penalty_content": "省级住建主管部门限制投标一年",
         "authority_level": "province",
         "start_date": "2026-08-05", "end_date": "2027-08-05"}]}
    src, out = diagnostics.check_source(
        "creditchina", "测试公司", uscc="91510000TEST0000XX",
        registry_yaml=reg_path, app_yaml=app_yaml, allow_daytime=True,
        get=lambda url, t: (200, json.dumps(fixture, ensure_ascii=False)))
    assert out.status.value == "PASS" and len(out.findings) == 1
    text = diagnostics.format_outcome(src, out)
    assert "SAME_SUBJECT" in text and "penalty_bid_restriction" in text


def test_cli_check_source_refused_by_gate(tmp_path, monkeypatch):
    """CLI 门控：默认配置（packaged app.yaml nightly_mock_only=true）拒绝执行。"""
    from app.main import main as cli
    rc = cli(["check-source", "creditchina", "--name", "某公司"])
    assert rc == 2


def test_cli_check_source_save_evidence(tmp_path, monkeypatch):
    """--save-evidence：联调实测的响应原文入库为哈希证据（P6 打通）。"""
    import json as _json
    import sqlite3

    reg = tmp_path / "reg.yaml"
    reg.write_text(yaml.safe_dump({"sources": [
        {"id": "creditchina", "name": "信用中国", "level": "national",
         "automation_mode": "auto",
         "official_home": "https://www.creditchina.gov.cn/",
         "query_url": "https://www.creditchina.gov.cn/q",
         "adapter": "app.sources.national.creditchina"}]}, allow_unicode=True),
        encoding="utf-8")
    app_yaml = tmp_path / "app.yaml"
    app_yaml.write_text("nightly_mock_only: false\n", encoding="utf-8")
    monkeypatch.setattr(runner, "REGISTRY_YAML", reg)
    monkeypatch.setattr(runner, "APP_YAML", app_yaml)

    fixture = {"result": []}
    monkeypatch.setattr(
        "app.sources.national.base.httpx_get",
        lambda url, timeout, **kw: (200, _json.dumps(fixture)),
        raising=False)

    from app.main import main as cli
    db = tmp_path / "ev.sqlite3"
    rc = cli(["check-source", "creditchina", "--name", "测试公司",
              "--daytime-override", "--save-evidence", str(db)])
    assert rc == 0
    conn = sqlite3.connect(db)
    try:
        row = conn.execute("SELECT source_id, kind, sha256, file_path FROM evidence").fetchone()
    finally:
        conn.close()
    assert row[0] == "creditchina" and row[1] == "p3r_probe"
    assert Path(row[3]).is_file()


def test_cli_verify_evidence_and_friendly_errors(tmp_path, monkeypatch):
    """verify-evidence 子命令 + report/import-bans 的友好报错（退出码而非堆栈）。"""
    from app.main import main as cli

    # 证据完整 → 0；篡改 → 1
    db = tmp_path / "ev.sqlite3"
    from app.core.evidence import save_evidence
    from app.core.db import init_db
    init_db(db)
    save_evidence(db, source_id="s", url=None, raw_text="原文", kind="k")
    assert cli(["verify-evidence", "--db", str(db)]) == 0

    db2 = tmp_path / "ev2.sqlite3"
    init_db(db2)
    from app.core.evidence import evidence_dir_for
    eid, fpath, _ = save_evidence(db2, source_id="s", url=None, raw_text="原文", kind="k")
    fpath.write_text("篡改", encoding="utf-8")
    assert cli(["verify-evidence", "--db", str(db2)]) == 1

    # report：pc 不存在 → 退出码 2 无堆栈
    import io
    from contextlib import redirect_stderr
    err = io.StringIO()
    with redirect_stderr(err):
        rc = cli(["report", "99999", "--db", str(tmp_path / "none.sqlite3"),
                  "--excel", str(tmp_path / "x.xlsx")])
    assert rc == 2

    # import-bans：文件不存在 → 退出码 2
    assert cli(["import-bans", str(tmp_path / "不存在.json"), "--db", str(db)]) == 2
