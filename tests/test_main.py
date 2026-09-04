import os
import subprocess
import sys
from pathlib import Path

import app

REPO = Path(__file__).resolve().parents[1]

# CLI 契约：管道输出一律 UTF-8（app.main._force_utf8_stdio）。
# 测试必须显式按 UTF-8 解码——Windows 上 text=True 默认按本地代码页（如 cp1252）
# 解码，中文 UTF-8 字节里的 0x81/0x8D 等 cp1252 未定义字节会让读取线程静默死亡，
# r.stdout 变成 None（2026-09-04 CI Windows 实证）。
RUN_KW = dict(cwd=REPO, capture_output=True, text=True, encoding="utf-8")


def test_cli_help_runs():
    r = subprocess.run([sys.executable, "-m", "app.main", "--help"], **RUN_KW)
    assert r.returncode == 0, r.stderr
    assert "投标人资格智能核查系统" in r.stdout


def test_cli_init_db(tmp_path):
    target = tmp_path / "db" / "x.sqlite3"
    r = subprocess.run(
        [sys.executable, "-m", "app.main", "init-db", "--db", str(target)], **RUN_KW
    )
    assert r.returncode == 0, r.stderr
    assert target.exists()
    assert "数据库已初始化" in r.stdout


def test_cli_version():
    r = subprocess.run([sys.executable, "-m", "app.main", "--version"], **RUN_KW)
    assert r.returncode == 0 and app.__version__ in r.stdout


def test_cli_help_on_legacy_codepage_console():
    """旧代码页环境下管道输出不得崩溃，且仍是 UTF-8。

    两层根因（CI Windows 实证）：
    1. 子进程 stdout=cp1252 时 argparse 写中文 UnicodeEncodeError → 退出码 1；
    2. 若子进程编码不确定，父进程 text=True 按 cp1252 解码中文 UTF-8 字节时
       读线程静默死亡 → r.stdout 为 None（TypeError 而非断言失败）。
    修复=CLI 管道输出强制 UTF-8；测试显式 encoding="utf-8" 解码。
    """
    env = dict(os.environ, PYTHONIOENCODING="cp1252")
    r = subprocess.run(
        [sys.executable, "-m", "app.main", "--help"], env=env, **RUN_KW
    )
    assert r.returncode == 0, f"旧控制台下 --help 崩溃:\n{r.stderr}"
    assert "usage:" in r.stdout
