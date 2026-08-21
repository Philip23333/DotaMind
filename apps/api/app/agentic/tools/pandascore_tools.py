"""Agentic tools for PandaScore competition and fixture discovery."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.agentic.evidence import EvidenceItem
from app.agentic.models import QueryContext, ToolResult, ToolSource
from app.agentic.tools import (
    AcceptedRef,
    ArgContract,
    OutputPathContract,
    ToolDefinition,
    ToolRegistry,
)
from app.core.config import Settings, get_policy
from app.integrations.pandascore.competitions import PandaScoreCompetitions
from app.integrations.pandascore.matches import PandaScoreMatches
from app.integrations.pandascore.models import (
    CompetitionSelection,
    PandaCompetition,
    PandaMatchFixture,
)
from app.integrations.pandascore.transport import PandaScoreTransport


class PandaScoreResolveCompetitionInput(BaseModel):
    query: str = Field(min_length=1)
    year: int | None = Field(default=None, ge=2011, le=2100)

    @model_validator(mode="after")
    def reject_year_conflict(self) -> PandaScoreResolveCompetitionInput:
        _query, query_year = _extract_explicit_year(self.query)
        if query_year is not None and self.year is not None and query_year != self.year:
            raise ValueError("year conflicts with the year in query")
        return self


class PandaScoreListMatchesInput(BaseModel):
    series_id: int = Field(gt=0)
    date_from: datetime | None = None
    date_to: datetime | None = None
    statuses: (
        list[Literal["not_started", "running", "finished", "canceled", "postponed"]] | None
    ) = None
    limit: int = Field(default=20, ge=1, le=100)


class PandaScoreResolveMatchGamesInput(BaseModel):
    series_id: int = Field(gt=0)
    team_queries: list[str] = Field(min_length=2, max_length=2)
    game_number: int | None = Field(default=None, ge=1)
    scheduled_date: date | None = None
    pandascore_match_id: int | None = Field(default=None, gt=0)


def register_pandascore_tools(registry: ToolRegistry, settings: Settings) -> None:
    policy = get_policy().pandascore
    source = ToolSource(
        name="PandaScore",
        kind="public_api",
        url=settings.pandascore_base_url,
        status="live",
    )
    registry.register(
        ToolDefinition(
            name="pandascore.resolve_competition",
            description=(
                "Resolve a named recurring Dota 2 competition. When the competition is named "
                "but no edition year is supplied, omit `year` so the resolver selects the latest "
                "edition. Do not request clarification solely for a missing edition year."
            ),
            input_model=PandaScoreResolveCompetitionInput,
            handler=_resolve_competition_handler(settings, policy),
            source=source,
            evidence_extractor=competition_evidence,
            evidence_kinds=("competition_identity", "tournament_stage"),
            mandatory_evidence=("competition_identity",),
            arg_contracts={
                "query": ArgContract(description="Competition family or series name."),
                "year": ArgContract(
                    description="Explicit edition year; omit it to resolve the latest edition."
                ),
            },
            output_paths={
                "competition": OutputPathContract(
                    path="data.competition",
                    type="dict",
                    description="Resolved PandaScore competition context.",
                ),
                "series_id": OutputPathContract(
                    path="data.competition.series_id",
                    type="int",
                    description="PandaScore series id.",
                )
            },
            metadata={"game": "dota2", "domain": "competition"},
        )
    )
    registry.register(
        ToolDefinition(
            name="pandascore.list_matches",
            description=(
                "List the newest PandaScore fixtures first across upcoming, running, and past "
                "fixtures for a resolved series. Defaults to the newest 20 fixtures."
            ),
            input_model=PandaScoreListMatchesInput,
            handler=_list_matches_handler(settings, policy),
            source=source,
            evidence_extractor=match_schedule_evidence,
            evidence_kinds=("match_schedule", "match_state", "series_score"),
            mandatory_evidence=("match_schedule",),
            arg_contracts={
                "series_id": ArgContract(
                    description="PandaScore series id from resolve_competition.",
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="pandascore.resolve_competition",
                            path="data.competition.series_id",
                            type="int",
                        ),
                    ),
                    requires_reference=True,
                ),
                "date_from": ArgContract(description="Inclusive UTC lower bound."),
                "date_to": ArgContract(description="Inclusive UTC upper bound."),
                "statuses": ArgContract(description="PandaScore fixture statuses."),
                "limit": ArgContract(description="Maximum returned fixtures."),
            },
            output_paths={
                "matches": OutputPathContract(
                    path="data.matches", type="list[dict]", description="Normalized fixture rows."
                )
            },
            metadata={"game": "dota2", "domain": "match_schedule"},
        )
    )
    registry.register(
        ToolDefinition(
            name="pandascore.resolve_match_games",
            description=(
                "Resolve one uniquely identified PandaScore series and return all "
                "provider-exposed games when no game number is supplied."
            ),
            input_model=PandaScoreResolveMatchGamesInput,
            handler=_resolve_match_games_handler(settings, policy),
            source=source,
            evidence_extractor=match_games_evidence,
            evidence_kinds=(
                "match_identity",
                "pandascore_game_identity",
                "series_context",
            ),
            mandatory_evidence=("match_identity", "pandascore_game_identity"),
            arg_contracts={
                "series_id": ArgContract(
                    description="PandaScore series id from resolve_competition.",
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="pandascore.resolve_competition",
                            path="data.competition.series_id",
                            type="int",
                        ),
                    ),
                    requires_reference=True,
                ),
                "team_queries": ArgContract(description="Two team names, order independent."),
                "game_number": ArgContract(
                    description="Optional 1-based game position; omit to return all actual games."
                ),
                "scheduled_date": ArgContract(
                    description="Optional UTC calendar date for disambiguation."
                ),
                "pandascore_match_id": ArgContract(
                    description="Optional exact PandaScore Fixture id for disambiguation."
                ),
            },
            output_paths={
                "resolution_inputs": OutputPathContract(
                    path="data.resolution_inputs",
                    type="list[dict]",
                    description="Deterministic cross-source inputs for all selected games.",
                ),
                "games": OutputPathContract(
                    path="data.games",
                    type="list[dict]",
                    description="Selected PandaScore game rows.",
                ),
            },
            metadata={"game": "dota2", "domain": "match_identity"},
        )
    )


def _clients(
    settings: Settings, policy: Any
) -> tuple[PandaScoreTransport, PandaScoreCompetitions, PandaScoreMatches]:
    transport = PandaScoreTransport(
        settings.pandascore_base_url,
        settings.pandascore_token,
        request_timeout_seconds=policy.request_timeout_seconds,
        default_cache_ttl_seconds=policy.default_cache_ttl_seconds,
        max_page_size=policy.max_page_size,
    )
    competitions = PandaScoreCompetitions(transport)
    return transport, competitions, PandaScoreMatches(transport, competitions)


def _resolve_competition_handler(settings: Settings, policy: Any):
    async def handle(
        args: PandaScoreResolveCompetitionInput, context: QueryContext
    ) -> dict[str, Any]:
        transport, competitions, _matches = _clients(settings, policy)
        try:
            query, year_from_query = _extract_explicit_year(args.query)
            requested_year = args.year if args.year is not None else year_from_query
            rows = await competitions.list_series(year=requested_year)
            eligible_rows = [
                row
                for row in rows
                if requested_year is None or row.year == requested_year
            ]
            ranked = [
                (row, _competition_match_rank(row, query))
                for row in eligible_rows
                if _competition_match_rank(row, query) > 0
            ]
            best_rank = max((rank for _row, rank in ranked), default=0)
            candidates = [row for row, rank in ranked if rank == best_rank]
            selection = select_latest_competition(
                candidates,
                now=datetime.now(UTC),
                requested_year=requested_year,
                match_rank=best_rank or None,
            )
            if selection.status == "resolved" and selection.selected is not None:
                row = selection.selected
                return {
                    "status": "resolved",
                    "query": args.query,
                    "competition": _competition_data(row),
                    "tournaments": row.tournaments,
                    "selection": _selection_data(selection),
                }
            return {
                "status": selection.status,
                "query": args.query,
                "candidates": [_competition_data(row) for row in selection.candidates[:10]],
                "selection": _selection_data(selection),
            }
        finally:
            await transport.aclose()

    return handle


def _list_matches_handler(settings: Settings, policy: Any):
    async def handle(args: PandaScoreListMatchesInput, context: QueryContext) -> dict[str, Any]:
        transport, _competitions, matches_client = _clients(settings, policy)
        try:
            fixtures = await matches_client.list_matches(args.series_id, limit=args.limit)
            fixtures = [
                fixture
                for fixture in fixtures
                if _date_filter(fixture, args.date_from, args.date_to)
            ]
            if args.statuses:
                fixtures = [fixture for fixture in fixtures if fixture.status in args.statuses]
            fixtures = fixtures[: args.limit]
            return {
                "series_id": args.series_id,
                "matches": [_fixture_data(fixture) for fixture in fixtures],
                "count": len(fixtures),
            }
        finally:
            await transport.aclose()

    return handle


def _resolve_match_games_handler(settings: Settings, policy: Any):
    async def handle(
        args: PandaScoreResolveMatchGamesInput, context: QueryContext
    ) -> dict[str, Any]:
        transport, _competitions, matches_client = _clients(settings, policy)
        try:
            resolved = await matches_client.resolve_games(
                args.series_id,
                args.team_queries,
                game_number=args.game_number,
                scheduled_date=args.scheduled_date,
                pandascore_match_id=args.pandascore_match_id,
            )
            result: dict[str, Any] = {
                "status": resolved.status,
                "coverage": [item.model_dump(mode="json") for item in resolved.coverage],
                "candidates": [_fixture_data(item) for item in resolved.candidates],
            }
            if resolved.match is not None:
                result["match"] = _fixture_data(resolved.match)
            result["games"] = [game.model_dump(mode="json") for game in resolved.games]
            result["resolution_inputs"] = [
                _resolution_input(resolved.match, game) for game in resolved.games
            ]
            return result
        finally:
            await transport.aclose()

    return handle


def competition_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    if data.get("status") != "resolved" or not isinstance(data.get("competition"), dict):
        return []
    competition = data["competition"]
    series_id = competition.get("series_id")
    if not isinstance(series_id, int):
        return []
    items = [
        EvidenceItem(
            id=f"{result.tool_call_id}:competition_identity",
            kind="competition_identity",
            subject=str(competition.get("full_name") or competition.get("name")),
            value={**competition, "selection": data.get("selection")},
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        )
    ]
    for stage in data.get("tournaments", []):
        if not isinstance(stage, dict):
            continue
        stage_id = stage.get("id") or stage.get("pandascore_tournament_id")
        items.append(
            EvidenceItem(
                id=f"{result.tool_call_id}:tournament_stage:{stage_id}",
                kind="tournament_stage",
                subject=str(stage.get("name") or "tournament stage"),
                value=stage,
                source=result.source,
                tool_call_id=result.tool_call_id,
                tool=result.tool,
            )
        )
    return items


def match_schedule_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    matches = data.get("matches")
    if not isinstance(matches, list) or not matches:
        return []
    items: list[EvidenceItem] = []
    for fixture in matches:
        if not isinstance(fixture, dict) or not isinstance(fixture.get("pandascore_match_id"), int):
            continue
        call_id = result.tool_call_id
        match_id = fixture["pandascore_match_id"]
        items.append(
            EvidenceItem(
                id=f"{call_id}:match_schedule:{match_id}",
                kind="match_schedule",
                subject=str(fixture.get("name") or match_id),
                value=fixture,
                source=result.source,
                tool_call_id=call_id,
                tool=result.tool,
            )
        )
        items.append(
            EvidenceItem(
                id=f"{call_id}:match_state:{match_id}",
                kind="match_state",
                subject=str(fixture.get("name") or match_id),
                value={
                    "status": fixture.get("status"),
                    "scheduled_at": fixture.get("scheduled_at"),
                },
                source=result.source,
                tool_call_id=call_id,
                tool=result.tool,
            )
        )
        if fixture.get("results"):
            items.append(
                EvidenceItem(
                    id=f"{call_id}:series_score:{match_id}",
                    kind="series_score",
                    subject=str(fixture.get("name") or match_id),
                    value={"results": fixture["results"]},
                    source=result.source,
                    tool_call_id=call_id,
                    tool=result.tool,
                )
            )
    return items


def match_games_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    match = data.get("match")
    games = data.get("games")
    if not isinstance(match, dict) or not isinstance(games, list) or not games:
        return []
    call_id = result.tool_call_id
    items = [
        EvidenceItem(
            id=f"{call_id}:match_identity",
            kind="match_identity",
            subject=str(match.get("name") or match.get("pandascore_match_id")),
            value=match,
            source=result.source,
            tool_call_id=call_id,
            tool=result.tool,
        ),
        EvidenceItem(
            id=f"{call_id}:series_context",
            kind="series_context",
            subject=str(match.get("name") or match.get("pandascore_match_id")),
            value={
                "pandascore_series_id": match.get("pandascore_series_id"),
                "tournament": match.get("tournament"),
            },
            source=result.source,
            tool_call_id=call_id,
            tool=result.tool,
        ),
    ]
    for game in games:
        if not isinstance(game, dict):
            continue
        items.append(
            EvidenceItem(
                id=f"{call_id}:pandascore_game_identity:{game.get('pandascore_game_id')}",
                kind="pandascore_game_identity",
                subject=str(game.get("pandascore_game_id")),
                value=game,
                source=result.source,
                tool_call_id=call_id,
                tool=result.tool,
            )
        )
    return items


def _competition_data(row: Any) -> dict[str, Any]:
    data = row.model_dump(mode="json")
    data["series_id"] = data["pandascore_series_id"]
    data["series_name"] = data["name"]
    stages = data.get("tournaments") or []
    if stages:
        stage = stages[0]
        data["tournament_id"] = stage.get("pandascore_tournament_id")
        data["tournament_name"] = stage.get("name")
        data["begin_at"] = stage.get("begin_at")
        data["end_at"] = stage.get("end_at")
    else:
        data["tournament_id"] = None
        data["tournament_name"] = None
        data["begin_at"] = None
        data["end_at"] = None
    return data


def _extract_explicit_year(query: str) -> tuple[str, int | None]:
    """Remove one standalone edition year while preserving the competition name."""

    match = re.search(r"(?<!\d)(20\d{2})(?!\d)", query)
    if match is None:
        return " ".join(query.split()), None
    base = f"{query[:match.start()]} {query[match.end():]}"
    return " ".join(base.split()), int(match.group(1))


def _normalize_label(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _competition_match_rank(row: PandaCompetition, query: str) -> int:
    needle = _normalize_label(query)
    if not needle:
        return 0
    name = _normalize_label(row.name)
    full_name = _normalize_label(row.full_name)
    league_name = _normalize_label(row.league.get("name") if row.league else None)
    combined = _normalize_label(
        f"{row.league.get('name', '') if row.league else ''} {row.full_name or ''}"
    )
    if needle in {name, full_name, combined}:
        return 3
    if league_name and needle == league_name:
        return 2
    labels = {name, full_name, league_name, combined}
    if any(needle in label for label in labels if label):
        return 1
    return 0


def select_latest_competition(
    candidates: list[PandaCompetition],
    *,
    now: datetime,
    requested_year: int | None = None,
    match_rank: int | None = None,
) -> CompetitionSelection:
    """Choose a latest edition without depending on API array order or IDs."""

    mode = "explicit_year" if requested_year is not None else "latest_edition"
    candidate_count = len(candidates)
    if requested_year is not None:
        if len(candidates) != 1:
            return CompetitionSelection(
                status="ambiguous" if candidates else "not_found",
                mode=mode,
                requested_year=requested_year,
                match_rank=match_rank,
                candidate_count_before_selection=len(candidates),
                candidates=_stable_candidates(candidates),
            )
        selected = candidates[0]
        return CompetitionSelection(
            status="resolved",
            mode=mode,
            requested_year=requested_year,
            selected_year=selected.year,
            match_rank=match_rank,
            candidate_count_before_selection=len(candidates),
            selected=selected,
            candidates=[selected],
        )

    now_utc = _as_utc(now)
    active = [row for row in candidates if _competition_is_active(row, now_utc)]
    if active:
        return _select_temporal_candidates(
            active,
            mode,
            requested_year,
            match_rank,
            reverse=True,
            candidate_count=candidate_count,
            prefer_end=False,
        )

    historical = [row for row in candidates if _competition_is_historical(row, now_utc)]
    if historical:
        return _select_temporal_candidates(
            historical,
            mode,
            requested_year,
            match_rank,
            reverse=True,
            candidate_count=candidate_count,
            prefer_end=True,
        )

    upcoming = [row for row in candidates if _competition_begin(row) is not None]
    if upcoming:
        return _select_temporal_candidates(
            upcoming,
            mode,
            requested_year,
            match_rank,
            reverse=False,
            candidate_count=candidate_count,
            prefer_end=False,
        )

    return CompetitionSelection(
        status="resolved" if len(candidates) == 1 else ("ambiguous" if candidates else "not_found"),
        mode=mode,
        requested_year=requested_year,
        selected=candidates[0] if len(candidates) == 1 else None,
        selected_year=candidates[0].year if len(candidates) == 1 else None,
        match_rank=match_rank,
        candidate_count_before_selection=len(candidates),
        candidates=_stable_candidates(candidates),
    )


def _select_temporal_candidates(
    candidates: list[PandaCompetition],
    mode: Literal["latest_edition", "explicit_year"],
    requested_year: int | None,
    match_rank: int | None,
    *,
    reverse: bool,
    candidate_count: int,
    prefer_end: bool,
) -> CompetitionSelection:
    keyed = []
    for row in candidates:
        value = (
            _competition_end(row) or _competition_begin(row)
            if prefer_end
            else _competition_begin(row) or _competition_end(row)
        )
        keyed.append((value, row))
    keyed = [(value, row) for value, row in keyed if value is not None]
    if not keyed:
        return CompetitionSelection(
            status="ambiguous" if len(candidates) > 1 else "not_found",
            mode=mode,
            requested_year=requested_year,
            match_rank=match_rank,
            candidate_count_before_selection=candidate_count,
            candidates=_stable_candidates(candidates),
        )
    target = (max if reverse else min)(value for value, _row in keyed)
    tied = [row for value, row in keyed if value == target]
    selected = tied[0] if len(tied) == 1 else None
    return CompetitionSelection(
        status="resolved" if selected is not None else "ambiguous",
        mode=mode,
        requested_year=requested_year,
        selected_year=selected.year if selected is not None else None,
        match_rank=match_rank,
        candidate_count_before_selection=candidate_count,
        selected=selected,
        candidates=_stable_candidates(tied if len(tied) > 1 else [selected]),
    )


def _competition_times(row: PandaCompetition) -> tuple[datetime | None, datetime | None]:
    begins = [_parse_datetime(stage.get("begin_at")) for stage in row.tournaments]
    ends = [_parse_datetime(stage.get("end_at")) for stage in row.tournaments]
    begins = [value for value in begins if value is not None]
    ends = [value for value in ends if value is not None]
    return (min(begins) if begins else None, max(ends) if ends else None)


def _competition_begin(row: PandaCompetition) -> datetime | None:
    return _competition_times(row)[0]


def _competition_end(row: PandaCompetition) -> datetime | None:
    return _competition_times(row)[1]


def _competition_is_active(row: PandaCompetition, now: datetime) -> bool:
    begin, end = _competition_times(row)
    return begin is not None and begin <= now and (end is None or end >= now)


def _competition_is_historical(row: PandaCompetition, now: datetime) -> bool:
    begin, end = _competition_times(row)
    return (end is not None and end < now) or (begin is not None and begin <= now)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _stable_candidates(candidates: list[PandaCompetition]) -> list[PandaCompetition]:
    return sorted(candidates, key=lambda row: row.pandascore_series_id)


def _selection_data(selection: CompetitionSelection) -> dict[str, Any]:
    return {
        "mode": selection.mode,
        "requested_year": selection.requested_year,
        "selected_year": selection.selected_year,
        "match_rank": selection.match_rank,
        "candidate_count_before_selection": selection.candidate_count_before_selection,
    }


def _competition_labels(row: Any) -> set[str]:
    labels = {row.name.casefold()}
    if row.full_name:
        labels.add(row.full_name.casefold())
    if row.league and row.league.get("name"):
        labels.add(str(row.league["name"]).casefold())
        if row.full_name:
            labels.add(f"{row.league['name']} {row.full_name}".casefold())
    return labels


def _fixture_data(fixture: PandaMatchFixture) -> dict[str, Any]:
    return fixture.model_dump(mode="json")


def _resolution_input(match: PandaMatchFixture | None, game: Any) -> dict[str, Any]:
    if match is None:
        return {}
    teams: list[dict[str, Any]] = []
    for opponent in match.opponents:
        team = opponent.get("opponent") if isinstance(opponent, dict) else None
        if not isinstance(team, dict) or team.get("id") is None:
            continue
        teams.append(
            {
                "pandascore_team_id": team.get("id"),
                "name": team.get("name"),
                "acronym": team.get("acronym"),
            }
        )
    return {
        "pandascore_series_id": match.pandascore_series_id,
        "pandascore_tournament_id": match.pandascore_tournament_id,
        "pandascore_match_id": match.pandascore_match_id,
        "pandascore_game_id": game.pandascore_game_id,
        "game_position": game.position,
        "game_begin_at": _isoformat(game.begin_at),
        "match_begin_at": _isoformat(match.begin_at),
        "scheduled_at": _isoformat(match.scheduled_at),
        "length_seconds": game.length_seconds,
        "teams": teams,
        "winner_pandascore_team_id": game.winner_team_id,
    }


def _isoformat(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, (datetime, date)) else value


def _date_filter(
    fixture: PandaMatchFixture, date_from: datetime | None, date_to: datetime | None
) -> bool:
    value = fixture.scheduled_at or fixture.begin_at
    if value is None:
        return date_from is None and date_to is None
    value = _as_utc(value)
    date_from = _as_utc(date_from) if date_from is not None else None
    date_to = _as_utc(date_to) if date_to is not None else None
    if date_from is not None and value < date_from:
        return False
    if date_to is not None and value > date_to:
        return False
    return True


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
