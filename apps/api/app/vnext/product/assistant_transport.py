"""Project product chat states into official AssistantTransport state operations."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any, Protocol

from .chat import PreparedVNextChatTurn, ProductChatState

logger = logging.getLogger(__name__)
_SAFE_TRANSPORT_ERROR = "聊天流暂时不可用，请重试。"


class _StateController(Protocol):
    state: Any

    def append_state_text(self, path: list[str], text_delta: str) -> None: ...

    def add_error(self, error: str) -> None: ...


def product_state_envelope(
    prepared: PreparedVNextChatTurn,
    update: ProductChatState,
) -> dict[str, Any]:
    """Return the bounded, server-owned state sent for one accepted request."""

    return {
        "session_id": str(prepared.session_id),
        "request_id": str(prepared.request_id),
        "user_message": {
            "id": f"user:{prepared.request_id}",
            "text": prepared.query,
        },
        "run": update.state.model_dump(mode="json"),
        "turn_index": update.turn_index,
        "trace": update.trace.model_dump(mode="json") if update.trace is not None else None,
    }


def apply_product_state_update(
    controller: _StateController,
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> None:
    """Use official set and append-text state operations without resending the envelope."""

    if previous is None:
        controller.state = current
        return

    for key in ("session_id", "request_id", "user_message", "turn_index", "trace"):
        if previous[key] != current[key]:
            controller.state[key] = current[key]

    previous_run = previous["run"]
    current_run = current["run"]
    previous_answer = previous_run["answer"]
    current_answer = current_run["answer"]
    answer_identity_changed = (
        previous_answer["attempt_id"] != current_answer["attempt_id"]
        or previous_answer["kind"] != current_answer["kind"]
    )
    if answer_identity_changed:
        # One set keeps fallback attempt selection and its empty text atomic.
        controller.state["run"]["answer"] = current_answer
    else:
        old_text = previous_answer["text"]
        new_text = current_answer["text"]
        if new_text != old_text:
            if new_text.startswith(old_text):
                controller.append_state_text(
                    ["run", "answer", "text"],
                    new_text[len(old_text) :],
                )
            else:
                controller.state["run"]["answer"]["text"] = new_text
        for key, value in current_answer.items():
            if key != "text" and previous_answer[key] != value:
                controller.state["run"]["answer"][key] = value

    for key, value in current_run.items():
        if key != "answer" and previous_run[key] != value:
            controller.state["run"][key] = value


async def forward_product_states(
    prepared: PreparedVNextChatTurn,
    states: AsyncIterator[ProductChatState],
    controller: _StateController,
) -> None:
    previous: dict[str, Any] | None = None
    try:
        async for update in states:
            current = product_state_envelope(prepared, update)
            apply_product_state_update(controller, previous, current)
            previous = current
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("AssistantTransport state forwarding failed (%s)", type(exc).__name__)
        controller.add_error(_SAFE_TRANSPORT_ERROR)
    finally:
        close = getattr(states, "aclose", None)
        if callable(close):
            try:
                await close()
            except Exception as exc:
                logger.warning("could not close product state stream (%s)", type(exc).__name__)


__all__ = [
    "apply_product_state_update",
    "forward_product_states",
    "product_state_envelope",
]
