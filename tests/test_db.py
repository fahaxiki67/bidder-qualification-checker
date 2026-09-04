import app
from app.core import db


def test_init_db_creates_all_ten_tables(tmp_path):
    p = tmp_path / "data" / "bqc.sqlite3"
    db.init_db(p)
    tables = db.table_names(p)
    for t in db.EXPECTED_TABLES:
        assert t in tables


def test_minimal_insert_roundtrip(tmp_path):
    p = tmp_path / "b.sqlite3"
    db.init_db(p)
    conn = db.connect(p)
    cur = conn.cursor()
    cur.execute("INSERT INTO projects (name, province, base_date) VALUES ('proj', '四川', '2026-09-04')")
    cur.execute("INSERT INTO companies (name, uscc) VALUES ('公司A', '91510112MACD5CDJ9F')")
    cur.execute("INSERT INTO project_companies (project_id, company_id) VALUES (1, 1)")
    cur.execute(
        "INSERT INTO source_registry (id, name, level) VALUES ('gsxt', '公示系统', 'national')"
    )
    cur.execute(
        "INSERT INTO source_queries (project_id, company_id, source_id, status) "
        "VALUES (1, 1, 'gsxt', 'PASS')"
    )
    conn.commit()
    assert cur.execute("SELECT COUNT(*) FROM project_companies").fetchone()[0] == 1
    assert cur.execute("SELECT version FROM app_versions").fetchone()[0] == app.__version__
    conn.close()
