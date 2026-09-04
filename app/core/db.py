"""SQLite 存储层（任务书 §16）。原始响应可存 raw_json，关键字段必须结构化。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .. import __version__

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    province TEXT, city TEXT, industry TEXT,
    owner_group TEXT,
    base_date TEXT NOT NULL,
    years_back INTEGER NOT NULL DEFAULT 3,
    terms TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    uscc TEXT UNIQUE,
    registered_province TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS project_companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    company_id INTEGER NOT NULL REFERENCES companies(id),
    status TEXT NOT NULL DEFAULT 'pending',
    overall_status TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (project_id, company_id)
);

CREATE TABLE IF NOT EXISTS source_registry (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    level TEXT NOT NULL,
    province TEXT, city TEXT, industry TEXT, owner_group TEXT,
    authority TEXT, source_type TEXT,
    official_home TEXT, query_url TEXT,
    automation_mode TEXT, evidence_grade TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_verified TEXT,
    adapter TEXT, notes TEXT
);

CREATE TABLE IF NOT EXISTS source_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id),
    company_id INTEGER REFERENCES companies(id),
    source_id TEXT NOT NULL,
    query_url TEXT, query_params TEXT,
    queried_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    status TEXT NOT NULL,
    page_title TEXT, key_text TEXT,
    adapter_version TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id INTEGER REFERENCES source_queries(id),
    company_id INTEGER REFERENCES companies(id),
    kind TEXT NOT NULL,
    grade TEXT NOT NULL,
    description TEXT,
    start_date TEXT, end_date TEXT,
    attrs_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS rule_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id),
    company_id INTEGER REFERENCES companies(id),
    rule_id TEXT NOT NULL,
    status TEXT NOT NULL,
    reasons_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id INTEGER REFERENCES source_queries(id),
    source_id TEXT NOT NULL,
    url TEXT,
    captured_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    kind TEXT,
    file_path TEXT,
    sha256 TEXT,
    grade TEXT,
    key_text TEXT
);

CREATE TABLE IF NOT EXISTS manual_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id INTEGER REFERENCES source_queries(id),
    rule_result_id INTEGER REFERENCES rule_results(id),
    reviewer TEXT,
    decision TEXT NOT NULL,
    note TEXT,
    reviewed_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 核查批次（P0.5 §五）：同一条 project/company 重复核查互不混杂。
-- finished_at IS NULL = 运行中断未完成；历史批次永久保留，不得删除。
CREATE TABLE IF NOT EXISTS check_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    company_id INTEGER NOT NULL REFERENCES companies(id),
    scenario TEXT,
    decision_status TEXT,
    data_status TEXT,
    manual_required INTEGER NOT NULL DEFAULT 0,
    overall_status TEXT,
    started_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS app_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

EXPECTED_TABLES = (
    "projects", "companies", "project_companies", "source_registry",
    "source_queries", "findings", "rule_results", "evidence",
    "manual_reviews", "app_versions", "check_runs",
)

#: 旧库升级（0.3.x → 0.4+）：为既有表补批次绑定列，幂等执行。
#: 旧行 run_id 为 NULL = 迁移前的历史数据，原样保留可追溯，绝不删除旧库。
_MIGRATIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "source_queries": (("run_id", "TEXT"),),
    "rule_results": (("run_id", "TEXT"),),
    "manual_reviews": (("run_id", "TEXT"),),
    "project_companies": (("run_id", "TEXT"),),
}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, cols in _MIGRATIONS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not have:
            continue  # 表尚不存在（由 SCHEMA 建表）
        for name, ddl in cols:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def connect(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str | Path) -> Path:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        # 版本登记单点来源 app.__version__，避免库内硬编码与包版本漂移
        conn.execute(
            "INSERT INTO app_versions (version) SELECT ? "
            "WHERE NOT EXISTS (SELECT 1 FROM app_versions)",
            (__version__,),
        )
        conn.commit()
    finally:
        conn.close()
    return Path(path)


def table_names(path: str | Path) -> set[str]:
    conn = connect(path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()
