"""Run the configured vNext agent against its real model and provider adapters."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.composition import VNextSettings, build_vnext_runtime, build_vnext_services
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    Message,
    ModelClient,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.tools.registry import ToolRegistry

_RESULT_DIR = Path(__file__).resolve().parents[1] / "tests" / "vnext" / "testResult"
_SAFE_RESULT_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")


class _TracingModelClient:
    """Record complete model turns without changing AgentRuntime behavior."""

    def __init__(self, client: ModelClient) -> None:
        self._client = client
        self.requests: list[ModelRequest] = []
        self.responses: list[ModelResponse] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request.model_copy(deep=True))
        response = await self._client.complete(request)
        self.responses.append(response.model_copy(deep=True))
        return response


class _TracingToolRegistry:
    """Copy complete tool results before the runtime advances to another model step."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self.results: list[ToolResultMessage] = []

    def schemas(self):
        return self._registry.schemas()

    def get(self, name: str):
        return self._registry.get(name)

    async def execute(
        self,
        call: ToolCall,
        *,
        timeout: float | None = None,
    ) -> ToolResultMessage:
        result = await self._registry.execute(call, timeout=timeout)
        self.results.append(result.model_copy(deep=True))
        return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the configured vNext agent through its real model and provider chain."
    )
    parser.add_argument("prompt", nargs="*", help="One user question to run.")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Keep a conversation open; type /exit to leave.",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Disable proxy environment variables for this console process only.",
    )
    parser.add_argument(
        "--result-name",
        help="Optional safe result basename for a one-shot run (without .json).",
    )
    args = parser.parse_args()
    if not args.prompt and not args.interactive:
        parser.error("provide a prompt or pass --interactive")
    if args.result_name and not _SAFE_RESULT_NAME.fullmatch(args.result_name):
        parser.error("--result-name may contain only letters, digits, underscores, and hyphens")
    return args


def _disable_proxies_for_process() -> None:
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        os.environ.pop(name, None)


def _console_text(value: str, *, encoding: str | None = None) -> str:
    """Keep a completed run from failing when the active Windows console is GBK."""

    resolved_encoding = encoding or sys.stdout.encoding or "utf-8"
    return value.encode(resolved_encoding, errors="replace").decode(resolved_encoding)


def _print_console(value: str) -> None:
    print(_console_text(value))


def _tool_calls(model: _TracingModelClient, *, start: int) -> list[ToolCall]:
    return [
        call
        for response in model.responses[start:]
        if isinstance(response.message, AssistantMessage)
        for call in response.message.tool_calls
    ]


def _tool_results(model: _TracingModelClient, *, start: int) -> list[ToolResultMessage]:
    results: list[ToolResultMessage] = []
    seen_ids: set[str] = set()
    for request in model.requests[start:]:
        for message in request.messages:
            if isinstance(message, ToolResultMessage) and message.tool_call_id not in seen_ids:
                seen_ids.add(message.tool_call_id)
                results.append(message)
    return results


