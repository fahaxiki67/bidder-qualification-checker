"""企业同一性判定：统一社会信用代码优先，同名企业不得误匹配（任务书 §18）。"""
from __future__ import annotations

from .models import Company


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
