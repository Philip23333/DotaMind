from __future__ import annotations

import asyncio

from app.vnext.domain.common.models import CompetitionRef
from app.vnext.domain.competitions.service import competition_display_name
from app.vnext.domain.matches.normalization import normalize_panda_match
from app.vnext.domain.matches.resolution import (
    LeagueMatchSignal,
    LeagueSignal,
    MatchResolutionService,
    MatchSignal,
    TeamSignal,
)
from app.vnext.providers.pandascore.models import PandaScoreMatch, PandaScoreSeries
from tests.vnext.phase2_support import FETCHED_AT, fixture_services, load_fixture


def test_competition_search_normalizes_year_deduplicates_and_preserves_provenance() -> None:
    competition_service, _, _, _ = fixture_services()

    exact = asyncio.run(competition_service.search("  The   International 2026 ", year=2026))
    ambiguous = asyncio.run(competition_service.search("The International"))
    missing = asyncio.run(competition_service.search("No such event"))

    assert exact.status == "unique"
    assert exact.candidate_count == 1
    assert exact.candidates[0].name == "The International 2026"
    assert exact.candidates[0].year == 2026
    assert exact.provenance.sources == ["pandascore"]
    assert exact.provenance.freshness.fetched_at == FETCHED_AT
    assert ambiguous.status == "ambiguous"
    assert ambiguous.candidate_count == 2
    assert missing.status == "not_found"
    assert missing.candidates == []


def test_competition_display_identity_composes_league_year_and_qualifier() -> None:
    competition_service, _, panda, _ = fixture_services()
    panda.direct_series = [
        PandaScoreSeries.model_validate(
            {
                "id": 21001,
                "name": "2026",
                "full_name": "2026",
                "year": 2026,
                "league": {"id": 551, "name": "Example League"},
            }
        ),
        PandaScoreSeries.model_validate(
            {
                "id": 21002,
                "name": "China Closed Qualifier",
                "full_name": "China Closed Qualifier 2026",
                "year": 2026,
                "league": {"id": 551, "name": "Example League"},
            }
        ),
    ]
    panda.league_series = panda.direct_series

    result = asyncio.run(competition_service.search("Example League", year=2026))

    names = {candidate.name for candidate in result.candidates}
    assert names == {
        "Example League 2026",
        "Example League 2026 — China Closed Qualifier",
    }
    assert (
        competition_display_name(
            league_name="Example League",
            series_name="Example League 2026",
            series_full_name="Example League 2026",
            year=2026,
        )
        == "Example League 2026"
    )
    assert (
        competition_display_name(
            league_name=None,
            series_name="Standalone Championship 2026",
            series_full_name="Standalone Championship 2026",
            year=2026,
        )
        == "Standalone Championship 2026"
    )


def test_competition_schedule_truncated_uses_provider_pagination_even_after_local_filter() -> None:
    competition_service, _, panda, _ = fixture_services()
    found = asyncio.run(competition_service.search("The International 2026", year=2026))
    panda.list_matches_has_more = True

    result = asyncio.run(
        competition_service.list_matches(
            found.candidates[0].ref,
            time_scope="recent",
            status="finished",
            limit=10,
        )
    )

    assert result.candidate_count == 2
    assert result.truncated is True


def test_unknown_competition_schedule_is_not_truncated() -> None:
    competition_service, _, _, _ = fixture_services()
    unknown = CompetitionRef(value="competition:" + "f" * 24)

    result = asyncio.run(competition_service.list_matches(unknown))

    assert result.status == "not_found"
    assert result.truncated is False


def test_competition_search_uses_league_route_when_direct_series_is_empty() -> None:
    competition_service, _, panda, _ = fixture_services()
    panda.direct_series = []
    panda.league_series = [panda.series[0]]

    result = asyncio.run(competition_service.search("The International", year=2026))

    assert result.status == "unique"
    assert result.candidate_count == 1
    assert result.candidates[0].year == 2026
    assert panda.league_search_calls == [{"query": "The International", "limit": 10}]
    assert panda.league_series_calls == [{"league_id": 501, "year": 2026, "limit": 10}]


def test_competition_search_deduplicates_direct_and_league_series_by_provider_id() -> None:
    competition_service, _, panda, _ = fixture_services()

    result = asyncio.run(competition_service.search("The International", year=2026))

    assert result.status == "unique"
    assert result.candidate_count == 1
    assert result.candidates[0].year == 2026
    assert len(panda.league_series_calls) == 1


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
    assert schedule.truncated is False
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


