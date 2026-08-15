"""Internal tools for retrieving older conversation messages."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.agentic.models import QueryContext
from app.agentic.tools.registry import ToolDefinition, ToolRegistry
from app.application.history_lookup import lookup_history


class ConversationHistoryLookupInput(BaseModel):
    query_text: str | None = Field(default=None, max_length=200)
    turn_indexes: list[int] = Field(
        default_factory=list,
        max_length=8,
    )
    before_turn_index: int | None = Field(default=None, ge=1)
    limit: int = Field(default=8, ge=1, le=8)

    @model_validator(mode="after")
    def validate_lookup_selector(self) -> ConversationHistoryLookupInput:
        if not (
            (self.query_text and self.query_text.strip())
            or self.turn_indexes
            or self.before_turn_index is not None
        ):
            raise ValueError(
                "conversation.history_lookup requires query_text, turn_indexes, "
                "or before_turn_index"
            )
        if any(index < 1 for index in self.turn_indexes):
            raise ValueError("turn_indexes must contain only positive turn indexes")
        self.turn_indexes = list(dict.fromkeys(self.turn_indexes))
        return self


async def _history_lookup_handler(
    args: ConversationHistoryLookupInput,
    _context: QueryContext,
) -> dict[str, Any]:
    return await lookup_history(
        query_text=args.query_text,
        turn_indexes=args.turn_indexes or None,
        before_turn_index=args.before_turn_index,
        limit=args.limit,
    )


def register_conversation_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="conversation.history_lookup",
            description=(
                "Retrieve additional older user/assistant messages from the current "
                "conversation."
            ),
            input_model=ConversationHistoryLookupInput,
            handler=_history_lookup_handler,
            result_destination="controller_context",
            metadata={"internal": True},
        )
    )


__all__ = ["ConversationHistoryLookupInput", "register_conversation_tools"]
