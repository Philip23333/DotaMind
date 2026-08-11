"""Strict Redis persistence DTOs for recent dialogue and request state."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.agentic.conversation.models import RecentDialogueWindow, Turn
from app.application.idempotency import RequestRecord


class _StrictRedisModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StoredTurnDataV2(_StrictRedisModel):
    turn_index: int = Field(ge=0)
    query: str
    status: Literal[
        "ok",
        "clarification_required",
        "insufficient_context",
        "insufficient_tools",
        "insufficient_evidence",
        "error",
    ]
    response_type: str | None = None
    intent: str | None = None
    context_scope: dict[str, Any]
    missing_fields: list[str]
    response_summary: str


class StoredTurnV2(_StrictRedisModel):
    schema_version: Literal[2] = 2
    data: StoredTurnDataV2


class StoredRequestRecordDataV1(_StrictRedisModel):
    request_id: UUID
    payload_hash: str
    status: Literal["in_progress", "completed", "failed"]
    owner_token: UUID
    run_id: UUID | None = None
    cached_public_response: dict[str, Any] | None = None
    turn_index: int | None = None
    started_at: datetime
    completed_at: datetime | None = None
    expires_at: datetime


class StoredRequestRecordV1(_StrictRedisModel):
    schema_version: Literal[1] = 1
    data: StoredRequestRecordDataV1


def canonical_json(value: BaseModel | dict[str, Any]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def serialize_turn(turn: Turn) -> str:
    return canonical_json(
        StoredTurnV2(
            data=StoredTurnDataV2(
                turn_index=turn.turn_index,
                query=turn.query,
                status=turn.status,
                response_type=turn.response_type,
                intent=turn.intent,
                context_scope=turn.context_scope,
                missing_fields=turn.missing_fields,
                response_summary=turn.response_summary,
            )
        )
    )


def deserialize_turn(payload: str) -> Turn:
    try:
        stored = StoredTurnV2.model_validate(json.loads(payload))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid stored turn") from exc
    return Turn(
        turn_index=stored.data.turn_index,
        query=stored.data.query,
        status=stored.data.status,
        response_type=stored.data.response_type,
        intent=stored.data.intent,
        context_scope=stored.data.context_scope,
        missing_fields=stored.data.missing_fields,
        response_summary=stored.data.response_summary,
    )


class StoredRecentDialogueWindowV1(_StrictRedisModel):
    schema_version: Literal[1] = 1
    data: RecentDialogueWindow


def serialize_recent_dialogue(window: RecentDialogueWindow) -> str:
    return canonical_json(StoredRecentDialogueWindowV1(data=window))


def deserialize_recent_dialogue(payload: str) -> RecentDialogueWindow:
    try:
        stored = StoredRecentDialogueWindowV1.model_validate(json.loads(payload))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid stored recent dialogue") from exc
    return stored.data


def serialize_request_record(record: RequestRecord) -> str:
    return canonical_json(
        StoredRequestRecordV1(
            data=StoredRequestRecordDataV1.model_validate(record.model_dump())
        )
    )


def deserialize_request_record(payload: str) -> RequestRecord:
    try:
        stored = StoredRequestRecordV1.model_validate(json.loads(payload))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid stored request record") from exc
    return RequestRecord.model_validate(stored.data.model_dump())
