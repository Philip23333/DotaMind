from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.vnext.agent.errors import ModelContextWindowExceeded
from app.vnext.agent.limits import AgentLimits
from app.vnext.artifacts import SessionArtifactStore
from app.vnext.composition import VNextSettings
from app.vnext.llm.errors import ModelContextWindowError
from app.vnext.llm.protocol import (
    AssistantMessage,
    ModelRequest,
    ModelResponse,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from tests.vnext.evals.context_governance_cases import (
    EDITION_DOCUMENTS,
    EDITION_IDS,
    FIRST_QUESTION,
    FOLLOW_UP_EXPECTED,
    HUMAN_REVIEW_CHECKLIST,
    SECOND_QUESTION,
    get_edition_document,
    validate_fixture,
)
from tests.vnext.evals.context_governance_runner import (
    EvaluationBudgetExceeded,
    EvaluationError,
    EvaluationModelClient,
    aggregate_usage,
    build_evaluation_registry,
    main,
    prepare_evaluation,
    run_evaluation,
)


def _settings(*, window: int | None = 500_000) -> VNextSettings:
    return VNextSettings(
        llm_api_key="synthetic-test-secret",
        llm_model="offline-eval-model",
        agent_limits=AgentLimits(
            max_steps=12,
            deadline_seconds=10,
            answer_timeout_seconds=5,
            degraded_answer_timeout_seconds=3,
            max_materialized_context_bytes=80_000,
            compaction_recent_history_bytes=10_000,
            compaction_max_input_bytes=100_000,
            compaction_max_output_tokens=256,
            compaction_max_summary_bytes=2_000,
            context_window_tokens=window,
            context_output_reserve_tokens=512,
            context_safety_margin_tokens=128,
            context_estimate_bytes_per_token=2,
            context_compaction_trigger_percent=75,
        ),
    )


def _call(call_id: str, name: str, arguments: dict[str, Any]) -> ModelResponse:
    return ModelResponse.from_assistant(
        AssistantMessage(tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)])
    )


class _RecordingClient:
    def __init__(self, *, clock: Any = None) -> None:
        self.requests: list[ModelRequest] = []
        self.clock = clock
        self.responses: list[ModelResponse] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request.model_copy(deep=True))
        if self.clock is not None:
            self.clock.value += 4
        response = ModelResponse.from_final("offline response", usage={"input_tokens": 3})
        self.responses.append(response)
        return response


def test_profiles_copy_limits_and_only_override_the_selected_fields() -> None:
    settings = _settings()
    original = settings.agent_limits.model_dump(mode="python")

    baseline = prepare_evaluation(settings, profile="baseline")
    current = prepare_evaluation(settings, profile="current")
    pressure = prepare_evaluation(settings, profile="pressure")

    assert baseline.limits.context_window_tokens is None
    assert current.limits == settings.agent_limits
    assert pressure.limits.context_window_tokens == settings.agent_limits.context_window_tokens
    assert pressure.limits.context_compaction_trigger_percent == 1
    assert pressure.limits.compaction_recent_history_bytes == 4096
    assert settings.agent_limits.model_dump(mode="python") == original
    assert baseline.limits is not settings.agent_limits
    assert pressure.limits is not settings.agent_limits


def test_current_profiles_require_window_before_client_creation() -> None:
    settings = _settings(window=None)
    for profile in ("current", "pressure"):
        with pytest.raises(EvaluationError, match="requires a valid configured context window"):
            prepare_evaluation(settings, profile=profile)


def test_baseline_business_output_cap_matches_other_profiles_and_summary_keeps_its_cap() -> None:
    async def exercise() -> tuple[list[ModelRequest], list[ModelRequest]]:
        observed: list[ModelRequest] = []
        for profile in ("baseline", "current", "pressure"):
            prepared = prepare_evaluation(_settings(), profile=profile)
            provider = _RecordingClient()
            evaluator = EvaluationModelClient(
                provider,
                output_token_limit=prepared.limits.context_output_reserve_tokens,
                max_model_calls=2,
                max_wall_seconds=20,
                started_at=0,
                clock=lambda: 1,
            )
            await evaluator.complete(ModelRequest(messages=[UserMessage(content="q")]))
            await evaluator.complete(
                ModelRequest(
                    messages=[SystemMessage(content="summary")],
                    metadata={"purpose": "context_compaction"},
                    max_output_tokens=prepared.limits.compaction_max_output_tokens,
                )
            )
            observed.extend(provider.requests)
        business = [observed[index].max_output_tokens for index in (0, 2, 4)]
        summaries = [observed[index].max_output_tokens for index in (1, 3, 5)]
        return business, summaries

    business, summaries = asyncio.run(exercise())
    assert len(set(business)) == 1
    assert business[0] == _settings().agent_limits.context_output_reserve_tokens
    assert summaries == [256, 256, 256]


