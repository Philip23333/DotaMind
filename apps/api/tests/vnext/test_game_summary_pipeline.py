"""Focused source-to-canonical tests for the game-summary construction pipeline."""

from copy import deepcopy

import pytest

from app.vnext.artifacts.game_summary_builder import (
    GameSummaryBuilder,
    MissingValveMatchIdError,
)
from app.vnext.domain.refs import HeroRef, ItemRef
from app.vnext.identity import AbilityResolver, HeroResolver, ItemResolver
from app.vnext.providers.opendota import OpenDotaGameConstructionAdapter
from app.vnext.providers.opendota.models import OpenDotaGameConstructionMatch


def source_payload() -> dict[str, object]:
    """Return compact complete OpenDota source data for the focused pipeline."""

    return {
        "match_id": 8123456789,
        "start_time": 1_700_000_000,
        "duration": 2400,
        "radiant_win": True,
        "game_mode": 22,
        "lobby_type": 1,
        "radiant_team": {"team_id": 15, "name": "Radiant Team"},
        "dire_team": {"team_id": 2163, "name": "Dire Team"},
        "radiant_score": 30,
        "dire_score": 20,
        "players": [
            {
                "account_id": 123456,
                "name": "Player",
                "personaname": "Persona",
                "player_slot": 0,
                "hero_id": 1,
                "item_0": 0,
                "item_1": 1,
                "backpack_0": 2,
                "item_neutral": 3,
                "item_neutral2": 4,
                "ability_upgrades": [
                    {"ability": 101, "level": 1, "time": 0},
                ],
            }
        ],
        "picks_bans": [
            {"order": 0, "team": 0, "hero_id": 1, "is_pick": True},
            {"order": 1, "team": 1, "hero_id": 2, "is_pick": False},
        ],
    }


def builder() -> GameSummaryBuilder:
    return GameSummaryBuilder(
        hero_resolver=HeroResolver({1: "Anti-Mage", 2: "Axe"}),
        item_resolver=ItemResolver(
            {1: "Blink Dagger", 2: "Boots of Speed", 3: "Trusty Shovel", 4: "Mystical"}
        ),
        ability_resolver=AbilityResolver({101: "Mana Break"}),
    )


def construction_context(payload: dict[str, object] | None = None):
    source = OpenDotaGameConstructionMatch.model_validate(payload or source_payload())
    return OpenDotaGameConstructionAdapter().to_construction_context(source)


def test_zero_source_item_maps_to_an_empty_item_slot_ref() -> None:
    context = construction_context()

    assert context.players[0].item_slots[0].item is None


def test_hero_resolver_returns_an_artifact_hero_name() -> None:
    hero = HeroResolver({1: "Anti-Mage"}).resolve(HeroRef(valve_hero_id=1))

    assert hero.id == 1
    assert hero.name == "Anti-Mage"


def test_item_resolver_uses_the_injected_catalog() -> None:
    item = ItemResolver({1: "Blink Dagger"}).resolve(ItemRef(valve_item_id=1))

    assert item.id == 1
    assert item.name == "Blink Dagger"


def test_complete_source_model_flows_to_a_canonical_artifact() -> None:
    artifact = builder().build(construction_context())

    assert artifact.artifact_type == "game_summary"
    assert artifact.schema_version == "2"
    assert artifact.game.valve_match_id == 8123456789
    assert artifact.game.winner == "radiant"
    assert artifact.players[0].hero.name == "Anti-Mage"
    assert artifact.players[0].items.inventory[1].name == "Blink Dagger"
    assert artifact.players[0].ability_upgrades[0].ability_name == "Mana Break"
    assert artifact.draft.picks[0].hero_name == "Anti-Mage"
    assert artifact.draft.bans[0].hero_name == "Axe"


def test_neutral_source_slots_remain_positional_until_builder_shapes_artifact() -> None:
    context = construction_context()
    player = context.players[0]

    assert "enhancement" not in type(player).model_fields
    assert len(player.neutral_items) == 2
    assert player.neutral_items[0].item is not None
    assert player.neutral_items[1].item is not None

    artifact = builder().build(context)
    items = artifact.players[0].items

    assert "enhancement" not in type(items).model_fields
    assert [(item.id, item.name) for item in items.neutral_items] == [
        (3, "Trusty Shovel"),
        (4, "Mystical"),
    ]

    payload = deepcopy(source_payload())
    payload["players"][0]["item_neutral"] = 0
    artifact_with_empty_source_slot = builder().build(construction_context(payload))

    assert [item.id for item in artifact_with_empty_source_slot.players[0].items.neutral_items] == [
        4
    ]


def test_zero_item_id_never_reaches_canonical_item_fields() -> None:
    artifact = builder().build(construction_context())
    items = artifact.players[0].items

    assert items.inventory[0].id is None
    assert items.inventory[0].name is None
    assert all(slot.id != 0 for slot in [*items.inventory, *items.backpack])
    assert all(item.id != 0 for item in items.neutral_items)


def test_builder_rejects_a_missing_valve_match_id() -> None:
    payload = deepcopy(source_payload())
    payload["match_id"] = None

    with pytest.raises(MissingValveMatchIdError):
        builder().build(construction_context(payload))


def test_builder_omits_a_player_without_hero_identity() -> None:
    payload = deepcopy(source_payload())
    payload["players"][0]["hero_id"] = None

    artifact = builder().build(construction_context(payload))

    assert artifact.players == []
