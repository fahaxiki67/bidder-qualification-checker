"""数据路径解析测试（P8）：frozen → 用户数据目录；源码 → 当前工作目录。"""
import sys

from app.paths import default_data_dir, default_db_path, is_frozen


def test_source_mode_uses_cwd():
    assert is_frozen() is False
    assert default_data_dir() == __import__("pathlib").Path("data")
    assert str(default_db_path()).endswith("bqc.sqlite3")


def test_frozen_windows_uses_localappdata(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\demo\AppData\Local")
    d = default_data_dir()
    assert str(d).replace("/", "\\").endswith(r"C:\Users\demo\AppData\Local\bqc\data")
    assert "bqc.sqlite3" in str(default_db_path())


def test_frozen_without_localappdata_falls_back(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert "bqc" in str(default_data_dir())


def test_frozen_darwin_uses_application_support(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    d = default_data_dir()
    assert "Application Support" in str(d) and d.name == "data"
