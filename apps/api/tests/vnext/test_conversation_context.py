"""Deterministic contracts for durable-dialogue context projection."""

from app.agentic.conversation.models import DialogueTurn
from app.vnext.llm.protocol import FinalMessage, UserMessage
from app.vnext.product.context import ConversationContextBuilder


def _turn(index: int) -> DialogueTurn:
    return DialogueTurn(
        turn_index=index,
        user_message=f"user {index}",
        assistant_message=f"assistant {index}",
    )


def test_empty_dialogue_contains_only_the_current_user_message() -> None:
    messages = ConversationContextBuilder().build([], "Ame在哪个战队？")

    assert messages == [UserMessage(content="Ame在哪个战队？")]


def test_dialogue_preserves_complete_turn_order_before_current_query() -> None:
    messages = ConversationContextBuilder().build(
        [
            DialogueTurn(
                turn_index=1,
                user_message="Ame在哪个战队？",
                assistant_message="Xtreme Gaming。",
            ),
            DialogueTurn(
                turn_index=2,
                user_message="最近一场呢？",
                assistant_message="最近一场已结束。",
            ),
        ],
        "他用了什么英雄？",
    )

    assert messages == [
        UserMessage(content="Ame在哪个战队？"),
        FinalMessage(content="Xtreme Gaming。"),
        UserMessage(content="最近一场呢？"),
        FinalMessage(content="最近一场已结束。"),
        UserMessage(content="他用了什么英雄？"),
    ]


def test_commit_one_context_builder_does_not_trim_long_dialogue() -> None:
    messages = ConversationContextBuilder().build([_turn(index) for index in range(1, 51)], "now")

    assert len(messages) == 101
    assert messages[0] == UserMessage(content="user 1")
    assert messages[-2] == FinalMessage(content="assistant 50")
    assert messages[-1] == UserMessage(content="now")
