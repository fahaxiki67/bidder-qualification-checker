"""CLI 入口。P1 仅提供 init-db 与帮助；核查任务与 Web UI 在 P2 接入。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .core.db import init_db
from .paths import default_db_path

DEFAULT_DB = default_db_path()


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
    p_import = sub.add_parser(
        "import-bans", help="导入集团禁入名单 JSON（人工导入口，文件哈希留证；名单文件不入库）")
    p_import.add_argument("file", help="名单 JSON 文件（契约见 app/sources/owners/powerchina.py）")
    p_import.add_argument("--db", default=str(DEFAULT_DB), help="数据库路径")
    p_import.add_argument("--source", default="powerchina_ban", help="数据源 id")
    p_report = sub.add_parser("report", help="导出核查报告（Excel 明细 11 sheet / PDF）")
    p_report.add_argument("pc_id", type=int, help="project_companies 记录 id")
    p_report.add_argument("--db", default=str(DEFAULT_DB), help="数据库路径")
    p_report.add_argument("--excel", help="输出 .xlsx 路径")
    p_report.add_argument("--pdf", help="输出 .pdf 路径")
    args = parser.parse_args(argv)

    if args.command == "init-db":
        path = init_db(args.db)
        print(f"数据库已初始化: {path}")
        return 0

    if args.command == "import-bans":
        from .core.evidence import save_evidence, verify_evidence

        src = Path(args.file)
        text = src.read_text(encoding="utf-8")
        init_db(args.db)
        eid, fpath, digest = save_evidence(
            args.db, source_id=args.source,
            url=f"file://{src.resolve()}", raw_text=text,
            kind="owner_ban", grade="A",
            key_text=f"人工导入名单：{src.name}（{len(text)} 字符）",
        )
        ok, broken = verify_evidence(args.db, eid)
        if broken:
            print("导入后哈希校验失败，请检查磁盘/权限：", broken)
            return 1
        print(f"名单证据已入库: evidence_id={eid} sha256={digest}")
        print(f"存档路径: {fpath}")
        print("后续核查（bqc serve / run_check）将自动经主体一致性检查离线评判该名单")
        return 0

    if args.command == "report":
        if not args.excel and not args.pdf:
            print("至少指定 --excel 或 --pdf 输出路径")
            return 2
        from .reports.excel import export_excel
        from .reports.pdf import export_pdf
        if args.excel:
            out = export_excel(args.db, args.pc_id, args.excel)
            print(f"Excel 明细已导出: {out}")
        if args.pdf:
            out = export_pdf(args.db, args.pc_id, args.pdf)
            print(f"PDF 报告已导出: {out}")
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
