from pathlib import Path

import pytest

from app.core.models import SourceRef
from app.core.registry import SourceRegistry

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def registry():
    return SourceRegistry.from_yaml(REPO / "config" / "sources_registry.yaml")


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


def test_unknown_key_in_yaml_is_ignored(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(
        "sources:\n  - id: x\n    name: 某源\n    level: national\n    typo_field: 1\n",
        encoding="utf-8",
    )
    reg = SourceRegistry.from_yaml(p)
    assert reg.get("x").name == "某源"
