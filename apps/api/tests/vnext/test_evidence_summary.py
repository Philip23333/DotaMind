from __future__ import annotations

from app.vnext.agent.evidence_summary import HistoryCompactionRange
from app.vnext.llm.protocol import FinalMessage, ToolResultMessage, UserMessage


def test_history_compaction_range_is_a_small_immutable_data_contract() -> None:
    prefix = (UserMessage(content="old"),)
    retained = (FinalMessage(content="recent"),)

    result = HistoryCompactionRange(
        cut_index=1,
        prefix_messages=prefix,
        retained_messages=retained,
        retained_bytes=42,
    )

    assert result.cut_index == 1
    assert result.prefix_messages == prefix
    assert result.retained_messages == retained
    assert result.retained_bytes == 42


def test_range_contract_does_not_share_nested_message_content_with_input() -> None:
    message = ToolResultMessage(
        tool_call_id="read",
        content={"facts": [{"value": 1}]},
    )
    result = HistoryCompactionRange(
        cut_index=0,
        prefix_messages=(),
        retained_messages=(message.model_copy(deep=True),),
        retained_bytes=1,
    )

    message.content["facts"][0]["value"] = 9  # type: ignore[index]

    assert result.retained_messages[0].content == {"facts": [{"value": 1}]}


def test_range_parts_can_reconstruct_the_input_in_order() -> None:
    messages = (
        UserMessage(content="one"),
        FinalMessage(content="two"),
        UserMessage(content="three"),
    )
    result = HistoryCompactionRange(
        cut_index=2,
        prefix_messages=tuple(message.model_copy(deep=True) for message in messages[:2]),
        retained_messages=tuple(message.model_copy(deep=True) for message in messages[2:]),
        retained_bytes=10,
    )

    assert result.prefix_messages + result.retained_messages == messages
    assert result.cut_index == 2
