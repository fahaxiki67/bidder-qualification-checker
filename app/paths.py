"""数据路径解析（P8）：源码/CLI 运行落当前工作目录；PyInstaller 打包后落用户数据目录。

- Windows（frozen）：%LOCALAPPDATA%\\bqc\\data\\（任务书 P8 要求）；
- macOS（frozen）：~/Library/Application Support/bqc/data/；
- 源码运行：./data/（与既有 CLI 行为一致，测试/开发不受影响）。
环境变量 BQC_DB（数据库覆盖）优先级始终最高。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def default_data_dir() -> Path:
    if not is_frozen():
        return Path("data")
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "bqc"
    else:
        base = Path(os.environ.get("LOCALAPPDATA") or
                    (Path.home() / "AppData" / "Local")) / "bqc"
    return base / "data"


def default_db_path() -> Path:
    return default_data_dir() / "bqc.sqlite3"
