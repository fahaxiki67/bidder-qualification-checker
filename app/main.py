"""CLI 入口。P1 仅提供 init-db 与帮助；核查任务与 Web UI 在 P2 接入。"""
from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__
from .core.db import init_db

DEFAULT_DB = Path("data/bqc.sqlite3")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="bqc", description="投标人资格智能核查系统 — 资格前审证据链工具"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")
    p_init = sub.add_parser("init-db", help="初始化 SQLite 数据库（不存在则创建）")
    p_init.add_argument("--db", default=str(DEFAULT_DB), help="数据库文件路径")
    args = parser.parse_args(argv)

    if args.command == "init-db":
        path = init_db(args.db)
        print(f"数据库已初始化: {path}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
