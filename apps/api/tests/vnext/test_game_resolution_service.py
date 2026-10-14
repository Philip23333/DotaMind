from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from functools import wraps
from typing import Any

import pytest
from pydantic import ValidationError

from app.vnext.capabilities.esports.game_resolution import (
    EsportsGameResolutionResult,
    GameResolutionContractError,
    GameResolutionService,
)
from app.vnext.capabilities.game.detail import GameDetailInput, GameDetailResult
from app.vnext.providers.match_resolution import (
    GameResolutionReadAttempt,
    GameResolutionReadPolicy,
    LeagueCandidateResult,
    LeagueSearchDiagnostic,
    MultiLeagueGameResolutionResult,
    PandaScoreOpenDotaGameResolutionProvider,
    ResolutionBudgetExceeded,
    TargetGameCheck,
    find_league_candidates,
    resolve_game_across_leagues,
)
from app.vnext.tools.errors import StructuredToolError

_MATCH_ID = 1_709_131
_GAME_POSITION = 4
_PANDASCORE_GAME_ID = 739_826
_VALVE_GAME_ID = 9_040_578_015
_START_TIME = 1_791_743_534
_RETRIEVED_AT = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)


def _async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def _context(*, games: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": _MATCH_ID,
        "league": {"name": "BLAST SLAM", "unmodeled": {"keep": 0}},
        "serie": {"name": "Season 8", "season": "8", "year": 2026},
        "opponents": [
            {"opponent": {"id": 137_073, "name": "Team Yandex"}},
            {"opponent": {"id": 1669, "name": "Team Spirit"}},
        ],
        "games": games
        if games is not None
        else [
            {
                "id": _PANDASCORE_GAME_ID,
                "position": _GAME_POSITION,
                "begin_at": "2026-10-11T18:33:41Z",
                "length": 3400,
                "winner": {"id": 137_073, "type": "Team"},
                "winner_id": 137_073,
                "winner_type": "Team",
                "unmodeled_game_fact": [0, False, None],
            }
        ],
        "unmodeled_match_fact": {"ordered": ["first", "second"]},
    }


def _league(league_id: int = 19_102) -> dict[str, Any]:
    return {
        "leagueid": league_id,
        "name": "BLAST SLAM VIII",
        "extension": {"keep": True},
    }


def _league_row() -> dict[str, Any]:
    return {
        "match_id": _VALVE_GAME_ID,
        "start_time": _START_TIME,
        "duration": 3400,
        "leagueid": 19_102,
        "series_id": 1_153_562,
        "zero": 0,
        "false": False,
        "null": None,
        "ordered": ["one", "two"],
    }


def _detail() -> GameDetailResult:
    return GameDetailResult(
        valve_game_id=_VALVE_GAME_ID,
        provider="opendota",
        retrieved_at=_RETRIEVED_AT,
        data={
            "match_id": _VALVE_GAME_ID,
            "start_time": _START_TIME,
            "duration": 3400,
            "radiant_team": {"team_id": 9_823_272, "name": "Team Yandex"},
            "dire_team": {"team_id": 7_119_388, "name": "Team Spirit"},
            "radiant_win": True,
            "extension": {"zero": 0, "false": False, "null": None},
        },
    )


def _policy() -> GameResolutionReadPolicy:
    return GameResolutionReadPolicy(
        start_time_tolerance_seconds=180,
        duration_tolerance_seconds=5,
        max_leagues=10,
        max_candidate_details=10,
        max_requests=30,
    )


