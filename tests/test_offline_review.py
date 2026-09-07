import json
import hashlib
import importlib
import os
import zipfile
from pathlib import Path

import openpyxl
import pytest

from app.main import main
import app.offline_review as offline_review
from app.offline_review import review_directory, to_json, to_markdown, write_outputs


def _write_bid(path: Path, total: int, *, identical_text: bool = True, unit: str = "m³",
               specification: str = "一般土方") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "报价.csv").write_text(
        "项目名称,规格,单位,数量,单价,合价\n"
        f"土方,{specification},{unit},1,30000,30000\n"
        f"混凝土,{specification},{unit},2,20000,40000\n"
        f"钢筋,{specification},{unit},1,30000,30000\n"
        f"投标报价,{total}\n",
        encoding="utf-8",
    )
    text = "施工组织设计统一说明。\n" * 20 if identical_text else "不同施工方案说明。\n" * 20
    (path / "说明.txt").write_text(text, encoding="utf-8")


def test_review_directory_excludes_relation_file_and_emits_risk_signals(tmp_path):
    _write_bid(tmp_path / "甲公司", 100000)
    _write_bid(tmp_path / "乙公司", 100300)
    _write_bid(tmp_path / "丙公司", 120000, identical_text=False)
    relation = tmp_path / "relations.csv"
    relation.write_text(
        "bidder_a,bidder_b,relation,source\n甲公司,乙公司,法定代表人相同,本地依法取得的登记资料\n",
        encoding="utf-8",
    )

    result = review_directory(tmp_path, project="测试项目", relations=relation)

    assert {x["name"] for x in result["bidders"]} == {"甲公司", "乙公司", "丙公司"}
    assert result["summary"]["file_count"] == 6
    assert result["relation_source"]["sha256"]
    codes = {signal["code"] for signal in result["signals"]}
    assert {"QUOTE_NEAR_MATCH", "QUOTE_OUTLIER", "SYNCHRONIZED_LINE_ITEMS", "LOCAL_RELATION_CLUE"} <= codes
    assert all(signal["auto_conclusion"] is False for signal in result["signals"])
    assert result["summary"]["manual_review_required"] is True


