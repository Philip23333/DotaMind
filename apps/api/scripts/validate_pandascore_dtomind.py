"""Validate the real PandaScore -> DotaMind DTO pipeline without the agent runtime."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.vnext.capabilities.esports.league import LeagueSearchInput
from app.vnext.capabilities.esports.match import MatchSearchInput
from app.vnext.capabilities.esports.player import PlayerSearchInput
from app.vnext.capabilities.esports.series import SeriesSearchInput, SeriesTeamsInput
from app.vnext.capabilities.esports.team import TeamSearchInput
from app.vnext.capabilities.esports.tournament import TournamentSearchInput
from app.vnext.composition import VNextSettings
from app.vnext.providers.pandascore.client import PandaScoreClient
from app.vnext.providers.pandascore.league_adapter import PandaScoreLeagueAdapter
from app.vnext.providers.pandascore.match_adapter import PandaScoreMatchAdapter
from app.vnext.providers.pandascore.player_adapter import PandaScorePlayerAdapter
from app.vnext.providers.pandascore.series_adapter import PandaScoreSeriesAdapter
from app.vnext.providers.pandascore.team_adapter import PandaScoreTeamAdapter
from app.vnext.providers.pandascore.tournament_adapter import (
    PandaScoreTournamentAdapter,
)

ROOT = Path(__file__).resolve().parents[3]
REPORT_PATH = ROOT / "docs" / "pandascore_real_endpoint_validation.md"


class RecordingPandaScoreClient(PandaScoreClient):
    """Keep request and response summaries without changing client behavior."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.requests: list[dict[str, Any]] = []
        self.responses: list[list[Any]] = []

    async def get_list(self, path: str, *, params: dict[str, Any]) -> list[Any]:
        self.requests.append({"path": path, "params": dict(params)})
        payload = await super().get_list(path, params=params)
        self.responses.append(payload)
        return payload


@dataclass
class CaseResult:
    capability: str
    name: str
    query: dict[str, Any]
    request: dict[str, Any] | None = None
    raw_summary: dict[str, Any] = None  # type: ignore[assignment]
    dto_count: int = 0
    dto_json: str = "[]"
    anomalies: list[dict[str, Any]] = None  # type: ignore[assignment]
    status: str = "FAIL"
    findings: list[str] = None  # type: ignore[assignment]
    error: str | None = None

    def __post_init__(self) -> None:
        self.raw_summary = self.raw_summary or {}
        self.anomalies = self.anomalies or []
        self.findings = self.findings or []


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _contains_key(value: Any, names: set[str]) -> list[str]:
    found: list[str] = []

    def visit(current: Any, path: str) -> None:
        if isinstance(current, dict):
            for key, child in current.items():
                child_path = f"{path}.{key}" if path else key
                if key in names:
                    found.append(child_path)
                visit(child, child_path)
        elif isinstance(current, list):
            for index, child in enumerate(current):
                visit(child, f"{path}[{index}]")

    visit(value, "")
    return found


def _raw_summary(rows: list[Any]) -> dict[str, Any]:
    key_names: set[str] = set()
    type_counts: dict[str, int] = {}
    for row in rows:
        type_name = type(row).__name__
        type_counts[type_name] = type_counts.get(type_name, 0) + 1
        if isinstance(row, dict):
            key_names.update(row)
    return {
        "item_count": len(rows),
        "item_types": type_counts,
        "top_level_keys": sorted(key_names),
    }


def _dto_sample(items: list[Any]) -> str:
    text = _json([item.model_dump(mode="json") for item in items[:2]])
    if len(text) <= 8000:
        return text
    return text[:8000] + "\n... [DTO sample truncated]"


def _role_values(rows: list[Any]) -> list[Any]:
    values: list[Any] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if "role" in value and value["role"] not in values:
                values.append(value["role"])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(rows)
    return values


