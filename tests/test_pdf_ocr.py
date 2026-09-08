"""PDF 页级覆盖、OCR 降级及金额来源回归；不依赖机器是否装 OCR。"""
import hashlib
import subprocess
import os
import pytest

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

import app.offline_review as review


def make_pdf(path, pages):
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    document = canvas.Canvas(str(path))
    for lines in pages:
        document.setFont("STSong-Light", 12)
        for index, line in enumerate(lines):
            document.drawString(50, 780 - index * 24, line)
        document.showPage()
    document.save()


def test_mixed_pdf_ocr_preserves_page_sources_and_private_text(tmp_path, monkeypatch):
    path = tmp_path / "甲__报价.pdf"
    make_pdf(path, [["项目说明"], []])
    before = path.read_bytes()
    calls = []

    def ocr(path, number, timeout):
        calls.append(number)
        return "投标报价: 1234.56元\n仅存在于OCR的私密全文"

    monkeypatch.setattr(review, "_ocr_pdf_page", lambda path, number, timeout, *tools: ocr(path, number, timeout))
    result = review.review_directory(tmp_path)
    bidder = result["bidders"][0]
    assert calls == [2]
    assert bidder["primary_quote"]["value"] == 1234.56
    assert bidder["primary_quote"]["locator"].startswith("第2页")
    assert bidder["primary_quote"]["extraction_method"] == "ocr"
    assert bidder["files"][0]["sha256"] == hashlib.sha256(before).hexdigest()
    assert bidder["files"][0]["size_bytes"] == len(before)
    assert path.read_bytes() == before
    assert "仅存在于OCR的私密全文" not in review.to_json(result)


def test_mixed_page_conflicting_ocr_quote_keeps_text_layer_quote(tmp_path, monkeypatch):
    path = tmp_path / "甲__报价.pdf"
    make_pdf(path, [["投标报价: 1000元"]])
    monkeypatch.setattr(review, "_has_large_pdf_image", lambda *args: True)
    monkeypatch.setattr(review, "_ocr_pdf_page", lambda *args: "投标报价: 2000元")

    result = review.review_directory(tmp_path)
    bidder = result["bidders"][0]

    assert bidder["primary_quote"]["value"] == 1000
    assert bidder["primary_quote"]["extraction_method"] == "text"
    assert {quote["extraction_method"] for quote in bidder["quotes"]} == {"text", "ocr"}
    assert bidder["files"][0]["parse_status"] == "PARTIAL"
    assert any("文本层与 OCR 报价不一致" in item["error"] for item in result["parse_warnings"])


def test_failed_ocr_is_partial_and_does_not_claim_full_text_match(tmp_path, monkeypatch):
    for company in ("甲", "乙"):
        make_pdf(tmp_path / f"{company}__报价.pdf", [["相同的说明文字。" * 20, "投标报价: 5000元"], []])

    def unavailable(*args):
        raise ValueError("OCR 组件缺失")

    monkeypatch.setattr(review, "_ocr_pdf_page", unavailable)
    result = review.review_directory(tmp_path)
    assert result["summary"]["partial_file_count"] == 2
    assert all(b["primary_quote"]["value"] == 5000 for b in result["bidders"])
    assert not any(s["code"] in {"TEXT_EXACT_MATCH", "TEXT_HIGH_SIMILARITY", "SHARED_TEXT_BLOCKS"} for s in result["signals"])
    assert "OCR 组件缺失" in review.to_markdown(result)


def test_page_501_is_read_and_limits_are_explicit(tmp_path, monkeypatch):
    path = tmp_path / "甲__报价.pdf"
    make_pdf(path, [["说明"]] * 500 + [["投标报价: 9000元"]])
    result = review.review_directory(tmp_path)
    assert result["bidders"][0]["primary_quote"]["locator"].startswith("第501页")
    monkeypatch.setattr(review, "MAX_PDF_PAGES", 500)
    result = review.review_directory(tmp_path)
    assert result["bidders"][0]["primary_quote"] is None
    assert result["bidders"][0]["files"][0]["parse_status"] == "PARTIAL"
    assert "1 页未处理" in review.to_markdown(result)


def test_pdf_split_quote_and_ambiguous_decimal(tmp_path):
    make_pdf(tmp_path / "甲__报价.pdf", [["投标总价:", "1234.56元"]])
    make_pdf(tmp_path / "乙__报价.pdf", [["投标报价: 123.456元"]])
    make_pdf(tmp_path / "丙__报价.pdf", [["投标总价:", "13", "100000"]])
    make_pdf(tmp_path / "丁__报价.pdf", [["投标报价: 123.456, 789"]])
    result = review.review_directory(tmp_path)
    bidders = {b["name"]: b for b in result["bidders"]}
    assert bidders["甲"]["primary_quote"]["value"] == 1234.56
    assert bidders["乙"]["primary_quote"] is None
    assert bidders["丙"]["primary_quote"] is None
    assert bidders["丁"]["primary_quote"] is None
    assert "歧义" in review.to_markdown(result)


def test_ocr_budget_and_timeout_keep_coverage(tmp_path, monkeypatch):
    make_pdf(tmp_path / "甲__报价.pdf", [[], []])
    monkeypatch.setattr(review, "MAX_PDF_OCR_PAGES", 1)

    def timeout(*args):
        raise subprocess.TimeoutExpired("tesseract", 1)

    monkeypatch.setattr(review, "_ocr_pdf_page", timeout)
    result = review.review_directory(tmp_path)
    assert result["bidders"][0]["files"][0]["parse_status"] == "PARTIAL"
    report = review.to_markdown(result)
    assert "TimeoutExpired" in report
    assert "预算已用完" in report


def test_missing_chinese_language_is_not_silent_english_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(review.shutil, "which", lambda name: name)
    monkeypatch.setattr(review.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 0, b"List of available languages:\neng\n", b""))
    with pytest.raises(ValueError, match="语言包"):
        review._ocr_pdf_page(tmp_path / "not-read.pdf", 1, 30)


@pytest.mark.skipif(os.environ.get("BQC_RUN_OCR_TEST") != "1", reason="设置 BQC_RUN_OCR_TEST=1 运行本机 OCR 引擎实测")
def test_real_chinese_ocr_image_only_and_same_page_mixed(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source, [["投标报价: 123456.78元", "扫描件中文识别测试"]])
    subprocess.run(["pdftoppm", "-png", "-singlefile", "-r", "150", str(source), str(tmp_path / "page")],
                   check=True, timeout=30, capture_output=True,
                   **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for name, mixed in (("甲", False), ("乙", True)):
        document = canvas.Canvas(str(inputs / f"{name}__报价.pdf"))
        document.drawImage(str(tmp_path / "page.png"), 0, 0, width=595, height=842)
        if mixed:
            document.setFont("Helvetica", 10)
            document.drawString(50, 40, "Text header on image page")
        document.save()
    result = review.review_directory(inputs)
    assert not result["parse_errors"]
    for bidder in result["bidders"]:
        assert bidder["primary_quote"] is not None, result["parse_warnings"]
        assert bidder["primary_quote"]["value"] == 123456.78
        assert bidder["primary_quote"]["extraction_method"] == "ocr"
        assert bidder["files"][0]["structure"]["ocr_pages"] == 1
