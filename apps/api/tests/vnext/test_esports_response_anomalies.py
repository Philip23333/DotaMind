from __future__ import annotations

import pytest

from app.vnext.capabilities.esports.dtos import ResponseAnomaly
from app.vnext.capabilities.esports.league import LeagueSearchResult
from app.vnext.capabilities.esports.match import MatchSearchResult
from app.vnext.capabilities.esports.player import PlayerSearchResult
from app.vnext.capabilities.esports.series import SeriesSearchResult, SeriesTeamsResult
from app.vnext.capabilities.esports.team import TeamSearchResult
from app.vnext.capabilities.esports.tournament import TournamentSearchResult


@pytest.mark.parametrize(
    "result_type",
    [
        LeagueSearchResult,
        SeriesSearchResult,
        SeriesTeamsResult,
        TournamentSearchResult,
        MatchSearchResult,
        TeamSearchResult,
        PlayerSearchResult,
    ],
)
def test_esports_search_results_have_uniform_anomaly_envelope(result_type) -> None:
    result = result_type(items=[], page=1, limit=20)

    assert result.anomalies == []
    assert result.model_dump(mode="json")["anomalies"] == []


def test_response_anomaly_is_strict_and_serializable() -> None:
    anomaly = ResponseAnomaly(
        path="provider.items[2]",
        reason="provider item is not an object",
        provider_id=42,
    )

    assert anomaly.model_dump(mode="json") == {
        "path": "provider.items[2]",
        "reason": "provider item is not an object",
        "provider_id": 42,
    }
    with pytest.raises(ValueError):
        ResponseAnomaly(path="provider.items[2]", reason="bad", raw_payload={})