def test_team_search_discovers_pair_on_second_page() -> None:
    _, match_service, panda, _ = fixture_services()
    panda.team_match_pages[70001] = [[panda.matches[-1]], [panda.matches[0]]]

    result = asyncio.run(
        match_service.search(
            teams=["Nigma Galaxy", "OG"],
            query="Nigma Galaxy vs OG",
            time_scope="recent",
            limit=1,
        )
    )

    assert result.status == "unique"
    assert result.candidate_count == 1
    assert result.candidates[0].name == "Round 2: NGX vs OG"
    assert [call["query"] for call in panda.team_search_calls] == ["Nigma Galaxy", "OG"]
    assert [call["page_number"] for call in panda.team_match_calls] == [1, 2]
    assert all(call["query"] is None for call in panda.team_match_calls)


def test_single_team_recent_search_uses_team_route_and_filters_time_scope() -> None:
    _, match_service, panda, _ = fixture_services()

    result = asyncio.run(
        match_service.search(
            teams=["Nigma Galaxy"],
            time_scope="recent",
            limit=10,
        )
    )

    assert result.status == "ambiguous"
    assert result.candidate_count == 2
    assert all(candidate.status == "finished" for candidate in result.candidates)
    assert panda.list_calls == []
    assert len(panda.team_match_calls) == 1


def test_team_search_stops_at_page_bound_and_discloses_truncation() -> None:
    _, match_service, panda, _ = fixture_services()
    panda.team_match_pages[70001] = [[panda.matches[0]] for _ in range(6)]

    result = asyncio.run(
        match_service.search(
            teams=["Nigma Galaxy", "OG"],
            time_scope="recent",
            limit=10,
        )
    )

    assert result.status == "unique"
    assert result.candidate_count == 1
    assert len(panda.team_match_calls) == 5
    warning_text = " ".join(result.provenance.warnings)
    assert "bounded" in warning_text
    assert "truncated" in warning_text


def test_team_search_result_does_not_serialize_provider_team_ids() -> None:
    _, match_service, panda, _ = fixture_services()

    result = asyncio.run(
        match_service.search(
            teams=["Team Alpha", "Team Beta"],
            time_scope="recent",
            limit=1,
        )
    )
    serialized = result.model_dump_json()

    assert result.status == "unique"
    assert "70010" not in serialized
    assert "70011" not in serialized
    assert panda.team_search_calls


def test_match_service_detail_resolves_and_normalizes_opendota_detail() -> None:
    _, match_service, panda, opendota = fixture_services()
    result = asyncio.run(match_service.search(query="Round 2", time_scope="recent"))
    detail = asyncio.run(match_service.get_detail(match_ref=result.candidates[0].ref))

    assert result.status == "unique"
    assert detail.status == "available"
    assert detail.games[0].resolution is not None
    assert detail.games[0].resolution.status == "resolved"
    assert detail.games[0].valve_match_id == 40001
    assert detail.games[1].resolution is not None
    assert detail.games[1].resolution.status == "insufficient_signals"
    assert detail.provenance.identity_status == "inferred_cross_source"
    assert detail.games[0].detail_status == "available"
    assert detail.games[0].scoreboard[0].kills == 8
    assert panda.get_calls == []
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
    assert "40001" in serialized


def test_match_detail_uses_cached_series_facts_without_pandascore_detail() -> None:
    _, match_service, panda, _ = fixture_services(pandascore_detail_available=False)
    result = asyncio.run(match_service.search(query="Round 2", time_scope="recent"))

    detail = asyncio.run(match_service.get_detail(match_ref=result.candidates[0].ref))

    assert detail.status == "available"
    assert detail.games[0].resolution is not None
    assert detail.games[0].resolution.status == "resolved"
    assert detail.match is not None
    assert panda.get_calls == []


def test_competition_list_caches_fixture_for_match_detail_without_pandascore_detail() -> None:
    competition_service, match_service, panda, opendota = fixture_services()
    found = asyncio.run(competition_service.search("The International 2026", year=2026))

    schedule = asyncio.run(
        competition_service.list_matches(
            found.candidates[0].ref,
            time_scope="recent",
            limit=1,
        )
    )
    detail = asyncio.run(match_service.get_detail(match_ref=schedule.matches[0].ref))

    assert schedule.status == "ok"
    assert schedule.matches[0].ref == detail.match.ref  # type: ignore[union-attr]
    assert detail.status == "available"
    assert panda.list_calls[-1]["series_id"] == 20001
    assert panda.get_calls == []
    assert opendota.detail_calls == [40001]