def test_call_quota_includes_summary_and_is_shared_across_both_user_requests() -> None:
    provider = _RecordingClient()
    evaluator = EvaluationModelClient(
        provider,
        output_token_limit=64,
        max_model_calls=2,
        max_wall_seconds=10,
        started_at=0,
        clock=lambda: 1,
    )

    async def exercise() -> None:
        evaluator.user_request_number = 1
        await evaluator.complete(ModelRequest(messages=[UserMessage(content="first")]))
        await evaluator.complete(
            ModelRequest(
                messages=[SystemMessage(content="summary")],
                metadata={"purpose": "context_compaction"},
                max_output_tokens=32,
            )
        )
        evaluator.user_request_number = 2
        with pytest.raises(EvaluationBudgetExceeded, match="model-call"):
            await evaluator.complete(ModelRequest(messages=[UserMessage(content="second")]))

    asyncio.run(exercise())
    assert len(provider.requests) == 2
    assert [record["purpose"] for record in evaluator.calls] == ["business", "summary"]
    assert [record["user_request_number"] for record in evaluator.calls] == [1, 1]


def test_wall_time_budget_is_not_reset_for_second_user_request() -> None:
    class _Clock:
        value = 0.0

        def __call__(self) -> float:
            return self.value

    clock = _Clock()
    provider = _RecordingClient(clock=clock)
    evaluator = EvaluationModelClient(
        provider,
        output_token_limit=64,
        max_model_calls=5,
        max_wall_seconds=3,
        started_at=0,
        clock=clock,
    )

    async def exercise() -> None:
        evaluator.user_request_number = 1
        await evaluator.complete(ModelRequest(messages=[UserMessage(content="first")]))
        evaluator.user_request_number = 2
        with pytest.raises(EvaluationBudgetExceeded, match="wall-time"):
            await evaluator.complete(ModelRequest(messages=[UserMessage(content="second")]))

    asyncio.run(exercise())
    assert len(provider.requests) == 1


