"""CLI 入口。P1 仅提供 init-db 与帮助；核查任务与 Web UI 在 P2 接入。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .core.db import init_db

DEFAULT_DB = Path("data/bqc.sqlite3")


def _force_utf8_stdio() -> None:
    """中文输出在旧代码页控制台（Windows cp1252/cp437）会 UnicodeEncodeError 崩溃。

    强制 UTF-8：现代终端正常显示；旧控制台最多乱码，绝不因编码崩溃。
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None) -> int:
    _force_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="bqc", description="投标人资格智能核查系统 — 资格前审证据链工具"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")
    p_init = sub.add_parser("init-db", help="初始化 SQLite 数据库（不存在则创建）")
    p_init.add_argument("--db", default=str(DEFAULT_DB), help="数据库文件路径")
    p_serve = sub.add_parser("serve", help="启动本地 Web UI（仅监听 127.0.0.1）")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    if args.command == "init-db":
        path = init_db(args.db)
        print(f"数据库已初始化: {path}")
        return 0

    if args.command == "serve":
        import uvicorn
        from .web.server import app as web_app
        uvicorn.run(web_app, host=args.host, port=args.port)
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
