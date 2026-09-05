from pathlib import Path

import pytest

import app
from app.core.models import SourceRef
from app.core.registry import SourceRegistry

# 配置随包分发（app/config/），源码与安装环境读同一处
PKG_ROOT = Path(app.__file__).resolve().parent


@pytest.fixture(scope="module")
def registry():
    return SourceRegistry.from_yaml(PKG_ROOT / "config" / "sources_registry.yaml")


def test_yaml_loads_and_fields_complete(registry):
    entries = registry.all()
    assert len(entries) >= 8
    for e in entries:
        assert e.id and e.name and e.level in ("national", "province", "city", "owner")
        assert e.evidence_grade in ("A", "B", "C", "D")


def test_get_national_source(registry):
    e = registry.get("gsxt")
    assert e.level == "national"
    assert e.official_home == "https://www.gsxt.gov.cn/"
    assert e.automation_mode == "auto_fill_manual_verify"


def test_owner_source_has_group(registry):
    e = registry.get("powerchina_ban")
    assert e.level == "owner" and e.owner_group == "powerchina"


def test_filter_by_province(registry):
    ids = {e.id for e in registry.filter(level="province", province="四川")}
    assert "sc_construction" in ids and "gd_construction" not in ids


def test_disabled_entries_excluded_from_enabled(registry):
    enabled_ids = {e.id for e in registry.enabled()}
    assert "gsxt" in enabled_ids


def test_unknown_key_in_yaml_is_rejected(tmp_path):
    """0.18.1 复核修复：未知字段必须拒绝而非静默丢弃（拼错的配置不得悄悄失效）。"""
    p = tmp_path / "r.yaml"
    p.write_text(
        "sources:\n  - id: x\n    name: 某源\n    level: national\n    typo_field: 1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="未知字段"):
        SourceRegistry.from_yaml(p)


def test_duplicate_source_id_is_rejected(tmp_path):
    """重复 id 在旧实现里静默后者顶替前者，必须启动即报错。"""
    p = tmp_path / "r.yaml"
    p.write_text(
        "sources:\n"
        "  - id: x\n    name: 第一份\n    level: national\n"
        "  - id: x\n    name: 第二份\n    level: national\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="重复数据源 id"):
        SourceRegistry.from_yaml(p)


def test_invalid_automation_mode_is_rejected(tmp_path):
    """非法 automation_mode（如拼错 auto→automagic）不得静默按缺省处理。"""
    p = tmp_path / "r.yaml"
    p.write_text(
        "sources:\n  - id: x\n    name: 某源\n    level: national\n"
        "    automation_mode: automagic\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="automation_mode 非法"):
        SourceRegistry.from_yaml(p)


def test_owner_source_requires_owner_group(tmp_path):
    """level=owner 而缺 owner_group：路由无法归组，必须配置期报错。"""
    p = tmp_path / "r.yaml"
    p.write_text(
        "sources:\n  - id: x\n    name: 集团名单\n    level: owner\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="owner_group"):
        SourceRegistry.from_yaml(p)


def test_valid_manual_intake_owner_source_is_accepted(tmp_path):
    """合法组合（owner+owner_group+manual_intake）不受新校验误伤（P6 语义）。"""
    p = tmp_path / "r.yaml"
    p.write_text(
        "sources:\n  - id: x\n    name: 集团名单\n    level: owner\n"
        "    owner_group: powerchina\n    automation_mode: manual_intake\n",
        encoding="utf-8",
    )
    e = SourceRegistry.from_yaml(p).get("x")
    assert e.level == "owner" and e.owner_group == "powerchina"
