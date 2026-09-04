"""四川省建筑市场监管公共服务平台（含安许/资质/诚信）adapter——四川插件主源。

采集契约（fixture 假设格式，URL 人工复核后修正）：
- qualifications[]：资质/安许当前状态 → kind=license_authority_status（供 §6 背景规则）
- penalties[]：省级行政处罚/不良行为 → 同信用中国映射（限制投标/证照吊销/其他）
全部记录经主体一致性检查（subject_attrs）；状态映射/SSRF/超时由共享基座承担。
"""
from __future__ import annotations

import json

from ....core.models import Company, Finding
from ...national.base import NationalAdapter, parse_date, subject_attrs

_REVOCATION_STATES = (
    "责令停产停业", "暂扣营业执照", "吊销营业执照", "暂扣许可证", "吊销许可证",
    "吊销资质证书", "暂扣安全生产许可证", "吊销安全生产许可证",
)


class Adapter(NationalAdapter):
    source_id = "sc_construction"

    def parse(self, text: str, *, company: Company) -> list[Finding]:
        data = json.loads(text) or {}
        findings: list[Finding] = []
        for it in data.get("qualifications") or []:
            findings.append(Finding(
                kind="license_authority_status", source_id=self.source_id,
                grade=str(it.get("grade", "A")),
                description=str(it.get("cert_name", "资质/安许登记")),
                attrs={**subject_attrs(company, it),
                       "status": str(it.get("status", "")),
                       "cert": it.get("cert_name")},
            ))
        for it in data.get("penalties") or []:
            content = str(it.get("penalty_content", ""))
            grade = str(it.get("grade", "A"))
            start, end = parse_date(it.get("start_date")), parse_date(it.get("end_date"))
            subj = subject_attrs(company, it)
            if "限制投标" in content or "限制采购" in content:
                findings.append(Finding(
                    kind="penalty_bid_restriction", source_id=self.source_id, grade=grade,
                    description=content, start_date=start, end_date=end,
                    attrs={**subj, "authority_level": str(it.get("authority_level", "province"))},
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
