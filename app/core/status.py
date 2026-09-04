"""核查状态模型（任务书 §7）。

强制规则：ERROR / TIMEOUT / BLOCKED / MANUAL / UNKNOWN 永远不得自动算作 PASS；
"没有查到"（NO_DATA）与"确认不存在"必须分开。

两层状态（P0.5 §三）：业务判断与数据获取分开合并。
此前单一严重度表把 WARNING 排在 MANUAL/BLOCKED/TIMEOUT/ERROR 之前，
导致"风险提示"掩盖数据异常与人工复核要求——已修正：

- 决策层（规则评判）：FAIL > MANUAL > WARNING > PASS
- 数据层（数据源查询）：MANUAL > BLOCKED > TIMEOUT > ERROR > UNKNOWN > NO_DATA > PASS
- 展示层 overall(decision, data)：FAIL/MANUAL 决策优先展示，数据层 NEVER_PASS
  状态优先于 WARNING/PASS/NO_DATA 展示；决策 FAIL 时数据异常经 data_status 保留。
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

#: 数据源"不适用"标记（P0.5 §七）：不属于九态判定结果，只是路由结论——
#: 行业/集团不适用的源记录为该值，绝不写成 NO_DATA（"不适用"≠"查了没查到"），
#: 也不参与数据层状态合并（不把总体结论顶成任何失败态）。
NOT_APPLICABLE = "NOT_APPLICABLE"

#: 决策层（规则评判）严重度：index 越小越严重。
#: 规则可产出 UNKNOWN（C/D 级线索不足以 FAIL）与 NO_DATA（未检索到该类记录），
#: 二者属于决策信息，排在 WARNING 之后、PASS 之前。
_DECISION_ORDER: tuple[Status, ...] = (
    Status.FAIL,
    Status.MANUAL,
    Status.WARNING,
    Status.UNKNOWN,
    Status.NO_DATA,
    Status.PASS,
)

#: 数据获取层严重度：人工复核/访问受限/超时/失败绝不被业务提示或"无记录"掩盖
_DATA_ORDER: tuple[Status, ...] = (
    Status.MANUAL,
    Status.BLOCKED,
    Status.TIMEOUT,
    Status.ERROR,
    Status.UNKNOWN,
    Status.NO_DATA,
    Status.PASS,
)

_DECISION_SET = frozenset(_DECISION_ORDER)
_DATA_SET = frozenset(_DATA_ORDER)


def combine_decision(statuses) -> Status:
    """合并规则评判状态（FAIL/MANUAL/WARNING/UNKNOWN/NO_DATA/PASS）。

    空输入 = 规则未检索到任何相关记录 → NO_DATA（"没有查到"不得显示为"正常"）。
    """
    sts = [Status(s) for s in statuses]
    if not sts:
        return Status.NO_DATA
    return min(sts, key=_DECISION_ORDER.index)


def combine_data(statuses) -> Status:
    """合并数据源查询状态。任一 NEVER_PASS 状态绝不被 PASS/NO_DATA/WARNING 掩盖。"""
    sts = [Status(s) for s in statuses]
    if not sts:
        return Status.NO_DATA
    return min(sts, key=_DATA_ORDER.index)


def overall(decision: Status, data: Status) -> Status:
    """展示层单一结论。

    - FAIL / MANUAL 决策优先展示（数据异常经 data_status 单独保留，不丢失）；
    - 数据层 NEVER_PASS 状态优先于 WARNING/PASS/NO_DATA 展示：
      要求人工复核的最终结果不得仅显示 WARNING/NO_DATA/PASS；
      数据获取失败不得因另一条 WARNING 而丢失。
    """
    decision = Status(decision)
    data = Status(data)
    if decision == Status.FAIL:
        return Status.FAIL
    if decision == Status.MANUAL:
        return Status.MANUAL
    if data in NEVER_PASS:
        return data
    if decision == Status.WARNING:
        return Status.WARNING
    if decision == Status.UNKNOWN:
        return Status.UNKNOWN
    if decision == Status.NO_DATA or data == Status.NO_DATA:
        return Status.NO_DATA
    return Status.PASS


def needs_manual(decision_statuses, data_statuses) -> bool:
    """人工复核要求：任一规则或任一数据源明确要求人工 → True。

    该标记独立于展示层状态保存，确保 FAIL+MANUAL 等组合下
    "仍需人工复核"的信息不因 FAIL 抢占展示位而丢失。
    """
    return any(Status(s) == Status.MANUAL for s in list(decision_statuses) + list(data_statuses))


def combine(statuses) -> Status:
    """兼容旧签名：任意状态列表的保守合并。

    语义 = 决策层与数据层各自归位后取 overall；
    仅决策层输入 → 决策层结论；仅数据层输入 → 数据层结论。
    """
    sts = [Status(s) for s in statuses]
    if not sts:
        return Status.NO_DATA
    decisions = [s for s in sts if s in _DECISION_SET]
    datas = [s for s in sts if s not in _DECISION_SET]
    if not datas:
        return combine_decision(decisions)
    if not decisions:
        return combine_data(datas)
    return overall(combine_decision(decisions), combine_data(datas))


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
