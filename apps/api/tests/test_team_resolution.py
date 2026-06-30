import asyncio
from unittest.mock import ANY, AsyncMock

import pytest

from app.domain.teams import (
    AmbiguousTeamError,
    TeamDataUnavailableError,
    TeamNotFoundError,
    TeamSelectionNotFoundError,
)
from app.pipeline.retriever import RetrieverTool, _parse_days


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


@pytest.mark.parametrize(
    ("time_range", "expected_days"),
    [
        ("last_10_days", 10),
        ("last_3_weeks", 21),
        ("last_2_months", 60),
        ("last_1_year", 365),
        ("last_month", 30),
        ("unknown", 30),
    ],
)
def test_parse_days_respects_time_units(time_range: str, expected_days: int) -> None:
    assert _parse_days(time_range) == expected_days


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


def test_resolve_team_does_not_let_generic_name_match_hide_tag_ambiguity() -> None:
    teams = [
        _team(8255888, "BoomBoys", "BB", rating=1440, last_match_time=1780832552),
        _team(9131584, "BB Team", "BB", rating=1396, last_match_time=1754141860),
    ]

    resolution = RetrieverTool.resolve_team("Team BB", teams)

    assert resolution.status == "ambiguous"
    assert [candidate["team_id"] for candidate in resolution.candidates] == [
        8255888,
        9131584,
    ]


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
    assert raised.value.time_range == "last_30_days"


def test_retrieve_team_uses_validated_selected_team_id() -> None:
    retriever = RetrieverTool()
    retriever._live_data_enabled = True
    selected_team = _team(2, "Bright Blades", "BB")
    retriever._opendota_teams.get_all = AsyncMock(
        return_value=[
            _team(1, "Big Bears", "BB"),
            selected_team,
        ]
    )
    retriever._opendota_teams.get_report_data = AsyncMock(
        return_value={"team_id": 2, "team_name": "Bright Blades"}
    )

    bundle = asyncio.run(
        retriever.retrieve_team("Bright Blades", "last_30_days", team_id=2)
    )

    assert bundle.query["team_id"] == 2
    retriever._opendota_teams.get_report_data.assert_awaited_once_with(
        "Bright Blades",
        days=30,
        resolved_team=selected_team,
        cache_before=ANY,
    )


def test_retrieve_team_rejects_stale_selected_team_id() -> None:
    retriever = RetrieverTool()
    retriever._live_data_enabled = True
    retriever._opendota_teams.get_all = AsyncMock(
        return_value=[_team(1, "Big Bears", "BB")]
    )

    with pytest.raises(TeamSelectionNotFoundError):
        asyncio.run(
            retriever.retrieve_team("Bright Blades", "last_30_days", team_id=2)
        )


def test_retrieve_team_does_not_use_mock_when_live_data_is_disabled() -> None:
    retriever = RetrieverTool()
    retriever._live_data_enabled = False

    with pytest.raises(TeamDataUnavailableError):
        asyncio.run(retriever.retrieve_team("Team Spirit", "last_30_days"))
