"""国家企业信用信息公示系统（gsxt.gov.cn）骨架（P3 仅占位）。

有图片验证码（automation_mode=auto_fill_manual_verify）：任何情况下都返回 MANUAL，
等待白天「自动导航+人工验证+继续解析」真机联调；绝不自动提交、绝不伪造查询成功。
"""
from __future__ import annotations

from ...core.models import Company, SourceRef
from .base import AdapterOutcome, NationalAdapter
from ...core.status import Status


class Adapter(NationalAdapter):
    source_id = "gsxt"

    def query(self, company: Company, source: SourceRef, *, get=None, timeout: float = 15.0) -> AdapterOutcome:
        return AdapterOutcome(
            self.source_id, Status.MANUAL, [], source.query_url or source.official_home,
            note="gsxt 有验证码：需自动导航+人工验证联调，骨架期一律转人工核查",
        )

    def parse(self, text: str, *, company: Company) -> list:
        return []  # 骨架期不解析 gsxt 页面
