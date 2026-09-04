"""CLI 入口。P1 仅提供 init-db 与帮助；核查任务与 Web UI 在 P2 接入。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .core.db import init_db

DEFAULT_DB = Path("data/bqc.sqlite3")


def _force_utf8_stdio() -> None:
    """中文输出的编码契约：管道/文件一律 UTF-8；真控制台保留本地代码页。

    背景（CI Windows 实测）：stdout=cp1252 的控制台写中文会 UnicodeEncodeError
    崩溃；而管道场景若子进程编码不确定，父进程按错误代码页解码会得到坏字节。
    - 管道/文件：强制 UTF-8，消费方（测试/上游进程）按 UTF-8 解码即可；
    - 真控制台：保留原编码（中文 Windows cp936 仍正常显示），
      仅把不可编码字符降级为 '?'，旧代码页最多丢符号不崩溃。
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            if stream.isatty():
                stream.reconfigure(errors="replace")
            else:
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # 流已关闭等极端场景，不阻断 CLI
            pass


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
