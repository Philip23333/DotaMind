from app.agentic.runtime.streaming import CheckpointStreamEvent
from app.application.redis_run_event_bus import _parse_event


def test_checkpoint_event_round_trips_through_event_parser() -> None:
    event = CheckpointStreamEvent(
        checkpoint={
            "checkpoint_type": "selection",
            "question": "请选择比赛。",
            "options": [],
            "source_tool_call_id": "resolve_games",
            "resume_node": "tools",
        }
    )

    parsed = _parse_event(event.model_dump(mode="json"))

    assert parsed.type == "checkpoint"
    assert parsed.checkpoint["source_tool_call_id"] == "resolve_games"
