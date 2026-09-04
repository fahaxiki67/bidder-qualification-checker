"""全国建筑市场监管公共服务平台（jzsc.mohurd.gov.cn）：建筑企业资质 / 人员。

P3 骨架：响应格式为联调前假设（JSON：qualifications[]，status ∈ 正常/延期/过期/
注销/吊销/暂扣），真实接口复核后必须修正解析器。抽取映射：
kind=license_authority_status（主管部门当前状态，直接供 LicenseValidityRule 评判）。
"""
from __future__ import annotations

import json

from ...core.models import Company, Finding
from .base import NationalAdapter, subject_attrs


class Adapter(NationalAdapter):
    source_id = "jzsc"

    def parse(self, text: str, *, company: Company) -> list[Finding]:
        data = json.loads(text) or {}
        findings: list[Finding] = []
        for it in data.get("qualifications") or []:
            findings.append(Finding(
                kind="license_authority_status", source_id=self.source_id,
                grade=str(it.get("grade", "A")),
                description=str(it.get("cert_name", "资质登记")),
                attrs={**subject_attrs(company, it),
                       "status": str(it.get("status", "")), "cert": it.get("cert_name")},
            ))
        return findings
