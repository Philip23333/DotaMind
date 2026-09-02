from __future__ import annotations

import pytest

from scripts.generate_pandascore_capabilities import build_capabilities, serialize_capabilities


def test_generated_capabilities_preserve_endpoint_local_query_fields() -> None:
    capabilities = build_capabilities()
    resources = capabilities["resources"]

    league = resources["league"]["scopes"]["all"]
    assert "name" in league["filter"]
    assert "name" in league["search"]
    assert "year" not in league["filter"]

    serie = resources["serie"]["scopes"]["all"]
    assert "league_id" in serie["filter"]
    assert "year" in serie["filter"]
    assert "name" in serie["search"]

    tournament = resources["tournament"]["scopes"]["all"]
    assert "serie_id" in tournament["filter"]
    assert "name" in tournament["filter"]
    assert "league_id" not in tournament["filter"]
    assert "year" not in tournament["filter"]

    match = resources["match"]["scopes"]["all"]
    assert {"league_id", "serie_id", "tournament_id"} <= set(match["filter"])
    assert "name" in match["search"]
    assert match["filter"]["match_type"] == {
        "type": "string",
        "multiple": True,
        "enum": [
            "all_games_played",
            "best_of",
            "custom",
            "first_to",
            "ow_best_of",
            "red_bull_home_ground",
        ],
        "format": None,
    }

    team_by_serie = resources["team"]["scopes"]["by_serie"]
    assert team_by_serie["path"] == "/dota2/series/{serie_id_or_slug}/teams"
    assert "serie_id_or_slug" in team_by_serie["path_params"]
    assert team_by_serie["path_params"]["serie_id_or_slug"]["type"] == "integer|string"

    expected_lifecycle_scopes = {"all", "past", "running", "upcoming"}
    assert set(resources["match"]["scopes"]) == expected_lifecycle_scopes
    assert set(resources["serie"]["scopes"]) == expected_lifecycle_scopes
    assert set(resources["tournament"]["scopes"]) == expected_lifecycle_scopes


def test_generation_is_deterministic() -> None:
    first_generation = serialize_capabilities(build_capabilities())
    second_generation = serialize_capabilities(build_capabilities())
    assert first_generation == second_generation


def test_generation_rejects_an_incomplete_endpoint_fact_directory(tmp_path) -> None:
    with pytest.raises(ValueError, match="Expected 16 endpoint fact files, found 0"):
        build_capabilities(tmp_path)