def _base_attempt(
    *,
    stage: str = "resolution",
    category: str = "resolved",
    reason: str | None = None,
    match_context: dict[str, Any] | None = None,
    league_result: LeagueCandidateResult | None = None,
    target_check: TargetGameCheck | None = None,
    resolution_result: MultiLeagueGameResolutionResult | None = None,
    league_reads: tuple[dict[str, Any], ...] | None = None,
    league_rows: dict[int, tuple[dict[str, Any], ...]] | None = None,
    details: dict[int, GameDetailResult] | None = None,
) -> GameResolutionReadAttempt:
    context = _context() if match_context is None and stage != "match_context" else match_context
    if target_check is None and stage not in {"match_context"}:
        if stage == "target_game":
            target_check = TargetGameCheck(category, _GAME_POSITION, None, reason)
        else:
            target_check = TargetGameCheck(
                "ready",
                _GAME_POSITION,
                context["games"][0],  # type: ignore[index]
                None,
            )

    if league_result is None and stage in {"league_candidates", "resolution"}:
        if stage == "league_candidates":
            league_result = LeagueCandidateResult(category, (), 0, reason)
        else:
            league_result = find_league_candidates(
                context, [_league()], max_candidates=10  # type: ignore[arg-type]
            )

    if resolution_result is None and stage == "resolution":
        mapped_reason = None if category == "resolved" else (reason or category)
        result_category = category
        resolution_result = MultiLeagueGameResolutionResult(
            category=result_category,  # type: ignore[arg-type]
            pandascore_match_id=_MATCH_ID,
            pandascore_game_id=_PANDASCORE_GAME_ID,
            game_position=_GAME_POSITION,
            searched_league_ids=(19_102,),
            missing_league_ids=(),
            valve_game_id=_VALVE_GAME_ID if category == "resolved" else None,
            method="inferred_cross_source" if category == "resolved" else None,
            candidate_assessments=(),
            league_search_diagnostics=(LeagueSearchDiagnostic(19_102, 0),),
            reason=mapped_reason,
        )
        reason = mapped_reason

    return GameResolutionReadAttempt(
        match_id=_MATCH_ID,
        game_position=_GAME_POSITION,
        stage=stage,  # type: ignore[arg-type]
        target_game_result=target_check,
        league_candidate_result=league_result,
        resolution_result=resolution_result,
        reason=reason,
        requests_started=4 if stage == "resolution" else 1,
        retrieved_at=_RETRIEVED_AT,
        pandascore_match_context=context,
        opendota_leagues=league_reads,
        league_matches_by_id=league_rows or {},
        candidate_details=details or {},
    )


class _FakeProvider:
    def __init__(self, result: object | BaseException) -> None:
        self.result = result
        self.calls: list[tuple[Any, ...]] = []

    async def resolve(self, match_id, game_position, *, policy, confirmed_mappings):
        self.calls.append((match_id, game_position, policy, confirmed_mappings))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _service(provider: Any) -> GameResolutionService:
    return GameResolutionService(provider, policy=_policy())


def _resolver_attempt(category: str = "resolved") -> GameResolutionReadAttempt:
    context = _context()
    leagues = (_league(),)
    row = _league_row()
    detail = _detail()
    if category == "resolved":
        outcome = resolve_game_across_leagues(
            context,
            _GAME_POSITION,
            [19_102],
            {19_102: [row]},
            {_VALVE_GAME_ID: detail.data},
            start_time_tolerance_seconds=180,
            duration_tolerance_seconds=5,
            confirmed_mappings={},
        )
    else:
        outcome = MultiLeagueGameResolutionResult(
            category=category,  # type: ignore[arg-type]
            pandascore_match_id=_MATCH_ID,
            pandascore_game_id=_PANDASCORE_GAME_ID,
            game_position=_GAME_POSITION,
            searched_league_ids=(19_102,),
            missing_league_ids=(),
            valve_game_id=None,
            method=None,
            candidate_assessments=(),
            league_search_diagnostics=(LeagueSearchDiagnostic(19_102, 0),),
            reason=category,
        )
    return _base_attempt(
        reason=outcome.reason,
        resolution_result=outcome,
        league_reads=leagues,
        league_rows={19_102: (row,)},
        details={_VALVE_GAME_ID: detail},
    )


