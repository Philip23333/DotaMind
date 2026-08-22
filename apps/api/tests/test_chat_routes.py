from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.chat_routes import router
from app.application.chat_repository import (
    ChatSessionSnapshot,
    ChatSessionSummary,
    ChatTranscriptTurn,
)


def test_get_session_compacts_legacy_public_response() -> None:
    browser_id = str(uuid4())
    session_id = uuid4()
    now = datetime.now(UTC)
    api = FastAPI()
    api.include_router(router)
    api.state.chat_repository = LegacyResponseRepository(
        ChatSessionSnapshot(
            summary=ChatSessionSummary(
                session_id=session_id,
                game="dota2",
                title="Chat",
                title_is_custom=False,
                is_pinned=False,
                created_at=now,
                updated_at=now,
            ),
            turns=[
                ChatTranscriptTurn(
                    turn_index=1,
                    request_id=uuid4(),
                    user_query="details",
                    public_response={
                        "status": "ok",
                        "answer": {"summary": "done"},
                        "runtime": {"duration_ms": 1},
                        "tool_results": [{"data": {"raw_sentinel": "must-not-return"}}],
                        "evidence_graph": {"raw_sentinel": "must-not-return"},
                    },
                    created_at=now,
                )
            ],
        )
    )

    with TestClient(api) as client:
        response = client.get(
            f"/chat/sessions/{session_id}",
            headers={"X-DotaMind-Browser-Id": browser_id},
        )

    assert response.status_code == 200
    public_response = response.json()["turns"][0]["public_response"]
    assert public_response == {
        "status": "ok",
        "answer": {"summary": "done"},
        "runtime": {"duration_ms": 1},
    }


def test_get_session_keeps_visual_entities_from_compact_public_response() -> None:
    browser_id = str(uuid4())
    session_id = uuid4()
    now = datetime.now(UTC)
    visual_entities = [
        {
            "kind": "hero",
            "imagePath": "/api/v1/assets/dota/heroes/18.png",
            "label": "斯温",
            "names": ["斯温", "Sven"],
        }
    ]
    api = FastAPI()
    api.include_router(router)
    api.state.chat_repository = LegacyResponseRepository(
        ChatSessionSnapshot(
            summary=ChatSessionSummary(
                session_id=session_id,
                game="dota2",
                title="Chat",
                title_is_custom=False,
                is_pinned=False,
                created_at=now,
                updated_at=now,
            ),
            turns=[
                ChatTranscriptTurn(
                    turn_index=1,
                    request_id=uuid4(),
                    user_query="details",
                    public_response={
                        "status": "ok",
                        "answer": {"summary": "# 斯温"},
                        "runtime": {"duration_ms": 1},
                        "catalog_visual_entities": visual_entities,
                    },
                    created_at=now,
                )
            ],
        )
    )

    with TestClient(api) as client:
        response = client.get(
            f"/chat/sessions/{session_id}",
            headers={"X-DotaMind-Browser-Id": browser_id},
        )

    assert response.status_code == 200
    assert response.json()["turns"][0]["public_response"]["catalog_visual_entities"] == (
        visual_entities
    )


class LegacyResponseRepository:
    def __init__(self, snapshot: ChatSessionSnapshot) -> None:
        self.snapshot = snapshot

    async def get_session(self, browser_id: str, session_id):
        return self.snapshot
