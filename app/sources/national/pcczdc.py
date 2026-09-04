"""全国企业破产重整案件信息网（pccz.court.gov.cn）：破产 / 清算公告。

P3 骨架：响应格式为联调前假设（JSON：cases[]，state ∈ 宣告破产/清算程序/…），
域名与接口待人工复核后启用真实查询。抽取映射：
kind=bankruptcy_status（attrs.current/state，直接供 BankruptcyRule 评判）。
"""
from __future__ import annotations

import json

from ...core.models import Company, Finding
from .base import NationalAdapter, parse_date, subject_attrs


class Adapter(NationalAdapter):
    source_id = "pcczdc"

    def parse(self, text: str, *, company: Company) -> list[Finding]:
        data = json.loads(text) or {}
        findings: list[Finding] = []
        for it in data.get("cases") or []:
            findings.append(Finding(
                kind="bankruptcy_status", source_id=self.source_id,
                grade=str(it.get("grade", "A")),
                description=str(it.get("case_note", "破产重整案件公告")),
                start_date=parse_date(it.get("file_date")), end_date=None,
                attrs={**subject_attrs(company, it),
                       "current": bool(it.get("current", True)),
                       "state": str(it.get("state", "")),
                       "case_code": it.get("case_code"), "court": it.get("court")},
            ))
        return findings
