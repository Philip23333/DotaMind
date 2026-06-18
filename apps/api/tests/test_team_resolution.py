import asyncio
from unittest.mock import AsyncMock

import pytest

from app.domain.teams import (
    AmbiguousTeamError,
    TeamDataUnavailableError,
    TeamNotFoundError,
)
from app.pipeline.retriever import RetrieverTool


def _team(
    team_id: int,
    name: str,
    tag: str,
    *,
    rating: float = 1000,
    last_match_time: int = 0,
) -> dict:
    return {
        "team_id": team_id,
        "name": name,
        "tag": tag,
        "rating": rating,
        "last_match_time": last_match_time,
    }


def test_resolve_team_normalizes_generic_team_prefix() -> None:
    teams = [_team(8255888, "BB", "BB")]

    resolution = RetrieverTool.resolve_team("Team BB", teams)

    assert resolution.status == "resolved"
    assert resolution.team == teams[0]


def test_resolve_team_uses_camel_case_acronym_as_fallback() -> None:
    teams = [_team(8255888, "BB", "BB")]

    resolution = RetrieverTool.resolve_team("BetBoom", teams)

    assert resolution.status == "resolved"
    assert resolution.team == teams[0]
    assert resolution.candidates[0]["match_reason"] == "acronym matched team name"


def test_resolve_team_returns_ambiguous_candidates() -> None:
    teams = [
        _team(1, "Big Bears", "BB", last_match_time=100),
        _team(2, "Bright Blades", "BB", last_match_time=200),
    ]

    resolution = RetrieverTool.resolve_team("BB", teams)

    assert resolution.status == "ambiguous"
    assert {candidate["team_id"] for candidate in resolution.candidates} == {1, 2}


def test_resolve_team_returns_not_found() -> None:
    resolution = RetrieverTool.resolve_team(
        "No Such Team",
        [_team(1, "Team Liquid", "Liquid")],
    )

    assert resolution.status == "not_found"
    assert resolution.candidates == []


def test_resolve_team_uses_fuzzy_name_match_after_exact_stages_fail() -> None:
    teams = [_team(2163, "Team Liquid", "Liquid")]

    resolution = RetrieverTool.resolve_team("Liqud", teams)

    assert resolution.status == "resolved"
    assert resolution.team == teams[0]
    assert resolution.candidates[0]["match_reason"] == "fuzzy team name match"


def test_retrieve_team_raises_not_found_instead_of_returning_mock() -> None:
    retriever = RetrieverTool()
    retriever._live_data_enabled = True
    retriever._opendota_teams.get_all = AsyncMock(return_value=[])

    with pytest.raises(TeamNotFoundError):
        asyncio.run(retriever.retrieve_team("Missing Team", "last_30_days"))


def test_retrieve_team_raises_ambiguity_with_candidates() -> None:
    retriever = RetrieverTool()
    retriever._live_data_enabled = True
    retriever._opendota_teams.get_all = AsyncMock(
        return_value=[
            _team(1, "Big Bears", "BB"),
            _team(2, "Bright Blades", "BB"),
        ]
    )

    with pytest.raises(AmbiguousTeamError) as raised:
        asyncio.run(retriever.retrieve_team("BB", "last_30_days"))

    assert len(raised.value.candidates) == 2


def test_retrieve_team_does_not_use_mock_when_live_data_is_disabled() -> None:
    retriever = RetrieverTool()
    retriever._live_data_enabled = False

    with pytest.raises(TeamDataUnavailableError):
        asyncio.run(retriever.retrieve_team("Team Spirit", "last_30_days"))