def test_two_questions_share_real_session_artifact_and_summary_and_reset_task_state() -> None:
    from tests.vnext.evals.context_governance_runner import _run_two_questions

    settings = _settings()
    settings.agent_limits.compaction_recent_history_bytes = 512
    prepared = prepare_evaluation(settings, profile="current")

    class _Model:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []
            self.initial_overflowed = False
            self.first_detail_ref: str | None = None

        async def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request.model_copy(deep=True))
            if request.metadata.get("purpose") == "context_compaction":
                return ModelResponse.from_final(
                    "verified synthetic progress summary", finish_reason="stop"
                )

            current_question = (
                SECOND_QUESTION
                if any(
                    message == UserMessage(content=SECOND_QUESTION) for message in request.messages
                )
                else FIRST_QUESTION
            )
            assert (
                sum(
                    message == UserMessage(content=current_question) for message in request.messages
                )
                == 1
            )

            if current_question == FIRST_QUESTION:
                if request.step == 1:
                    return _call(
                        "initial-plan",
                        "task.plan",
                        {
                            "items": [
                                {"key": "first-edition-record", "objective": "Inspect edition one"},
                                {
                                    "key": "comparison-pending",
                                    "objective": "Retain comparison context",
                                },
                            ]
                        },
                    )
                if request.step == 2:
                    return _call(
                        "fixture-one",
                        "fixture.edition.lookup",
                        {"edition_id": EDITION_IDS[0]},
                    )
                if request.step == 3:
                    lookup = next(
                        message
                        for message in request.messages
                        if isinstance(message, ToolResultMessage)
                        and message.tool_call_id == "fixture-one"
                    )
                    self.first_detail_ref = lookup.content["artifact_ref"]
                    return _call(
                        "read-first-record",
                        "artifact.read",
                        {
                            "ref": self.first_detail_ref,
                            "mode": "read",
                            "path": "document.match_records",
                            "limit": 1,
                        },
                    )
                if request.step == 4:
                    return _call(
                        "checkpoint-first",
                        "task.checkpoint",
                        {
                            "key": "first-edition-record",
                            "value": {"verified": "SYN-01-SF1"},
                            "source_tool_call_ids": ["read-first-record"],
                        },
                    )
                if request.step == 5 and not self.initial_overflowed:
                    self.initial_overflowed = True
                    cause = ModelContextWindowError(
                        provider_code="context_length_exceeded", status_code=400
                    )
                    raise ModelContextWindowExceeded(
                        cause=cause,
                        provider_code="context_length_exceeded",
                        status_code=400,
                    )
                if request.step == 5:
                    return ModelResponse.from_final(
                        "first execution stopped at a verified checkpoint"
                    )
                assert request.tools == []
                return ModelResponse.from_final("first synthetic comparison answer")

            if request.tools:
                assert request.step == 1
                session_message = next(
                    message
                    for message in request.messages
                    if isinstance(message, SystemMessage)
                    and "Session context data:\n" in message.content
                )
                session_payload, _ = json.JSONDecoder().raw_decode(
                    session_message.content.split("Session context data:\n", 1)[1]
                )
                assert session_payload["summary"] == "verified synthetic progress summary"
                assert any(
                    locator["ref"] == self.first_detail_ref
                    for locator in session_payload["artifact_locators"]
                )
                assert not any(
                    isinstance(message, SystemMessage) and "Task plan:\nCURRENT:" in message.content
                    for message in request.messages
                )
                return ModelResponse.from_final("follow-up execution")
            return ModelResponse.from_final("follow-up verified answer")

    model = _Model()
    traces: list[dict[str, Any]] = []
    started = 0.0
    evaluator_client = EvaluationModelClient(
        model,
        output_token_limit=prepared.limits.context_output_reserve_tokens,
        max_model_calls=12,
        max_wall_seconds=120,
        started_at=started,
        clock=lambda: 1.0,
    )

    answers = asyncio.run(
        _run_two_questions(
            settings=settings,
            prepared=prepared,
            client=evaluator_client,
            traces=traces,
            on_trace=lambda _: None,
            clock=lambda: 1.0,
            started_at=started,
        )
    )
    assert [item["answer"] for item in answers] == [
        "first synthetic comparison answer",
        "follow-up verified answer",
    ]
    assert [item["user_request_number"] for item in traces] == [1, 2]
    assert traces[0]["trace"]["compaction_commits"]
    assert traces[0]["trace"]["overflow_recoveries"][0]["status"] == "retry_succeeded"
    second_requests = [
        request
        for record, request in zip(evaluator_client.calls, model.requests, strict=True)
        if record["user_request_number"] == 2 and record["purpose"] == "business"
    ]
    assert second_requests[0].step == 1
    assert model.initial_overflowed


def test_usage_aliases_are_not_double_counted_and_missing_remains_unknown() -> None:
    calls = [
        {
            "purpose": "business",
            "usage": {
                "input_tokens": 10,
                "prompt_tokens": 99,
                "output_tokens": 4,
                "completion_tokens": 77,
            },
        },
        {"purpose": "business", "usage": {}},
        {"purpose": "summary", "usage": {"prompt_tokens": 7, "completion_tokens": 2}},
    ]
    usage = aggregate_usage(calls)
    assert usage["business_input_tokens"] == 10
    assert usage["business_output_tokens"] == 4
    assert usage["business_input_tokens_missing_calls"] == 1
    assert usage["summary_input_tokens"] == 7
    assert usage["summary_output_tokens"] == 2
    assert usage["summary_input_tokens_missing_calls"] == 0
    unknown = aggregate_usage([{"purpose": "summary", "usage": None}])
    assert unknown["summary_input_tokens"] is None
    assert unknown["summary_input_tokens_missing_calls"] == 1


