from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.vnext.agent.context_accounting import measure_request_context_bytes
from app.vnext.agent.errors import AgentRuntimeError
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.output_budget import derive_output_budget
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.openai_compatible import OpenAICompatibleModelClient
from app.vnext.llm.protocol import (
    FinalMessage,
    ModelRequest,
    ModelResponse,
    ModelTool,
    SystemMessage,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools.registry import ToolRegistry


def _limits(**values: object) -> AgentLimits:
    config: dict[str, object] = {
        "application_max_output_tokens": 100,
        "context_window_tokens": 10_000,
        "context_safety_margin_tokens": 10,
        "context_estimate_bytes_per_token": 1,
        "compaction_reserve_tokens": 20,
    }
    config.update(values)
    return AgentLimits(**config)


def _request(text: str = "query") -> ModelRequest:
    return ModelRequest(messages=[SystemMessage(content="system"), UserMessage(content=text)])


def test_model_and_application_caps_use_the_lower_value() -> None:
    budget = derive_output_budget(
        _request(),
        _limits(model_max_output_tokens=80, application_max_output_tokens=50),
    )

    assert budget.expected_output_tokens == 50
    assert budget.actual_output_tokens == 50
    assert not budget.clipped_by_context


@pytest.mark.parametrize(
    ("limits", "expected"),
    [
        ({"model_max_output_tokens": 80, "application_max_output_tokens": None}, 80),
        ({"model_max_output_tokens": None, "application_max_output_tokens": 70}, 70),
    ],
)
def test_either_configured_cap_can_supply_the_expected_output_limit(
    limits: dict[str, int | None], expected: int
) -> None:
    budget = derive_output_budget(_request(), _limits(**limits))
    assert budget.expected_output_tokens == expected
    assert budget.actual_output_tokens == expected


def test_missing_caps_are_rejected_before_a_budget_can_be_derived() -> None:
    limits = AgentLimits(context_safety_margin_tokens=10, compaction_reserve_tokens=20)
    with pytest.raises(ValueError, match="DOTAMIND_MODEL_MAX_OUTPUT_TOKENS"):
        derive_output_budget(_request(), limits)


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "12"])
@pytest.mark.parametrize(
    "field", ["model_max_output_tokens", "application_max_output_tokens"]
)
def test_output_caps_require_strict_positive_integers(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        AgentLimits(**{field: value})


def test_context_space_that_fits_expected_output_is_not_clipped() -> None:
    request = _request()
    input_tokens = measure_request_context_bytes(request)
    budget = derive_output_budget(
        request,
        _limits(
            application_max_output_tokens=120,
            context_window_tokens=input_tokens + 10 + 120,
        ),
    )

    assert budget.estimated_input_tokens == input_tokens
    assert budget.remaining_output_tokens == 120
    assert budget.actual_output_tokens == 120
    assert not budget.clipped_by_context


def test_actual_output_is_clipped_to_remaining_space() -> None:
    request = _request()
    input_tokens = measure_request_context_bytes(request)
    budget = derive_output_budget(
        request,
        _limits(
            application_max_output_tokens=120,
            context_window_tokens=input_tokens + 10 + 37,
        ),
    )

    assert budget.expected_output_tokens == 120
    assert budget.remaining_output_tokens == 37
    assert budget.actual_output_tokens == 37
    assert budget.clipped_by_context


def test_no_remaining_output_space_is_zero_and_not_rounded_up() -> None:
    request = _request()
    input_tokens = measure_request_context_bytes(request)
    budget = derive_output_budget(
        request,
        _limits(
            application_max_output_tokens=120,
            context_window_tokens=input_tokens + 10,
        ),
    )

    assert budget.remaining_output_tokens == 0
    assert budget.actual_output_tokens == 0
    assert budget.clipped_by_context


def test_unconfigured_context_window_keeps_expected_cap_and_no_capacity_claim() -> None:
    budget = derive_output_budget(
        _request(),
        AgentLimits(application_max_output_tokens=72),
    )

    assert budget.expected_output_tokens == 72
    assert budget.actual_output_tokens == 72
    assert budget.remaining_output_tokens is None
    assert not budget.clipped_by_context


def test_estimate_includes_system_messages_tools_and_full_request_projection() -> None:
    tool = ModelTool(
        name="catalog.lookup",
        description="Look up catalog entities.",
        input_schema={"type": "object", "properties": {"ids": {"type": "array"}}},
    )
    base = _request()
    expanded = ModelRequest(
        messages=[
            SystemMessage(content="system"),
            SystemMessage(content="task state and projected context"),
            UserMessage(content="query"),
        ],
        tools=[tool],
    )

    base_budget = derive_output_budget(
        base,
        _limits(context_estimate_bytes_per_token=1),
    )
    expanded_budget = derive_output_budget(
        expanded,
        _limits(context_estimate_bytes_per_token=1),
    )

    assert expanded_budget.estimated_input_tokens > base_budget.estimated_input_tokens
    assert expanded_budget.estimated_input_tokens == measure_request_context_bytes(expanded)


def test_request_and_limits_are_not_mutated_and_changed_input_is_remeasured() -> None:
    request = _request("short")
    limits = _limits(context_estimate_bytes_per_token=1)
    request_before = request.model_dump(mode="json")
    limits_before = limits.model_dump(mode="json")
    first = derive_output_budget(request, limits)
    changed = _request("a much longer request body")
    second = derive_output_budget(changed, limits)

    assert second.estimated_input_tokens > first.estimated_input_tokens
    assert first == derive_output_budget(request, limits)
    assert request.model_dump(mode="json") == request_before
    assert limits.model_dump(mode="json") == limits_before


def test_runtime_without_an_output_cap_fails_before_calling_the_model() -> None:
    class CapturingModel:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []

        async def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            return ModelResponse(message=FinalMessage(content="unexpected"))

    model = CapturingModel()
    runtime = AgentRuntime(model, ToolRegistry())

    async def run() -> None:
        with pytest.raises(AgentRuntimeError, match="DOTAMIND_MODEL_MAX_OUTPUT_TOKENS"):
            await runtime.run([UserMessage(content="question")])

    asyncio.run(run())
    assert model.requests == []


def test_execution_primary_and_degraded_calls_share_budget_and_trace_the_actual_cap() -> None:
    class ThreeStageModel:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []
            self.responses = [
                ModelResponse.from_final("execution complete"),
                RuntimeError("primary answer unavailable"),
                ModelResponse.from_final("degraded answer"),
            ]

        async def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            response = self.responses.pop(0)
            if isinstance(response, BaseException):
                raise response
            return response

    model = ThreeStageModel()
    limits = _limits(
        application_max_output_tokens=500,
        context_window_tokens=50_000,
        context_safety_margin_tokens=100,
        context_estimate_bytes_per_token=2,
        compaction_reserve_tokens=1000,
    )
    runtime = AgentRuntime(model, ToolRegistry(), limits=limits)
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(
        request_id,
        "question",
        initial_messages=[UserMessage(content="question")],
    )
    trace = AgentTraceCollector(capture_full_calls=True)

    asyncio.run(
        runtime.run(
            history.effective_messages(),
            execution_history=history,
            request_id=request_id,
            trace_collector=trace,
        )
    )

    calls = trace.snapshot()["model_calls"]
    assert [call["purpose"] for call in calls] == [
        "execution",
        "primary_answer",
        "degraded_answer",
    ]
    assert len(model.requests) == len(calls) == 3
    for request, call in zip(model.requests, calls, strict=True):
        budget = call["output_budget"]
        assert request.max_output_tokens == budget["actual_output_tokens"]
        assert call["request"]["max_output_tokens"] == request.max_output_tokens
        step = next(item for item in trace.snapshot()["steps"] if item["step"] == request.step)
        assert step["output_budget"] == budget
    capacities = trace.snapshot()["context_capacity_checks"]
    before_model = {
        item["stage"]: item["capacity"]
        for item in capacities
        if item["phase"] == "before_model"
    }
    assert set(before_model) == {"execution", "primary_answer", "degraded_answer"}
    for stage, capacity in before_model.items():
        request = model.requests[
            {"execution": 0, "primary_answer": 1, "degraded_answer": 2}[stage]
        ]
        assert capacity["actual_output_tokens"] == request.max_output_tokens
        assert capacity["expected_output_tokens"] == 500


def test_runtime_cap_matches_trace_and_openai_compatible_max_tokens() -> None:
    payloads: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.read()))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                "data: "
                + json.dumps(
                    {
                        "choices": [
                            {
                                "delta": {"role": "assistant", "content": "complete"},
                                "finish_reason": None,
                            }
                        ]
                    }
                )
                + "\n\ndata: "
                + json.dumps(
                    {"choices": [{"delta": {}, "finish_reason": "stop"}]}
                )
                + "\n\ndata: [DONE]\n\n"
            ),
            request=request,
        )

    model = OpenAICompatibleModelClient(
        api_key="offline-test-key",
        base_url="https://provider.test/v1",
        model="offline-test-model",
        transport=httpx.MockTransport(handle),
    )
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(application_max_output_tokens=333),
    )
    trace = AgentTraceCollector(capture_full_calls=True)

    asyncio.run(runtime.run([UserMessage(content="question")], trace_collector=trace))

    calls = trace.snapshot()["model_calls"]
    assert len(payloads) == len(calls) == 2
    for payload, call in zip(payloads, calls, strict=True):
        actual = call["output_budget"]["actual_output_tokens"]
        assert call["request"]["max_output_tokens"] == actual == payload["max_tokens"] == 333
