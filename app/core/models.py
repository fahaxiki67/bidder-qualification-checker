"""核心数据模型（轻量 dataclass，P1 骨架）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


def years_ago(d: date, n: int) -> date:
    """d 往前推 n 年；闰日 2/29 无对应年时落到 2/28。"""
    try:
        return d.replace(year=d.year - n)
    except ValueError:  # 2月29日
        return d.replace(year=d.year - n, day=28)


@dataclass(frozen=True)
class Company:
    """被核查企业。统一社会信用代码是主键级标识，名称仅作展示/模糊线索。"""

    name: str
    uscc: str | None = None
    registered_province: str | None = None  # 注册地省份，如“四川”


@dataclass(frozen=True)
class Project:
    """招标项目信息：数据源路由与条款评判都依赖它。"""

    name: str
    province: str | None = None            # 项目所在地省
    city: str | None = None
    industry: str | None = None            # 行业
    owner_group: str | None = None         # 招标人/采购人集团标识，如 powerchina
    base_date: date = field(default_factory=date.today)  # 核查基准日
    years_back: int = 3                    # “近三年”窗口
    terms: tuple[str, ...] = ()            # 本项目具体资格审查条款编号

    @property
    def window_start(self) -> date:
        return years_ago(self.base_date, self.years_back)


@dataclass(frozen=True)
class SourceRef:
    """数据源注册表条目（config/sources_registry.yaml 的一行，任务书 §10）。"""

    id: str
    name: str
    level: str                      # national | province | city | owner
    province: str | None = None
    city: str | None = None
    industry: str | None = None
    owner_group: str | None = None  # level=owner 时必填，如 powerchina
    authority: str | None = None
    source_type: str | None = None
    official_home: str | None = None
    query_url: str | None = None
    automation_mode: str = "manual"  # auto | auto_fill_manual_verify | manual
    evidence_grade: str = "A"        # A | B | C | D
    enabled: bool = True
    last_verified: str | None = None  # 最近人工验证日期 YYYY-MM-DD
    adapter: str | None = None
    notes: str | None = None


@dataclass
class Finding:
    """Source Adapter 产出的一条客观事实（只描述“查到了什么”，不做资格判断）。"""

    kind: str                       # penalty_bid_restriction / penalty_business / bankruptcy_status / owner_ban / license_surface_expired / license_authority_status ...
    source_id: str
    grade: str                      # 证据等级 A|B|C|D
    description: str = ""
    start_date: date | None = None
    end_date: date | None = None
    attrs: dict = field(default_factory=dict)


@dataclass
class RuleResult:
    """RuleEngine 对单条资格条款的评判结论。"""

    rule_id: str
    title: str
    status: str                     # Status 值
    reasons: list[str] = field(default_factory=list)
    company: str | None = None
