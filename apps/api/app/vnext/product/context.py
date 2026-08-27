"""Projection of durable dialogue into model-visible vNext context."""

from collections.abc import Sequence

from app.agentic.conversation.models import DialogueTurn
from app.vnext.llm.protocol import FinalMessage, Message, UserMessage

DEFAULT_MAX_TURNS = 12
DEFAULT_MAX_HISTORY_CHARS = 40_000


class ConversationContextBuilder:
    """Project durable dialogue into model-visible conversation context."""

    def __init__(
        self,
        *,
        max_turns: int = DEFAULT_MAX_TURNS,
        max_history_chars: int = DEFAULT_MAX_HISTORY_CHARS,
    ) -> None:
        if max_turns < 1:
            raise ValueError("max_turns must be at least 1")
        if max_history_chars < 1:
            raise ValueError("max_history_chars must be at least 1")
        self._max_turns = max_turns
        self._max_history_chars = max_history_chars

    def build(self, turns: Sequence[DialogueTurn], query: str) -> list[Message]:
        selected: list[DialogueTurn] = []
        history_chars = 0
        for turn in reversed(turns):
            if len(selected) >= self._max_turns:
                break
            turn_chars = len(turn.user_message) + len(turn.assistant_message)
            if history_chars + turn_chars > self._max_history_chars:
                break
            selected.append(turn)
            history_chars += turn_chars

        messages: list[Message] = []
        for turn in reversed(selected):
            messages.extend(
                (
                    UserMessage(content=turn.user_message),
                    FinalMessage(content=turn.assistant_message),
                )
            )
        messages.append(UserMessage(content=query))
        return messages


__all__ = [
    "ConversationContextBuilder",
    "DEFAULT_MAX_HISTORY_CHARS",
    "DEFAULT_MAX_TURNS",
]
