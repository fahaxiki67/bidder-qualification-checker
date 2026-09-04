#!/usr/bin/env python
"""从 CHANGELOG.md 提取指定版本的章节作为 Release 说明。

用法：python scripts/extract_changelog.py <版本号，如 0.11.0>
找不到该版本章节时退化为全文提示（不静默伪造）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    version = sys.argv[1].lstrip("v")
    text = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)",
                  text, re.M | re.S)
    if not m:
        print(f"# {version}\n\n（CHANGELOG.md 中未找到 {version} 章节，请补充后重发）")
        return 1
    print(m.group(1).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
