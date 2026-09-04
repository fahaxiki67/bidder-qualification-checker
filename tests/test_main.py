import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_cli_help_runs():
    r = subprocess.run(
        [sys.executable, "-m", "app.main", "--help"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "投标人资格智能核查系统" in r.stdout


def test_cli_init_db(tmp_path):
    target = tmp_path / "db" / "x.sqlite3"
    r = subprocess.run(
        [sys.executable, "-m", "app.main", "init-db", "--db", str(target)],
        cwd=REPO, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert target.exists()
    assert "数据库已初始化" in r.stdout


def test_cli_version():
    r = subprocess.run(
        [sys.executable, "-m", "app.main", "--version"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert r.returncode == 0 and "0.1.0" in r.stdout
