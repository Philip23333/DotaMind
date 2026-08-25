"""Contract tests for the canonical GameSummaryArtifact v0 schema."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.vnext.artifacts import GameSummaryArtifact
from app.vnext.artifacts.game_summary import (
    AbilityUpgrade,
    CanonicalItem,
    Draft,
    DraftEvent,
    GameInfo,
    Hero,
    ItemSlot,
    PlayerEconomy,
    PlayerGameSummary,
    PlayerIdentity,
    PlayerItems,
    PlayerStats,
    PurchaseEvent,
    Teams,
    TeamSummary,
)


def artifact_payload() -> dict[str, object]:
    """Return a complete minimal v0 payload with native Dota identifiers."""

    return {
        "game": {
            "valve_match_id": 8123456789,
            "start_time": "2026-08-25T12:00:00+00:00",
            "duration_seconds": 2345,
            "winner": "radiant",
            "game_mode": {"id": 22, "name": "All Pick"},
            "lobby_type": {"id": 1, "name": "Tournament"},
        },
        "teams": {
            "radiant": {"valve_team_id": 15, "name": "Radiant", "score": 30},
            "dire": {"valve_team_id": 2163, "name": "Dire", "score": 20},
        },
        "players": [
            {
                "identity": {
                    "steam_account_id": 123456,
                    "registered_name": "Player",
                    "persona_name": "Persona",
                },
                "side": "radiant",
                "player_slot": 0,
                "hero": {"id": 137, "name": "Marci"},
                "stats": {
                    "level": 20,
                    "kills": 12,
                    "deaths": 3,
                    "assists": 15,
                    "last_hits": 201,
                    "denies": 10,
                },
                "economy": {
                    "net_worth": 18000,
                    "gold_per_min": 600,
                    "xp_per_min": 700,
                },
                "items": {
                    "inventory": [{"slot": 0, "id": 50, "name": "Power Treads"}],
                    "backpack": [{"slot": 6, "id": None, "name": None}],
                    "neutral": {
                        "item": {"id": 287, "name": "Trusty Shovel"},
                        "enhancement": {"id": 1700, "name": "Mystical"},
                    },
                },
                "purchase_history": [
                    {"time_seconds": 120, "item_id": 50, "item_name": "Power Treads"}
                ],
                "ability_upgrades": [
                    {
                        "level": 1,
                        "time_seconds": 0,
                        "ability_id": 1367,
                        "ability_name": "Dispose",
                    }
                ],
            }
        ],
        "draft": {
            "picks": [{"order": 0, "side": "radiant", "hero_id": 137, "hero_name": "Marci"}],
            "bans": [{"order": 1, "side": "dire", "hero_id": 1, "hero_name": "Anti-Mage"}],
        },
    }


def test_minimal_artifact_has_fixed_schema_identity() -> None:
    artifact = GameSummaryArtifact.model_validate(artifact_payload())

    assert artifact.artifact_type == "game_summary"
    assert artifact.schema_version == "1"
    assert artifact.game.start_time == datetime(2026, 8, 25, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("field", "value"),
    [("artifact_type", "other"), ("schema_version", "2")],
)
def test_root_literal_contract_rejects_other_identity_values(field: str, value: str) -> None:
    payload = artifact_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        GameSummaryArtifact.model_validate(payload)


def test_nullable_source_facts_and_catalog_names_are_valid() -> None:
    payload = artifact_payload()
    game = payload["game"]
    teams = payload["teams"]
    player = payload["players"][0]
    assert isinstance(game, dict)
    assert isinstance(teams, dict)
    assert isinstance(player, dict)

    game["winner"] = None
    game["game_mode"] = {"id": 22, "name": None}
    teams["radiant"] = {"valve_team_id": None, "name": None, "score": None}
    player["identity"] = {
        "steam_account_id": None,
        "registered_name": None,
        "persona_name": None,
    }
    player["hero"] = {"id": 137, "name": None}
    player["stats"]["kills"] = None
    player["stats"].pop("deaths")
    player["items"]["inventory"][0]["name"] = None

    artifact = GameSummaryArtifact.model_validate(payload)

    assert artifact.game.winner is None
    assert artifact.teams.radiant.name is None
    assert artifact.players[0].identity.registered_name is None
    assert artifact.players[0].stats.kills is None
    assert artifact.players[0].stats.deaths is None
    assert artifact.players[0].items.inventory[0].name is None


def test_missing_scalars_and_fixed_structures_use_the_documented_empty_shape() -> None:
    artifact = GameSummaryArtifact.model_validate(
        {
            "game": {"valve_match_id": 8123456789},
            "teams": {},
            "players": [
                {
                    "identity": {
                        "steam_account_id": None,
                        "registered_name": None,
                        "persona_name": None,
                    },
                    "side": "dire",
                    "player_slot": 128,
                    "hero": {"id": 1},
                }
            ],
        }
    )
    player = artifact.players[0]

    assert artifact.game.start_time is None
    assert artifact.game.duration_seconds is None
    assert artifact.game.game_mode.id is None
    assert artifact.game.game_mode.name is None
    assert artifact.game.lobby_type.id is None
    assert artifact.game.lobby_type.name is None
    assert artifact.teams.radiant == TeamSummary()
    assert artifact.teams.dire == TeamSummary()
    assert player.stats == PlayerStats()
    assert player.economy == PlayerEconomy()
    assert player.items.inventory == []
    assert player.items.backpack == []
    assert player.items.neutral.item is None
    assert player.items.neutral.enhancement is None
    assert artifact.draft == Draft()


def test_collections_default_to_empty_lists() -> None:
    payload = artifact_payload()
    player = payload["players"][0]
    assert isinstance(player, dict)
    player.pop("purchase_history")
    player.pop("ability_upgrades")
    payload.pop("draft")

    artifact = GameSummaryArtifact.model_validate(payload)

    assert artifact.players[0].purchase_history == []
    assert artifact.players[0].ability_upgrades == []
    assert artifact.draft.picks == []
    assert artifact.draft.bans == []


def test_neutral_structure_remains_present_when_both_values_are_missing() -> None:
    payload = artifact_payload()
    player = payload["players"][0]
    assert isinstance(player, dict)
    player["items"] = {"inventory": [], "backpack": []}

    artifact = GameSummaryArtifact.model_validate(payload)

    assert artifact.players[0].items.neutral.item is None
    assert artifact.players[0].items.neutral.enhancement is None


def test_empty_inventory_slot_is_valid() -> None:
    artifact = GameSummaryArtifact.model_validate(artifact_payload())
    empty_slot = ItemSlot(slot=2, id=None, name=None)
    artifact.players[0].items.inventory.append(empty_slot)

    assert artifact.players[0].items.inventory[-1] == empty_slot


def test_native_identifiers_populate_the_canonical_fields() -> None:
    artifact = GameSummaryArtifact.model_validate(artifact_payload())
    player = artifact.players[0]

    assert artifact.game.valve_match_id == 8123456789
    assert artifact.teams.radiant.valve_team_id == 15
    assert player.identity.steam_account_id == 123456
    assert player.hero.id == 137
    assert player.items.inventory[0].id == 50
    assert player.ability_upgrades[0].ability_id == 1367


def test_valve_match_and_hero_ids_remain_required() -> None:
    missing_match_id = deepcopy(artifact_payload())
    missing_match_id["game"].pop("valve_match_id")

    with pytest.raises(ValidationError):
        GameSummaryArtifact.model_validate(missing_match_id)

    missing_hero_id = deepcopy(artifact_payload())
    missing_hero_id["players"][0]["hero"].pop("id")

    with pytest.raises(ValidationError):
        GameSummaryArtifact.model_validate(missing_hero_id)


def test_contract_has_no_provider_private_or_derived_analytics_fields() -> None:
    assert set(GameSummaryArtifact.model_fields) == {
        "artifact_type",
        "schema_version",
        "game",
        "teams",
        "players",
        "draft",
    }
    assert "match_id" not in GameInfo.model_fields
    assert "pandascore_match_id" not in GameInfo.model_fields
    assert "pandascore_team_id" not in TeamSummary.model_fields
    assert "pandascore_player_id" not in PlayerIdentity.model_fields
    assert set(PlayerStats.model_fields) == {
        "level",
        "kills",
        "deaths",
        "assists",
        "last_hits",
        "denies",
    }
    assert set(PlayerEconomy.model_fields) == {
        "net_worth",
        "gold_per_min",
        "xp_per_min",
    }
    assert "kda" not in PlayerStats.model_fields
    assert "total_gold" not in PlayerEconomy.model_fields
    assert "total_xp" not in PlayerEconomy.model_fields
    assert "abilities" not in PlayerGameSummary.model_fields
    assert "is_pick" not in DraftEvent.model_fields


def test_component_models_use_only_the_documented_fields() -> None:
    assert set(Teams.model_fields) == {"radiant", "dire"}
    assert set(Hero.model_fields) == {"id", "name"}
    assert set(PlayerItems.model_fields) == {"inventory", "backpack", "neutral"}
    assert set(CanonicalItem.model_fields) == {"id", "name"}
    assert set(PurchaseEvent.model_fields) == {"time_seconds", "item_id", "item_name"}
    assert set(AbilityUpgrade.model_fields) == {
        "level",
        "time_seconds",
        "ability_id",
        "ability_name",
    }
    assert set(Draft.model_fields) == {"picks", "bans"}


def test_extra_provider_private_field_is_rejected() -> None:
    payload = deepcopy(artifact_payload())
    payload["game"]["pandascore_match_id"] = 42

    with pytest.raises(ValidationError):
        GameSummaryArtifact.model_validate(payload)
