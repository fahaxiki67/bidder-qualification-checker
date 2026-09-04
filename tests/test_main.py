import os
import subprocess
import sys
from pathlib import Path

import app

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
    assert r.returncode == 0 and app.__version__ in r.stdout


def test_cli_help_on_legacy_codepage_console():
    """旧代码页控制台（Windows cp1252/cp437）下中文 --help 不得崩溃。

    根因复现：CI Windows runner stdout=cp1252，argparse 写中文帮助文本
    UnicodeEncodeError 退出码 1。修复=CLI 入口强制 stdout/stderr UTF-8。
    """
    env = dict(os.environ, PYTHONIOENCODING="cp1252")
    r = subprocess.run(
        [sys.executable, "-m", "app.main", "--help"],
        cwd=REPO, capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, f"旧控制台下 --help 崩溃:\n{r.stderr}"
    assert "usage:" in r.stdout
