"""Coordinate bounded PandaScore and OpenDota reads for game resolution."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, TypeVar

from pydantic import JsonValue

from app.vnext.providers.opendota.discovery import OpenDotaDiscoveryAdapter
from app.vnext.providers.opendota.game_detail import OpenDotaGameDetailAdapter, OpenDotaGameRecord
from app.vnext.providers.pandascore.match_context import PandaScoreMatchContextAdapter
from app.vnext.tools.errors import StructuredToolError

from .candidates import GameCandidateResult, find_game_candidates
from .leagues import LeagueCandidateResult, find_league_candidates
from .resolver import MultiLeagueGameResolutionResult, resolve_game_across_leagues

_TARGET_PROBE_LEAGUE_ID = 1
_T = TypeVar("_T")

TargetGameCategory = Literal[
    "ready",
    "insufficient_signals",
    "target_game_not_found",
    "ambiguous_target_game",
    "target_not_ready",
]
ReadStage = Literal[
    "match_context",
    "target_game",
    "leagues",
    "league_candidates",
    "league_matches",
    "candidate_details",
    "resolution",
]


@dataclass(frozen=True, slots=True)
class GameResolutionReadPolicy:
    """Explicit per-call limits; no production defaults are assumed."""

    start_time_tolerance_seconds: int
    duration_tolerance_seconds: int
    max_leagues: int
    max_candidate_details: int
    max_requests: int
    max_concurrency: int = 4

    def __post_init__(self) -> None:
        for field_name in (
            "start_time_tolerance_seconds",
            "duration_tolerance_seconds",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        for field_name in (
            "max_leagues", "max_candidate_details", "max_requests", "max_concurrency",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")


class ResolutionBudgetExceeded(Exception):
    """A complete provider-read phase does not fit the supplied policy."""

    def __init__(
        self,
        *,
        operation: str,
        limit_name: str,
        limit: int,
        required: int,
        remaining: int | None,
        requests_started: int,
    ) -> None:
        self.operation = operation
        self.limit_name = limit_name
        self.limit = limit
        self.required = required
        self.remaining = remaining
        self.requests_started = requests_started
        super().__init__(f"{operation} exceeds {limit_name}")


@dataclass(frozen=True, slots=True)
class TargetGameCheck:
    """Selected Game readiness without pretending a League has been searched."""

    category: TargetGameCategory
    game_position: int
    target_game: Mapping[str, JsonValue] | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class GameResolutionReadAttempt:
    """One bounded read attempt with complete source records and offline results."""

    match_id: int
    game_position: int
    stage: ReadStage
    target_game_result: TargetGameCheck | None
    league_candidate_result: LeagueCandidateResult | None
    resolution_result: MultiLeagueGameResolutionResult | None
    reason: str | None
    requests_started: int
    retrieved_at: datetime
    pandascore_match_context: Mapping[str, JsonValue] | None
    opendota_leagues: tuple[Mapping[str, JsonValue], ...] | None
    league_matches_by_id: Mapping[int, tuple[Mapping[str, JsonValue], ...]]
    candidate_details: Mapping[int, OpenDotaGameRecord]


class PandaScoreOpenDotaGameResolutionProvider:
    """Read bounded source data, then delegate all identity decisions offline."""

    def __init__(
        self,
        pandascore_match_context: PandaScoreMatchContextAdapter,
        opendota_discovery: OpenDotaDiscoveryAdapter,
        opendota_game_detail: OpenDotaGameDetailAdapter,
    ) -> None:
        self._pandascore_match_context = pandascore_match_context
        self._opendota_discovery = opendota_discovery
        self._opendota_game_detail = opendota_game_detail

    async def resolve(
        self,
        match_id: int,
        game_position: int,
        *,
        policy: GameResolutionReadPolicy,
        confirmed_mappings: Mapping[int, int],
    ) -> GameResolutionReadAttempt:
        _validate_request(match_id, game_position, policy, confirmed_mappings)

        requests_started = 0
        match_context: Mapping[str, JsonValue] | None = None
        opendota_leagues: tuple[Mapping[str, JsonValue], ...] | None = None
        league_matches_by_id: dict[
            int, tuple[Mapping[str, JsonValue], ...]
        ] = {}
        candidate_details: dict[int, OpenDotaGameRecord] = {}
        target_game_result: TargetGameCheck | None = None
        league_candidate_result: LeagueCandidateResult | None = None
        resolution_result: MultiLeagueGameResolutionResult | None = None

        async def read(operation: str, call: Callable[[], Awaitable[_T]]) -> _T:
            nonlocal requests_started
            _require_request_budget(
                operation=operation,
                policy=policy,
                requests_started=requests_started,
                required=1,
            )
            requests_started += 1
            try:
                return await call()
            except StructuredToolError as error:
                details = dict(error.details)
                details.update(
                    {"operation": operation, "requests_started": requests_started}
                )
                raise StructuredToolError(error.code, str(error), details) from None

        def finish(
            *,
            stage: ReadStage,
            reason: str | None = None,
        ) -> GameResolutionReadAttempt:
            return GameResolutionReadAttempt(
                match_id=match_id,
                game_position=game_position,
                stage=stage,
                target_game_result=target_game_result,
                league_candidate_result=league_candidate_result,
                resolution_result=resolution_result,
                reason=reason,
                requests_started=requests_started,
                retrieved_at=datetime.now(UTC),
                pandascore_match_context=match_context,
                opendota_leagues=opendota_leagues,
                league_matches_by_id=dict(league_matches_by_id),
                candidate_details=dict(candidate_details),
            )

        match_context = await read(
            "match_context",
            lambda: self._pandascore_match_context.get_match_context(match_id),
        )
        if match_context is None:
            return finish(stage="match_context", reason="match_not_found")

        # The offline filter requires a positive League ID even for its empty
        # target-only probe. This internal placeholder is neither read nor
        # included in the attempt result.
        target_probe = find_game_candidates(
            match_context,
            game_position,
            _TARGET_PROBE_LEAGUE_ID,
            [],
            start_time_tolerance_seconds=policy.start_time_tolerance_seconds,
            duration_tolerance_seconds=policy.duration_tolerance_seconds,
        )
        target_game_result = _target_check(target_probe, game_position)
        if target_game_result.category != "ready":
            return finish(stage="target_game", reason=target_game_result.reason)

        opendota_leagues = tuple(
            await read("leagues", self._opendota_discovery.get_leagues)
        )
        league_candidate_result = find_league_candidates(
            match_context,
            opendota_leagues,
            max_candidates=policy.max_leagues,
        )
        if league_candidate_result.category == "candidate_limit_exceeded":
            raise ResolutionBudgetExceeded(
                operation="league_candidates",
                limit_name="max_leagues",
                limit=policy.max_leagues,
                required=league_candidate_result.total_candidate_count,
                remaining=None,
                requests_started=requests_started,
            )
        if league_candidate_result.category != "candidates_found":
            return finish(
                stage="league_candidates",
                reason=league_candidate_result.reason,
            )

        selected_league_ids = _candidate_league_ids(league_candidate_result)
        _require_request_budget(
            operation="league_matches",
            policy=policy,
            requests_started=requests_started,
            required=len(selected_league_ids),
        )
        async def read_league(league_id: int):
            rows = await read(
                "league_matches",
                lambda: self._opendota_discovery.get_league_matches(league_id),
            )
            return tuple(rows)

        league_matches_by_id = await _read_phase(
            selected_league_ids, read_league, max_concurrency=policy.max_concurrency
        )

        valve_game_ids = _candidate_valve_game_ids(
            match_context,
            game_position,
            selected_league_ids,
            league_matches_by_id,
            policy,
        )
        if len(valve_game_ids) > policy.max_candidate_details:
            raise ResolutionBudgetExceeded(
                operation="candidate_details",
                limit_name="max_candidate_details",
                limit=policy.max_candidate_details,
                required=len(valve_game_ids),
                remaining=None,
                requests_started=requests_started,
            )
        _require_request_budget(
            operation="candidate_details",
            policy=policy,
            requests_started=requests_started,
            required=len(valve_game_ids),
        )
        async def read_detail(valve_game_id: int):
            detail = await read(
                "game_detail",
                lambda: self._opendota_game_detail.get_game_record(valve_game_id),
            )
            if not isinstance(detail, OpenDotaGameRecord):
                raise TypeError("OpenDota detail adapter returned an invalid result")
            if detail.match_id != valve_game_id:
                raise ValueError("OpenDota detail identity changed after validation")
            return detail

        candidate_details = await _read_phase(
            valve_game_ids, read_detail, max_concurrency=policy.max_concurrency
        )

        resolution_result = resolve_game_across_leagues(
            match_context,
            game_position,
            selected_league_ids,
            league_matches_by_id,
            {key: value.data for key, value in candidate_details.items()},
            start_time_tolerance_seconds=policy.start_time_tolerance_seconds,
            duration_tolerance_seconds=policy.duration_tolerance_seconds,
            confirmed_mappings=confirmed_mappings,
        )
        return finish(stage="resolution", reason=resolution_result.reason)


async def _read_phase(
    identities: Sequence[int],
    fetch: Callable[[int], Awaitable[_T]],
    *,
    max_concurrency: int,
) -> dict[int, _T]:
    """Bound active workers, retain source order, and join cancelled siblings."""

    pending = iter(identities)
    results: dict[int, _T] = {}
    stopped = False

    async def worker() -> None:
        nonlocal stopped
        try:
            for identity in pending:
                if stopped:
                    return
                results[identity] = await fetch(identity)
        except BaseException:
            stopped = True
            raise

    workers = [
        asyncio.create_task(worker()) for _ in range(min(max_concurrency, len(identities)))
    ]
    try:
        await asyncio.gather(*workers)
    except BaseException:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        raise
    return {identity: results[identity] for identity in identities}


def _validate_request(
    match_id: int,
    game_position: int,
    policy: GameResolutionReadPolicy,
    confirmed_mappings: Mapping[int, int],
) -> None:
    if type(match_id) is not int or match_id <= 0:
        raise ValueError("match_id must be a positive integer")
    if type(game_position) is not int or game_position <= 0:
        raise ValueError("game_position must be a positive integer")
    if not isinstance(policy, GameResolutionReadPolicy):
        raise ValueError("policy must be a GameResolutionReadPolicy")
    if not isinstance(confirmed_mappings, Mapping):
        raise ValueError("confirmed_mappings must be a mapping")
    for pandascore_id, valve_id in confirmed_mappings.items():
        if type(pandascore_id) is not int or pandascore_id <= 0:
            raise ValueError("confirmed mapping keys must be positive integers")
        if type(valve_id) is not int or valve_id <= 0:
            raise ValueError("confirmed mapping values must be positive integers")


def _target_check(
    result: GameCandidateResult,
    game_position: int,
) -> TargetGameCheck:
    if result.category == "no_candidates":
        return TargetGameCheck("ready", game_position, result.target_game, None)
    if result.category == "candidates_found":
        raise AssertionError("empty target probe cannot contain candidates")
    return TargetGameCheck(
        category=result.category,
        game_position=game_position,
        target_game=result.target_game,
        reason=result.reason,
    )


def _candidate_league_ids(result: LeagueCandidateResult) -> tuple[int, ...]:
    identifiers: list[int] = []
    seen: set[int] = set()
    for candidate in result.candidates:
        league_id = candidate.record.get("leagueid")
        if type(league_id) is not int or league_id <= 0:
            raise ValueError("validated League candidate is missing its positive ID")
        if league_id not in seen:
            seen.add(league_id)
            identifiers.append(league_id)
    return tuple(identifiers)


def _candidate_valve_game_ids(
    match_context: Mapping[str, JsonValue],
    game_position: int,
    league_ids: Sequence[int],
    league_matches_by_id: Mapping[
        int, Sequence[Mapping[str, JsonValue]]
    ],
    policy: GameResolutionReadPolicy,
) -> tuple[int, ...]:
    identifiers: list[int] = []
    seen: set[int] = set()
    for league_id in league_ids:
        result = find_game_candidates(
            match_context,
            game_position,
            league_id,
            league_matches_by_id[league_id],
            start_time_tolerance_seconds=policy.start_time_tolerance_seconds,
            duration_tolerance_seconds=policy.duration_tolerance_seconds,
        )
        for candidate in result.candidates:
            valve_game_id = candidate.record.get("match_id")
            if type(valve_game_id) is not int or valve_game_id <= 0:
                raise ValueError("validated candidate is missing its positive Valve ID")
            if valve_game_id not in seen:
                seen.add(valve_game_id)
                identifiers.append(valve_game_id)
    return tuple(identifiers)


def _require_request_budget(
    *,
    operation: str,
    policy: GameResolutionReadPolicy,
    requests_started: int,
    required: int,
) -> None:
    remaining = policy.max_requests - requests_started
    if required > remaining:
        raise ResolutionBudgetExceeded(
            operation=operation,
            limit_name="max_requests",
            limit=policy.max_requests,
            required=required,
            remaining=remaining,
            requests_started=requests_started,
        )


__all__ = [
    "GameResolutionReadAttempt",
    "GameResolutionReadPolicy",
    "PandaScoreOpenDotaGameResolutionProvider",
    "ResolutionBudgetExceeded",
    "TargetGameCheck",
]