def _event_tool_states(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for event in events:
        kind = event["kind"]
        if kind == "tool_completed":
            states[event["tool_call_id"]] = {"status": "ok", "error": None}
        elif kind == "tool_failed":
            states[event["tool_call_id"]] = {
                "status": "error",
                "error": event["error_code"],
            }
    return states


def _trace_rows(
    calls: list[ToolCall],
    results: list[ToolResultMessage],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result_by_id = {result.tool_call_id: result for result in results}
    event_states = _event_tool_states(events)
    rows: list[dict[str, Any]] = []
    for call in calls:
        result = result_by_id.get(call.id)
        event_state = event_states.get(call.id)
        rows.append(
            {
                "tool_call_id": call.id,
                "tool": call.name,
                "arguments": call.arguments,
                "status": (
                    result.status
                    if result is not None
                    else event_state["status"]
                    if event_state is not None
                    else "not_returned"
                ),
                "error": (
                    result.error.model_dump(mode="json")
                    if result is not None and result.error is not None
                    else event_state["error"]
                    if event_state is not None
                    else None
                ),
                "result": result.content if result is not None else None,
            }
        )
    return rows


@dataclass
class _ConversationTrace:
    """Persist every completed console turn in one local conversation record."""

    name: str
    result_dir: Path = _RESULT_DIR
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    turns: list[dict[str, Any]] = field(default_factory=list)

    def append_turn(
        self,
        *,
        prompt: str,
        answer: str | None,
        terminal_error: Exception | None,
        model_steps: int,
        calls: list[ToolCall],
        results: list[ToolResultMessage],
        events: list[dict[str, Any]],
        agent_trace: dict[str, Any],
    ) -> Path:
        self.turns.append(
            {
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "terminal_status": "final" if terminal_error is None else "error",
                "prompt": prompt,
                "answer": answer,
                "terminal_error": (
                    None
                    if terminal_error is None
                    else {"type": type(terminal_error).__name__, "message": str(terminal_error)}
                ),
                "model_steps": model_steps,
                "trace": _trace_rows(calls, results, events),
                "agent_trace": agent_trace,
                "events": events,
            }
        )
        return self.write()

    def write(self) -> Path:
        payload = {
            "recorded_at": self.recorded_at,
            "name": self.name,
            "turns": self.turns,
        }
        self.result_dir.mkdir(parents=True, exist_ok=True)
        destination = self.result_dir / f"{self.name}.json"
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
        return destination


def _new_result_name() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"console_{timestamp}_{uuid4().hex[:8]}"


async def _run_turn(
    runtime: AgentRuntime,
    model: _TracingModelClient,
    history: Sequence[Message],
    prompt: str,
    result_name: str,
    *,
    conversation: _ConversationTrace | None = None,
    tool_trace: _TracingToolRegistry | None = None,
) -> tuple[FinalMessage | None, list[Message], Path, Exception | None]:
    response_start = len(model.responses)
    request_start = len(model.requests)
    result_start = len(tool_trace.results) if tool_trace is not None else None
    events: list[dict[str, Any]] = []
    recorder = conversation or _ConversationTrace(name=result_name)
    trace_collector = AgentTraceCollector()

    def record_event(event: Any) -> None:
        events.append(event.model_dump(mode="json"))

    try:
        final = await runtime.run(
            [*history, UserMessage(content=prompt)],
            event_sink=record_event,
            trace_collector=trace_collector,
        )
    except Exception as exc:
        calls = _tool_calls(model, start=response_start)
        results = (
            tool_trace.results[result_start:]
            if tool_trace is not None and result_start is not None
            else _tool_results(model, start=request_start)
        )
        destination = recorder.append_turn(
            prompt=prompt,
            answer=None,
            terminal_error=exc,
            model_steps=len(model.responses) - response_start,
            calls=calls,
            results=results,
            events=events,
            agent_trace=trace_collector.snapshot(),
        )
        return None, list(history), destination, exc

    calls = _tool_calls(model, start=response_start)
    results = (
        tool_trace.results[result_start:]
        if tool_trace is not None and result_start is not None
        else _tool_results(model, start=request_start)
    )
    destination = recorder.append_turn(
        prompt=prompt,
        answer=final.content,
        terminal_error=None,
        model_steps=len(model.responses) - response_start,
        calls=calls,
        results=results,
        events=events,
        agent_trace=trace_collector.snapshot(),
    )
    return final, [*model.requests[-1].messages, final], destination, None


async def _run(args: argparse.Namespace) -> int:
    settings = VNextSettings.from_env()
    services = build_vnext_services(settings)
    base_runtime = build_vnext_runtime(settings, services=services)
    model = _TracingModelClient(base_runtime.model)
    tool_trace = _TracingToolRegistry(base_runtime.tools)
    runtime = AgentRuntime(
        model,
        tool_trace,
        limits=base_runtime.limits,
        system_instruction=base_runtime.system_instruction,
    )
    try:
        conversation = _ConversationTrace(name=args.result_name or _new_result_name())
        if args.prompt:
            prompt = " ".join(args.prompt)
            final, _history, destination, error = await _run_turn(
                runtime,
                model,
                [],
                prompt,
                conversation.name,
                conversation=conversation,
                tool_trace=tool_trace,
            )
            _print_console(f"Conversation trace: {destination}")
            if error is not None:
                _print_console(f"Agent failed: {type(error).__name__}: {error}")
                return 1
            _print_console(final.content)
            return 0

        history: list[Message] = []
        _print_console("vNext console ready. Type /exit to leave.")
        while True:
            try:
                prompt = input("vNext> ").strip()
            except EOFError:
                _print_console("")
                return 0
            if prompt in {"/exit", "/quit"}:
                return 0
            if not prompt:
                continue
            final, history, destination, error = await _run_turn(
                runtime,
                model,
                history,
                prompt,
                conversation.name,
                conversation=conversation,
                tool_trace=tool_trace,
            )
            _print_console(f"Conversation trace: {destination}")
            if error is not None:
                _print_console(f"Agent failed: {type(error).__name__}: {error}")
                continue
            _print_console(final.content)
    finally:
        await services.aclose()


def main() -> int:
    args = parse_args()
    if args.direct:
        _disable_proxies_for_process()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
