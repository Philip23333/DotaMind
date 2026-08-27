"""Projection of durable dialogue into model-visible vNext context."""

from collections.abc import Sequence

from app.agentic.conversation.models import DialogueTurn
from app.vnext.llm.protocol import FinalMessage, Message, UserMessage


class ConversationContextBuilder:
    """Project durable dialogue into model-visible conversation context."""

    def build(self, turns: Sequence[DialogueTurn], query: str) -> list[Message]:
        messages: list[Message] = []
        for turn in turns:
            messages.extend(
                (
                    UserMessage(content=turn.user_message),
                    FinalMessage(content=turn.assistant_message),
                )
            )
        messages.append(UserMessage(content=query))
        return messages


__all__ = ["ConversationContextBuilder"]
