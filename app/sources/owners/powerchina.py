"""中国电建禁入/受限供应商名单 adapter（ec.powerchina.cn，P4）。

红线（WORKPLAN §三/任务书）：
- 股份公司/子企业/基层单位三级禁入名单属**内部下发资料**，公开门户不可自动核验
  → automation_mode=manual_intake，查询一律返回 MANUAL（待人工核查），绝不伪造查询成功；
- 名单经人工导入（离线结构化记录）后可离线评判：本模块 parse() 即导入契约，
  记录必须带主体标识（subject_name/subject_uscc），经主体一致性检查后才成为 Finding；
- adapter 只采集，是否触发条款4（招标人集团禁入）由 RuleEngine 评判。
"""
from __future__ import annotations

import json

from ...core.models import Company, Finding
from ..national.base import NationalAdapter, parse_date, subject_attrs

#: 三级禁入口径（股份公司/子企业/基层单位）
_KNOWN_LEVELS = ("股份公司级", "子企业级", "基层单位级")


class Adapter(NationalAdapter):
    source_id = "powerchina_ban"

    def parse(self, text: str, *, company: Company) -> list[Finding]:
        """人工导入名单的离线评判契约（fixture 测试同用此格式）。

        记录字段：
        - subject_name / subject_uscc：名单对象主体标识（必带，进入主体一致性检查）
        - scope：禁入范围（如 全部/施工/物资）
        - list_level：三级口径（股份公司级/子企业级/基层单位级）
        - ban_start / ban_end：禁入起止（ISO 日期；end 为空=未载明解除日期）
        - document_name：下发文件名（证据溯源，P6 接 SHA-256 证据链）
        """
        data = json.loads(text) or {}
        findings: list[Finding] = []
        for it in data.get("bans") or []:
            level = str(it.get("list_level", "")).strip()
            scope = str(it.get("scope", "全部")).strip()
            findings.append(Finding(
                kind="owner_ban", source_id=self.source_id,
                grade=str(it.get("grade", "A")),
                description=str(it.get("description", "")
                                or f"列入中国电建{level or '禁入'}名单（范围：{scope}）"),
                start_date=parse_date(it.get("ban_start")),
                end_date=parse_date(it.get("ban_end")),
                attrs={**subject_attrs(company, it),
                       "owner_group": str(it.get("owner_group", "powerchina")),
                       "scope": scope,
                       "list_level": level if level in _KNOWN_LEVELS else "",
                       "document_name": str(it.get("document_name", "")),
                       },
            ))
        return findings
