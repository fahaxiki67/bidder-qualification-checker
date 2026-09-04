"""数据源注册表：官方 URL 只进 config/sources_registry.yaml，禁止散落源码（任务书 §10）。"""
from __future__ import annotations

from pathlib import Path

import yaml

from .models import SourceRef

_FIELDS = set(SourceRef.__dataclass_fields__)


class SourceRegistry:
    def __init__(self, entries):
        self._entries: list[SourceRef] = list(entries)
        self._by_id: dict[str, SourceRef] = {e.id: e for e in self._entries}

    @classmethod
    def from_yaml(cls, path: str | Path) -> "SourceRegistry":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        raw = data.get("sources") or []
        entries = [SourceRef(**{k: v for k, v in item.items() if k in _FIELDS}) for item in raw]
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
