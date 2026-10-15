from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.vnext.catalog import UnitCatalog

BUNDLED_MAPPING = (
    Path(__file__).resolve().parents[2] / "app" / "data" / "units" / "unit_mapping.json"
)
TOWER = "npc_dota_goodguys_tower2_bot"


def payload() -> dict:
    return {
        "schema_version": 1,
        "sources": [
            {
                "repository": "test/unit-definitions",
                "revision": "a" * 40,
                "path": "npc_units.txt",
                "sha256": "b" * 64,
            }
        ],
        "units": [
            {
                "internal_name": TOWER,
                "kind": "tower",
                "name_zh": "防御塔",
                "name_en": "Tower",
                "side": "radiant",
                "lane": "bot",
                "tier": 2,
            }
        ],
    }


def write_mapping(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_exact_tower_lookup_returns_names_and_explicit_location() -> None:
    result = UnitCatalog.load_default().lookup(TOWER)

    assert result is not None
    assert result.model_dump() == payload()["units"][0]


@pytest.mark.parametrize(
    "key",
    [
        "dota_unknown",
        "npc_dota_hero_antimage",
        "npc_dota_goodguys_tower99_bot",
        "npc_dota_goodguys_tower2_bot_new",
        "npc_dota_goodguys_tower2",
        "NPC_DOTA_GOODGUYS_TOWER2_BOT",
        " npc_dota_goodguys_tower2_bot ",
        "Tower",
        "防御塔",
    ],
)
def test_unmatched_keys_have_no_fuzzy_prefix_or_display_name_fallback(key: str) -> None:
    assert UnitCatalog.load_default().lookup(key) is None


@pytest.mark.parametrize("key", [None, True, 1, [], {}, ""])
def test_invalid_query_types_raise_value_error(key: object) -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        UnitCatalog.load_default().lookup(key)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("key", "kind", "name_zh", "name_en"),
    [
        ("npc_dota_courier", "courier", "信使", "Courier"),
        ("npc_dota_observer_wards", "ward", "侦察守卫", "Observer Ward"),
        ("npc_dota_furion_treant", "summoned_unit", "树人", "Treant"),
        ("npc_dota_neutral_centaur_khan", "neutral_creep", "半人马征服者", "Centaur Conqueror"),
        ("npc_dota_miniboss", "tormentor", "痛苦魔方", "Tormentor"),
        ("npc_dota_roshan", "roshan", "肉山", "Roshan"),
        ("dota_fountain", "fountain", "泉水", "Fountain"),
    ],
)
def test_generic_units_never_acquire_side_from_static_defaults(
    key: str, kind: str, name_zh: str, name_en: str
) -> None:
    row = UnitCatalog.load_default().lookup(key)

    assert row is not None
    assert (row.kind, row.name_zh, row.name_en) == (kind, name_zh, name_en)
    assert row.side is None
    assert row.lane is None
    assert row.tier is None
    assert "hero_id" not in row.model_dump()
    assert "player_slot" not in row.model_dump()


def test_explicit_creep_and_barracks_side_and_lane_are_retained() -> None:
    catalog = UnitCatalog.load_default()
    creep = catalog.lookup("npc_dota_creep_badguys_flagbearer")
    barracks = catalog.lookup("npc_dota_goodguys_range_rax_top")
    tower = catalog.lookup("npc_dota_goodguys_tower4")

    assert creep is not None and creep.side == "dire" and creep.lane is None
    assert barracks is not None and barracks.side == "radiant" and barracks.lane == "top"
    assert tower is not None and tower.tier == 4 and tower.lane is None


def test_bundled_sample_resource_has_117_unique_bilingual_records_and_pinned_sources() -> None:
    raw = json.loads(BUNDLED_MAPPING.read_text(encoding="utf-8"))
    catalog = UnitCatalog.load_default()

    assert len(raw["units"]) == 117
    assert len({r["internal_name"] for r in raw["units"]}) == 117
    assert len(catalog.sources) == 4
    for unit in raw["units"]:
        row = catalog.lookup(unit["internal_name"])
        assert row is not None and row.name_zh and row.name_en
    assert {s.revision for s in catalog.sources} == {
        "fc24352806127812d3746b47d7c53ed5f802ffaa",
        "68348f45cb38e5c29388e13bd2ca4f825393357d",
    }
    assert catalog.version.startswith("sha256:") and len(catalog.version) == 71