def test_relation_json_respects_depth_budget(tmp_path, monkeypatch):
    relation = tmp_path / "relations.json"
    relation.write_text(
        json.dumps({"relations": [{"bidder_a": "甲", "bidder_b": "乙", "relation": "相同"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(offline_review, "MAX_JSON_DEPTH", 2)

    result = review_directory(tmp_path, relations=relation)

    assert result["summary"]["parse_error_count"] == 1
    assert "JSON 解析受限" in result["parse_errors"][0]["error"]


def test_review_directory_integrates_new_pattern_signals_and_control_quote(tmp_path):
    item_rows = [
        "项目名称,规格,单位,数量,单价,合价",
        *(f"清单项{i},一般土方,m³,1,100,100" for i in range(1, 9)),
    ]
    for name, total in (("甲公司", 900000), ("乙公司", 900100), ("丙公司", 900200)):
        bidder = tmp_path / name
        bidder.mkdir()
        (bidder / "报价.csv").write_text(
            "\n".join(item_rows + [
                f"投标报价,{total}",
                "招标控制价,1000000",
                "项目经理,张三",
                "联系电话,13800000000",
            ]) + "\n",
            encoding="utf-8",
        )
    relations = tmp_path / "relations.csv"
    relations.write_text(
        "bidder_a,bidder_b,relation,source\n"
        "甲公司,乙公司,两家法定代表人系亲兄弟,本地登记资料\n",
        encoding="utf-8",
    )

    result = review_directory(tmp_path, relations=relations)
    codes = {signal["code"] for signal in result["signals"]}
    expected = {
        "QUOTE_ARITHMETIC_PATTERN", "UNIFORM_DISCOUNT_RATE", "LINE_ITEM_SET_MATCH",
        "PERSON_OVERLAP", "KINSHIP_RELATION",
    }

    assert expected <= codes
    assert all(
        signal["auto_conclusion"] is False
        for signal in result["signals"]
        if signal["code"] in expected
    )
    assert result["summary"]["manual_review_required"] is True

    bidders = {bidder["name"]: bidder for bidder in result["bidders"]}
    for bidder in bidders.values():
        assert bidder["primary_quote"]["kind"] == "explicit_total"
        assert bidder["primary_quote"]["label"] == "投标报价"
        control_quotes = [quote for quote in bidder["quotes"] if quote["kind"] == "control"]
        assert len(control_quotes) == 1
        assert control_quotes[0]["label"] == "招标控制价"
        assert bidder["primary_quote"]["kind"] != control_quotes[0]["kind"]


def test_csv_quote_uses_first_amount_before_tax_rate(tmp_path):
    bidder = tmp_path / "甲"
    bidder.mkdir()
    (bidder / "报价.csv").write_text("投标报价,1000,税率,13\n", encoding="utf-8")
    ambiguous = tmp_path / "乙"
    ambiguous.mkdir()
    (ambiguous / "报价.csv").write_text("bid_price,tax_rate,13,100000\n", encoding="utf-8")

    result = review_directory(tmp_path)

    bidders = {bidder["name"]: bidder for bidder in result["bidders"]}
    assert bidders["甲"]["primary_quote"]["value"] == 1000
    assert bidders["乙"]["primary_quote"] is None


def test_text_quote_skips_multiple_amounts_in_one_line(tmp_path):
    bidder = tmp_path / "甲"
    bidder.mkdir()
    (bidder / "报价.txt").write_text("投标报价：税率13%，金额100000\n", encoding="utf-8")

    result = review_directory(tmp_path)

    assert result["bidders"][0]["primary_quote"] is None
    assert not result["bidders"][0]["quotes"]


def test_review_parses_json_and_xlsx_with_traceable_hashes(tmp_path):
    first = tmp_path / "甲"
    first.mkdir()
    (first / "报价.json").write_text(
        json.dumps({"投标总价": "1.2万元", "items": [{"项目名称": "土方", "合价": 1200}]}),
        encoding="utf-8",
    )
    second = tmp_path / "乙"
    second.mkdir()
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "报价表"
    sheet.append(["项目名称", "数量", "单价", "合价"])
    sheet.append(["土方", 1, 1200, 1200])
    sheet.append(["混凝土", 1, 800, 800])
    sheet.append(["钢筋", 1, 1000, 1000])
    sheet.append(["投标报价", 3000, None, None])
    sheet.row_dimensions[2].hidden = True
    sheet["F1"] = "=SUM(B2:B4)"
    workbook.properties.creator = "测试作者"
    workbook.save(second / "报价.xlsx")

    result = review_directory(tmp_path)
    bidders = {x["name"]: x for x in result["bidders"]}
    assert bidders["甲"]["primary_quote"]["value"] == 12000
    assert bidders["乙"]["primary_quote"]["value"] == 3000
    assert bidders["乙"]["files"][0]["sha256"]
    assert "author" in bidders["乙"]["metadata"]
    assert bidders["乙"]["files"][0]["structure"]["sheet_count"] == 1
    sheet_meta = bidders["乙"]["files"][0]["structure"]["sheets"][0]
    assert sheet_meta["hidden_row_count"] == 1
    assert sheet_meta["formula_count"] == 1
    assert bidders["乙"]["line_items"][0]["comparability_status"] == "INSUFFICIENT_DATA"
    json.loads(to_json(result))


def test_xlsx_formula_without_cached_value_is_explicit_warning(tmp_path):
    bidder = tmp_path / "甲"
    bidder.mkdir()
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["投标报价", "=100000"])
    workbook.save(bidder / "报价.xlsx")

    result = review_directory(tmp_path)
    bidder_result = result["bidders"][0]
    sheet_meta = bidder_result["files"][0]["structure"]["sheets"][0]

    assert bidder_result["primary_quote"] is None
    assert sheet_meta["formula_count"] == 1
    assert any("不计算公式" in warning["error"] for warning in result["parse_warnings"])
    assert "解析提示" in to_markdown(result)


def test_line_items_do_not_match_by_name_when_units_differ(tmp_path):
    _write_bid(tmp_path / "甲", 100000, unit="m³")
    _write_bid(tmp_path / "乙", 100300, unit="吨")

    result = review_directory(tmp_path)

    assert not any(signal["code"] == "SYNCHRONIZED_LINE_ITEMS" for signal in result["signals"])
    assert result["summary"]["comparable_line_item_count"] == 6
    assert all(
        item["comparison_key"]
        for bidder in result["bidders"]
        for item in bidder["line_items"]
    )


def test_line_items_do_not_match_by_name_when_specifications_differ(tmp_path):
    _write_bid(tmp_path / "甲", 100000, specification="C30")
    _write_bid(tmp_path / "乙", 100300, specification="C40")

    result = review_directory(tmp_path)

    assert not any(signal["code"] == "SYNCHRONIZED_LINE_ITEMS" for signal in result["signals"])


def test_line_items_with_missing_unit_or_specification_are_marked_not_comparable(tmp_path):
    for name in ("甲", "乙"):
        bidder = tmp_path / name
        bidder.mkdir()
        (bidder / "报价.csv").write_text(
            "项目名称,数量,单价,合价\n"
            "土方,1,30000,30000\n"
            "混凝土,2,20000,40000\n"
            "钢筋,1,30000,30000\n",
            encoding="utf-8",
        )

    result = review_directory(tmp_path)
    items = [item for bidder in result["bidders"] for item in bidder["line_items"]]

    assert len(items) == 6
    assert all(item["comparability_status"] == "INSUFFICIENT_DATA" for item in items)
    assert all(item["comparison_key"] is None for item in items)
    assert result["summary"]["insufficient_line_item_count"] == 6
    assert result["summary"]["line_item_comparability"]["auto_merge"] is False
    assert not any(signal["code"] == "SYNCHRONIZED_LINE_ITEMS" for signal in result["signals"])


def test_json_composite_total_is_not_parsed_as_scalar_quote(tmp_path):
    bidder = tmp_path / "甲"
    bidder.mkdir()
    (bidder / "报价.json").write_text(
        json.dumps({
            "bid_price": {"amount": 12345, "currency": "CNY"},
            "total": {"value": "12345元", "currency": "CNY"},
            "items": [{"项目名称": "土方", "单位": "m³", "规格": "一般土方", "合价": 100}],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    result = review_directory(tmp_path)
    bidder_result = result["bidders"][0]

    assert bidder_result["primary_quote"] is None
    assert bidder_result["quotes"] == []
    assert bidder_result["line_items"][0]["comparability_status"] == "COMPARABLE"


def test_quote_parser_keeps_invalid_currency_and_negative_values_traceable(tmp_path):
    bidder = tmp_path / "甲"
    bidder.mkdir()
    (bidder / "报价.csv").write_text(
        "项目名称,规格,单位,合价\n"
        "土方,一般土方,m³,100\n"
        "投标报价,-5000\n"
        "报价金额,100 USD\n",
        encoding="utf-8",
    )

    result = review_directory(tmp_path)

    assert result["bidders"][0]["primary_quote"] is None
    assert result["bidders"][0]["quotes"] == []
    warnings = result["parse_warnings"]
    assert any("负值" in warning["error"] for warning in warnings)
    assert any("非人民币" in warning["error"] for warning in warnings)
    assert result["summary"]["parse_warning_count"] == 2


def test_normalized_text_hash_covers_content_after_compare_prefix(tmp_path):
    prefix = "a" * (offline_review.MAX_TEXT_FOR_COMPARE + 100)
    for name, suffix in (("甲", "left-tail"), ("乙", "right-tail")):
        bidder = tmp_path / name
        bidder.mkdir()
        (bidder / "说明.txt").write_text(prefix + suffix, encoding="utf-8")

    result = review_directory(tmp_path)
    files = [bidder["files"][0] for bidder in result["bidders"]]

    assert files[0]["normalized_sha256"] != files[1]["normalized_sha256"]
    assert not any(signal["code"] == "TEXT_EXACT_MATCH" for signal in result["signals"])


def test_short_identical_files_do_not_create_exact_match_signal(tmp_path):
    for name in ("甲", "乙"):
        bidder = tmp_path / name
        bidder.mkdir()
        (bidder / "空.txt").write_text("", encoding="utf-8")

    result = review_directory(tmp_path)

    assert not any(signal["code"] == "TEXT_EXACT_MATCH" for signal in result["signals"])


def test_json_item_prefers_total_over_unit_price(tmp_path):
    bidder = tmp_path / "甲"
    bidder.mkdir()
    (bidder / "报价.json").write_text(
        json.dumps({"items": [{"项目名称": "土方", "单位": "m³", "规格": "一般土方",
                                "单价": 12, "合价": 120}]}),
        encoding="utf-8",
    )

    result = review_directory(tmp_path)

    assert result["bidders"][0]["line_items"][0]["amount"] == 120


def test_scan_skips_and_records_symlink(tmp_path):
    target = tmp_path / "outside.txt"
    target.write_text("投标报价,100", encoding="utf-8")
    bidder = tmp_path / "甲"
    bidder.mkdir()
    link = bidder / "链接.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"当前环境不允许创建符号链接：{exc}")

    result = review_directory(tmp_path)

    assert not any(file["path"].endswith("链接.txt") for bidder in result["bidders"] for file in bidder["files"])
    assert any(item["path"].endswith("链接.txt") and item["reason"] == "SYMLINK_SKIPPED"
               for item in result["skipped_files"])
    assert result["summary"]["skipped_file_count"] == 1
    assert result["scan"]["symlink_count"] == 1


def test_scan_stops_at_file_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(offline_review, "MAX_INPUT_FILES", 1)
    (tmp_path / "a.txt").write_text("投标报价,100", encoding="utf-8")
    (tmp_path / "b.txt").write_text("投标报价,200", encoding="utf-8")

    result = review_directory(tmp_path)

    assert result["scan"]["truncated"] is True
    assert any(item["kind"] == "file_count" for item in result["scan"]["budget_errors"])
    assert result["summary"]["scan_error_count"] == 1
    assert result["summary"]["file_count"] == 1


def test_scan_stops_at_byte_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(offline_review, "MAX_INPUT_BYTES", 10)
    (tmp_path / "a.txt").write_bytes(b"123456")
    (tmp_path / "b.txt").write_bytes(b"123456")

    result = review_directory(tmp_path)

    assert result["scan"]["truncated"] is True
    assert any(item["kind"] == "bytes" for item in result["scan"]["budget_errors"])
    assert result["summary"]["file_count"] == 1


def test_xlsx_zip_guard_runs_before_openpyxl(tmp_path, monkeypatch):
    bidder = tmp_path / "甲"
    bidder.mkdir()
    archive_path = bidder / "恶意.xlsx"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("xl/large.bin", b"123456")
    monkeypatch.setattr(offline_review, "MAX_XLSX_ENTRY_UNCOMPRESSED_BYTES", 5)

    result = review_directory(tmp_path)

    assert result["summary"]["parse_error_count"] == 1
    assert "XLSX 压缩包成员" in result["parse_errors"][0]["error"]


def test_xlsx_read_pass_respects_audit_cell_budget(tmp_path, monkeypatch):
    bidder = tmp_path / "甲"
    bidder.mkdir()
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["项目名称", "合价"])
    sheet.append(["土方", 100])
    workbook.save(bidder / "报价.xlsx")
    monkeypatch.setattr(offline_review, "MAX_XLSX_AUDIT_CELLS", 2)

    result = review_directory(tmp_path)
    sheet_meta = result["bidders"][0]["files"][0]["structure"]["sheets"][0]

    assert sheet_meta["read_truncated"] is True
    assert sheet_meta["audit_truncated"] is True
    assert sheet_meta["formula_count"] is None


def test_unsupported_and_broken_files_are_not_silently_clean(tmp_path):
    bidder = tmp_path / "甲"
    bidder.mkdir()
    (bidder / "附件.xls").write_bytes(b"legacy workbook")
    (bidder / "坏.json").write_text("{not-json", encoding="utf-8")

    result = review_directory(tmp_path)

    assert result["summary"]["unsupported_file_count"] == 1
    assert result["summary"]["parse_error_count"] == 1
    assert any(".xls" in x["path"] for x in result["unsupported_files"])
    assert any(x["path"].endswith("坏.json") for x in result["parse_errors"])


def test_broken_json_parse_error_keeps_file_fingerprint(tmp_path):
    bidder = tmp_path / "甲"
    bidder.mkdir()
    broken = bidder / "坏.json"
    broken.write_text("{not-json", encoding="utf-8")
    raw = broken.read_bytes()

    result = review_directory(tmp_path)
    file_meta = result["bidders"][0]["files"][0]
    parse_error = result["parse_errors"][0]

    expected_sha256 = hashlib.sha256(raw).hexdigest()
    assert file_meta["size_bytes"] == len(raw)
    assert file_meta["sha256"] == expected_sha256
    assert parse_error["size_bytes"] == len(raw)
    assert parse_error["sha256"] == expected_sha256


def test_markdown_and_json_keep_manual_only_boundary(tmp_path):
    _write_bid(tmp_path / "甲", 100000)
    result = review_directory(tmp_path)

    report = to_markdown(result)
    payload = json.loads(to_json(result))
    assert "不构成串通投标、违法" in report
    assert payload["legal_notice"]["conclusion"].startswith("仅输出风险预警")
    assert payload["summary"]["manual_review_required"] is True


def test_cli_review_bids_writes_json_and_markdown(tmp_path, capsys):
    _write_bid(tmp_path / "甲", 100000)
    output_dir = tmp_path.parent / f"{tmp_path.name}-out"
    json_path = output_dir / "review.json"
    report_path = output_dir / "review.md"

    rc = main([
        "review-bids", str(tmp_path), "--output-json", str(json_path),
        "--output-report", str(report_path),
    ])

    assert rc == 0
    assert json_path.is_file() and report_path.is_file()
    assert "风险信号" in capsys.readouterr().out


def test_write_outputs_rejects_input_paths_before_writing(tmp_path, capsys):
    _write_bid(tmp_path / "甲", 100000)
    result = review_directory(tmp_path)
    source_path = tmp_path / "甲" / "报价.csv"
    before = source_path.read_bytes()
    new_output_dir = tmp_path / "new-output"

    with pytest.raises(ValueError, match="输入目录"):
        write_outputs(result, json_path=tmp_path)

    with pytest.raises(ValueError, match="输入目录"):
        write_outputs(
            result,
            json_path=source_path,
            report_path=new_output_dir / "report.md",
        )

    assert source_path.read_bytes() == before
    assert not new_output_dir.exists()

    rc = main([
        "review-bids", str(tmp_path), "--output-json", str(source_path),
    ])
    cli_output = capsys.readouterr().out
    assert rc == 2
    assert "Traceback" not in cli_output
    assert "无法完成离线审查" in cli_output
    assert source_path.read_bytes() == before


def test_write_outputs_rejects_hardlink_alias(tmp_path):
    _write_bid(tmp_path / "甲", 100000)
    result = review_directory(tmp_path)
    source_path = tmp_path / "甲" / "报价.csv"
    alias = tmp_path.parent / f"{tmp_path.name}-alias.csv"
    try:
        os.link(source_path, alias)
    except OSError as exc:
        pytest.skip(f"当前环境不允许创建硬链接：{exc}")

    before = source_path.read_bytes()
    with pytest.raises(ValueError, match="输入源文件"):
        write_outputs(result, json_path=alias)
    assert source_path.read_bytes() == before


def test_web_offline_review_entry_reads_only_explicit_directory(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.web.server as server

    _write_bid(tmp_path / "甲", 100000)
    monkeypatch.setenv("BQC_REVIEW_ROOT", str(tmp_path))
    importlib.reload(server)
    client = TestClient(server.app)

    page = client.get("/review-bids")
    result = client.post("/review-bids", data={"input_dir": str(tmp_path), "project": "Web 测试"})

    assert page.status_code == 200
    assert "离线审查" in page.text
    assert result.status_code == 200
    assert "人工复核" in result.text
    assert "Web 测试" in result.text

    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    _write_bid(outside / "乙", 100000)
    rejected = client.post("/review-bids", data={"input_dir": str(outside)})
    assert rejected.status_code == 400
    assert "BQC_REVIEW_ROOT" in rejected.json()["detail"]
