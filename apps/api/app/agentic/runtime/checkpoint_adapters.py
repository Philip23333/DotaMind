"""Domain-specific Checkpoint producers and deterministic resume patches."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from app.agentic.models import ExecutionPlan, ToolResult
from app.agentic.runtime.checkpoint import Checkpoint, CheckpointOption

MATCH_SELECTION_CHECKPOINT_TYPE = "pandascore_match_selection"
MATCH_GAMES_TOOL = "pandascore.resolve_match_games"


def match_selection_checkpoint(result: ToolResult) -> Checkpoint | None:
    """Build the pilot Checkpoint for an ambiguous PandaScore match lookup."""

    if result.tool != MATCH_GAMES_TOOL or result.status != "ok":
        return None
    data = result.data if isinstance(result.data, dict) else {}
    if data.get("status") != "ambiguous":
        return None
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        return None

    options: list[CheckpointOption] = []
    used_ids: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        scheduled_date = _candidate_date(candidate)
        if scheduled_date is None:
            continue
        stage = _stage_name(candidate)
        option_id = f"{_slug(stage)}_{scheduled_date.isoformat()}"
        match_id = candidate.get("pandascore_match_id")
        if option_id in used_ids and isinstance(match_id, int):
            option_id = f"{option_id}_{match_id}"
        used_ids.add(option_id)
        options.append(
            CheckpointOption(
                id=option_id,
                label=(
                    f"{scheduled_date.month} 月 {scheduled_date.day} 日 · "
                    f"{stage} · {_fixture_label(candidate)}"
                ),
                value={"scheduled_date": scheduled_date.isoformat()},
            )
        )
    if not options:
        return None

    match_name = _fixture_label(candidates[0]) if isinstance(candidates[0], dict) else "该对阵"
    return Checkpoint(
        checkpoint_type=MATCH_SELECTION_CHECKPOINT_TYPE,
        question=f"找到 {len(candidates)} 场 {match_name}，请选择要查看详情的比赛。",
        options=options,
        source_tool_call_id=result.tool_call_id,
        resume_node="tools",
    )


def apply_match_selection(
    plan: ExecutionPlan,
    checkpoint: Checkpoint,
    selected_option_id: str | None,
) -> ExecutionPlan:
    """Patch the persisted match lookup with the server-selected UTC date."""

    if checkpoint.checkpoint_type != MATCH_SELECTION_CHECKPOINT_TYPE:
        return plan.model_copy(deep=True)
    if selected_option_id is None:
        raise ValueError("checkpoint selection is missing")
    option = next(
        (candidate for candidate in checkpoint.options if candidate.id == selected_option_id),
        None,
    )
    if option is None:
        raise ValueError("checkpoint option is invalid")
    scheduled_date = option.value.get("scheduled_date")
    if not isinstance(scheduled_date, str):
        raise ValueError("checkpoint option has no scheduled_date")
    try:
        date.fromisoformat(scheduled_date)
    except ValueError as exc:
        raise ValueError("checkpoint option has invalid scheduled_date") from exc

    patched = plan.model_copy(deep=True)
    source_call = next(
        (call for call in patched.tool_calls if call.id == checkpoint.source_tool_call_id),
        None,
    )
    if source_call is None or source_call.tool != MATCH_GAMES_TOOL:
        raise ValueError("checkpoint source tool call is unavailable")
    source_call.args["scheduled_date"] = scheduled_date
    return patched


def _candidate_date(candidate: dict[str, Any]) -> date | None:
    value = candidate.get("scheduled_at") or candidate.get("begin_at")
    if isinstance(value, datetime):
        return value.astimezone(UTC).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _stage_name(candidate: dict[str, Any]) -> str:
    tournament = candidate.get("tournament")
    if isinstance(tournament, dict) and tournament.get("name"):
        return str(tournament["name"])
    return "比赛"


def _fixture_label(candidate: dict[str, Any]) -> str:
    name = str(candidate.get("name") or candidate.get("pandascore_match_id") or "该对阵")
    opponents = candidate.get("opponents")
    results = candidate.get("results")
    if not isinstance(opponents, list) or len(opponents) != 2 or not isinstance(results, list):
        return name
    names: list[str] = []
    scores: dict[int, int] = {}
    for opponent in opponents:
        team = opponent.get("opponent") if isinstance(opponent, dict) else None
        if not isinstance(team, dict) or team.get("id") is None or not team.get("name"):
            return name
        names.append(str(team["name"]))
    for result in results:
        if not isinstance(result, dict):
            continue
        team_id = result.get("team_id")
        score = result.get("score")
        if isinstance(team_id, int) and isinstance(score, int):
            scores[team_id] = score
    if len(scores) != 2:
        return name
    team_ids = [
        opponent["opponent"]["id"]
        for opponent in opponents
        if isinstance(opponent, dict)
        and isinstance(opponent.get("opponent"), dict)
        and isinstance(opponent["opponent"].get("id"), int)
    ]
    if len(team_ids) != 2 or any(team_id not in scores for team_id in team_ids):
        return name
    return f"{names[0]} {scores[team_ids[0]]}–{scores[team_ids[1]]} {names[1]}"


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return normalized or "match"


__all__ = [
    "MATCH_GAMES_TOOL",
    "MATCH_SELECTION_CHECKPOINT_TYPE",
    "apply_match_selection",
    "match_selection_checkpoint",
]