@_async_test
async def test_service_calls_provider_once_with_original_request_objects() -> None:
    attempt = _resolver_attempt()
    provider = _FakeProvider(attempt)
    policy = _policy()
    mappings = {739_827: _VALVE_GAME_ID + 1}
    service = GameResolutionService(provider, policy=policy)  # type: ignore[arg-type]

    result = await service.resolve(
        _MATCH_ID, _GAME_POSITION, confirmed_mappings=mappings
    )

    assert len(provider.calls) == 1
    match_id, position, passed_policy, passed_mappings = provider.calls[0]
    assert (match_id, position) == (_MATCH_ID, _GAME_POSITION)
    assert passed_policy is policy
    assert passed_mappings is mappings
    assert result.status == "resolved"


@pytest.mark.parametrize(
    ("target_category", "target_reason", "expected_reason"),
    [
        ("target_game_not_found", "selected_position_absent", "target_game_not_found"),
        ("ambiguous_target_game", "position_repeated", "ambiguous_target_game"),
        ("target_not_ready", "game_not_started", "target_not_ready"),
        ("insufficient_signals", "game_time_missing", "insufficient_signals"),
    ],
)
@_async_test
async def test_service_preserves_each_target_failure_category(
    target_category: str, target_reason: str, expected_reason: str
) -> None:
    attempt = _base_attempt(
        stage="target_game",
        category=target_category,
        reason=target_reason,
        target_check=TargetGameCheck(
            target_category, _GAME_POSITION, None, target_reason  # type: ignore[arg-type]
        ),
    )
    result = await _service(_FakeProvider(attempt)).resolve(
        _MATCH_ID, _GAME_POSITION, confirmed_mappings={}
    )

    assert result.status == "unresolved"
    assert result.reason == expected_reason
    assert result.providers == ["pandascore"]


@pytest.mark.parametrize(
    ("attempt", "expected_reason", "expected_providers"),
    [
        (
            _base_attempt(stage="match_context", reason="match_not_found"),
            "match_not_found",
            ["pandascore"],
        ),
        (
            _base_attempt(
                stage="league_candidates",
                category="insufficient_context",
                reason="competition_name_missing",
                league_result=LeagueCandidateResult(
                    "insufficient_context", (), 0, "competition_name_missing"
                ),
                league_reads=(),
            ),
            "insufficient_context",
            ["pandascore", "opendota"],
        ),
        (
            _base_attempt(
                stage="league_candidates",
                category="no_candidates",
                reason="no_league_matches",
                league_result=LeagueCandidateResult(
                    "no_candidates", (), 0, "no_league_matches"
                ),
                league_reads=(),
            ),
            "no_league_candidates",
            ["pandascore", "opendota"],
        ),
    ],
)
@_async_test
async def test_service_maps_source_stop_reasons_and_actual_sources(
    attempt: GameResolutionReadAttempt,
    expected_reason: str,
    expected_providers: list[str],
) -> None:
    result = await _service(_FakeProvider(attempt)).resolve(
        _MATCH_ID, _GAME_POSITION, confirmed_mappings={}
    )

    assert result.status == "unresolved"
    assert result.reason == expected_reason
    assert result.valve_game_id is None
    assert result.providers == expected_providers


