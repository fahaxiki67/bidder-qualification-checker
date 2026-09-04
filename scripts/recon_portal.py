#!/usr/bin/env python
"""门户侦察工具（P3R 人工复核辅助，WORKPLAN 允许的"页面结构调研"类工作）。

对指定数据源的官方入口做一次浏览器自动导航：
- 打开 official_home 并截图；
- 自动填入测试企业名并点击"查询/搜索"，截图结果页；
- 捕获页面发出的全部网络请求（XHR/fetch 接口候选）；
- 产出 candidates.json + 截图，供**人工**复核确认后回填 query_url。

红线与边界：
- 本工具不回填注册表、不写 last_verified——回填必须由人工确认后手工完成；
- 请在**白天**由人执行（夜间纪律禁止无人值守访问真实政府网站）；
- 单次单页导航，低频，不破解验证码（遇验证码截图留证即停）。

用法：
    python scripts/recon_portal.py <source_id> [--url 入口覆盖] [--query 企业名]
        [--out 目录] [--headed]

依赖（开发用，非运行时依赖）：pip install playwright && playwright install chromium
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.core.registry import SourceRegistry  # noqa: E402
from app.core.runner import REGISTRY_YAML  # noqa: E402

_SEARCH_BUTTON_WORDS = ("查询", "搜索", "search")


def recon(source_id: str, entry_url: str | None, query_name: str,
          out_dir: Path, headless: bool = True) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("缺少 playwright：pip install playwright && playwright install chromium")
        return 2

    registry = SourceRegistry.from_yaml(REGISTRY_YAML)
    try:
        src = registry.get(source_id)
    except KeyError:
        print(f"注册表中不存在数据源：{source_id}")
        return 2
    entry = entry_url or src.official_home
    if not entry:
        print(f"{source_id} 注册表 official_home 为空，请用 --url 指定待复核入口")
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    captured: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
        page = context.new_page()
        page.on("response", lambda r: captured.append(
            {"url": r.url, "status": r.status, "method": r.request.method}))

        print(f"[recon] 打开入口：{entry}")
        page.goto(entry, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        page.screenshot(path=str(out_dir / "01_home.png"), full_page=True)

        inputs = page.locator("input[type='text'], input:not([type]), input[type='search']")
        n_inputs = inputs.count()
        if n_inputs:
            inputs.first.fill(query_name)
            print(f"[recon] 已填入测试名：{query_name}（{n_inputs} 个输入框）")
        clicked = False
        for word in _SEARCH_BUTTON_WORDS:
            btn = page.get_by_role("button", name=word).or_(
                page.locator(f"a:has-text('{word}')").first)
            if btn.count():
                btn.first.click()
                clicked = True
                break
        if not clicked:
            inputs.first.press("Enter") if n_inputs else None
        page.wait_for_timeout(5000)  # 等待结果/接口往返
        page.screenshot(path=str(out_dir / "02_results.png"), full_page=True)

        body_text = ""
        try:
            body_text = page.inner_text("body")[:2000]
        except Exception:
            pass
        browser.close()

    # 页面触发的接口请求 = query_url 的主要候选（排除静态资源）
    api_like = [c for c in captured
                if not any(c["url"].endswith(ext)
                           for ext in (".png", ".jpg", ".css", ".js", ".ico", ".woff", ".svg"))
                and c["method"] in ("GET", "POST")]
    result = {
        "source_id": source_id,
        "entry_url": entry,
        "query_name": query_name,
        "recon_time": datetime.now().isoformat(timespec="seconds"),
        "inputs_found": n_inputs,
        "search_clicked": clicked,
        "api_candidates": api_like,
        "page_text_head": body_text,
        "screenshots": ["01_home.png", "02_results.png"],
        "note": "候选接口须经人工复核确认后手工回填注册表 query_url + last_verified",
    }
    (out_dir / "candidates.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[recon] 完成：截图 2 张、接口候选 {len(api_like)} 个 → {out_dir}")
    print(f"[recon] 请人工查看 01_home.png / 02_results.png / candidates.json 后回填")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source_id")
    ap.add_argument("--url", default=None, help="入口覆盖（official_home 为空时必填）")
    ap.add_argument("--query", default="测试企业有限公司", help="填入的测试企业名")
    ap.add_argument("--out", default=str(REPO / "local" / "recon"), help="输出目录")
    ap.add_argument("--headed", action="store_true", help="有头模式（观察导航过程）")
    a = ap.parse_args()
    return recon(a.source_id, a.url, a.query, Path(a.out), headless=not a.headed)


if __name__ == "__main__":
    raise SystemExit(main())
