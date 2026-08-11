import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.agentic.conversation.models import DialogueTurn, RecentDialogueWindow, Turn
from app.application.idempotency import RequestRecord
from app.application.redis_models import (
    deserialize_request_record,
    deserialize_turn,
    serialize_request_record,
    serialize_turn,
)


def test_turn_round_trip_uses_schema_v2_envelope() -> None:
    turn = Turn(
        turn_index=3,
        query="enemy picked Lina",
        context_scope={"position": 3},
        response_summary="pick a durable offlaner",
    )

    payload = serialize_turn(turn)

    assert '"schema_version":2' in payload
    assert deserialize_turn(payload) == turn


def test_recent_dialogue_round_trip_uses_separate_schema_v1_envelope() -> None:
    from app.application.redis_models import deserialize_recent_dialogue, serialize_recent_dialogue

    window = RecentDialogueWindow(
        through_turn_index=3,
        turns=[
            DialogueTurn(
                turn_index=3,
                user_message="技能cd是多少？",
                assistant_message="请说明具体技能。",
            )
        ],
    )
    payload = serialize_recent_dialogue(window)
    assert '"schema_version":1' in payload
    assert deserialize_recent_dialogue(payload) == window


def test_request_record_round_trip_keeps_only_declared_fields() -> None:
    now = datetime.now(UTC)
    record = RequestRecord(
        request_id=uuid4(),
        payload_hash="payload-hash",
        status="completed",
        owner_token=uuid4(),
        run_id=uuid4(),
        cached_public_response={"status": "ok", "runtime": {"run_id": "safe"}},
        turn_index=4,
        started_at=now,
        completed_at=now,
        expires_at=now + timedelta(hours=1),
    )

    assert deserialize_request_record(serialize_request_record(record)) == record


def test_request_record_deserialization_rejects_invalid_schema() -> None:
    now = datetime.now(UTC)
    record = RequestRecord(
        request_id=uuid4(),
        payload_hash="payload-hash",
        status="in_progress",
        owner_token=uuid4(),
        started_at=now,
        expires_at=now + timedelta(hours=1),
    )
    valid = json.loads(serialize_request_record(record))
    unknown_version = {**valid, "schema_version": 2}
    missing_field = json.loads(json.dumps(valid))
    del missing_field["data"]["owner_token"]
    extra_field = json.loads(json.dumps(valid))
    extra_field["data"]["unexpected"] = True

    for payload in (unknown_version, missing_field, extra_field):
        with pytest.raises(ValueError, match="invalid stored request record"):
            deserialize_request_record(json.dumps(payload))


@pytest.mark.parametrize(
    "payload",
    [
        '{"schema_version":1,"data":{}}',
        '{"schema_version":1,"data":{"turn_index":1}}',
        '{"schema_version":1,"data":{"turn_index":1},"extra":true}',
        "not-json",
    ],
)
def test_turn_deserialization_rejects_unknown_or_invalid_schema(payload: str) -> None:
    with pytest.raises(ValueError, match="invalid stored turn"):
        deserialize_turn(payload)