async def _run_case(
    client: RecordingPandaScoreClient,
    *,
    capability: str,
    name: str,
    query: Any,
    operation: Callable[[Any], Awaitable[Any]],
    forbidden_dto_fields: set[str] | None = None,
    extra_check: Callable[[list[Any], Any], list[str]] | None = None,
) -> CaseResult:
    result = CaseResult(
        capability=capability,
        name=name,
        query=query.model_dump(mode="json"),
    )
    request_start = len(client.requests)
    response_start = len(client.responses)
    try:
        output = await operation(query)
    except Exception as exc:  # noqa: BLE001 - the report must classify live failures
        result.error = f"{type(exc).__name__}: {exc}"
        result.findings.append("live request or adapter failed")
        return result

    result.request = client.requests[request_start] if client.requests[request_start:] else None
    rows = client.responses[response_start] if client.responses[response_start:] else []
    result.raw_summary = _raw_summary(rows)
    result.raw_summary["role_values"] = _role_values(rows)
    result.dto_count = len(output.items)
    result.dto_json = _dto_sample(output.items)
    result.anomalies = [anomaly.model_dump(mode="json") for anomaly in output.anomalies]
    repeated_reasons = Counter(
        str(anomaly.get("reason", "<unknown>")) for anomaly in result.anomalies
    )
    for reason, count in repeated_reasons.items():
        if count >= 3:
            result.findings.append(
                f"repeated anomaly reason requires mapper/contract review: {reason} ({count})"
            )

    if forbidden_dto_fields:
        for item in output.items:
            leaked = _contains_key(item.model_dump(mode="json"), forbidden_dto_fields)
            result.findings.extend(f"DTO leaked forbidden field: {path}" for path in leaked)
    if extra_check is not None:
        result.findings.extend(extra_check(rows, output))

    if result.findings:
        result.status = "CONTRACT_REVIEW_REQUIRED"
    elif result.dto_count == 0:
        result.status = "NO_DATA"
    elif result.anomalies:
        result.status = "PASS_WITH_ANOMALIES"
    else:
        result.status = "PASS"
    return result


def _tournament_check(rows: list[Any], output: Any) -> list[str]:
    if not rows or not output.items or not isinstance(rows[0], dict):
        return []
    row = rows[0]
    primary_ids = [team.get("id") for team in row.get("teams", []) if isinstance(team, dict)]
    roster_ids = [
        entry.get("team", {}).get("id")
        for entry in row.get("expected_roster", [])
        if isinstance(entry, dict) and isinstance(entry.get("team"), dict)
    ]
    expected_ids = list(dict.fromkeys(primary_ids + roster_ids))
    actual_ids = [participant.team.id for participant in output.items[0].participants]
    if expected_ids and actual_ids != expected_ids:
        return [f"participant union/order mismatch: expected {expected_ids}, got {actual_ids}"]
    return []


def _match_check(rows: list[Any], output: Any) -> list[str]:
    if not output.items:
        return []
    item = output.items[0]
    findings: list[str] = []
    if item.status == "finished" and item.draw and item.winner_id is not None:
        findings.append("finished match is marked draw with a winner")
    return findings


def _render_case(case: CaseResult) -> str:
    lines = [
        f"### {case.name}",
        "",
        f"- Capability: `{case.capability}`",
        f"- Status: `{case.status}`",
        f"- Query: `{_json(case.query)}`",
        f"- Request: `{_json(case.request) if case.request else 'not recorded'}`",
        f"- Raw summary: `{_json(case.raw_summary)}`",
        f"- DTO item count: `{case.dto_count}`",
        f"- Anomaly count: `{len(case.anomalies)}`",
        "",
        "DTO sample:",
        "```json",
        case.dto_json,
        "```",
        "",
        "Anomalies:",
        "```json",
        _json(case.anomalies),
        "```",
    ]
    if case.error:
        lines.extend(["", f"- Error: `{case.error}`"])
    if case.findings:
        lines.extend(["", "Findings:", "```text", *case.findings, "```"])
    return "\n".join(lines)


def _render_report(cases: list[CaseResult], settings: VNextSettings) -> str:
    summary_rows = "\n".join(
        f"| {case.capability} | {case.name} | {case.status} | {len(case.anomalies)} |"
        for case in cases
    )
    generated = datetime.now(timezone.utc).isoformat()
    sections = "\n\n".join(_render_case(case) for case in cases)
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return f"""# PandaScore Real Endpoint → DotaMind DTO Validation

Date: `{generated}`  
Branch: `codex/model_behavior_optimization`  
Commit: `{commit}`  
Base URL: `{settings.pandascore_base_url}`

## Summary

| Capability | Case | Result | Anomalies |
| --- | --- | --- | ---: |
{summary_rows}

The script reads `DOTAMIND_PANDASCORE_TOKEN` from the existing vNext
environment and never writes credentials to this report. Request entries below
contain only endpoint paths and query parameters. `ResponseAnomaly.path` values
use provider-source locations such as `provider.items[0].games[2]`.

## Cases

{sections}

## Findings

### Confirmed contracts

- Requests are sent directly through `PandaScoreClient` and the corresponding
  adapter, without Agent/LLM/Tool Runtime involvement.
- DTO samples are serialized from the DotaMind SearchResult items.
- Normal missing data remains `None`/`[]`; local mapping anomalies remain visible
  in the SearchResult envelope.

### Provider anomalies observed

See the per-case anomaly blocks above. An empty list means no local mapping
anomaly was observed for that response.

### Contract mismatches requiring discussion

Cases marked `CONTRACT_REVIEW_REQUIRED` require manual review before any frozen
contract is changed. This validation run does not modify DTOs or query schemas.
"""


