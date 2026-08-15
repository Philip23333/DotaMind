"""Pure rendering helpers for the Controller prompt surface."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from app.agentic.conversation.models import ConversationMessage
from app.agentic.planning.contracts import render_controller_contracts, render_controller_tools
from app.agentic.planning.sample_policy import render_sample_policy
from app.agentic.prompts import controller_rules
from app.agentic.prompts.versions import build_prompt_versions
from app.agentic.tools import ToolRegistry
from app.core.config import AppPolicy


@dataclass(frozen=True)
class ControllerPromptBundle:
    system_prompt: str
    prompt_versions: dict[str, str]


def build_controller_prompt(
    registry: ToolRegistry,
    policy: AppPolicy,
) -> ControllerPromptBundle:
    tools = render_controller_tools(registry)
    rendered_contracts = render_controller_contracts(registry)
    sample_policy = render_sample_policy(policy, registry)
    base = (
        controller_rules.PLANNER_SYSTEM_PROMPT.replace("{tools}", tools)
        .replace("{contracts}", rendered_contracts)
        .replace("{sample_policy}", sample_policy)
    )
    system_prompt = controller_rules.CONVERSATION_HISTORY_RULES + base
    return ControllerPromptBundle(
        system_prompt=system_prompt,
        prompt_versions=build_prompt_versions(system_prompt),
    )


def render_controller_system_prompt(
    system_prompt: str,
    game: str,
    runtime_context: Mapping[str, str] | None = None,
    request_time: str | None = None,
) -> str:
    """Append request-scoped game metadata without wrapping the user query."""

    lines = [
        "",
        "Runtime context:",
        f"- game: {game}",
        f"- request_time: {request_time or datetime.now(UTC).isoformat()}",
    ]
    for key, value in (runtime_context or {}).items():
        lines.append(f"- {key}: {value}")
    return f"{system_prompt}\n" + "\n".join(lines)


def render_controller_messages(
    query: str,
    _game: str,
    recent_messages: list[ConversationMessage],
    retrieved_messages: list[ConversationMessage] | None = None,
) -> list[dict[str, str]]:
    """Render real alternating conversation messages plus the current query."""

    messages_by_key = {
        (message.turn_index, message.role): message
        for message in [*(retrieved_messages or []), *recent_messages]
    }
    role_order = {"user": 0, "assistant": 1}
    ordered = sorted(
        messages_by_key.values(),
        key=lambda item: (item.turn_index, role_order[item.role]),
    )
    rendered: list[dict[str, str]] = [
        {"role": message.role, "content": message.content}
        for message in ordered
        if message.content
    ]
    rendered.append({"role": "user", "content": query})
    return rendered
