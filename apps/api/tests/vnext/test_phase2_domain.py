from __future__ import annotations

import asyncio

from app.vnext.domain.common.models import CompetitionRef
from app.vnext.domain.matches.normalization import normalize_panda_match
from app.vnext.domain.matches.resolution import (
    LeagueMatchSignal,
    LeagueSignal,
    MatchResolutionService,
    MatchSignal,
    TeamSignal,
)
from app.vnext.providers.pandascore.models import PandaScoreMatch
from tests.vnext.phase2_support import FETCHED_AT, fixture_services, load_fixture


def test_competition_search_normalizes_year_deduplicates_and_preserves_provenance() -> None:
    competition_service, _, _, _ = fixture_services()

    exact = asyncio.run(competition_service.search("  The   International 2026 ", year=2026))
    ambiguous = asyncio.run(competition_service.search("The International"))
    missing = asyncio.run(competition_service.search("No such event"))

    assert exact.status == "unique"
    assert exact.candidate_count == 1
    assert exact.candidates[0].year == 2026
    assert exact.provenance.sources == ["pandascore"]
    assert exact.provenance.freshness.fetched_at == FETCHED_AT
    assert ambiguous.status == "ambiguous"
    assert ambiguous.candidate_count == 2
    assert missing.status == "not_found"
    assert missing.candidates == []


def test_competition_schedule_is_normalized_and_status_filtered() -> None:
    competition_service, _, _, _ = fixture_services()
    search = asyncio.run(competition_service.search("The International 2026", year=2026))
    competition_ref = search.candidates[0].ref

    schedule = asyncio.run(
        competition_service.list_matches(
            competition_ref,
            time_scope="recent",
            status="finished",
            limit=10,
        )
    )
    assert schedule.status == "ok"
    assert schedule.candidate_count == 2
    assert all(match.status == "finished" for match in schedule.matches)
    assert all(
        match.competition and match.competition.ref == competition_ref for match in schedule.matches
    )
    assert schedule.provenance.freshness.fetched_at == FETCHED_AT


def test_panda_year_only_series_uses_league_name_without_exposing_provider_ids() -> None:
    row = PandaScoreMatch.model_validate(
        load_fixture("pandascore", "match_generic_series.json")
    )

    normalized = normalize_panda_match(row, fetched_at=FETCHED_AT)
    competition = normalized.summary.competition

    assert competition is not None
    assert competition.name == "The International"
    assert competition.year == 2026

    serialized = normalized.summary.model_dump_json()
    for provider_id in (
        row.provider_id,
        row.series_id,
        row.series.provider_id if row.series else None,
        *(opponent.opponent.provider_id for opponent in row.opponents),
        *(game.provider_id for game in row.games),
    ):
        if provider_id is not None:
            assert str(provider_id) not in serialized
    for forbidden in (
        "pandascore_id",
        "opendota_id",
        "league_id",
        "raw_response",
        "provider_payload",
    ):
        assert forbidden not in serialized


def test_match_search_unknown_competition_is_a_typed_not_found_result() -> None:
    _, match_service, panda, _ = fixture_services()
    unknown = CompetitionRef(value="competition:" + "f" * 24)

    result = asyncio.run(match_service.search(competition=unknown))

    assert result.status == "not_found"
    assert result.candidate_count == 0
    assert result.candidates == []
    assert "not known" in result.provenance.warnings[0]
    assert panda.get_calls == []


def test_match_search_orders_recent_candidates_and_keeps_ambiguity() -> None:
    _, match_service, _, _ = fixture_services()
    result = asyncio.run(
        match_service.search(
            teams=["Nigma Galaxy", "OG"],
            time_scope="recent",
            limit=10,
        )
    )
    assert result.status == "ambiguous"
    assert result.candidate_count == 2
    assert result.candidates[0].scheduled_at > result.candidates[1].scheduled_at
    assert result.candidates[0].teams[0].name == "Nigma Galaxy"


