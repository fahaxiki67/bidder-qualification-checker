"""应急管理部安全生产信用查询（mem.gov.cn）：安全生产失信 / 处罚。

P3 骨架：响应格式为联调前假设（JSON：penalties[]），查询子路径待复核
（见 sources_registry notes）。抽取映射：
- 一律 kind=penalty_safety（客观记录）
- 内容含「限制投标/限制采购」且机关层级达到省级 → 另记 penalty_bid_restriction
"""
from __future__ import annotations

import json

from ...core.models import Company, Finding
from .base import NationalAdapter, parse_date


class Adapter(NationalAdapter):
    source_id = "mem_safety_credit"

    def parse(self, text: str, *, company: Company) -> list[Finding]:
        data = json.loads(text) or {}
        findings: list[Finding] = []
        for it in data.get("penalties") or []:
            content = str(it.get("content", ""))
            grade = str(it.get("grade", "A"))
            level = it.get("authority_level", "national")
            start, end = parse_date(it.get("start_date")), parse_date(it.get("end_date"))
            findings.append(Finding(
                kind="penalty_safety", source_id=self.source_id, grade=grade,
                description=content, start_date=start, end_date=end,
                attrs={"authority_level": level},
            ))
            if ("限制投标" in content or "限制采购" in content) and level in ("province", "national"):
                findings.append(Finding(
                    kind="penalty_bid_restriction", source_id=self.source_id, grade=grade,
                    description=content, start_date=start, end_date=end,
                    attrs={"authority_level": level},
                ))
        return findings
