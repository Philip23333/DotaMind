"""Agentic tools for PandaScore competition and fixture discovery."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

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
from app.integrations.pandascore.models import PandaMatchFixture
from app.integrations.pandascore.transport import PandaScoreTransport


class PandaScoreResolveCompetitionInput(BaseModel):
    query: str = Field(min_length=1)


class PandaScoreListMatchesInput(BaseModel):
    series_id: int = Field(gt=0)
    date_from: datetime | None = None
    date_to: datetime | None = None
    statuses: (
        list[Literal["not_started", "running", "finished", "canceled", "postponed"]] | None
    ) = None
    limit: int = Field(default=20, ge=1, le=100)


class PandaScoreResolveMatchGameInput(BaseModel):
    series_id: int = Field(gt=0)
    team_queries: list[str] = Field(min_length=2, max_length=2)
    game_number: int | None = Field(default=None, ge=1)
    scheduled_date: date | None = None


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
            description="Resolve a Dota 2 competition or series using PandaScore fixture metadata.",
            input_model=PandaScoreResolveCompetitionInput,
            handler=_resolve_competition_handler(settings, policy),
            source=source,
            evidence_extractor=competition_evidence,
            evidence_kinds=("competition_identity", "tournament_stage"),
            mandatory_evidence=("competition_identity",),
            arg_contracts={"query": ArgContract(description="Competition or series name.")},
            output_paths={
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
                "List upcoming, running, and past PandaScore fixtures for a resolved series."
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
            name="pandascore.resolve_match_game",
            description=(
                "Resolve teams and an optional game number to PandaScore and Valve "
                "match identities."
            ),
            input_model=PandaScoreResolveMatchGameInput,
            handler=_resolve_match_game_handler(settings, policy),
            source=source,
            evidence_extractor=match_game_evidence,
            evidence_kinds=("match_identity", "series_context", "valve_match_identity"),
            mandatory_evidence=("match_identity", "valve_match_identity"),
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
                "game_number": ArgContract(description="1-based game position inside the series."),
                "scheduled_date": ArgContract(
                    description="Optional UTC calendar date for disambiguation."
                ),
            },
            output_paths={
                "pandascore_match_id": OutputPathContract(
                    path="data.match.pandascore_match_id",
                    type="int",
                    description="PandaScore match id.",
                ),
                "pandascore_game_id": OutputPathContract(
                    path="data.game.pandascore_game_id",
                    type="int",
                    description="PandaScore game id.",
                ),
                "valve_match_id": OutputPathContract(
                    path="data.game.valve_match_id",
                    type="int",
                    description="Valve match id when exposed.",
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
            rows = await competitions.list_series()
            query = args.query.strip().casefold()
            exact = [
                row
                for row in rows
                if query in _competition_labels(row)
            ]
            candidates = exact or [
                row
                for row in rows
                if any(query in label for label in _competition_labels(row))
            ]
            if len(candidates) == 1:
                row = candidates[0]
                return {
                    "status": "resolved",
                    "query": args.query,
                    "competition": _competition_data(row),
                    "tournaments": row.tournaments,
                }
            return {
                "status": "ambiguous" if candidates else "not_found",
                "query": args.query,
                "candidates": [_competition_data(row) for row in candidates[:10]],
            }
        finally:
            await transport.aclose()

    return handle


def _list_matches_handler(settings: Settings, policy: Any):
    async def handle(args: PandaScoreListMatchesInput, context: QueryContext) -> dict[str, Any]:
        transport, _competitions, matches_client = _clients(settings, policy)
        try:
            fixtures = await matches_client.list_matches(args.series_id)
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


def _resolve_match_game_handler(settings: Settings, policy: Any):
    async def handle(
        args: PandaScoreResolveMatchGameInput, context: QueryContext
    ) -> dict[str, Any]:
        transport, _competitions, matches_client = _clients(settings, policy)
        try:
            resolved = await matches_client.resolve_game(
                args.series_id,
                args.team_queries,
                game_number=args.game_number,
                scheduled_date=args.scheduled_date,
            )
            result: dict[str, Any] = {
                "status": resolved.status,
                "coverage": resolved.coverage.model_dump(mode="json")
                if resolved.coverage
                else None,
                "candidates": [_fixture_data(item) for item in resolved.candidates],
            }
            if resolved.match is not None:
                result["match"] = _fixture_data(resolved.match)
            if resolved.game is not None:
                result["game"] = resolved.game.model_dump(mode="json")
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
            value=competition,
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


def match_game_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    match = data.get("match")
    game = data.get("game")
    if not isinstance(match, dict) or not isinstance(game, dict):
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
    valve_id = game.get("valve_match_id")
    if isinstance(valve_id, int) and valve_id > 0:
        items.append(
            EvidenceItem(
                id=f"{call_id}:valve_match_identity",
                kind="valve_match_identity",
                subject=f"Valve match {valve_id}",
                value={
                    "valve_match_id": valve_id,
                    "pandascore_game_id": game.get("pandascore_game_id"),
                },
                source=result.source,
                tool_call_id=call_id,
                tool=result.tool,
            )
        )
    return items


def _competition_data(row: Any) -> dict[str, Any]:
    data = row.model_dump(mode="json")
    data["series_id"] = data["pandascore_series_id"]
    return data


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
