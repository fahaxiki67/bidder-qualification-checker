"""增量规则模块 offline_review_patterns 的单元测试（不依赖文件解析与接线）。"""
import json

from app.offline_review_patterns import (
    PATTERN_THRESHOLDS,
    apply,
    kinship_signals,
    line_item_set_signals,
    near_quote_band_signals,
    payment_account_signals,
    person_overlap_signals,
    person_table_overlap_signals,
    quote_pattern_signals,
    shared_block_signals,
    uniform_discount_signals,
)


def _item(name: str, amount: float) -> dict:
    return {"name": name, "key": name, "comparison_key": f"{name}|m³|一般土方",
            "comparability_status": "COMPARABLE", "amount": amount}


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

    conflict = [_bidder("甲", 90_000, control=100_000),
                _bidder("乙", 90_000, control=100_000)]
    conflict[0]["quotes"].append({"label": "最高限价", "value": 101_000,
                                   "source": "", "locator": "", "raw": "", "kind": "control"})
    assert uniform_discount_signals(conflict) == []


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


def _bidder_with_text(name, *texts):
    bidder = _bidder(name)
    bidder["_internal_files"] = [{"public": {"path": f"{name}_{i}.txt"}, "text": text}
                                 for i, text in enumerate(texts)]
    return bidder


def test_shared_block_text_flags_s05_for_partial_plagiarism():
    # 三段互异的 200 字共享块（对齐块边界），避免重复内容被块集合去重。
    shared = ("共享段落一" + "一" * 195) + ("共享段落二" + "二" * 195) + ("共享段落三" + "三" * 195)
    left = _bidder_with_text("甲", "甲" * 200 + shared + "丙" * 200)
    right = _bidder_with_text("乙", "乙" * 200 + shared + "丁" * 200)
    signals = shared_block_signals([left, right])
    assert _codes(signals) == ["SHARED_TEXT_BLOCKS"]
    assert signals[0]["rule_id"] == "S-05"
    assert signals[0]["level"] == "中"
    evidence_payload = json.dumps(signals[0]["evidence"], ensure_ascii=False)
    # 隐私边界：块内容与原文不得写入证据。
    assert "共享段落" not in evidence_payload and "text" not in evidence_payload

    unrelated = [
        _bidder_with_text("甲", "戊" * 800),
        _bidder_with_text("乙", "己" * 800),
    ]
    assert shared_block_signals(unrelated) == []
    assert shared_block_signals([_bidder_with_text("甲", "短文本")]) == []


def test_payment_account_match_flags_e02_with_masked_evidence():
    account = {"bank_account": [{"key": "保证金账户", "value": "6222021234567890123"}]}
    signals = payment_account_signals([
        _bidder("甲", 100, metadata=account),
        _bidder("乙", 200, metadata=account),
    ])
    assert _codes(signals) == ["PAYMENT_ACCOUNT_MATCH"]
    assert signals[0]["rule_id"] == "E-02"
    assert signals[0]["level"] == "高"
    assert "第40条第6项" in signals[0]["legal_basis"]
    evidence_payload = json.dumps(signals[0]["evidence"], ensure_ascii=False)
    assert "6222021234567890123" not in evidence_payload
    assert "6222" in evidence_payload and "0123" in evidence_payload and "*" * 8 in evidence_payload

    distinct = [
        _bidder("甲", 100, metadata=account),
        _bidder("乙", 200, metadata={"bank_account": [{"key": "保证金账户",
                                                       "value": "6217009988776655443"}]}),
    ]
    assert payment_account_signals(distinct) == []


