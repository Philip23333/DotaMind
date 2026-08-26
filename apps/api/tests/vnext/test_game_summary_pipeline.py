"""Focused source-to-canonical tests for the game-summary construction pipeline."""

from copy import deepcopy

import pytest

from app.vnext.artifacts.game_summary import CanonicalItem, ItemSlot
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
                "level": 20,
                "kills": 12,
                "deaths": 3,
                "assists": 15,
                "last_hits": 201,
                "denies": 10,
                "net_worth": 18000,
                "gold_per_min": 600,
                "xp_per_min": 700,
                "item_0": 0,
                "item_1": 1,
                "backpack_0": 2,
                "item_neutral": 3,
                "item_neutral2": 4,
                "purchase_log": [
                    {"time": 120, "key": "blink"},
                ],
                "ability_upgrades_arr": [
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
            {1: "Blink Dagger", 2: "Boots of Speed", 3: "Trusty Shovel", 4: "Mystical"},
            item_key_to_id={"blink": 1},
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


def test_item_resolver_resolves_known_keys_and_omits_unknown_keys() -> None:
    resolver = ItemResolver(
        {1: "Blink Dagger"},
        item_key_to_id={"blink": 1},
    )

    assert resolver.resolve_key(" blink ") == CanonicalItem(id=1, name="Blink Dagger")
    assert resolver.resolve_key("unknown_item") is None


def test_ability_upgrade_aliases_accept_current_and_legacy_dict_shapes() -> None:
    legacy_payload = deepcopy(source_payload())
    legacy_source = OpenDotaGameConstructionMatch.model_validate(legacy_payload)
    assert legacy_source.players[0].ability_upgrades[0].ability_id == 101

    current_payload = deepcopy(source_payload())
    current_player = current_payload["players"][0]
    current_player.pop("ability_upgrades_arr")
    current_player["ability_upgrades"] = [
        {"ability_id": 101, "level": 1, "time_seconds": 0},
    ]
    current_source = OpenDotaGameConstructionMatch.model_validate(current_payload)

    assert current_source.players[0].ability_upgrades[0].ability_id == 101


def test_real_integer_ability_upgrade_array_is_accepted_without_alias_leak() -> None:
    payload = deepcopy(source_payload())
    payload["players"][0]["ability_upgrades_arr"] = [5028, 5029]

    source = OpenDotaGameConstructionMatch.model_validate(payload)
    context = OpenDotaGameConstructionAdapter().to_construction_context(source)

    assert [upgrade.ability_id for upgrade in source.players[0].ability_upgrades] == [
        5028,
        5029,
    ]
    assert "ability_upgrades_arr" not in type(source.players[0]).model_fields
    assert "ability_upgrades_arr" not in type(context.players[0]).model_fields
    assert [upgrade.valve_ability_id for upgrade in context.players[0].ability_upgrades] == [
        5028,
        5029,
    ]
    assert [upgrade.level for upgrade in context.players[0].ability_upgrades] == [None, None]
    assert [upgrade.time_seconds for upgrade in context.players[0].ability_upgrades] == [
        None,
        None,
    ]

    artifact = builder().build(context)
    assert [upgrade.ability_id for upgrade in artifact.players[0].ability_upgrades] == [
        5028,
        5029,
    ]
    assert [upgrade.level for upgrade in artifact.players[0].ability_upgrades] == [None, None]
    assert [upgrade.time_seconds for upgrade in artifact.players[0].ability_upgrades] == [
        None,
        None,
    ]


def test_complete_source_model_flows_to_a_canonical_artifact() -> None:
    artifact = builder().build(construction_context())

    assert artifact.artifact_type == "game_summary"
    assert artifact.schema_version == "3"
    assert artifact.game.valve_match_id == 8123456789
    assert artifact.game.winner == "radiant"
    assert artifact.players[0].hero.name == "Anti-Mage"
    assert artifact.players[0].stats.level == 20
    assert artifact.players[0].stats.kills == 12
    assert artifact.players[0].stats.deaths == 3
    assert artifact.players[0].stats.assists == 15
    assert artifact.players[0].stats.last_hits == 201
    assert artifact.players[0].stats.denies == 10
    assert artifact.players[0].economy.net_worth == 18000
    assert artifact.players[0].economy.gold_per_min == 600
    assert artifact.players[0].economy.xp_per_min == 700
    assert artifact.players[0].items.inventory[1].name == "Blink Dagger"
    assert len(artifact.players[0].purchase_history) == 1
    assert artifact.players[0].purchase_history[0].time_seconds == 120
    assert artifact.players[0].purchase_history[0].item_id == 1
    assert artifact.players[0].purchase_history[0].item_name == "Blink Dagger"
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
    assert items.neutral_items == [
        ItemSlot(slot=0, id=3, name="Trusty Shovel"),
        ItemSlot(slot=1, id=4, name="Mystical"),
    ]

    payload = deepcopy(source_payload())
    payload["players"][0]["item_neutral"] = 0
    artifact_with_empty_source_slot = builder().build(construction_context(payload))

    assert artifact_with_empty_source_slot.players[0].items.neutral_items == [
        ItemSlot(slot=0, id=None, name=None),
        ItemSlot(slot=1, id=4, name="Mystical"),
    ]


def test_builder_shapes_missing_context_neutral_items_as_two_empty_slots() -> None:
    context = construction_context()
    context = context.model_copy(
        update={
            "players": [
                context.players[0].model_copy(update={"neutral_items": []}),
            ]
        }
    )

    artifact = builder().build(context)

    assert artifact.players[0].items.neutral_items == [
        ItemSlot(slot=0, id=None, name=None),
        ItemSlot(slot=1, id=None, name=None),
    ]


def test_zero_item_id_never_reaches_canonical_item_fields() -> None:
    artifact = builder().build(construction_context())
    items = artifact.players[0].items

    assert items.inventory[0].id is None
    assert items.inventory[0].name is None
    assert all(slot.id != 0 for slot in [*items.inventory, *items.backpack])
    assert all(slot.id != 0 for slot in items.neutral_items)


def test_missing_stats_and_economy_values_remain_null() -> None:
    payload = deepcopy(source_payload())
    payload["players"][0]["kills"] = None
    payload["players"][0]["net_worth"] = None

    player = builder().build(construction_context(payload)).players[0]

    assert player.stats.kills is None
    assert player.economy.net_worth is None


def test_unknown_purchase_key_is_omitted_without_failing_the_artifact() -> None:
    payload = deepcopy(source_payload())
    payload["players"][0]["purchase_log"] = [
        {"time": 300, "key": "blink"},
        {"time": 120, "key": "unknown_item"},
        {"time": 180, "key": "blink"},
    ]

    player = builder().build(construction_context(payload)).players[0]

    assert [event.time_seconds for event in player.purchase_history] == [300, 180]
    assert [event.item_id for event in player.purchase_history] == [1, 1]
    assert [event.item_name for event in player.purchase_history] == [
        "Blink Dagger",
        "Blink Dagger",
    ]


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
