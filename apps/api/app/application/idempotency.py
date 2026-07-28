"""Request-idempotency value objects for stateful plan requests."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

RequestStatus = Literal["in_progress", "completed", "failed"]
RequestBeginAction = Literal["execute", "replay", "conflict"]


def build_request_hash(*, query: str, game: str) -> str:
    """Hash the exact validated execution inputs with canonical JSON."""

    payload = json.dumps(
        {"game": game, "query": query},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RequestRecord(BaseModel):
    """Allowlisted state needed to replay one completed stateful request."""

    request_id: UUID
    request_hash: str
    status: RequestStatus
    owner_token: UUID
    run_id: UUID | None = None
    cached_public_response: dict[str, Any] | None = None
    turn_index: int | None = None
    started_at: datetime
    completed_at: datetime | None = None
    expires_at: datetime


class RequestBeginResult(BaseModel):
    """Deterministic result of claiming, replaying, or rejecting a request."""

    action: RequestBeginAction
    owner_token: UUID | None = None
    cached_public_response: dict[str, Any] | None = None
    existing_request_hash: str | None = None


class IdempotencyConflictError(Exception):
    """Raised before Graph execution when one key receives different inputs."""

    def __init__(self, *, query: str, game: str, session_id: str) -> None:
        super().__init__("request_id has already been used with different request inputs")
        self.query = query
        self.game = game
        self.session_id = session_id
