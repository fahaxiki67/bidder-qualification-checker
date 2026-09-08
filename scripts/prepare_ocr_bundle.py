"""把 macOS Homebrew OCR 及其非系统动态库准备为自包含目录。"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


def _lines(binary: Path) -> list[str]:
    return subprocess.run(["otool", "-L", str(binary)], check=True,
                          capture_output=True, text=True).stdout.splitlines()[1:]


def _rpaths(binary: Path) -> list[str]:
    lines = subprocess.run(["otool", "-l", str(binary)], check=True,
                           capture_output=True, text=True).stdout.splitlines()
    return [line.strip().split(" ", 1)[1].split(" ", 1)[0]
            for line in lines if line.strip().startswith("path ")]


def _resolve_dependency(name: str, owner: Path, executable: Path) -> Path | None:
    if name.startswith("/"):
        candidate = Path(name)
    else:
        candidates = []
        if name.startswith("@loader_path/"):
            candidates.append(owner.parent / name.removeprefix("@loader_path/"))
        elif name.startswith("@executable_path/"):
            candidates.append(executable.parent / name.removeprefix("@executable_path/"))
        elif name.startswith("@rpath/"):
            suffix = name.removeprefix("@rpath/")
            for rpath in _rpaths(owner):
                base = rpath.replace("@loader_path", str(owner.parent)).replace(
                    "@executable_path", str(executable.parent))
                candidates.append(Path(base) / suffix)
        else:
            return None
        candidate = next((item for item in candidates if item.is_file()), None)
        if candidate is None:
            return None
    if not candidate.is_file() or str(candidate).startswith(("/System/", "/usr/lib/")):
        return None
    return candidate.resolve()


def _prepare(stage: Path) -> None:
    if stage.exists():
        raise RuntimeError(f"OCR 临时目录已存在，拒绝覆盖：{stage}")
    (stage / "renderer").mkdir(parents=True)
    (stage / "engine").mkdir()
    (stage / "lib").mkdir()
    sources = {name: Path(shutil.which(name)).resolve() for name in ("pdftoppm", "tesseract")}
    destinations = {
        sources["pdftoppm"]: stage / "renderer" / "pdftoppm",
        sources["tesseract"]: stage / "engine" / "tesseract",
    }
    for source, destination in destinations.items():
        shutil.copy2(source, destination)

    pending = list(destinations.items())
    copied: dict[Path, Path] = {}
    changes: list[tuple[Path, str, str]] = []
    executable = sources["tesseract"]
    while pending:
        source, owner = pending.pop()
        for line in _lines(source):
            dependency = line.strip().split(" (", 1)[0]
            target = _resolve_dependency(dependency, source, executable)
            if target is None:
                continue
            destination = copied.get(target)
            if destination is None:
                destination = stage / "lib" / target.name
                if any(item.name == destination.name and item != destination for item in copied.values()):
                    raise RuntimeError(f"OCR 动态库同名冲突：{target.name}")
                shutil.copy2(target, destination)
                copied[target] = destination
                pending.append((target, destination))
            relative = "@loader_path/../lib/" + destination.name if owner.parent.name in {"renderer", "engine"} else "@loader_path/" + destination.name
            changes.append((owner, dependency, relative))

    for owner, old, new in changes:
        subprocess.run(["install_name_tool", "-change", old, new, str(owner)], check=True)
    for destination in copied.values():
        subprocess.run(["install_name_tool", "-id", "@loader_path/" + destination.name,
                        str(destination)], check=True)
    print(f"Prepared bundled OCR: {stage} ({len(copied)} dynamic libraries)")


def main() -> int:
    if sys.platform != "darwin":
        print("OCR bundle staging is only required on macOS")
        return 0
    missing = [name for name in ("pdftoppm", "tesseract") if not shutil.which(name)]
    if missing:
        raise SystemExit(f"OCR 打包缺少：{', '.join(missing)}")
    stage = Path(os.environ.get("RUNNER_TEMP", ".")) / "bqc-ocr-stage"
    _prepare(stage)
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as stream:
            stream.write(f"BQC_OCR_STAGE={stage}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
