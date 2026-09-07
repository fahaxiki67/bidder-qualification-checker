"""增量规则模块 offline_review_patterns 的单元测试（不依赖文件解析与接线）。"""
from app.offline_review_patterns import (
    PATTERN_THRESHOLDS,
    apply,
    kinship_signals,
    line_item_set_signals,
    person_overlap_signals,
    quote_pattern_signals,
    uniform_discount_signals,
)


def _item(name: str, amount: float) -> dict:
    return {"name": name, "key": name, "amount": amount}


def _bidder(name, total=None, *, control=None, items=(), metadata=None):
    quotes = []
    primary = None
    if total is not None:
        quote = {"label": "投标报价", "value": total, "source": "", "locator": "",
                 "raw": "", "kind": "explicit_total"}
        quotes.append(quote)
        primary = quote
    if control is not None:
        quotes.append({"label": "招标控制价", "value": control, "source": "", "locator": "",
                       "raw": "", "kind": "control"})
    return {"name": name, "quotes": quotes, "primary_quote": primary,
            "line_items": list(items), "metadata": metadata or {}}


def _codes(signals):
    return [s["code"] for s in signals]


def test_arithmetic_and_geometric_quote_patterns_flag_f05():
    arithmetic = [_bidder("甲", 9_000_000), _bidder("乙", 9_500_000), _bidder("丙", 10_000_000)]
    signals = quote_pattern_signals(arithmetic)
    # 等差数列在小步长下同时近似等比，等差/等比两类描述可能同报。
    assert set(_codes(signals)) == {"QUOTE_ARITHMETIC_PATTERN"}
    assert {s["level"] for s in signals} == {"高"}

    geometric = [_bidder("甲", 10_000_000), _bidder("乙", 11_000_000), _bidder("丙", 12_100_000)]
    assert set(_codes(quote_pattern_signals(geometric))) == {"QUOTE_ARITHMETIC_PATTERN"}

    scattered = [_bidder("甲", 9_000_000), _bidder("乙", 9_500_000), _bidder("丙", 13_000_000)]
    assert quote_pattern_signals(scattered) == []

    pair = [_bidder("甲", 9_000_000), _bidder("乙", 9_500_000)]
    assert quote_pattern_signals(pair) == []


def test_uniform_discount_rate_flags_f06_and_skips_control_only_bidders():
    bidders = [
        _bidder("甲", 90_000, control=100_000),
        _bidder("乙", 90_050, control=100_000),
        _bidder("丙", 95_000, control=100_000),
    ]
    assert uniform_discount_signals(bidders) == []

    aligned = [
        _bidder("甲", 90_000, control=100_000),
        _bidder("乙", 90_050, control=100_000),
    ]
    signals = uniform_discount_signals(aligned)
    assert _codes(signals) == ["UNIFORM_DISCOUNT_RATE"]
    assert {e["bidder"] for e in signals[0]["evidence"]} == {"甲", "乙"}

    # 无控制价资料的投标人被如实跳过，不参与下浮率比较。
    mixed = [
        _bidder("甲", 90_000, control=100_000),
        _bidder("乙", 90_000, control=100_000),
        _bidder("丁", 99_000),
    ]
    signals = uniform_discount_signals(mixed)
    assert _codes(signals) == ["UNIFORM_DISCOUNT_RATE"]
    assert {e["bidder"] for e in signals[0]["evidence"]} == {"甲", "乙"}


def test_line_item_set_match_flags_s04_only_above_common_floor():
    names = [f"清单项{i}" for i in range(9)]
    a = [_item(n, 100 + i) for i, n in enumerate(names)]
    b = [_item(n, 200 + i) for i, n in enumerate(names)]
    signals = line_item_set_signals([_bidder("甲", items=a), _bidder("乙", items=b)])
    assert _codes(signals) == ["LINE_ITEM_SET_MATCH"]
    assert signals[0]["level"] == "中"

    few = [_item(n, 100) for n in names[:3]]
    assert line_item_set_signals([_bidder("甲", items=few), _bidder("乙", items=few)]) == []


def test_person_overlap_flags_p02_with_raw_values():
    metadata = {"project_manager": [{"key": "项目经理", "value": "张三"}],
                "author": [{"key": "author", "value": "李四"}]}
    bidders = [_bidder("甲", 100, metadata=metadata), _bidder("乙", 200, metadata=metadata)]
    signals = person_overlap_signals(bidders)
    assert _codes(signals) == ["PERSON_OVERLAP"]
    assert signals[0]["level"] == "高"
    assert signals[0]["evidence"][0]["values"] == ["张三"]

    distinct = [
        _bidder("甲", 100, metadata={"project_manager": [{"key": "项目经理", "value": "张三"}]}),
        _bidder("乙", 200, metadata={"project_manager": [{"key": "项目经理", "value": "王五"}]}),
    ]
    assert person_overlap_signals(distinct) == []


def test_kinship_relation_flags_p03_only_for_known_bidders():
    result = {"relation_clues": [
        {"row": 2, "bidder_a": "甲公司", "bidder_b": "乙公司",
         "relation": "两家法定代表人系亲兄弟", "source": "本地登记资料"},
        {"row": 3, "bidder_a": "丙公司", "bidder_b": "丁公司",
         "relation": "同写字楼办公", "source": "观察"},
    ]}
    signals = kinship_signals(result, {"甲公司", "乙公司"})
    assert _codes(signals) == ["KINSHIP_RELATION"]
    assert signals[0]["level"] == "高"

    unknown = kinship_signals(result, {"戊公司"})
    assert unknown == []


def test_apply_aggregates_all_rules_and_keeps_manual_boundary():
    metadata = {"contact_phone": [{"key": "联系电话", "value": "13800000000"}]}
    result = {"relation_clues": [{"row": 2, "bidder_a": "甲", "bidder_b": "乙",
                                  "relation": "配偶关系", "source": "本地线索"}]}
    bidders = [
        _bidder("甲", 9_000_000, control=10_000_000,
                items=[_item(f"项{i}", 100 + i) for i in range(8)], metadata=metadata),
        _bidder("乙", 9_000_500, control=10_000_000,
                items=[_item(f"项{i}", 100 + i) for i in range(8)], metadata=metadata),
        _bidder("丙", 9_000_900, control=10_000_000,
                items=[_item(f"项{i}", 100 + i) for i in range(8)]),
    ]
    signals: list[dict] = []
    apply(result, bidders, signals)
    codes = set(_codes(signals))
    # 等差/等比(F-05)与下浮率(F-06)对数值形态要求互斥，本组数据只覆盖后四类；
    # F-05 已在其单元测试覆盖。
    assert {"UNIFORM_DISCOUNT_RATE", "LINE_ITEM_SET_MATCH",
            "PERSON_OVERLAP", "KINSHIP_RELATION"} <= codes
    assert all(s["rule_id"] for s in signals)
    assert all(s["auto_conclusion"] is False for s in signals)
    assert PATTERN_THRESHOLDS["discount_rate_band"] == 0.001