def test_match_service_detail_resolves_and_normalizes_opendota_detail() -> None:
    _, match_service, panda, opendota = fixture_services()
    result = asyncio.run(match_service.search(query="Round 2", time_scope="recent"))
    detail = asyncio.run(match_service.get_detail(match_ref=result.candidates[0].ref))

    assert result.status == "unique"
    assert detail.status == "available"
    assert detail.resolution.status == "resolved"
    assert detail.provenance.identity_status == "inferred_cross_source"
    assert detail.games[0].detail_status == "available"
    assert detail.games[0].scoreboard[0].kills == 8
    assert panda.get_calls == [30001]
    assert opendota.detail_calls == [40001]
    serialized = detail.model_dump_json()
    for forbidden in (
        "pandascore_id",
        "opendota_id",
        "league_id",
        "hero_id",
        "raw_response",
        "provider_payload",
    ):
        assert forbidden not in serialized
    assert "30001" not in serialized
    assert "40001" not in serialized


def test_match_detail_uses_cached_series_facts_after_pandascore_404() -> None:
    _, match_service, _, _ = fixture_services(pandascore_detail_available=False)
    result = asyncio.run(match_service.search(query="Round 2", time_scope="recent"))

    detail = asyncio.run(match_service.get_detail(match_ref=result.candidates[0].ref))

    assert detail.status == "available"
    assert detail.resolution.status == "resolved"
    assert detail.match is not None
    assert "PandaScore match detail is unavailable" in " ".join(detail.provenance.warnings)
    assert "cached PandaScore series facts" in " ".join(detail.provenance.warnings)


def test_match_detail_preserves_series_facts_when_opendota_detail_is_unavailable() -> None:
    _, match_service, _, opendota = fixture_services(detail_available=False)
    result = asyncio.run(match_service.search(query="Round 2", time_scope="recent"))
    detail = asyncio.run(match_service.get_detail(match_ref=result.candidates[0].ref))

    assert detail.status == "detail_unavailable"
    assert detail.match is not None
    assert detail.resolution.status == "resolved"
    assert "PandaScore series facts remain available" in " ".join(detail.provenance.warnings)
    assert opendota.detail_calls == [40001]


def test_match_detail_returns_explicit_boundary_when_opendota_resolution_fails() -> None:
    _, match_service, _, _ = fixture_services(resolution_available=False)
    result = asyncio.run(match_service.search(query="Round 2", time_scope="recent"))

    detail = asyncio.run(match_service.get_detail(match_ref=result.candidates[0].ref))

    assert detail.status == "detail_unavailable"
    assert detail.match is not None
    assert detail.resolution.status == "insufficient_signals"
    assert detail.provenance.sources == ["pandascore"]
    assert "OpenDota provider data was unavailable" in " ".join(detail.provenance.warnings)


def test_resolution_unique_mapping() -> None:
    result = _resolve()
    assert result.status == "resolved"
    assert result.resolved_provider_match_id == 40001
    assert result.candidate_count == 1
    assert "winner_consistency" in result.signals


def test_resolution_rejects_missing_or_ambiguous_leagues_and_teams() -> None:
    service = MatchResolutionService()
    fixture = _fixture()
    teams = _teams()
    matches = {9001: [_league_match()]}

    assert service.resolve(fixture, [], teams, matches).status == "league_not_found"
    assert (
        service.resolve(
            fixture,
            [
                LeagueSignal(9001, "The International 2026"),
                LeagueSignal(9002, "The International 2026"),
            ],
            teams,
            matches,
        ).status
        == "ambiguous_league"
    )
    assert (
        service.resolve(fixture, [LeagueSignal(9001, "The International 2026")], {}, matches).status
        == "team_not_found"
    )
    ambiguous_teams = {
        "alpha": [TeamSignal(101, "Alpha"), TeamSignal(103, "Alpha")],
        "beta": [TeamSignal(102, "Beta")],
    }
    ambiguous_matches = {
        9001: [
            _league_match(radiant=101, dire=102),
            _league_match(provider_id=40002, radiant=103, dire=102),
        ]
    }
    assert (
        service.resolve(
            fixture,
            [LeagueSignal(9001, "The International 2026")],
            ambiguous_teams,
            ambiguous_matches,
        ).status
        == "ambiguous_team"
    )