def test_version_ignores_json_formatting_and_changes_with_names_or_provenance(
    tmp_path: Path,
) -> None:
    path = tmp_path / "units.json"
    data = payload()
    write_mapping(path, data)
    first = UnitCatalog.from_file(path)
    path.write_text(json.dumps(data, indent=4, sort_keys=True), encoding="utf-8")
    assert UnitCatalog.from_file(path).version == first.version

    data["units"][0]["name_en"] = "Changed label"
    write_mapping(path, data)
    renamed = UnitCatalog.from_file(path)
    assert renamed.version != first.version

    data["sources"][0]["revision"] = "c" * 40
    write_mapping(path, data)
    assert UnitCatalog.from_file(path).version != renamed.version
    assert first.lookup(TOWER).name_en == "Tower"
    assert first.sources[0].revision == "a" * 40


def test_loaded_snapshot_is_immutable_and_reads_do_not_reopen_resource(tmp_path: Path) -> None:
    path = tmp_path / "units.json"
    write_mapping(path, payload())
    catalog = UnitCatalog.from_file(path)
    version = catalog.version
    row = catalog.lookup(TOWER)
    assert row is not None
    path.unlink()

    with pytest.raises(ValidationError):
        row.name_en = "Changed"
    with pytest.raises(ValidationError):
        catalog.sources[0].revision = "c" * 40
    assert catalog.lookup(TOWER).name_en == "Tower"
    assert catalog.lookup("dota_unknown") is None
    assert catalog.version == version


@pytest.mark.parametrize("language", ["name_zh", "name_en"])
@pytest.mark.parametrize("missing_name", [None, ""])
def test_missing_language_remains_null_without_translation(
    tmp_path: Path, missing_name: str | None, language: str
) -> None:
    data = payload()
    data["units"][0][language] = missing_name
    path = tmp_path / "units.json"
    write_mapping(path, data)

    row = UnitCatalog.from_file(path).lookup(TOWER)

    assert row is not None
    assert getattr(row, language) is None
    other_language = "name_en" if language == "name_zh" else "name_zh"
    assert getattr(row, other_language) == payload()["units"][0][other_language]


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "unknown"},
        {"kind": "hero"},
        {"internal_name": "dota_unknown"},
        {"internal_name": "npc_dota_hero_antimage"},
        {"side": "dire"},
        {"internal_name": "npc_dota_courier", "kind": "courier", "side": "radiant"},
        {"kind": "summoned_unit"},
        {"tier": True},
        {"tier": 5},
        {"tier": 3},
        {"lane": "top"},
        {"name_en": 1},
        {"player_slot": 128},
        {"hero_id": 1},
    ],
)
def test_invalid_or_invented_mapping_facts_are_rejected(tmp_path: Path, change: dict) -> None:
    data = payload()
    data["units"][0].update(change)
    path = tmp_path / "units.json"
    write_mapping(path, data)

    with pytest.raises(ValidationError):
        UnitCatalog.from_file(path)


def test_duplicate_identifiers_are_rejected_instead_of_overwriting(tmp_path: Path) -> None:
    data = payload()
    data["units"].append(dict(data["units"][0], name_en="Other"))
    path = tmp_path / "units.json"
    write_mapping(path, data)

    with pytest.raises(ValidationError, match="Duplicate unit"):
        UnitCatalog.from_file(path)


@pytest.mark.parametrize("version", [True, "1", 2])
def test_unsupported_or_coerced_schema_versions_are_rejected(
    tmp_path: Path, version: object
) -> None:
    data = payload()
    data["schema_version"] = version
    path = tmp_path / "units.json"
    write_mapping(path, data)

    with pytest.raises(ValidationError):
        UnitCatalog.from_file(path)


def test_missing_corrupt_and_unreadable_resources_propagate_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "units.json"
    with pytest.raises(FileNotFoundError):
        UnitCatalog.from_file(path)
    path.write_text("{invalid json", encoding="utf-8")
    with pytest.raises(ValidationError):
        UnitCatalog.from_file(path)

    def fail_read(self: Path) -> bytes:
        raise OSError("resource read failed")

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    with pytest.raises(OSError, match="resource read failed"):
        UnitCatalog.from_file(path)


def test_default_resource_path_is_independent_of_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert UnitCatalog.load_default().lookup(TOWER) is not None
