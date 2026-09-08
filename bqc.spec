# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包规格（P8）：onefile 控制台应用 bqc(.exe)。

- 数据源/地区插件/集团插件 adapter 经注册表动态导入（importlib），必须显式列入
  hiddenimports，否则打包后运行时 ModuleNotFoundError；
- app/config/*.yaml 与 app/web/templates/*.html 随包分发（datas）；
- 用户数据落用户目录（app/paths.py，Windows=%LOCALAPPDATA%\\bqc）。
"""
import sys
import os
import shutil
from pathlib import Path

APP = Path(SPECPATH)

# 发布构建显式要求本机 OCR，缺引擎/语言数据时失败，避免产出名不副实的安装包。
ocr_binaries, ocr_data = [], []
if os.environ.get("BQC_BUNDLE_OCR") == "1":
    stage_value = os.environ.get("BQC_OCR_STAGE")
    stage = Path(stage_value) if stage_value else None
    for name, directory in (("pdftoppm", "renderer"), ("tesseract", "engine")):
        executable = stage / directory / name if stage and stage.is_dir() else Path(shutil.which(name) or "")
        if not executable.is_file():
            raise RuntimeError(f"OCR 打包缺少 {name}")
        executable = executable.resolve()
        destination = f"ocr/{directory}"
        ocr_binaries.append((str(executable), destination))
        if sys.platform == "win32" and not stage:
            ocr_binaries.extend((str(dll), destination) for dll in executable.parent.glob("*.dll"))
        # 各引擎随安装目录提供的版权说明一并保留。
        for pattern in ("*LICENSE*", "*COPYING*", "*license*", "*copying*"):
            ocr_data.extend((str(file), f"ocr/licenses/{directory}")
                            for file in executable.parent.glob(pattern) if file.is_file())
    if stage and stage.is_dir():
        ocr_binaries.extend((str(file), "ocr/lib") for file in (stage / "lib").iterdir() if file.is_file())
    tessdata = Path(os.environ["BQC_TESSDATA_PREFIX"])
    for language in ("chi_sim", "eng"):
        trained = tessdata / f"{language}.traineddata"
        if not trained.is_file():
            raise RuntimeError(f"OCR 打包缺少 {trained}")
        ocr_data.append((str(trained), "ocr/tessdata"))
    if (tessdata / "LICENSE").is_file():
        ocr_data.append((str(tessdata / "LICENSE"), "ocr/tessdata"))

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
    binaries=ocr_binaries,
    datas=[
        (str(APP / "app" / "config"), "app/config"),
        (str(APP / "app" / "web" / "templates"), "app/web/templates"),
        *ocr_data,
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
