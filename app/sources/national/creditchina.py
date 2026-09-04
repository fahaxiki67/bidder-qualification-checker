"""信用中国（creditchina.gov.cn）：行政处罚 / 失信记录。

P3 骨架：响应格式为联调前假设（JSON 列表 result[...]），真实接口复核后必须
修正解析器并回填 last_verified。抽取映射：
- 处罚内容含「限制投标/限制采购」→ kind=penalty_bid_restriction（authority_level 取备案层级）
- 处罚内容含证照否决关键词 → kind=penalty_business（current/status）
- 其余 → kind=penalty_other（仅记录；普通罚款不自动等于 FAIL）
"""
from __future__ import annotations

import json

from ...core.models import Company, Finding
from .base import NationalAdapter, parse_date, subject_attrs

_REVOCATION_STATES = (
    "责令停产停业", "暂扣营业执照", "吊销营业执照", "暂扣许可证", "吊销许可证", "吊销资质证书",
)


class Adapter(NationalAdapter):
    source_id = "creditchina"

    def parse(self, text: str, *, company: Company) -> list[Finding]:
        data = json.loads(text) or {}
        items = data.get("result") or []
        findings: list[Finding] = []
        for it in items:
            content = str(it.get("penalty_content", ""))
            grade = str(it.get("grade", "A"))
            start, end = parse_date(it.get("start_date")), parse_date(it.get("end_date"))
            subj = subject_attrs(company, it)
            if "限制投标" in content or "限制采购" in content:
                findings.append(Finding(
                    kind="penalty_bid_restriction", source_id=self.source_id, grade=grade,
                    description=content, start_date=start, end_date=end,
                    attrs={**subj, "authority_level": it.get("authority_level", "city")},
                ))
                continue
            state = next((s for s in _REVOCATION_STATES if s in content), None)
            if state:
                findings.append(Finding(
                    kind="penalty_business", source_id=self.source_id, grade=grade,
                    description=content, start_date=start, end_date=end,
                    attrs={**subj, "current": bool(it.get("current", True)), "status": state},
                ))
                continue
            findings.append(Finding(
                kind="penalty_other", source_id=self.source_id, grade=grade,
                description=content, start_date=start, end_date=end, attrs=subj,
            ))
        return findings
