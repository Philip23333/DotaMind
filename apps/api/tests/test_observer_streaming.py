from app.agentic.runtime.streaming import (
    ObserverStreamEvent,
    bind_stream_event_publisher,
    publish_observer_event,
    reset_stream_event_publisher,
)
from app.application.redis_run_event_bus import _parse_event
from app.core.config import Settings


def _event() -> ObserverStreamEvent:
    return ObserverStreamEvent(
        kind="model_prompt",
        stage="controller",
        call_id="controller:0",
        name="controller",
        attempt_index=0,
        payload={"messages": [{"role": "user", "content": "hello"}]},
    )


def test_test_observer_event_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: Settings(test_observer_enabled=False),
    )
    published = []
    token = bind_stream_event_publisher(published.append)
    try:
        publish_observer_event(_event())
    finally:
        reset_stream_event_publisher(token)

    assert published == []


def test_test_observer_event_publishes_and_round_trips_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: Settings(test_observer_enabled=True),
    )
    published = []
    token = bind_stream_event_publisher(published.append)
    try:
        publish_observer_event(_event())
    finally:
        reset_stream_event_publisher(token)

    assert published == [_event()]
    assert _parse_event(published[0].model_dump(mode="json")) == _event()
