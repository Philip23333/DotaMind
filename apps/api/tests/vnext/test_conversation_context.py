"""Deterministic contracts for durable-dialogue context projection."""

import pytest

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


def test_small_history_is_preserved_before_the_current_query() -> None:
    messages = ConversationContextBuilder().build([_turn(index) for index in range(1, 6)], "now")

    assert len(messages) == 11
    assert messages[0] == UserMessage(content="user 1")
    assert messages[-2] == FinalMessage(content="assistant 5")
    assert messages[-1] == UserMessage(content="now")


def test_turn_count_keeps_the_recent_complete_turn_suffix() -> None:
    messages = ConversationContextBuilder(max_turns=12).build(
        [_turn(index) for index in range(1, 21)], "now"
    )

    assert len(messages) == 25
    assert messages[0] == UserMessage(content="user 9")
    assert messages[-2] == FinalMessage(content="assistant 20")
    assert messages[-1] == UserMessage(content="now")


def test_character_budget_keeps_a_contiguous_recent_turn_suffix() -> None:
    turns = [
        DialogueTurn(
            turn_index=index,
            user_message=f"u{index}" + "u" * 48,
            assistant_message=f"a{index}" + "a" * 48,
        )
        for index in range(1, 4)
    ]

    messages = ConversationContextBuilder(max_history_chars=220).build(turns, "now")

    assert messages == [
        UserMessage(content="u2" + "u" * 48),
        FinalMessage(content="a2" + "a" * 48),
        UserMessage(content="u3" + "u" * 48),
        FinalMessage(content="a3" + "a" * 48),
        UserMessage(content="now"),
    ]


def test_budget_never_splits_a_turn_or_skips_a_large_middle_turn() -> None:
    turns = [
        DialogueTurn(turn_index=1, user_message="old", assistant_message="old"),
        DialogueTurn(turn_index=2, user_message="u" * 60, assistant_message="a" * 60),
        DialogueTurn(turn_index=3, user_message="recent", assistant_message="recent"),
    ]

    messages = ConversationContextBuilder(max_history_chars=100).build(turns, "now")

    assert messages == [
        UserMessage(content="recent"),
        FinalMessage(content="recent"),
        UserMessage(content="now"),
    ]


def test_oversized_latest_turn_leaves_only_the_current_query() -> None:
    messages = ConversationContextBuilder(max_history_chars=10).build(
        [DialogueTurn(turn_index=1, user_message="u" * 6, assistant_message="a" * 6)],
        "current",
    )

    assert messages == [UserMessage(content="current")]


def test_current_query_is_not_counted_against_the_history_budget() -> None:
    query = "q" * 1_000

    assert ConversationContextBuilder(max_history_chars=1).build([], query) == [
        UserMessage(content=query)
    ]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_turns": 0}, "max_turns"),
        ({"max_history_chars": 0}, "max_history_chars"),
    ],
)
def test_invalid_context_limits_are_rejected(kwargs: dict[str, int], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ConversationContextBuilder(**kwargs)
