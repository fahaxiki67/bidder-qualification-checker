"""企业同一性判定：统一社会信用代码优先，同名企业不得误匹配（任务书 §18）。

P0.5 §六：主体一致性检查进入真实链路——全国源记录形成 Finding 前必须经过
check_subject 判定，判定结果与双方主体标识随 Finding.attrs 可追溯。

判定规则（宁可转人工，不可错并主体）：
1. 双方都有 USCC：必须一致才认定同一主体；
2. 名称写法有差异但 USCC 一致 → 认定同一主体并记录依据；
3. 名称相同但 USCC 不同 → 判定不是同一主体；
4. 仅一方有 USCC → 不得自动认定 → UNCONFIRMED；
5. 双方均无 USCC → 规范化名称一致才认定同一主体；
6. 仅简称/模糊包含/部分相似 → 不得形成确定性认定 → UNCONFIRMED；
7. 无法确认主体 → UNCONFIRMED（下游转人工，不得直接作否决证据）。
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import Company

SAME_SUBJECT = "SAME_SUBJECT"
DIFFERENT_SUBJECT = "DIFFERENT_SUBJECT"
UNCONFIRMED = "UNCONFIRMED"


def _norm_name(name: str) -> str:
    return "".join(name.split()).replace("（", "(").replace("）", ")").lower()


def same_company(a: Company, b: Company) -> bool:
    """判定两家公司记录是否指向同一主体。

    - 双方都有 USCC：只有代码一致才算同一家；
    - 仅一方有 USCC：不判定为同一家（宁可多查一次，不可错并主体）；
    - 双方都无 USCC：名称规范化后一致才视为同一家。
    """
    if a.uscc and b.uscc:
        return a.uscc.strip().upper() == b.uscc.strip().upper()
    if a.uscc or b.uscc:
        return False
    return bool(a.name) and _norm_name(a.name) == _norm_name(b.name)


@dataclass
class SubjectMatch:
    """主体一致性判定结果（随 Finding.attrs 全量留痕）。"""

    match_result: str        # SAME_SUBJECT / DIFFERENT_SUBJECT / UNCONFIRMED
    matched_by: str          # USCC / NORMALIZED_NAME / NONE
    reason: str              # 判定依据说明


def check_subject(requested_name, requested_uscc, source_name, source_uscc) -> SubjectMatch:
    """请求主体 vs 数据源记录主体的一致性判定（§六规则 1-7）。"""
    r_uscc = (requested_uscc or "").strip().upper() or None
    s_uscc = (source_uscc or "").strip().upper() or None
    r_name = (requested_name or "").strip()
    s_name = (source_name or "").strip()

    if r_uscc and s_uscc:
        if r_uscc == s_uscc:
            if _norm_name(r_name) != _norm_name(s_name):
                return SubjectMatch(
                    SAME_SUBJECT, "USCC",
                    f"USCC 一致认定同一主体（名称写法不同：请求「{r_name}」/来源「{s_name}」，以登记代码为准）")
            return SubjectMatch(SAME_SUBJECT, "USCC", "USCC 与名称均一致")
        if _norm_name(r_name) == _norm_name(s_name):
            return SubjectMatch(
                DIFFERENT_SUBJECT, "USCC",
                f"名称相同但 USCC 不同（请求 {r_uscc} / 来源 {s_uscc}）：不是同一主体")
        return SubjectMatch(
            DIFFERENT_SUBJECT, "USCC",
            f"USCC 不同（请求 {r_uscc} / 来源 {s_uscc}）：不是同一主体")

    if r_uscc or s_uscc:
        return SubjectMatch(
            UNCONFIRMED, "NONE",
            "仅一方提供 USCC，不得自动认定同一主体，转人工确认")

    if r_name and s_name and _norm_name(r_name) == _norm_name(s_name):
        return SubjectMatch(
            SAME_SUBJECT, "NORMALIZED_NAME",
            "双方均无 USCC，规范化名称完全一致认定同一主体（建议补录 USCC 闭环）")

    return SubjectMatch(
        UNCONFIRMED, "NONE",
        f"无法确认主体（请求「{r_name}」/来源「{s_name}」）：简称/模糊相似不得作确定性认定，转人工")
