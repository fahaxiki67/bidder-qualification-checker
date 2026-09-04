#!/usr/bin/env python
"""安装后烟测：包可导入、模板/配置随包分发、模板可解析、元数据版本一致。

必须以 pip 安装（editable 或 wheel）后的环境运行；在 build job 中还会脱离
源码目录运行，证明安装结果不依赖源码树。任一项不过即退出码 1。
"""
from __future__ import annotations

import importlib
import importlib.metadata
import os
import sys
import tempfile
from pathlib import Path

REQUIRED_MODULES = ("app", "app.core", "app.sources.national", "app.web")
SERVER_MODULE = "app.web.server"
TEMPLATE_FILES = ("base.html", "index.html", "result.html")
CONFIG_FILES = ("app.yaml", "rules.yaml", "sources_registry.yaml")


def main() -> int:
    failures: list[str] = []

    for mod in REQUIRED_MODULES:
        try:
            importlib.import_module(mod)
        except Exception as exc:  # 烟测要把任何导入失败如实报出
            failures.append(f"import {mod} 失败: {exc!r}")

    import app

    app_root = Path(app.__file__).resolve().parent
    for name in TEMPLATE_FILES:
        p = app_root / "web" / "templates" / name
        if not p.is_file():
            failures.append(f"模板缺失: app/web/templates/{name}")
    for name in CONFIG_FILES:
        p = app_root / "config" / name
        if not p.is_file():
            failures.append(f"配置缺失: app/config/{name}")

    # 模板可被 Jinja2 加载解析（仅加载不渲染，不需要请求上下文）
    if not failures:
        try:
            from jinja2 import Environment, FileSystemLoader

            env = Environment(loader=FileSystemLoader(str(app_root / "web" / "templates")))
            for name in TEMPLATE_FILES:
                env.get_template(name)
        except Exception as exc:
            failures.append(f"模板解析失败: {exc!r}")

    # server 模块导入时会 init_db：指向临时文件，不污染当前目录
    fd, db_tmp = tempfile.mkstemp(prefix="bqc_smoke_", suffix=".sqlite3")
    os.close(fd)
    os.environ["BQC_DB"] = db_tmp
    try:
        importlib.import_module(SERVER_MODULE)
    except Exception as exc:
        failures.append(f"import {SERVER_MODULE} 失败: {exc!r}")

    try:
        meta = importlib.metadata.version("bidder-qualification-checker")
        if meta != app.__version__:
            failures.append(f"版本漂移: 包元数据 {meta} != app.__version__ {app.__version__}")
    except importlib.metadata.PackageNotFoundError:
        failures.append(
            "包元数据缺失：本烟测要求先 pip 安装本包（pip install -e \".[dev]\" 或安装 wheel）")

    for f in failures:
        print(f"[smoke] FAIL {f}", file=sys.stderr)
    if failures:
        return 1
    print(f"[smoke] OK modules={len(REQUIRED_MODULES) + 1} "
          f"templates={len(TEMPLATE_FILES)} config={len(CONFIG_FILES)} "
          f"version={app.__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