def test_match_detail_preserves_series_facts_when_opendota_detail_is_unavailable() -> None:
    _, match_service, _, opendota = fixture_services(detail_available=False)
    result = asyncio.run(match_service.search(query="Round 2", time_scope="recent"))
    detail = asyncio.run(match_service.get_detail(match_ref=result.candidates[0].ref))

    assert detail.status == "detail_unavailable"
    assert detail.match is not None
    assert detail.games[0].detail_status == "unavailable"
    assert detail.games[0].resolution is not None
    assert detail.games[0].resolution.status == "resolved"
    assert detail.games[1].detail_status == "fixture_only"
    assert detail.games[1].resolution is not None
    assert detail.games[1].resolution.status == "insufficient_signals"
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


def test_bo3_resolves_each_game_to_a_distinct_opendota_match() -> None:
    _, match_service, _, opendota = fixture_services()
    result = asyncio.run(match_service.search(query="Grand Final", time_scope="recent"))

    detail = asyncio.run(match_service.get_detail(match_ref=result.candidates[0].ref))

    assert result.status == "unique"
    assert detail.status == "available"
    assert [game.resolution.status for game in detail.games] == [
        "resolved",
        "resolved",
        "resolved",
    ]
    assert [game.detail_status for game in detail.games] == [
        "available",
        "available",
        "available",
    ]
    assert opendota.detail_calls == [40002, 40003, 40004]
    assert detail.resolution.status == "resolved"


def test_game_ref_roundtrip_resolves_only_the_selected_second_game() -> None:
    _, match_service, _, opendota = fixture_services()
    result = asyncio.run(match_service.search(query="Grand Final", time_scope="recent"))
    series = asyncio.run(match_service.get_detail(match_ref=result.candidates[0].ref))
    game_two_ref = next(game.ref for game in series.games if game.position == 2)
    opendota.detail_calls.clear()

    selected = asyncio.run(match_service.get_detail(game_ref=game_two_ref))

    assert selected.status == "available"
    assert len(selected.games) == 1
    assert selected.games[0].position == 2
    assert selected.games[0].resolution is not None
    assert selected.games[0].resolution.status == "resolved"
    assert selected.games[0].winner == series.match.teams[1].ref  # type: ignore[union-attr]
    assert opendota.detail_calls == [40003]


def test_game_time_missing_does_not_fallback_to_series_time() -> None:
    row = PandaScoreMatch.model_validate(load_fixture("pandascore", "match_30001.json"))
    normalized = normalize_panda_match(row, fetched_at=FETCHED_AT)

    assert normalized.games[1].start_time is None
    assert normalized.games[1].public.started_at is None

    _, match_service, _, _ = fixture_services()
    result = asyncio.run(match_service.search(query="Round 2", time_scope="recent"))
    detail = asyncio.run(match_service.get_detail(match_ref=result.candidates[0].ref))

    assert detail.games[1].resolution is not None
    assert detail.games[1].resolution.status == "insufficient_signals"


def test_game_winner_uses_game_fixture_not_series_winner() -> None:
    _, match_service, _, _ = fixture_services()
    result = asyncio.run(match_service.search(query="Grand Final", time_scope="recent"))
    detail = asyncio.run(match_service.get_detail(match_ref=result.candidates[0].ref))

    assert detail.match is not None
    assert detail.match.result is not None
    series_winner = detail.match.result.winner
    assert series_winner == detail.games[0].winner
    assert detail.games[1].winner != series_winner
    assert detail.games[1].winner == detail.match.teams[1].ref
    assert detail.games[2].winner == series_winner


def test_one_game_opendota_failure_keeps_other_games_and_series_facts() -> None:
    _, match_service, _, opendota = fixture_services(unavailable_detail_ids={40003})
    result = asyncio.run(match_service.search(query="Grand Final", time_scope="recent"))

    detail = asyncio.run(match_service.get_detail(match_ref=result.candidates[0].ref))

    assert detail.status == "available"
    assert detail.match is not None
    assert [game.detail_status for game in detail.games] == [
        "available",
        "unavailable",
        "available",
    ]
    assert [game.resolution.status for game in detail.games] == [
        "resolved",
        "resolved",
        "resolved",
    ]
    assert opendota.detail_calls == [40002, 40003, 40004]
    assert "PandaScore series facts remain available" in " ".join(detail.provenance.warnings)