def test_resolution_rejects_insufficient_signals_and_wrong_team_pair() -> None:
    service = MatchResolutionService()
    fixture = _fixture()
    assert (
        service.resolve(
            fixture.__class__(
                provider_id=1,
                competition_name=fixture.competition_name,
                competition_year=None,
                teams=fixture.teams,
                start_time=fixture.start_time,
                duration_seconds=fixture.duration_seconds,
                winner_team_id=fixture.winner_team_id,
            ),
            [LeagueSignal(9001, "The International 2026")],
            _teams(),
            {9001: [_league_match()]},
        ).status
        == "insufficient_signals"
    )
    missing_time = _fixture(start_time=None)
    assert (
        service.resolve(
            missing_time,
            [LeagueSignal(9001, "The International 2026")],
            _teams(),
            {9001: [_league_match()]},
        ).status
        == "insufficient_signals"
    )
    wrong_pair = service.resolve(
        fixture,
        [LeagueSignal(9001, "The International 2026")],
        _teams(),
        {9001: [_league_match(radiant=101, dire=104)]},
    )
    assert wrong_pair.status == "not_found"


def test_resolution_rejects_time_duration_and_winner_mismatches() -> None:
    service = MatchResolutionService()
    leagues = [LeagueSignal(9001, "The International 2026")]
    teams = _teams()
    assert (
        service.resolve(_fixture(), leagues, teams, {9001: [_league_match(start=4000)]}).status
        == "not_found"
    )
    assert (
        service.resolve(_fixture(), leagues, teams, {9001: [_league_match(duration=200)]}).status
        == "not_found"
    )
    assert (
        service.resolve(_fixture(winner=12), leagues, teams, {9001: [_league_match()]}).status
        == "not_found"
    )


def test_two_credible_candidates_remain_ambiguous_instead_of_nearest_fallback() -> None:
    candidates = [
        _league_match(provider_id=40001, start=1000),
        _league_match(provider_id=40002, start=1001),
    ]
    result = MatchResolutionService().resolve(
        _fixture(),
        [LeagueSignal(9001, "The International 2026")],
        _teams(),
        {9001: candidates},
    )
    assert result.status == "ambiguous_match"
    assert result.candidate_count == 2
    assert result.resolved_provider_match_id is None


def test_resolution_does_not_ignore_an_incomplete_credible_candidate() -> None:
    candidates = [
        _league_match(provider_id=40001),
        _league_match(provider_id=40002, start=None),
    ]

    result = MatchResolutionService().resolve(
        _fixture(),
        [LeagueSignal(9001, "The International 2026")],
        _teams(),
        {9001: candidates},
    )

    assert result.status == "insufficient_signals"
    assert result.candidate_count == 2
    assert result.resolved_provider_match_id is None
    assert len(result.candidate_evidence) == 1


def test_resolution_requires_winner_signal_when_fixture_has_a_winner() -> None:
    result = MatchResolutionService().resolve(
        _fixture(),
        [LeagueSignal(9001, "The International 2026")],
        _teams(),
        {9001: [_league_match(radiant_win=None)]},
    )

    assert result.status == "insufficient_signals"
    assert result.resolved_provider_match_id is None


def _resolve():
    return MatchResolutionService().resolve(
        _fixture(),
        [LeagueSignal(9001, "The International 2026")],
        _teams(),
        {9001: [_league_match()]},
    )


def _fixture(
    *,
    start_time: int | None = 1000,
    duration: int | None = 100,
    winner: int | None = 11,
) -> MatchSignal:
    return MatchSignal(
        provider_id=1,
        competition_name="The International 2026",
        competition_year=2026,
        teams=(
            TeamSignal(11, "Alpha", fixture_id=11),
            TeamSignal(12, "Beta", fixture_id=12),
        ),
        start_time=start_time,
        duration_seconds=duration,
        winner_team_id=winner,
    )


def _teams():
    return {
        "alpha": [TeamSignal(101, "Alpha")],
        "beta": [TeamSignal(102, "Beta")],
    }


def _league_match(
    *,
    provider_id: int = 40001,
    start: int | None = 1000,
    duration: int | None = 100,
    radiant: int | None = 101,
    dire: int | None = 102,
    radiant_win: bool | None = True,
) -> LeagueMatchSignal:
    return LeagueMatchSignal(
        provider_id=provider_id,
        league_id=9001,
        start_time=start,
        duration_seconds=duration,
        radiant_team_id=radiant,
        dire_team_id=dire,
        radiant_win=radiant_win,
    )
