#!/usr/bin/env python
"""真实样本回放 harness（P0.5 §十二）。

只读业务文件不在此脚本内：样本由调用方提供的 samples.json 给出（含真实企业
数据时必须位于 gitignored 目录，禁止提交公开仓库）。

用法：
    python scripts/replay_samples.py <samples.json> <output_dir>

行为：
- 在 output_dir 下生成白天复核覆盖配置 app.yaml（nightly_mock_only: false，
  显式覆盖并留痕——本回放属白天人工复核场景）；
- 每个样本建 项目+企业 记录后 run_check(real_sources=True)；
- 输出 replay_results.json：每样本的 run_id、各源状态、findings、规则结论、
  decision/data/manual_required/overall，供 §十三 三列对照与 §十四 差异矩阵。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.core.db import connect, init_db  # noqa: E402
from app.core.runner import run_check  # noqa: E402


def _setup_output(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    app_yaml = out_dir / "app.yaml"
    app_yaml.write_text(
        "# 白天人工复核回放专用覆盖配置（本文件由 replay_samples.py 生成并留痕）\n"
        "nightly_mock_only: false\n", encoding="utf-8")
    return app_yaml


def _insert_sample(conn: sqlite3.Connection, s: dict, cfg: dict) -> int:
    cur = conn.execute(
        "INSERT INTO projects (name, industry, owner_group, base_date, years_back, terms) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (f"真实回放-{s['no']:02d}", cfg.get("industry") or None, None,
         cfg.get("base_date") or date.today().isoformat(), 5,
         cfg.get("terms") or None),
    )
    pid = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO companies (name, uscc) VALUES (?, ?)",
        (s["name"], (s.get("uscc") or None)),
    )
    cid = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO project_companies (project_id, company_id, status) VALUES (?, ?, 'running')",
        (pid, cid),
    )
    conn.commit()
    return cur.lastrowid


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    samples_path, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    payload = json.loads(samples_path.read_text(encoding="utf-8"))
    cfg = {"base_date": payload.get("base_date"), "industry": payload.get("industry"),
           "terms": payload.get("terms")}
    app_yaml = _setup_output(out_dir)
    db = out_dir / "replay.sqlite3"
    init_db(db)

    results = []
    for s in payload["samples"]:
        conn = connect(db)
        pc_id = _insert_sample(conn, s, cfg)
        conn.close()
        try:
            overall = run_check(db, pc_id, real_sources=True, app_yaml=app_yaml)
            err = ""
        except Exception as exc:  # 单样本失败不中断整批回放
            overall, err = None, f"{exc.__class__.__name__}: {exc}"
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        try:
            run = conn.execute(
                "SELECT * FROM check_runs WHERE project_id=(SELECT project_id FROM "
                "project_companies WHERE id=?) ORDER BY id DESC LIMIT 1", (pc_id,)).fetchone()
            queries = [dict(q) for q in conn.execute(
                "SELECT sq.source_id, sq.status, sq.query_url, sq.raw_json FROM source_queries sq "
                "JOIN project_companies pc ON pc.project_id=sq.project_id AND pc.company_id=sq.company_id "
                "WHERE pc.id=? ORDER BY sq.id", (pc_id,))]
            rules = [dict(r) for r in conn.execute(
                "SELECT rr.rule_id, rr.status, rr.scope, rr.reasons_json FROM rule_results rr "
                "JOIN project_companies pc ON pc.project_id=rr.project_id AND pc.company_id=rr.company_id "
                "WHERE pc.id=? ORDER BY rr.id", (pc_id,))]
        finally:
            conn.close()
        results.append({
            "no": s["no"], "name": s["name"], "uscc": s.get("uscc"),
            "sample_type": s.get("type"), "uscc_type": s.get("uscc_type"),
            "source_file": s.get("source_file"), "location": s.get("location"),
            "ledger_conclusion": s.get("ledger_conclusion"),
            "ledger_date": s.get("ledger_date"),
            "run_id": run["run_id"] if run else None,
            "overall": overall if overall is not None else (run or {}).get("overall_status"),
            "error": err,
            "decision_status": run["decision_status"] if run else None,
            "data_status": run["data_status"] if run else None,
            "manual_required": run["manual_required"] if run else None,
            "source_statuses": {q["source_id"]: q["status"] for q in queries},
            "source_notes": {q["source_id"]: json.loads(q["raw_json"] or "{}").get("note", "")
                             for q in queries},
            "rule_results": [{"rule_id": r["rule_id"], "status": r["status"],
                              "scope": r["scope"],
                              "reasons": json.loads(r["reasons_json"] or "[]")}
                             for r in rules],
        })
        print(f"[replay] {s['no']:02d} {s['name']}: overall={overall} err={err}")

    out = out_dir / "replay_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[replay] 结果已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
