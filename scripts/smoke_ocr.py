"""验证发布可执行文件在 PATH 不含外部 OCR 时仍能读取中文扫描报价。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas


def main():
    executable = Path(sys.argv[1]).resolve()
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    with tempfile.TemporaryDirectory(prefix="bqc-ocr-smoke-") as folder:
        root = Path(folder)
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        source = canvas.Canvas(str(root / "source.pdf"))
        source.setFont("STSong-Light", 20)
        source.drawString(50, 750, "投标报价: 123456.78元")
        source.save()
        subprocess.run(["pdftoppm", "-png", "-singlefile", "-r", "150",
                        str(root / "source.pdf"), str(root / "page")],
                       check=True, timeout=30, capture_output=True, **options)
        inputs = root / "inputs"
        inputs.mkdir()
        scan = canvas.Canvas(str(inputs / "甲__扫描件.pdf"))
        scan.drawImage(str(root / "page.png"), 0, 0, width=595, height=842)
        scan.save()
        output = root / "result.json"
        env = {**os.environ, "PATH": "", "TESSDATA_PREFIX": str(root / "missing-language-data")}
        subprocess.run([str(executable), "review-bids", str(inputs), "--output-json", str(output)],
                       env=env, cwd=root, check=True, timeout=120, capture_output=True, **options)
        result = json.loads(output.read_text(encoding="utf-8"))
        bidder = result["bidders"][0]
        assert bidder["primary_quote"] and bidder["primary_quote"]["value"] == 123456.78, result["parse_warnings"]
        assert bidder["primary_quote"]["extraction_method"] == "ocr"
        assert bidder["files"][0]["parse_status"] == "OK"
        print("Bundled OCR smoke OK: Chinese scan, PATH empty, quote=123456.78")


if __name__ == "__main__":
    main()
