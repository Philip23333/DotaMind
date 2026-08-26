"""Run the configured vNext agent against its real model and provider adapters."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.tool_result_summary import summarize_tool_result
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
    if args.result_name and args.interactive:
        parser.error("--result-name is available only for one-shot runs")
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


def _event_tool_states(events: list[dict[str, Any]]) -> dict[str, dict[str, str | None]]:
    states: dict[str, dict[str, str | None]] = {}
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
                    result.error.code
                    if result is not None and result.error is not None
                    else event_state["error"]
                    if event_state is not None
                    else None
                ),
                "result": (
                    summarize_tool_result(call.name, result.content)
                    if result is not None and result.status == "ok"
                    else None
                ),
            }
        )
    return rows


def _write_result(
    *,
    name: str,
    prompt: str,
    answer: str | None,
    terminal_error: Exception | None,
    model_steps: int,
    calls: list[ToolCall],
    results: list[ToolResultMessage],
    events: list[dict[str, Any]],
    result_dir: Path = _RESULT_DIR,
) -> Path:
    payload = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "name": name,
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
        "events": events,
    }
    result_dir.mkdir(parents=True, exist_ok=True)
    destination = result_dir / f"{name}.json"
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
) -> tuple[FinalMessage | None, list[Message], Path, Exception | None]:
    response_start = len(model.responses)
    request_start = len(model.requests)
    events: list[dict[str, Any]] = []

    def record_event(event: Any) -> None:
        events.append(event.model_dump(mode="json"))

    try:
        final = await runtime.run(
            [*history, UserMessage(content=prompt)],
            event_sink=record_event,
        )
    except Exception as exc:
        calls = _tool_calls(model, start=response_start)
        results = _tool_results(model, start=request_start)
        destination = _write_result(
            name=result_name,
            prompt=prompt,
            answer=None,
            terminal_error=exc,
            model_steps=len(model.responses) - response_start,
            calls=calls,
            results=results,
            events=events,
        )
        return None, list(history), destination, exc

    calls = _tool_calls(model, start=response_start)
    results = _tool_results(model, start=request_start)
    destination = _write_result(
        name=result_name,
        prompt=prompt,
        answer=final.content,
        terminal_error=None,
        model_steps=len(model.responses) - response_start,
        calls=calls,
        results=results,
        events=events,
    )
    return final, [*model.requests[-1].messages, final], destination, None


async def _run(args: argparse.Namespace) -> int:
    settings = VNextSettings.from_env()
    services = build_vnext_services(settings)
    base_runtime = build_vnext_runtime(settings, services=services)
    model = _TracingModelClient(base_runtime.model)
    runtime = AgentRuntime(model, base_runtime.tools, limits=base_runtime.limits)
    try:
        if args.prompt:
            prompt = " ".join(args.prompt)
            final, _history, destination, error = await _run_turn(
                runtime,
                model,
                [],
                prompt,
                args.result_name or _new_result_name(),
            )
            _print_console(f"Result trace: {destination}")
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
                _new_result_name(),
            )
            _print_console(f"Result trace: {destination}")
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
