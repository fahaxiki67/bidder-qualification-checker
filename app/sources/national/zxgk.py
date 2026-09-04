"""中国执行信息公开网（zxgk.court.gov.cn）：被执行人 / 失信被执行人。

P3 骨架：响应格式为联调前假设（JSON：dishonest[] / executed[]），真实接口复核后
必须修正解析器。抽取映射：kind=court_dishonesty / court_executed（客观记录；
条款映射待条款表确认后接入 RuleEngine，采集本身不做判断）。
"""
from __future__ import annotations

import json

from ...core.models import Company, Finding
from .base import NationalAdapter, parse_date, subject_attrs


class Adapter(NationalAdapter):
    source_id = "zxgk"

    def parse(self, text: str, *, company: Company) -> list[Finding]:
        data = json.loads(text) or {}
        findings: list[Finding] = []
        for it in data.get("dishonest") or []:
            findings.append(Finding(
                kind="court_dishonesty", source_id=self.source_id, grade="A",
                description=str(it.get("case_note", "失信被执行人记录")),
                start_date=parse_date(it.get("file_date")), end_date=None,
                attrs={**subject_attrs(company, it),
                       "case_code": it.get("case_code"), "court": it.get("court"),
                       "name": it.get("name")},
            ))
        for it in data.get("executed") or []:
            findings.append(Finding(
                kind="court_executed", source_id=self.source_id, grade="A",
                description=str(it.get("case_note", "被执行人记录")),
                start_date=parse_date(it.get("file_date")), end_date=None,
                attrs={**subject_attrs(company, it),
                       "case_code": it.get("case_code"), "court": it.get("court"),
                       "amount": it.get("amount")},
            ))
        return findings