@pytest.mark.parametrize(
    "category",
    [
        "ambiguous",
        "evidence_insufficient",
        "mapping_conflict",
        "no_acceptable_candidate",
        "no_candidates",
        "search_scope_incomplete",
    ],
)
@_async_test
async def test_service_preserves_resolver_outcome_without_confirming_unresolved_ids(
    category: str,
) -> None:
    attempt = _resolver_attempt(category)
    result = await _service(_FakeProvider(attempt)).resolve(
        _MATCH_ID, _GAME_POSITION, confirmed_mappings={}
    )

    assert result.status == "unresolved"
    assert result.reason == category
    assert result.valve_game_id is None
    assert result.method is None


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("operation", "candidate_details"),
        ("limit_name", "max_requests"),
        ("limit", 30),
        ("required", 2),
        ("remaining", 1),
        ("requests_started", 4),
    ],
)
@_async_test
async def test_budget_exhaustion_becomes_stable_tool_execution_error(
    field: str, expected: Any
) -> None:
    budget_error = ResolutionBudgetExceeded(
        operation="candidate_details",
        limit_name="max_requests",
        limit=30,
        required=2,
        remaining=1,
        requests_started=4,
    )
    service = _service(_FakeProvider(budget_error))

    with pytest.raises(StructuredToolError) as raised:
        await service.resolve(_MATCH_ID, _GAME_POSITION, confirmed_mappings={})

    error = raised.value
    assert error.code == "tool_execution_error"
    assert error.args[0] == "Game resolution read budget was exhausted"
    assert error.details["category"] == "budget_exhausted"
    assert error.details[field] == expected


@pytest.mark.parametrize(
    "provider_error",
    [
        StructuredToolError("provider_timeout", "timeout", {"provider": "opendota"}),
        asyncio.CancelledError(),
    ],
)
@_async_test
async def test_provider_errors_and_cancellation_propagate_unchanged(
    provider_error: BaseException,
) -> None:
    with pytest.raises(type(provider_error)) as raised:
        await _service(_FakeProvider(provider_error)).resolve(
            _MATCH_ID, _GAME_POSITION, confirmed_mappings={}
        )

    assert raised.value is provider_error


@pytest.mark.parametrize(
    ("match_id", "position"),
    [(_MATCH_ID + 1, _GAME_POSITION), (_MATCH_ID, _GAME_POSITION + 1)],
)
@_async_test
async def test_provider_attempt_identity_must_match_request(match_id: int, position: int) -> None:
    attempt = _resolver_attempt()
    attempt = replace(attempt, match_id=match_id, game_position=position)
    with pytest.raises(GameResolutionContractError, match="identity"):
        await _service(_FakeProvider(attempt)).resolve(
            _MATCH_ID, _GAME_POSITION, confirmed_mappings={}
        )


@pytest.mark.parametrize(
    "attempt",
    [
        GameResolutionReadAttempt(
            match_id=_MATCH_ID,
            game_position=_GAME_POSITION,
            stage="resolution",
            target_game_result=None,
            league_candidate_result=None,
            resolution_result=None,
            reason=None,
            requests_started=1,
            retrieved_at=_RETRIEVED_AT,
            pandascore_match_context=None,
            opendota_leagues=None,
            league_matches_by_id={},
            candidate_details={},
        ),
    ],
)
@_async_test
async def test_incomplete_attempt_is_a_contract_error(attempt: GameResolutionReadAttempt) -> None:
    with pytest.raises(GameResolutionContractError):
        await _service(_FakeProvider(attempt)).resolve(
            _MATCH_ID, _GAME_POSITION, confirmed_mappings={}
        )


@pytest.mark.parametrize(
    "corruption",
    ["unknown_stage", "unknown_category", "resolved_without_assessment"],
)
@_async_test
async def test_unknown_or_internally_incomplete_resolution_is_a_contract_error(
    corruption: str,
) -> None:
    attempt = _resolver_attempt()
    if corruption == "unknown_stage":
        attempt = replace(attempt, stage="unrecognized")
    else:
        assert attempt.resolution_result is not None
        if corruption == "unknown_category":
            invalid_result = replace(attempt.resolution_result, category="unrecognized")
        else:
            invalid_result = replace(attempt.resolution_result, candidate_assessments=())
        attempt = replace(attempt, resolution_result=invalid_result)

    with pytest.raises(GameResolutionContractError):
        await _service(_FakeProvider(attempt)).resolve(
            _MATCH_ID, _GAME_POSITION, confirmed_mappings={}
        )


