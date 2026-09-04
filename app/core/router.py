"""SourceRouter：查什么数据源不由“公司在哪”单方面决定（任务书 §3）。

正确模型 = 全国共性检查 + 证照发证地检查 + 项目所在地检查 + 招标人专项检查。
例：四川企业投广东的中国电建项目 → 全国平台 + 四川(发证地) + 广东(项目地) + 电建禁入。
"""
from __future__ import annotations

from .models import Company, Project, SourceRef
from .registry import SourceRegistry


def plan(company: Company, project: Project, registry: SourceRegistry) -> list[SourceRef]:
    picked: dict[str, SourceRef] = {}

    def add(e: SourceRef) -> None:
        picked.setdefault(e.id, e)

    enabled = registry.enabled()
    # 1) 全国共性：所有企业都跑
    for e in enabled:
        if e.level == "national":
            add(e)
    # 2) 招标人/集团专项
    for e in enabled:
        if e.level == "owner" and project.owner_group and e.owner_group == project.owner_group:
            add(e)
    # 3) 省级：注册地（发证地）与项目所在地都要核，同省只查一次
    for e in enabled:
        if e.level != "province":
            continue
        hit_registered = company.registered_province and e.province == company.registered_province
        hit_project = project.province and e.province == project.province
        if hit_registered or hit_project:
            add(e)
    return list(picked.values())
