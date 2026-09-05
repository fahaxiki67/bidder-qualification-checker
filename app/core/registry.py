"""数据源注册表：官方 URL 只进 app/config/sources_registry.yaml，禁止散落源码（任务书 §10）。

0.18.1 复核修复：注册表是评判依据的来源清单，配置错误必须启动即报错，
不得静默吞掉（重复 id 静默覆盖、未知字段静默丢弃、非法 automation_mode、
owner 源缺 owner_group 都会让路由/评判悄悄偏离预期）。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .models import SourceRef

_FIELDS = set(SourceRef.__dataclass_fields__)
_AUTOMATION_MODES = {"auto", "auto_fill_manual_verify", "manual", "manual_intake"}


def _validate_entry(item: dict, index: int) -> SourceRef:
    where = f"sources[{index}] (id={item.get('id', '?')})"
    unknown = set(item) - _FIELDS
    if unknown:
        raise ValueError(f"注册表 {where} 存在未知字段：{sorted(unknown)}")
    mode = item.get("automation_mode")
    if mode is not None and mode not in _AUTOMATION_MODES:
        # 省略该键走 SourceRef 默认值 manual，属合法写法；只拒绝显式的非法值
        raise ValueError(
            f"注册表 {where} automation_mode 非法：{mode!r}"
            f"（允许：{sorted(_AUTOMATION_MODES)}）")
    if item.get("level") == "owner" and not item.get("owner_group"):
        raise ValueError(f"注册表 {where} level=owner 必须提供 owner_group")
    return SourceRef(**item)


class SourceRegistry:
    def __init__(self, entries):
        seen: dict[str, SourceRef] = {}
        for e in entries:
            if e.id in seen:
                raise ValueError(f"注册表存在重复数据源 id：{e.id}")
            seen[e.id] = e
        self._entries: list[SourceRef] = list(entries)
        self._by_id: dict[str, SourceRef] = seen

    @classmethod
    def from_yaml(cls, path: str | Path) -> "SourceRegistry":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        raw = data.get("sources") or []
        entries = [_validate_entry(item, i) for i, item in enumerate(raw)]
        return cls(entries)

    def all(self) -> list[SourceRef]:
        return list(self._entries)

    def get(self, source_id: str) -> SourceRef:
        return self._by_id[source_id]

    def enabled(self) -> list[SourceRef]:
        return [e for e in self._entries if e.enabled]

    def filter(self, level=None, province=None, owner_group=None, industry=None) -> list[SourceRef]:
        out: list[SourceRef] = []
        for e in self._entries:
            if level and e.level != level:
                continue
            if province and e.province != province:
                continue
            if owner_group and e.owner_group != owner_group:
                continue
            if industry and e.industry != industry:
                continue
            out.append(e)
        return out
