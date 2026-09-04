"""单源联调诊断（P3R 人工复核辅助）：对指定数据源跑一次真实查询并如实输出。

红线：本工具供**白天人工复核**使用——默认受 nightly_mock_only 门控，
需显式 --daytime-override；不做任何回填，输出即所查，失败状态绝不美化。
"""
from __future__ import annotations

import json

from .core import runner
from .core.models import Company
from .core.registry import SourceRegistry
from .sources.national.base import query_source


def check_source(source_id: str, name: str, uscc: str | None = None,
                 timeout: float = 15.0, get=None,
                 registry_yaml=None, app_yaml=None, allow_daytime: bool = False):
    """对单源执行一次查询，返回 (SourceRef, AdapterOutcome)。

    get 参数仅供测试注入；CLI 真实联调不传（走默认传输层）。
    registry_yaml/app_yaml 默认取包内配置；测试可分别注入。
    """
    registry = SourceRegistry.from_yaml(registry_yaml or runner.REGISTRY_YAML)
    try:
        src = registry.get(source_id)
    except KeyError:
        raise ValueError(f"注册表中不存在数据源：{source_id}") from None
    if runner._nightly_mock_only(app_yaml) and not allow_daytime:
        raise RuntimeError(
            "nightly_mock_only=true：夜间/演示模式禁用真实查询。"
            "白天人工复核请显式加 --daytime-override。")
    company = Company(name=name, uscc=uscc or None)
    out = query_source(src, company, get=get, timeout=timeout)
    return src, out


def format_outcome(src, out) -> str:
    lines = [
        f"数据源: {src.id}（{src.name}）",
        f"查询入口: {out.query_url or src.official_home}",
        f"状态: {out.status.value} — 详见 docs/P3R_CHECKLIST.md 口径表",
        f"注记: {out.note}",
        f"发现条数: {len(out.findings)}",
    ]
    for f in out.findings:
        lines.append(f"  · [{f.kind}/{f.grade}] {f.description} "
                     f"(主体匹配: {f.attrs.get('match_result', '未标注')})")
    if out.raw_text:
        lines.append(f"响应前 300 字符: {out.raw_text[:300]!r}")
    return "\n".join(lines)
