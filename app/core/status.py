"""核查状态模型（任务书 §7）。

强制规则：ERROR / TIMEOUT / BLOCKED / MANUAL / UNKNOWN 永远不得自动算作 PASS；
"没有查到"（NO_DATA）与"确认不存在"必须分开。
"""
from __future__ import annotations

from enum import Enum


class Status(str, Enum):
    PASS = "PASS"          # 查询成功，未发现触发条件
    WARNING = "WARNING"    # 发现风险，但尚不足以否决
    FAIL = "FAIL"          # 存在明确官方证据触发条款
    MANUAL = "MANUAL"      # 需人工验证码/登录/复核
    NO_DATA = "NO_DATA"    # 查询成功，但本次未检索到相应记录
    ERROR = "ERROR"        # 查询失败
    TIMEOUT = "TIMEOUT"    # 超时
    BLOCKED = "BLOCKED"    # 访问被限制
    UNKNOWN = "UNKNOWN"    # 证据不足，无法确认


#: 这些状态永远不得被自动归约为 PASS
NEVER_PASS: frozenset[Status] = frozenset(
    {Status.ERROR, Status.TIMEOUT, Status.BLOCKED, Status.MANUAL, Status.UNKNOWN}
)

#: 严重度排序（index 越小越严重），combine 据此取最严重者
_SEVERITY_ORDER: tuple[Status, ...] = (
    Status.FAIL,
    Status.WARNING,
    Status.MANUAL,
    Status.BLOCKED,
    Status.TIMEOUT,
    Status.ERROR,
    Status.UNKNOWN,
    Status.NO_DATA,
    Status.PASS,
)


def combine(statuses) -> Status:
    """汇合多个状态，返回最严重者。空输入返回 NO_DATA（查过但没有可得结论）。"""
    sts = [Status(s) for s in statuses]
    if not sts:
        return Status.NO_DATA
    return min(sts, key=_SEVERITY_ORDER.index)


def report_label(status: Status) -> str:
    """报告用语（任务书 §21）：未成功查询绝不允许显示“正常”。"""
    if status in NEVER_PASS:
        return {
            Status.MANUAL: "待人工核查",
            Status.UNKNOWN: "无法确认",
            Status.ERROR: "查询失败",
            Status.TIMEOUT: "查询超时",
            Status.BLOCKED: "访问被限制",
        }[status]
    return {
        Status.PASS: "正常",
        Status.WARNING: "风险提示",
        Status.FAIL: "触发否决条款",
        Status.NO_DATA: "未检索到记录",
    }[status]
