from __future__ import annotations

from uuid import uuid4

from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory


def test_raw_records_are_defensive_and_effective_history_is_replaceable() -> None:
    history = SessionExecutionHistory()
    request_id = uuid4()
    tool_call = ToolCall(id="same", name="lookup", arguments={"key": "a"})
    assistant = AssistantMessage(tool_calls=[tool_call])
    result = ToolResultMessage(tool_call_id="same", content={"value": [1]})
    history.begin_request(request_id, "first", initial_messages=[])
    history.record(request_id, assistant, kind="assistant_tool_call")
    history.record_tool_results(request_id, [result])

    result.content["value"].append(2)  # type: ignore[index]
    history.set_effective([FinalMessage(content="receipt")])

    assert history.records[1].message == assistant
    assert history.records[2].message == ToolResultMessage(
        tool_call_id="same", content={"value": [1]}
    )
    assert history.effective_messages() == [FinalMessage(content="receipt")]


def test_each_request_gets_one_user_record_without_rebuilding_projection() -> None:
    history = SessionExecutionHistory()
    first_id = uuid4()
    second_id = uuid4()
    history.begin_request(first_id, "first", initial_messages=[])
    history.set_effective([UserMessage(content="first"), FinalMessage(content="answer")])
    second_messages = history.begin_request(second_id, "second")

    assert second_messages == [
        UserMessage(content="first"),
        FinalMessage(content="answer"),
        UserMessage(content="second"),
    ]
    assert [record.kind for record in history.records] == ["user", "user"]