def test_failure_keeps_manifest_calls_trace_and_report_and_redacts_secrets(tmp_path: Path) -> None:
    settings = _settings()
    secret = settings.llm_api_key

    class _FailingClient:
        async def complete(self, _request: ModelRequest) -> ModelResponse:
            raise RuntimeError("failure includes Authorization: Bearer hidden-value")

    result = run_evaluation(
        settings=settings,
        profile="baseline",
        output_dir=tmp_path / "failure-run",
        execute=True,
        client_factory=lambda _: _FailingClient(),
    )
    assert result.status == "failed"
    assert result.exit_code != 0
    assert result.manifest["model_call_count"] == 1
    assert len(result.traces) == 1
    assert result.traces[0]["trace"]["steps"]
    output = "\n".join(path.read_text(encoding="utf-8") for path in result.output_dir.iterdir())
    assert secret not in output
    assert "Authorization" not in output
    assert "RuntimeError" in (result.output_dir / "calls.jsonl").read_text(encoding="utf-8")
    assert "No final answer was delivered." in (result.output_dir / "report.md").read_text(
        encoding="utf-8"
    )


def test_later_request_failure_keeps_the_answer_already_delivered(tmp_path: Path) -> None:
    class _FirstRequestSucceeds:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, request: ModelRequest) -> ModelResponse:
            self.calls += 1
            if self.calls == 1:
                return ModelResponse.from_final("execution one")
            if self.calls == 2:
                return ModelResponse.from_final("answer one preserved")
            raise RuntimeError("offline second request failure")

    result = run_evaluation(
        settings=_settings(),
        profile="baseline",
        output_dir=tmp_path / "partial-run",
        execute=True,
        client_factory=lambda _: _FirstRequestSucceeds(),
    )
    report = (result.output_dir / "report.md").read_text(encoding="utf-8")
    assert result.status == "failed"
    assert result.manifest["model_call_count"] == 3
    assert len(result.traces) == 2
    assert "answer one preserved" in report
    assert "No final answer was delivered." not in report


def test_call_budget_termination_saves_partial_trace_and_artifacts(tmp_path: Path) -> None:
    provider = _RecordingClient()
    result = run_evaluation(
        settings=_settings(),
        profile="baseline",
        output_dir=tmp_path / "budget-run",
        execute=True,
        max_model_calls=1,
        client_factory=lambda _: provider,
    )
    assert result.status == "budget_terminated"
    assert result.exit_code != 0
    assert result.manifest["budget_termination"] == "model-call"
    assert len(provider.requests) == 1
    assert len(result.traces) == 2
    assert result.traces[1]["user_request_number"] == 2
    assert len(result.answers) == 1
    assert (result.output_dir / "manifest.json").exists()
    assert (result.output_dir / "calls.jsonl").read_text(encoding="utf-8").count("call_number") == 1
    assert "model-call" in (result.output_dir / "report.md").read_text(encoding="utf-8")


def test_output_directory_refuses_to_overwrite_evaluation_artifacts(tmp_path: Path) -> None:
    output_dir = tmp_path / "existing"
    output_dir.mkdir()
    (output_dir / "report.md").write_text("keep me", encoding="utf-8")
    called = False

    def client_factory(_: VNextSettings) -> object:
        nonlocal called
        called = True
        raise AssertionError("must reject before client creation")

    with pytest.raises(EvaluationError, match="already contains"):
        run_evaluation(
            settings=_settings(),
            profile="baseline",
            output_dir=output_dir,
            execute=True,
            client_factory=client_factory,
        )
    assert not called
    assert (output_dir / "report.md").read_text(encoding="utf-8") == "keep me"


def test_dry_run_never_creates_client_or_claims_execution(tmp_path: Path, capsys) -> None:
    output_dir = tmp_path / "dry-run"
    result = main(
        ["--profile", "baseline", "--output-dir", str(output_dir)],
        settings_loader=_settings,
        client_factory=lambda _: pytest.fail("dry-run must not construct a model client"),
    )
    displayed = json.loads(capsys.readouterr().out)
    assert result == 0
    assert displayed["status"] == "dry_run"
    assert displayed["execution_enabled"] is False
    assert displayed["model_calls_made"] == 0
    assert not output_dir.exists()


