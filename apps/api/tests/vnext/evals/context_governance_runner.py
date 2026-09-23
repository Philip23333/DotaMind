"""Bounded real-model harness for fixed synthetic Context Governance cases.

Dry-run is the default. Network-capable execution requires the explicit
``--execute`` switch; importing this module never creates a model client.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel

from app.vnext.agent.instructions import AGENT_INSTRUCTION
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.task_state import TaskStateCoordinator
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.artifacts import (
    ArtifactBackedToolResultProcessor,
    ArtifactGrepper,
    ArtifactObservationTranscriptRewriter,
    ArtifactReader,
    SessionArtifactStore,
    ToolResponseExternalizer,
)
from app.vnext.composition import VNextSettings
from app.vnext.llm.openai_compatible import OpenAICompatibleModelClient
from app.vnext.llm.protocol import ModelRequest, ModelResponse
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools.artifacts import register_artifact_tools
from app.vnext.tools.definition import ToolContextEffect, ToolDefinition
from app.vnext.tools.registry import ToolRegistry
from app.vnext.tools.task import register_task_checkpoint_tool, register_task_plan_tool

from .context_governance_cases import (
    EDITION_IDS,
    FIRST_QUESTION,
    HUMAN_REVIEW_CHECKLIST,
    SCENE_ID,
    SECOND_QUESTION,
    fixture_manifest_hash_payload,
    get_edition_document,
    validate_fixture,
)

OUTPUT_FILENAMES = ("manifest.json", "calls.jsonl", "traces.json", "report.md")
PROFILE_NAMES = ("baseline", "current", "pressure")
SYNTHETIC_FIXTURE_NOTE = (
    "The following fixed test fixture is synthetic and is not real TI history. "
    "Available edition identifiers: "
    + ", ".join(EDITION_IDS)
    + ". Use only the declared fixture and Artifact tools for its records."
)


class EvaluationError(RuntimeError):
    """An evaluation preflight or execution failure, never a production error."""


class EvaluationBudgetExceeded(EvaluationError):
    """The evaluation's shared call-count or elapsed-time allowance was reached."""

    def __init__(self, budget: str) -> None:
        self.budget = budget
        super().__init__(f"evaluation {budget} budget exhausted")


class FixtureLookupInput(BaseModel):
    edition_id: Literal[
        "synthetic-edition-one",
        "synthetic-edition-two",
        "synthetic-edition-three",
    ]


class FixtureLookupOutput(BaseModel):
    document: dict[str, Any]


@dataclass(frozen=True)
class PreparedEvaluation:
    profile: str
    model_name: str
    limits: AgentLimits
    max_model_calls: int
    max_wall_seconds: int
    fixture_sha256: str

    def safe_summary(self, output_dir: Path) -> dict[str, Any]:
        return {
            "status": "dry_run",
            "profile": self.profile,
            "scene_id": SCENE_ID,
            "model": self.model_name,
            "agent_limits": self.limits.model_dump(mode="json"),
            "max_model_calls": self.max_model_calls,
            "max_wall_seconds": self.max_wall_seconds,
            "fixture_sha256": self.fixture_sha256,
            "output_dir": str(output_dir),
            "model_calls_made": 0,
            "execution_enabled": False,
        }


@dataclass
class EvaluationResult:
    status: str
    exit_code: int
    manifest: dict[str, Any]
    calls: list[dict[str, Any]]
    traces: list[dict[str, Any]]
    answers: list[dict[str, Any]]
    output_dir: Path | None = None


