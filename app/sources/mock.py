"""演示/测试用 mock 数据源：按场景返回预置事实。

纪律：夜间无人值守只允许 mock（config/app.yaml nightly_mock_only）；
真实 adapter（P3 起）必须另行人工验证 URL 并在白天配合人工验证联调。
"""
from __future__ import annotations

from datetime import date, timedelta

from ..core.models import Company, Finding, Project

SCENARIOS = {
    "clean": "无异常（多数源无记录）",
    "bid_ban": "省级限制投标且在有效期内（条款1 FAIL）",
    "bid_ban_expired": "限制投标已解除（条款1 仅提示）",
    "revoked": "当前吊销营业执照（条款2 FAIL）",
    "bankruptcy": "已宣告破产（条款3 FAIL）",
    "owner_ban": "中国电建集团禁入有效期内（条款4 FAIL）",
    "license_surface_expired": "安许扫描件过期但官方已延期（§6 仅 WARNING）",
    "query_error": "数据源查询失败（ERROR 不得算 PASS）",
}


def findings_for(scenario: str, company: Company, project: Project) -> list[Finding]:
    today = project.base_date
    if scenario == "bid_ban":
        return [Finding(
            kind="penalty_bid_restriction", source_id="creditchina", grade="A",
            description=f"{company.name} 被省级住建主管部门暂停参加投标活动一年",
            start_date=today - timedelta(days=30), end_date=today + timedelta(days=335),
            attrs={"authority_level": "province"},
        )]
    if scenario == "bid_ban_expired":
        return [Finding(
            kind="penalty_bid_restriction", source_id="creditchina", grade="A",
            description="限制投标处罚已于去年到期解除",
            start_date=date(today.year - 2, 1, 1), end_date=date(today.year - 1, 1, 1),
            attrs={"authority_level": "province"},
        )]
    if scenario == "revoked":
        return [Finding(
            kind="penalty_business", source_id="creditchina", grade="A",
            description="营业执照被吊销，当前状态",
            attrs={"current": True, "status": "吊销营业执照"},
        )]
    if scenario == "bankruptcy":
        return [Finding(
            kind="bankruptcy_status", source_id="pcczdc", grade="A",
            description="法院已宣告该公司破产",
            attrs={"current": True, "state": "宣告破产"},
        )]
    if scenario == "owner_ban":
        group = project.owner_group or "powerchina"
        return [Finding(
            kind="owner_ban", source_id="powerchina_ban", grade="A",
            description="列入股份公司级禁入供应商名单，禁入三年",
            start_date=today - timedelta(days=100), end_date=today + timedelta(days=1000),
            attrs={"owner_group": group, "scope": "股份公司级"},
        )]
    if scenario == "license_surface_expired":
        return [
            Finding(
                kind="license_surface_expired", source_id="sc_construction", grade="B",
                description="投标文件扫描件载明有效期已过（如 (川)JZ安许证字〔2023〕007346 至 2026-04-17）",
            ),
            Finding(
                kind="license_authority_status", source_id="sc_construction", grade="A",
                description="主管部门登记显示已完成延期，证书当前有效",
                attrs={"status": "延期"},
            ),
        ]
    if scenario == "query_error":
        return [Finding(
            kind="source_error", source_id="creditchina", grade="A",
            description="模拟：数据源查询失败（演示 ERROR 不算 PASS）",
        )]
    return []  # clean