def test_cli_rejects_invalid_configuration_before_client_or_output(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as error:
        main(
            ["--profile", "current", "--output-dir", str(tmp_path / "no-window"), "--execute"],
            settings_loader=lambda: _settings(window=None),
            client_factory=lambda _: pytest.fail("invalid profile must not create client"),
        )
    assert error.value.code == 2
    assert not (tmp_path / "no-window").exists()
    assert "requires a valid configured context window" in capsys.readouterr().err


def test_fixed_fixture_is_synthetic_consistent_and_answer_key_stays_report_only() -> None:
    validate_fixture()
    assert FIRST_QUESTION.startswith("Compare the championship paths")
    assert SECOND_QUESTION.startswith("Verify the opponent and score")
    assert FOLLOW_UP_EXPECTED["opponent"] == "Ember Foxes"
    assert len(EDITION_DOCUMENTS) == 3
    for document in EDITION_DOCUMENTS.values():
        assert document["synthetic_fixture"] is True
        assert "not a real TI edition" in document["historical_fact_warning"]
        assert document["match_records"]
    expected_record = next(
        record
        for record in EDITION_DOCUMENTS[FOLLOW_UP_EXPECTED["edition_id"]]["match_records"]
        if record["match_id"] == FOLLOW_UP_EXPECTED["match_id"]
    )
    assert FOLLOW_UP_EXPECTED["opponent"] in expected_record["teams"]
    assert expected_record["series_score"]["Northwind Lanterns"] == 2
    assert expected_record["series_score"][FOLLOW_UP_EXPECTED["opponent"]] == 0
    model_visible = json.dumps(EDITION_DOCUMENTS, ensure_ascii=False)
    assert "HUMAN_REVIEW_CHECKLIST" not in model_visible
    assert len(HUMAN_REVIEW_CHECKLIST) == 6
    assert get_edition_document(EDITION_IDS[0]) == EDITION_DOCUMENTS[EDITION_IDS[0]]


def test_fixture_lookup_uses_external_artifact_and_real_artifact_read() -> None:
    from app.vnext.agent.task_state import TaskStateCoordinator
    from app.vnext.llm.protocol import ToolCall
    from app.vnext.tools.definition import ToolContextEffect

    store = SessionArtifactStore()
    registry = build_evaluation_registry(store, TaskStateCoordinator())
    lookup = asyncio.run(
        registry.execute(
            ToolCall(
                id="lookup-one",
                name="fixture.edition.lookup",
                arguments={"edition_id": EDITION_IDS[0]},
            )
        )
    )
    assert lookup.status == "ok"
    assert lookup.content["externalized"] is True
    artifact_ref = lookup.content["artifact_ref"]
    full_output = asyncio.run(store.get(artifact_ref))
    assert full_output["document"] == EDITION_DOCUMENTS[EDITION_IDS[0]]
    assert registry.get("fixture.edition.lookup").context_effect is ToolContextEffect.MATERIALIZING

    read = asyncio.run(
        registry.execute(
            ToolCall(
                id="read-one",
                name="artifact.read",
                arguments={
                    "ref": artifact_ref,
                    "mode": "read",
                    "path": "document.match_records",
                    "limit": 1,
                },
            )
        )
    )
    assert read.status == "ok"
    assert read.content["value"][0]["match_id"] == FOLLOW_UP_EXPECTED["match_id"]


def test_pressure_report_disclaims_quality_when_no_compaction_succeeded() -> None:
    from tests.vnext.evals.context_governance_runner import _report_markdown

    report = _report_markdown(
        manifest={
            "status": "completed",
            "scene_id": "synthetic-scene",
            "profile": "pressure",
            "model": "offline-test",
            "max_model_calls": 12,
            "max_wall_seconds": 180,
            "elapsed_wall_seconds": 1.0,
        },
        calls=[],
        traces=[{"trace": {"compaction_commits": []}}],
        answers=[],
    )
    assert "context_compaction_trigger_percent = 1" in report
    assert "compaction_recent_history_bytes = 4096" in report
    assert "本次未覆盖压缩后的模型行为，不能据此判断摘要质量。" in report