def prepare_evaluation(
    settings: VNextSettings,
    *,
    profile: str,
    max_model_calls: int = 12,
    max_wall_seconds: int = 180,
) -> PreparedEvaluation:
    """Validate the scenario/profile and copy only the selected profile overrides."""

    if profile not in PROFILE_NAMES:
        raise EvaluationError("profile must be baseline, current, or pressure")
    if type(max_model_calls) is not int or max_model_calls < 1:
        raise EvaluationError("max_model_calls must be a positive integer")
    if type(max_wall_seconds) is not int or max_wall_seconds < 1:
        raise EvaluationError("max_wall_seconds must be a positive integer")

    validate_fixture()
    limits = settings.agent_limits.model_copy(deep=True)
    if profile == "baseline":
        limits.context_window_tokens = None
    elif limits.context_window_tokens is None:
        raise EvaluationError(f"profile {profile} requires a valid configured context window")
    elif profile == "pressure":
        limits.context_compaction_trigger_percent = 1
        limits.compaction_recent_history_bytes = 4096

    fixture_json = json.dumps(
        fixture_manifest_hash_payload(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return PreparedEvaluation(
        profile=profile,
        model_name=settings.llm_model,
        limits=limits,
        max_model_calls=max_model_calls,
        max_wall_seconds=max_wall_seconds,
        fixture_sha256=hashlib.sha256(fixture_json).hexdigest(),
    )


class EvaluationModelClient:
    """Record the actual request while applying one shared evaluation budget."""

    def __init__(
        self,
        client: Any,
        *,
        output_token_limit: int,
        max_model_calls: int,
        max_wall_seconds: int,
        started_at: float,
        clock: Callable[[], float] = monotonic,
        on_record: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._client = client
        self._output_token_limit = output_token_limit
        self._max_model_calls = max_model_calls
        self._max_wall_seconds = max_wall_seconds
        self._started_at = started_at
        self._clock = clock
        self._on_record = on_record
        self.calls: list[dict[str, Any]] = []
        self.budget_termination: str | None = None
        self.user_request_number = 0

    def _budget_exceeded(self, budget: str) -> EvaluationBudgetExceeded:
        if budget not in {"model-call", "wall-time"}:
            raise ValueError("unknown evaluation budget")
        if self.budget_termination is None:
            self.budget_termination = budget
        return EvaluationBudgetExceeded(self.budget_termination)

    async def complete(self, request: ModelRequest) -> ModelResponse:
        if self.budget_termination is not None:
            raise self._budget_exceeded(self.budget_termination)
        elapsed = self._clock() - self._started_at
        if elapsed >= self._max_wall_seconds:
            raise self._budget_exceeded("wall-time")
        if len(self.calls) >= self._max_model_calls:
            raise self._budget_exceeded("model-call")

        actual_request = request
        if request.max_output_tokens is None:
            actual_request = request.model_copy(
                update={"max_output_tokens": self._output_token_limit}
            )

        call_number = len(self.calls) + 1
        purpose = (
            "summary"
            if actual_request.metadata.get("purpose") == "context_compaction"
            else "business"
        )
        record: dict[str, Any] = {
            "call_number": call_number,
            "user_request_number": self.user_request_number,
            "purpose": purpose,
            "actual_request": actual_request.model_dump(mode="json"),
        }
        call_started = self._clock()
        remaining = self._max_wall_seconds - (call_started - self._started_at)
        if remaining <= 0:
            raise self._budget_exceeded("wall-time")

        # Count immediately before entering the real client; rejected calls above
        # do not consume a slot and are not represented as provider calls.
        self.calls.append(record)
        task: asyncio.Task[ModelResponse] | None = None
        try:
            task = asyncio.create_task(self._client.complete(actual_request))
            completed, _ = await asyncio.wait({task}, timeout=remaining)
            if not completed:
                budget_error = self._budget_exceeded("wall-time")
                await self._cancel_call_task(task)
                raise budget_error
            response = await task
        except asyncio.CancelledError:
            if task is not None and not task.done():
                await self._cancel_call_task(task)
            record.update(
                response=None,
                usage=None,
                error_type="CancelledError",
                duration_seconds=max(0.0, self._clock() - call_started),
            )
            raise
        except Exception as exc:
            record.update(
                response=None,
                usage=None,
                error_type=type(exc).__name__,
                duration_seconds=max(0.0, self._clock() - call_started),
            )
            raise
        else:
            record.update(
                response=response.model_dump(mode="json"),
                usage=deepcopy(response.usage),
                error_type=None,
                duration_seconds=max(0.0, self._clock() - call_started),
            )
            return response
        finally:
            self._flush(record)

    @staticmethod
    async def _cancel_call_task(task: asyncio.Task[ModelResponse]) -> None:
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    def _flush(self, record: dict[str, Any]) -> None:
        if self._on_record is not None:
            self._on_record(record)


def build_evaluation_registry(
    store: SessionArtifactStore,
    coordinator: TaskStateCoordinator,
) -> ToolRegistry:
    """Build only the fixed-fixture, Artifact, and existing task-state tools."""

    registry = ToolRegistry(
        result_processor=ArtifactBackedToolResultProcessor(ToolResponseExternalizer(store))
    )
    register_artifact_tools(registry, ArtifactReader(store), ArtifactGrepper(store))

    async def lookup(arguments: FixtureLookupInput) -> FixtureLookupOutput:
        return FixtureLookupOutput(document=get_edition_document(arguments.edition_id))

    registry.register(
        ToolDefinition(
            name="fixture.edition.lookup",
            description=(
                "Return the complete fixed synthetic tournament record for one "
                "declared edition identifier."
            ),
            input_model=FixtureLookupInput,
            output_model=FixtureLookupOutput,
            handler=lookup,
            externalize_result=True,
            context_effect=ToolContextEffect.MATERIALIZING,
        )
    )
    register_task_plan_tool(registry, coordinator)
    register_task_checkpoint_tool(registry, coordinator)
    return registry


def required_output_files_exist(output_dir: Path) -> bool:
    return any((output_dir / filename).exists() for filename in OUTPUT_FILENAMES)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _append_jsonl(path: Path, value: Any) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()


def _write_traces(path: Path, traces: list[dict[str, Any]]) -> None:
    _write_json(path, traces)


def _safe_trace_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Keep trace structure but omit free-form exception text from provider errors."""

    safe = deepcopy(snapshot)
    pending: list[Any] = [safe]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                if key == "error_message" and isinstance(value, str):
                    current[key] = "[omitted by evaluation recorder]"
                elif isinstance(value, (dict, list)):
                    pending.append(value)
        elif isinstance(current, list):
            pending.extend(current)
    return safe


def _exception_chain_contains_budget(error: BaseException) -> str | None:
    seen: set[int] = set()
    pending: list[BaseException] = [error]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, EvaluationBudgetExceeded):
            return current.budget
        cause = getattr(current, "cause", None)
        if isinstance(cause, BaseException):
            pending.append(cause)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return None


def _usage_value(usage: dict[str, Any] | None, canonical: str, legacy: str) -> int | None:
    if not isinstance(usage, dict):
        return None
    canonical_value = usage.get(canonical)
    if isinstance(canonical_value, int) and not isinstance(canonical_value, bool):
        return canonical_value
    legacy_value = usage.get(legacy)
    return (
        legacy_value
        if isinstance(legacy_value, int) and not isinstance(legacy_value, bool)
        else None
    )


def aggregate_usage(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate token aliases once and retain missing-field counts."""

    result: dict[str, Any] = {}
    for purpose in ("business", "summary"):
        selected = [record for record in calls if record["purpose"] == purpose]
        for kind, canonical, legacy in (
            ("input_tokens", "input_tokens", "prompt_tokens"),
            ("output_tokens", "output_tokens", "completion_tokens"),
        ):
            values = [_usage_value(record.get("usage"), canonical, legacy) for record in selected]
            known = [value for value in values if value is not None]
            key = f"{purpose}_{kind}"
            result[key] = sum(known) if known else None
            result[f"{key}_missing_calls"] = len(values) - len(known)
    return result


def _tool_call_count(calls: list[dict[str, Any]], name: str) -> int:
    count = 0
    for record in calls:
        response = record.get("response")
        message = response.get("message") if isinstance(response, dict) else None
        tool_calls = message.get("tool_calls", []) if isinstance(message, dict) else []
        count += sum(isinstance(call, dict) and call.get("name") == name for call in tool_calls)
    return count


def _report_markdown(
    *,
    manifest: dict[str, Any],
    calls: list[dict[str, Any]],
    traces: list[dict[str, Any]],
    answers: list[dict[str, Any]],
) -> str:
    all_requests = [record.get("actual_request") for record in calls]
    peak_bytes = 0
    for request in all_requests:
        if not isinstance(request, dict):
            continue
        messages = request.get("messages", [])
        tools = request.get("tools", [])
        canonical = json.dumps(
            {"messages": messages, "tools": tools},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        peak_bytes = max(peak_bytes, len(canonical))

    commits = sum(len(trace.get("trace", {}).get("compaction_commits", [])) for trace in traces)
    recoveries = sum(len(trace.get("trace", {}).get("overflow_recoveries", [])) for trace in traces)
    total_duration = sum(
        float(record.get("duration_seconds", 0.0))
        for record in calls
        if isinstance(record.get("duration_seconds"), int | float)
    )
    usage = aggregate_usage(calls)

    lines = [
        "# Context Governance evaluation",
        "",
        f"- Status: `{manifest['status']}`",
        f"- Scene: `{manifest['scene_id']}` (synthetic fixture; not TI history)",
        f"- Profile: `{manifest['profile']}`",
        f"- Model: `{manifest['model']}`",
        f"- Actual model calls: {len(calls)} / {manifest['max_model_calls']}",
        f"- Summary calls: {sum(record['purpose'] == 'summary' for record in calls)}",
        f"- Successful compaction commits: {commits}",
        f"- Overflow recoveries: {recoveries}",
        f"- Artifact reads returned by model: {_tool_call_count(calls, 'artifact.read')}",
        f"- Peak complete request size: {peak_bytes} UTF-8 bytes (not token usage)",
        f"- Total scenario wall time: {manifest.get('elapsed_wall_seconds', 'unknown')}s",
        f"- Sum of model-call durations: {total_duration:.3f}s",
        "",
        "## Provider-reported token usage",
        "",
        "Values are usage fields reported by the provider; missing values are unknown, not zero.",
        "",
    ]
    for purpose in ("business", "summary"):
        input_tokens = usage[f"{purpose}_input_tokens"]
        output_tokens = usage[f"{purpose}_output_tokens"]
        input_text = "unknown" if input_tokens is None else str(input_tokens)
        output_text = "unknown" if output_tokens is None else str(output_tokens)
        lines.append(
            f"- {purpose}: input `{input_text}`, output `{output_text}` tokens; "
            f"missing usage in {usage[f'{purpose}_input_tokens_missing_calls']} input and "
            f"{usage[f'{purpose}_output_tokens_missing_calls']} output call records."
        )
    lines.extend(["", "## Delivered answers", ""])
    if answers:
        for answer in answers:
            lines.extend(
                [
                    f"### User request {answer['user_request_number']}",
                    "",
                    answer["question"],
                    "",
                    answer["answer"],
                    "",
                ]
            )
    else:
        lines.append("No final answer was delivered.")
        lines.append("")
    if manifest.get("failure_type"):
        lines.extend(["## Failure", "", f"`{manifest['failure_type']}`", ""])
    if manifest.get("budget_termination"):
        lines.extend(
            ["## Evaluation budget termination", "", f"`{manifest['budget_termination']}`", ""]
        )
    if manifest["profile"] == "pressure":
        lines.extend(
            [
                "## Pressure profile",
                "",
                "This is a pressure-test override, not a product recommendation:",
                "",
                "- `context_compaction_trigger_percent = 1`",
                "- `compaction_recent_history_bytes = 4096`",
                "",
            ]
        )
        if commits == 0:
            lines.extend(
                [
                    "本次未覆盖压缩后的模型行为，不能据此判断摘要质量。",
                    "",
                ]
            )
    lines.extend(["## Human review checklist", "", "Initial status: **待人工评审**", ""])
    lines.extend(f"- [ ] {item}" for item in HUMAN_REVIEW_CHECKLIST)
    lines.extend(
        [
            "",
            "A successful workflow is not evidence that an answer is correct. "
            "Review the recorded answers, observations, and traces manually.",
            "",
        ]
    )
    return "\n".join(lines)


async def _run_two_questions(
    *,
    settings: VNextSettings,
    prepared: PreparedEvaluation,
    client: EvaluationModelClient,
    traces: list[dict[str, Any]],
    on_trace: Callable[[list[dict[str, Any]]], None],
    answers: list[dict[str, Any]] | None = None,
    clock: Callable[[], float],
    started_at: float,
) -> list[dict[str, Any]]:
    store = SessionArtifactStore()
    coordinator = TaskStateCoordinator()
    registry = build_evaluation_registry(store, coordinator)
    system_instruction = AGENT_INSTRUCTION + "\n\n" + SYNTHETIC_FIXTURE_NOTE
    runtime = AgentRuntime(
        client,
        registry,
        system_instruction=system_instruction,
        limits=prepared.limits.model_copy(deep=True),
        transcript_rewriter=ArtifactObservationTranscriptRewriter(),
        task_state_coordinator=coordinator,
    )
    history = SessionExecutionHistory()
    session_id = uuid4()
    answer_records = answers if answers is not None else []

    def save_trace(index: int, question: str, trace: AgentTraceCollector) -> None:
        traces.append(
            {
                "session_id": str(session_id),
                "user_request_number": index,
                "question": question,
                "trace": _safe_trace_snapshot(trace.snapshot()),
            }
        )
        on_trace(traces)

    for index, question in enumerate((FIRST_QUESTION, SECOND_QUESTION), start=1):
        elapsed = clock() - started_at
        remaining = prepared.max_wall_seconds - elapsed
        if remaining <= 0:
            raise EvaluationBudgetExceeded("wall-time")
        request_id = uuid4()
        messages = history.begin_request(request_id, question)
        trace = AgentTraceCollector()
        client.user_request_number = index
        try:
            final = await asyncio.wait_for(
                runtime.run(
                    messages,
                    execution_history=history,
                    request_id=request_id,
                    trace_collector=trace,
                ),
                timeout=remaining,
            )
        except asyncio.TimeoutError as exc:
            save_trace(index, question, trace)
            raise EvaluationBudgetExceeded("wall-time") from exc
        except Exception:
            save_trace(index, question, trace)
            raise
        else:
            save_trace(index, question, trace)
            if client.budget_termination is not None:
                raise EvaluationBudgetExceeded(client.budget_termination)
        answer_records.append(
            {
                "user_request_number": index,
                "question": question,
                "answer": final.content,
            }
        )
    return answer_records


def run_evaluation(
    *,
    settings: VNextSettings,
    profile: str,
    output_dir: Path,
    execute: bool = False,
    max_model_calls: int = 12,
    max_wall_seconds: int = 180,
    client_factory: Callable[[VNextSettings], Any] | None = None,
    clock: Callable[[], float] = monotonic,
    utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> EvaluationResult | PreparedEvaluation:
    """Preflight a dry-run or execute one bounded two-question profile."""

    prepared = prepare_evaluation(
        settings,
        profile=profile,
        max_model_calls=max_model_calls,
        max_wall_seconds=max_wall_seconds,
    )
    if not execute:
        if required_output_files_exist(output_dir):
            raise EvaluationError("output directory already contains evaluation artifacts")
        return prepared
    if required_output_files_exist(output_dir):
        raise EvaluationError("output directory already contains evaluation artifacts")

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    calls_path = output_dir / "calls.jsonl"
    traces_path = output_dir / "traces.json"
    report_path = output_dir / "report.md"
    calls_path.touch(exist_ok=False)

    started_at = clock()
    started_at_utc = utc_now().astimezone(UTC).isoformat()
    manifest: dict[str, Any] = {
        "scene_id": SCENE_ID,
        "profile": prepared.profile,
        "model": prepared.model_name,
        "agent_limits": prepared.limits.model_dump(mode="json"),
        "max_model_calls": prepared.max_model_calls,
        "max_wall_seconds": prepared.max_wall_seconds,
        "fixture_sha256": prepared.fixture_sha256,
        "started_at_utc": started_at_utc,
        "status": "running",
        "model_call_count": 0,
    }
    _write_json(manifest_path, manifest)
    traces: list[dict[str, Any]] = []
    answers: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    evaluated_client: EvaluationModelClient | None = None
    exit_code = 0
    try:
        if client_factory is None:

            def client_factory(config: VNextSettings) -> OpenAICompatibleModelClient:
                return OpenAICompatibleModelClient(
                    api_key=config.llm_api_key,
                    base_url=config.llm_base_url,
                    model=config.llm_model,
                    timeout=config.llm_timeout_seconds,
                )

        provider_client = client_factory(settings)

        def record_call(record: dict[str, Any]) -> None:
            calls.append(record)
            manifest["model_call_count"] = len(calls)
            _append_jsonl(calls_path, record)
            _write_json(manifest_path, manifest)

        evaluated_client = EvaluationModelClient(
            provider_client,
            output_token_limit=prepared.limits.context_output_reserve_tokens,
            max_model_calls=prepared.max_model_calls,
            max_wall_seconds=prepared.max_wall_seconds,
            started_at=started_at,
            clock=clock,
            on_record=record_call,
        )

        def record_traces(current: list[dict[str, Any]]) -> None:
            _write_traces(traces_path, current)

        answers = asyncio.run(
            _run_two_questions(
                settings=settings,
                prepared=prepared,
                client=evaluated_client,
                traces=traces,
                on_trace=record_traces,
                answers=answers,
                clock=clock,
                started_at=started_at,
            )
        )
        manifest["status"] = "completed"
    except Exception as exc:
        budget = _exception_chain_contains_budget(exc)
        if budget is not None:
            manifest["status"] = "budget_terminated"
            manifest["budget_termination"] = budget
        else:
            manifest["status"] = "failed"
            manifest["failure_type"] = type(exc).__name__
        manifest["failure_type"] = manifest.get("failure_type") or (
            "EvaluationBudgetExceeded" if budget is not None else None
        )
        exit_code = 1
    finally:
        if evaluated_client is not None and evaluated_client.budget_termination is not None:
            manifest["status"] = "budget_terminated"
            manifest["budget_termination"] = evaluated_client.budget_termination
            manifest["failure_type"] = "EvaluationBudgetExceeded"
            exit_code = 1
        manifest["model_call_count"] = len(calls)
        manifest["finished_at_utc"] = utc_now().astimezone(UTC).isoformat()
        manifest["elapsed_wall_seconds"] = max(0.0, clock() - started_at)
        _write_json(manifest_path, manifest)
        if not traces_path.exists():
            _write_traces(traces_path, traces)
        report_path.write_text(
            _report_markdown(
                manifest=manifest,
                calls=calls,
                traces=traces,
                answers=answers,
            ),
            encoding="utf-8",
        )
    return EvaluationResult(
        status=manifest["status"],
        exit_code=exit_code,
        manifest=manifest,
        calls=calls,
        traces=traces,
        answers=answers,
        output_dir=output_dir,
    )


def _positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=PROFILE_NAMES)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-model-calls", type=_positive_integer, default=12)
    parser.add_argument("--max-wall-seconds", type=_positive_integer, default=180)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    settings_loader: Callable[[], VNextSettings] = VNextSettings.from_env,
    client_factory: Callable[[VNextSettings], Any] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = settings_loader()
        result = run_evaluation(
            settings=settings,
            profile=args.profile,
            output_dir=args.output_dir,
            execute=args.execute,
            max_model_calls=args.max_model_calls,
            max_wall_seconds=args.max_wall_seconds,
            client_factory=client_factory,
        )
    except (EvaluationError, ValueError) as exc:
        parser.error(str(exc))
    if isinstance(result, PreparedEvaluation):
        print(json.dumps(result.safe_summary(args.output_dir), ensure_ascii=False, indent=2))
        return 0
    print(
        json.dumps(
            {
                "status": result.status,
                "output_dir": str(result.output_dir),
                "model_call_count": len(result.calls),
            },
            ensure_ascii=False,
        )
    )
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "EvaluationBudgetExceeded",
    "EvaluationError",
    "EvaluationModelClient",
    "EvaluationResult",
    "PreparedEvaluation",
    "aggregate_usage",
    "build_evaluation_registry",
    "prepare_evaluation",
    "required_output_files_exist",
    "run_evaluation",
]