def test_person_table_overlap_flags_p04_for_shared_person():
    def _row(number, raw):
        return {"row": number, "bidder_a": "", "bidder_b": "",
                "relation": "用户提供的关联关系线索", "source": "未注明", "raw": raw}

    result = {"relation_clues": [
        _row(2, {"姓名": "张三", "企业名称": "甲公司", "职务": "监事"}),
        _row(3, {"姓名": "张三", "企业名称": "乙公司", "职务": "董事"}),
        _row(4, {"姓名": "李四", "企业名称": "甲公司", "职务": "经理"}),
        {"row": 5, "bidder_a": "甲公司", "bidder_b": "乙公司",
         "relation": "法定代表人相同", "source": "本地登记资料",
         "raw": {"bidder_a": "甲公司", "bidder_b": "乙公司"}},
    ]}
    signals = person_table_overlap_signals(result, {"甲公司", "乙公司"})
    assert _codes(signals) == ["PERSON_TABLE_OVERLAP"]
    assert signals[0]["rule_id"] == "P-04"
    assert signals[0]["level"] == "高"
    assert signals[0]["evidence"][0]["person"] == "张三"
    assert {c["company"] for c in signals[0]["evidence"][0]["companies"]} == {"甲公司", "乙公司"}
    assert "监事" in json.dumps(signals[0]["evidence"], ensure_ascii=False)

    # 配对表行归 P-01/P-03，不触发 P-04；单家命中或单字符人名不触发。
    paired_only = {"relation_clues": [result["relation_clues"][3]]}
    assert person_table_overlap_signals(paired_only, {"甲公司", "乙公司"}) == []
    single_hit = {"relation_clues": [result["relation_clues"][2]]}
    assert person_table_overlap_signals(single_hit, {"甲公司", "乙公司"}) == []


def test_review_directory_accepts_qichacha_style_person_table(tmp_path):
    from app.offline_review import review_directory

    for name in ("甲公司", "乙公司"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "报价.csv").write_text(
            f"投标报价,{100000 if name == '甲公司' else 100300}\n", encoding="utf-8")
    rel = tmp_path / "企查查导出.csv"
    rel.write_text(
        "姓名,企业名称,职务\n张三,甲公司,监事\n张三,乙公司,董事\n",
        encoding="utf-8")

    result = review_directory(tmp_path, relations=rel)
    codes = {s["code"] for s in result["signals"]}
    assert "PERSON_TABLE_OVERLAP" in codes
    assert all(s["auto_conclusion"] is False for s in result["signals"])


def test_person_table_overlap_skips_conflicts_and_all_pair_aliases():
    def row(raw):
        return {"raw": raw}

    conflicting = {"relation_clues": [
        row({"姓名": "张三", "高管姓名": "李四", "企业名称": "甲公司"}),
        row({"姓名": "张三", "企业名称": "乙公司"}),
    ]}
    assert person_table_overlap_signals(conflicting, {"甲公司", "乙公司"}) == []

    for left, right in (("party_a", "party_b"), ("甲方", "乙方"),
                        ("company_a", "company_b"), ("name_a", "name_b")):
        paired = {"relation_clues": [
            row({left: "甲公司", right: "乙公司", "姓名": "张三", "企业名称": "甲公司"}),
            row({left: "甲公司", right: "乙公司", "姓名": "张三", "企业名称": "乙公司"}),
        ]}
        assert person_table_overlap_signals(paired, {"甲公司", "乙公司"}) == []


def test_near_quote_band_flags_f07_in_secondary_range():
    import app.offline_review as offline

    lower = offline.THRESHOLDS["near_quote_relative_diff"]
    upper = PATTERN_THRESHOLDS["near_quote_secondary_relative_diff"]
    middle = (lower + upper) / 2

    inside = [_bidder("甲", 185_986_265.34), _bidder("乙", 185_986_265.34 * (1 - middle))]
    signals = near_quote_band_signals(inside)
    assert _codes(signals) == ["QUOTE_NEAR_BAND"]
    assert signals[0]["rule_id"] == "F-07"
    assert signals[0]["level"] == "中"

    tight = [_bidder("甲", 100_000), _bidder("乙", 100_300)]  # 0.3%，F-01 领域
    assert near_quote_band_signals(tight) == []
    wide = [_bidder("甲", 100_000), _bidder("乙", 103_000)]  # 3%，超出接近带
    assert near_quote_band_signals(wide) == []


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
