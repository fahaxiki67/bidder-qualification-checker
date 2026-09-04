"""状态合并闭环测试（P0.5 任务书 §三）。

业务判断（规则）与数据获取（数据源）分层合并：
- 明确要求人工复核的，最终结果不得仅显示 WARNING/NO_DATA/PASS；
- ERROR/TIMEOUT/BLOCKED/UNKNOWN 不得被 PASS/NO_DATA 掩盖；
- 数据获取失败不得因另一条 WARNING 而丢失；
- FAIL 是明确业务否决结论可作展示位，但数据异常与人工复核要求仍必须保留
  （经 data_status / manual_required 字段）。
"""
import pytest

from app.core.status import (
    NEVER_PASS,
    Status,
    combine,
    combine_data,
    combine_decision,
    needs_manual,
    overall,
)


@pytest.mark.parametrize(
    ("decision", "data", "expected"),
    [
        # 任务书 §三 最低要求的 8 组组合
        (Status.PASS, Status.MANUAL, Status.MANUAL),      # 不显示 PASS
        (Status.WARNING, Status.MANUAL, Status.MANUAL),   # 不显示 WARNING
        (Status.WARNING, Status.BLOCKED, Status.BLOCKED),  # 数据异常不被业务提示掩盖
        (Status.WARNING, Status.TIMEOUT, Status.TIMEOUT),
        (Status.WARNING, Status.ERROR, Status.ERROR),
        (Status.PASS, Status.UNKNOWN, Status.UNKNOWN),    # 不显示 PASS
        (Status.FAIL, Status.MANUAL, Status.FAIL),        # 否决结论成立，
        (Status.FAIL, Status.ERROR, Status.FAIL),         # 数据异常经 data_status 保留
        # 补充边界
        (Status.PASS, Status.PASS, Status.PASS),
        (Status.FAIL, Status.PASS, Status.FAIL),
        (Status.MANUAL, Status.PASS, Status.MANUAL),
        (Status.PASS, Status.NO_DATA, Status.NO_DATA),
        (Status.WARNING, Status.NO_DATA, Status.WARNING),
        (Status.WARNING, Status.PASS, Status.WARNING),
        (Status.UNKNOWN, Status.PASS, Status.UNKNOWN),
        (Status.NO_DATA, Status.PASS, Status.NO_DATA),
    ],
)
def test_overall_display_matrix(decision, data, expected):
    assert overall(decision, data) is expected


@pytest.mark.parametrize("s", sorted(NEVER_PASS, key=lambda x: x.value))
def test_data_failure_survives_warning_and_pass(s):
    """任一 NEVER_PASS 数据状态都不被 PASS/WARNING/NO_DATA 掩盖。"""
    for other in (Status.PASS, Status.WARNING, Status.NO_DATA):
        assert overall(other, s) is s
    for other in (Status.PASS, Status.NO_DATA):  # 数据源不产出 WARNING，不入 combine_data
        assert combine_data([other, s]) is s


def test_decision_layer_ordering():
    assert combine_decision([Status.FAIL, Status.WARNING]) is Status.FAIL
    assert combine_decision([Status.WARNING, Status.MANUAL]) is Status.MANUAL
    assert combine_decision([Status.UNKNOWN, Status.NO_DATA]) is Status.UNKNOWN
    assert combine_decision([Status.PASS, Status.NO_DATA]) is Status.NO_DATA
    # 空输入 = 规则未检索到记录 → NO_DATA（"没有查到"不得显示为"正常"）
    assert combine_decision([]) is Status.NO_DATA


def test_data_layer_ordering():
    assert combine_data([Status.BLOCKED, Status.TIMEOUT]) is Status.BLOCKED
    assert combine_data([Status.ERROR, Status.NO_DATA]) is Status.ERROR
    assert combine_data([Status.PASS, Status.NO_DATA]) is Status.NO_DATA
    assert combine_data([]) is Status.NO_DATA


@pytest.mark.parametrize(
    ("decision", "data", "expect"),
    [
        ((Status.FAIL,), (Status.MANUAL,), True),
        ((Status.PASS,), (Status.MANUAL,), True),
        ((Status.MANUAL,), (Status.PASS,), True),
        ((Status.PASS,), (Status.BLOCKED,), False),   # BLOCKED 是数据异常，不是"要求人工"
        ((Status.FAIL,), (Status.ERROR,), False),
        ((Status.PASS,), (Status.PASS,), False),
    ],
)
def test_needs_manual(decision, data, expect):
    assert needs_manual(decision, data) is expect


def test_legacy_combine_keeps_never_pass_visible():
    """兼容旧签名：数据层失败状态与 WARNING 混合时不得丢失。"""
    assert combine([Status.WARNING, Status.MANUAL]) is Status.MANUAL
    assert combine([Status.WARNING, Status.ERROR]) is Status.ERROR
    assert combine([Status.PASS, Status.BLOCKED]) is Status.BLOCKED
    assert combine([Status.FAIL, Status.WARNING]) is Status.FAIL
    assert combine([Status.PASS]) is Status.PASS


def test_fail_with_data_error_preserves_data_status():
    """FAIL 抢占展示位时，数据异常与人工要求必须仍可从分层字段读出。"""
    decision = combine_decision([Status.FAIL])
    data = combine_data([Status.ERROR])
    assert overall(decision, data) is Status.FAIL
    assert data is Status.ERROR          # 数据异常保留
    # needs_manual 吃的是合并前的原始状态列表（合并会把 MANUAL 吸收进 FAIL）：
    # 规则层有 FAIL 也有 MANUAL 时，人工要求不得因 FAIL 抢占而丢失
    assert needs_manual([Status.FAIL, Status.MANUAL], [Status.ERROR]) is True
    assert needs_manual([decision], [data]) is False  # 纯 FAIL 无人工成分
