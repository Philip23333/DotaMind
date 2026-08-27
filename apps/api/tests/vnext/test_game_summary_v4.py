"""Contract and construction tests for the localized GameSummaryArtifact v4."""

from copy import deepcopy

from app.vnext.artifacts.game_summary_builder_v4 import GameSummaryBuilderV4
from app.vnext.artifacts.game_summary_v4 import GameSummaryArtifactV4
from app.vnext.identity.ability_v4 import AbilityResolverV4
from app.vnext.identity.hero_v4 import HeroResolverV4
from app.vnext.identity.item_v4 import ItemResolverV4
from app.vnext.identity.localized import LocalizedName
from app.vnext.providers.opendota import OpenDotaGameConstructionAdapter
from app.vnext.providers.opendota.models import OpenDotaGameConstructionMatch


def _source_payload() -> dict[str, object]:
    return {
        "match_id": 8123456789,
        "radiant_win": True,
        "radiant_team": {},
        "dire_team": {},
        "players": [
            {
                "player_slot": 0,
                "hero_id": 85,
                "item_1": 1,
                "purchase_log": [{"time": 120, "key": "blink"}],
                "ability_upgrades_arr": [{"ability": 5442, "level": 1, "time": 0}],
            }
        ],
        "picks_bans": [
            {"order": 0, "team": 0, "hero_id": 85, "is_pick": True},
            {"order": 1, "team": 1, "hero_id": 2, "is_pick": False},
        ],
    }


def _builder() -> GameSummaryBuilderV4:
    return GameSummaryBuilderV4(
        hero_resolver=HeroResolverV4(
            {
                2: LocalizedName(name_en="Axe", name_zh="斧王"),
                85: LocalizedName(name_en="Undying", name_zh="不朽尸王"),
            }
        ),
        item_resolver=ItemResolverV4(
            {1: LocalizedName(name_en="Blink Dagger", name_zh="闪烁匕首")},
            item_key_to_id={"blink": 1, "unknown": 999},
        ),
        ability_resolver=AbilityResolverV4(
            {5442: LocalizedName(name_en="Decay", name_zh="腐朽")}
        ),
    )


def _build(payload: dict[str, object] | None = None) -> GameSummaryArtifactV4:
    source = OpenDotaGameConstructionMatch.model_validate(payload or _source_payload())
    context = OpenDotaGameConstructionAdapter().to_construction_context(source)
    return _builder().build(context)


def test_v4_preserves_native_ids_and_catalog_localized_names() -> None:
    artifact = _build()
    player = artifact.players[0]

    assert artifact.artifact_type == "game_summary"
    assert artifact.schema_version == "4"
    assert player.hero.model_dump() == {
        "id": 85,
        "name_en": "Undying",
        "name_zh": "不朽尸王",
    }
    assert player.items.inventory[1].model_dump() == {
        "slot": 1,
        "id": 1,
        "name_en": "Blink Dagger",
        "name_zh": "闪烁匕首",
    }
    assert player.purchase_history[0].model_dump() == {
        "time_seconds": 120,
        "item_id": 1,
        "item_name_en": "Blink Dagger",
        "item_name_zh": "闪烁匕首",
    }
    assert player.ability_upgrades[0].model_dump() == {
        "level": 1,
        "time_seconds": 0,
        "ability_id": 5442,
        "ability_name_en": "Decay",
        "ability_name_zh": "腐朽",
    }
    assert artifact.draft.picks[0].model_dump() == {
        "order": 0,
        "side": "radiant",
        "hero_id": 85,
        "hero_name_en": "Undying",
        "hero_name_zh": "不朽尸王",
    }
    assert artifact.draft.bans[0].model_dump() == {
        "order": 1,
        "side": "dire",
        "hero_id": 2,
        "hero_name_en": "Axe",
        "hero_name_zh": "斧王",
    }


def test_v4_catalog_misses_preserve_native_ids_and_leave_names_null() -> None:
    payload = deepcopy(_source_payload())
    player = payload["players"][0]
    assert isinstance(player, dict)
    player["hero_id"] = 999999
    player["item_1"] = 999999
    player["purchase_log"] = [{"time": 120, "key": "unknown"}]
    player["ability_upgrades_arr"] = [999999]
    payload["picks_bans"] = [
        {"order": 0, "team": 0, "hero_id": 999999, "is_pick": True},
    ]

    artifact = _build(payload)
    resolved_player = artifact.players[0]

    assert resolved_player.hero.model_dump() == {
        "id": 999999,
        "name_en": None,
        "name_zh": None,
    }
    assert resolved_player.items.inventory[1].model_dump() == {
        "slot": 1,
        "id": 999999,
        "name_en": None,
        "name_zh": None,
    }
    assert resolved_player.purchase_history[0].model_dump() == {
        "time_seconds": 120,
        "item_id": 999,
        "item_name_en": None,
        "item_name_zh": None,
    }
    assert resolved_player.ability_upgrades[0].model_dump() == {
        "level": None,
        "time_seconds": None,
        "ability_id": 999999,
        "ability_name_en": None,
        "ability_name_zh": None,
    }
    assert artifact.draft.picks[0].model_dump() == {
        "order": 0,
        "side": "radiant",
        "hero_id": 999999,
        "hero_name_en": None,
        "hero_name_zh": None,
    }


def test_v4_rejects_provider_private_fields() -> None:
    payload = _build().model_dump()
    payload["game"]["pandascore_match_id"] = 42

    try:
        GameSummaryArtifactV4.model_validate(payload)
    except ValueError:
        pass
    else:
        raise AssertionError("v4 accepted a provider-private field")
