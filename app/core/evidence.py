"""证据等级（任务书 §8）：A/B 级官方证据才支持资格否决；C/D 只用于发现线索。"""
from __future__ import annotations

from enum import Enum


class Grade(str, Enum):
    A = "A"  # 政府实时查询 / 法院官方平台 / 招标人集团官方系统
    B = "B"  # 政府正式公告 / 行政决定书 / 官方 PDF
    C = "C"  # 商业数据库（企查查/天眼查等）
    D = "D"  # 搜索引擎摘要 / 新闻 / 自媒体


OFFICIAL_GRADES: frozenset[Grade] = frozenset({Grade.A, Grade.B})


def can_support_fail(grades) -> bool:
    """是否存在至少一条 A/B 级证据。仅 C/D 时不得作 FAIL。"""
    return any(Grade(g) in OFFICIAL_GRADES for g in grades)
