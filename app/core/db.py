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

CREATE TABLE IF NOT EXISTS app_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

EXPECTED_TABLES = (
    "projects", "companies", "project_companies", "source_registry",
    "source_queries", "findings", "rule_results", "evidence",
    "manual_reviews", "app_versions",
)


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
