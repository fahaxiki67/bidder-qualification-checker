import pytest

from app.core.status import NEVER_PASS, Status, combine, report_label


def test_nine_states_exist():
    assert {s.value for s in Status} == {
        "PASS", "WARNING", "FAIL", "MANUAL", "NO_DATA",
        "ERROR", "TIMEOUT", "BLOCKED", "UNKNOWN",
    }


@pytest.mark.parametrize("s", list(NEVER_PASS))
def test_never_pass_states_survive_combine(s):
    assert combine([s, Status.PASS]) is s
    assert combine([Status.PASS, s]) is s
    assert combine([s]) is s


def test_combine_ordering():
    assert combine([Status.FAIL, Status.WARNING]) is Status.FAIL
    assert combine([Status.WARNING, Status.ERROR]) is Status.WARNING
    assert combine([Status.NO_DATA, Status.PASS]) is Status.NO_DATA
    assert combine([Status.PASS]) is Status.PASS


def test_combine_empty_is_no_data():
    assert combine([]) is Status.NO_DATA


def test_report_labels_never_call_failure_normal():
    for s in NEVER_PASS:
        assert report_label(s) != "正常"
    assert report_label(Status.ERROR) == "查询失败"
    assert report_label(Status.MANUAL) == "待人工核查"
    assert report_label(Status.UNKNOWN) == "无法确认"
    assert report_label(Status.NO_DATA) == "未检索到记录"
