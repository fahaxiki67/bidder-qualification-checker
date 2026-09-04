# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包规格（P8）：onefile 控制台应用 bqc(.exe)。

- 数据源/地区插件/集团插件 adapter 经注册表动态导入（importlib），必须显式列入
  hiddenimports，否则打包后运行时 ModuleNotFoundError；
- app/config/*.yaml 与 app/web/templates/*.html 随包分发（datas）；
- 用户数据落用户目录（app/paths.py，Windows=%LOCALAPPDATA%\\bqc）。
"""
import sys
from pathlib import Path

APP = Path(SPECPATH)

ADAPTERS = [
    "app.sources.national.gsxt",
    "app.sources.national.creditchina",
    "app.sources.national.zxgk",
    "app.sources.national.mem",
    "app.sources.national.jzsc",
    "app.sources.national.pcczdc",
    "app.sources.owners.powerchina",
    "app.sources.regions.sichuan.construction",
    "app.sources.regions.sichuan.credit",
    "app.sources.regions.guangdong.construction",
]

a = Analysis(
    [str(APP / "entry_bqc.py")],
    pathex=[str(APP)],
    binaries=[],
    datas=[
        (str(APP / "app" / "config"), "app/config"),
        (str(APP / "app" / "web" / "templates"), "app/web/templates"),
    ],
    hiddenimports=[
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "app.web.server",
        *ADAPTERS,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="bqc",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