@_async_test
async def test_complete_attempt_serialization_preserves_facts_without_mutation() -> None:
    attempt = _resolver_attempt()
    context = attempt.pandascore_match_context
    league = attempt.opendota_leagues[0]  # type: ignore[index]
    row = attempt.league_matches_by_id[19_102][0]
    detail = attempt.candidate_details[_VALVE_GAME_ID]
    mappings = {}
    before = deepcopy((context, league, row, detail, mappings))
    provider = _FakeProvider(attempt)

    result = await _service(provider).resolve(
        _MATCH_ID, _GAME_POSITION, confirmed_mappings=mappings
    )

    assert (context, league, row, detail, mappings) == before
    assert result.providers == ["pandascore", "opendota"]
    assert result.retrieved_at == _RETRIEVED_AT
    assert result.data["pandascore_match_context"]["unmodeled_match_fact"] == {
        "ordered": ["first", "second"]
    }
    assert result.data["pandascore_match_context"]["games"][0]["unmodeled_game_fact"] == [
        0,
        False,
        None,
    ]
    assert result.data["opendota_leagues"][0]["extension"] == {"keep": True}
    assert result.data["league_matches_by_id"]["19102"][0] == {
        **row,
    }
    detail_json = result.data["candidate_details"][str(_VALVE_GAME_ID)]
    assert detail_json["provider"] == "opendota"
    assert detail_json["retrieved_at"] == _RETRIEVED_AT.isoformat().replace("+00:00", "Z")
    assert detail_json["data"]["extension"] == {"zero": 0, "false": False, "null": None}
    assert result.data["requests_started"] == 4


def test_result_contract_rejects_coercion_unknown_fields_and_inconsistent_status() -> None:
    base = {
        "status": "resolved",
        "game_position": _GAME_POSITION,
        "valve_game_id": _VALVE_GAME_ID,
        "method": "inferred_cross_source",
        "reason": None,
        "providers": ["pandascore", "opendota"],
        "retrieved_at": _RETRIEVED_AT,
        "data": {},
    }
    assert EsportsGameResolutionResult(**base).status == "resolved"

    invalid_documents = [
        {**base, "game_position": True},
        {**base, "valve_game_id": 1.0},
        {**base, "providers": ["pandascore", "pandascore"]},
        {**base, "unexpected": "not allowed"},
        {**base, "match_id": _MATCH_ID},
        {**base, "retrieved_at": datetime(2026, 10, 14)},
        {**base, "status": "unresolved"},
        {**base, "valve_game_id": None},
        {**base, "reason": "made_up_reason"},
    ]
    for document in invalid_documents:
        with pytest.raises(ValidationError):
            EsportsGameResolutionResult(**document)


class _FakePandaScore:
    async def get_match_context(self, match_id: int) -> dict[str, Any]:
        assert match_id == _MATCH_ID
        return _context()


class _FakeDiscovery:
    async def get_leagues(self) -> list[dict[str, Any]]:
        return [_league()]

    async def get_league_matches(self, league_id: int) -> list[dict[str, Any]]:
        assert league_id == 19_102
        return [_league_row()]


class _FakeGameDetail:
    async def get_game_detail(self, query: GameDetailInput) -> GameDetailResult:
        assert query.valve_game_id == _VALVE_GAME_ID
        return _detail()


@_async_test
async def test_blast_game_four_resolves_through_actual_bounded_read_flow() -> None:
    provider = PandaScoreOpenDotaGameResolutionProvider(
        _FakePandaScore(),  # type: ignore[arg-type]
        _FakeDiscovery(),  # type: ignore[arg-type]
        _FakeGameDetail(),  # type: ignore[arg-type]
    )
    service = GameResolutionService(provider, policy=_policy())

    result = await service.resolve(
        _MATCH_ID, _GAME_POSITION, confirmed_mappings={}
    )

    assert result.status == "resolved"
    assert result.valve_game_id == _VALVE_GAME_ID
    assert result.reason is None
    assert result.providers == ["pandascore", "opendota"]
    assert result.data["resolution_result"]["category"] == "resolved"
