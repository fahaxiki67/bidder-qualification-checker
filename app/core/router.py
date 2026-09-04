"""SourceRouter：查什么数据源不由“公司在哪”单方面决定（任务书 §3）。

正确模型 = 全国共性检查 + 证照发证地检查 + 项目所在地检查 + 招标人专项检查。
例：四川企业投广东的中国电建项目 → 全国平台 + 四川(发证地) + 广东(项目地) + 电建禁入。

P0.5 §七：数据源限定行业（SourceRef.industry）时只对适用行业计划查询；
不适用的源必须显式记录 NOT_APPLICABLE（含原因），不得冒充"查询无数据"，
也不得被强行查询。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Company, Project, SourceRef
from .registry import SourceRegistry

_INDUSTRY_SPLIT = re.compile(r"[,，、;；/\s]+")


def _industry_set(raw: str | None) -> set[str]:
    return {x for x in _INDUSTRY_SPLIT.split(raw or "") if x}


def industry_applicable(source_industry: str | None, project_industry: str | None) -> bool:
    """数据源未限定行业 → 恒适用；限定行业时项目行业必须命中其一。"""
    wanted = _industry_set(source_industry)
    if not wanted:
        return True
    return bool(_industry_set(project_industry) & wanted)


@dataclass
class RouteResult:
    """路由结果：planned=要查的源；not_applicable=(源, 不适用原因) 显式留痕。"""

    planned: list[SourceRef] = field(default_factory=list)
    not_applicable: list[tuple[SourceRef, str]] = field(default_factory=list)


def plan_with_exclusions(company: Company, project: Project,
                         registry: SourceRegistry) -> RouteResult:
    """完整路由：计划内源 + 行业不适用清单（P0.5 §七）。

    原 plan() 的三维逻辑不变：全国共性 / 集团专项 / 注册地+项目地省级。
    新增行业门控：任何层级的数据源限定行业与项目行业不符 → NOT_APPLICABLE。
    """
    picked: dict[str, SourceRef] = {}
    not_applicable: list[tuple[SourceRef, str]] = []

    def add(e: SourceRef) -> None:
        picked.setdefault(e.id, e)

    for e in registry.enabled():
        if not industry_applicable(e.industry, project.industry):
            not_applicable.append((
                e,
                f"行业不适用：数据源限定行业[{e.industry}]，"
                f"项目行业[{project.industry or '未指定'}]",
            ))
            continue
        if e.level == "national":
            add(e)
        elif e.level == "owner":
            # 集团专项源：仅服务匹配的招标人集团（P4）；不匹配=不适用，显式留痕
            if project.owner_group and e.owner_group == project.owner_group:
                add(e)
            else:
                not_applicable.append((
                    e,
                    f"集团专项不适用：数据源属[{e.owner_group}]，"
                    f"本项目招标人集团[{project.owner_group or '未指定'}]",
                ))
        elif e.level == "province":
            hit_registered = company.registered_province and e.province == company.registered_province
            hit_project = project.province and e.province == project.province
            if hit_registered or hit_project:
                add(e)
    return RouteResult(planned=list(picked.values()), not_applicable=not_applicable)


def plan(company: Company, project: Project, registry: SourceRegistry) -> list[SourceRef]:
    """兼容旧签名：只返回计划内数据源。"""
    return plan_with_exclusions(company, project, registry).planned