async def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    settings = VNextSettings.from_env()
    if not settings.pandascore_token:
        raise SystemExit("DOTAMIND_PANDASCORE_TOKEN is not configured")
    client = RecordingPandaScoreClient(
        base_url=settings.pandascore_base_url,
        token=settings.pandascore_token,
        timeout_seconds=settings.pandascore_timeout_seconds,
    )
    league = PandaScoreLeagueAdapter(client)
    series = PandaScoreSeriesAdapter(client)
    tournament = PandaScoreTournamentAdapter(client)
    match = PandaScoreMatchAdapter(client)
    team = PandaScoreTeamAdapter(client)
    player = PandaScorePlayerAdapter(client)

    cases: list[CaseResult] = []
    cases.append(
        await _run_case(
            client,
            capability="league.search",
            name="L1 league by id",
            query=LeagueSearchInput(id=4106),
            operation=league.search,
            forbidden_dto_fields={"series", "videogame", "modified_at"},
        )
    )
    cases.append(
        await _run_case(
            client,
            capability="league.search",
            name="L2 league by name",
            query=LeagueSearchInput(name="The International"),
            operation=league.search,
            forbidden_dto_fields={"series", "videogame", "modified_at"},
        )
    )
    for name, query in (
        ("S1 series by id 10828", SeriesSearchInput(id=10828)),
        ("S2 series by league/year", SeriesSearchInput(league_id=4106, year=2026)),
        ("S3 series by id 4012", SeriesSearchInput(id=4012)),
    ):
        cases.append(
            await _run_case(
                client,
                capability="series.search",
                name=name,
                query=query,
                operation=series.search,
                forbidden_dto_fields={"tournaments", "teams"},
            )
        )

    series_teams_case = await _run_case(
        client,
        capability="series.teams",
        name="ST1 teams for series 10828",
        query=SeriesTeamsInput(series_id=10828),
        operation=series.teams,
        forbidden_dto_fields={"players"},
    )
    cases.append(series_teams_case)
    if series_teams_case.status == "NO_DATA":
        cases.append(
            await _run_case(
                client,
                capability="series.teams",
                name="ST-fallback teams for historical series 4012",
                query=SeriesTeamsInput(series_id=4012),
                operation=series.teams,
                forbidden_dto_fields={"players"},
            )
        )

    for name, query in (
        ("T1 tournaments for series 10828", TournamentSearchInput(series_id=10828, limit=20)),
        ("T2 historical TI tournaments", TournamentSearchInput(series_id=4012, limit=20)),
    ):
        cases.append(
            await _run_case(
                client,
                capability="tournament.search",
                name=name,
                query=query,
                operation=tournament.search,
                extra_check=_tournament_check,
            )
        )

    for name, query in (
        (
            "M1 past matches for series 10828",
            MatchSearchInput(lifecycle="past", series_id=10828, limit=10),
        ),
        (
            "M2 past canceled matches",
            MatchSearchInput(lifecycle="past", status="canceled", limit=10),
        ),
        ("M3 upcoming matches", MatchSearchInput(lifecycle="upcoming", limit=10)),
    ):
        cases.append(
            await _run_case(
                client,
                capability="match.search",
                name=name,
                query=query,
                operation=match.search,
                forbidden_dto_fields={
                    "live",
                    "streams_list",
                    "detailed_stats",
                    "videogame",
                    "game_advantage",
                },
                extra_check=_match_check,
            )
        )

    for name, query in (
        ("TEAM1 team by id 1669", TeamSearchInput(id=1669)),
        ("TEAM2 team by name", TeamSearchInput(name="Xtreme Gaming")),
    ):
        cases.append(
            await _run_case(
                client,
                capability="team.search",
                name=name,
                query=query,
                operation=team.search,
            )
        )

    for name, query in (
        ("P1 player by id 27480", PlayerSearchInput(id=27480)),
        ("P2 player by id 28009", PlayerSearchInput(id=28009)),
        ("P3 active players for team 1669", PlayerSearchInput(team_id=1669, limit=10)),
    ):
        cases.append(
            await _run_case(
                client,
                capability="player.search",
                name=name,
                query=query,
                operation=player.search,
                forbidden_dto_fields={"players"},
            )
        )

    REPORT_PATH.write_text(_render_report(cases, settings), encoding="utf-8")
    print(_render_report(cases, settings))
    print(f"\nReport written to {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
