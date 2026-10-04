from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

import app.vnext.composition as composition
from app.vnext.agent.context_accounting import measure_request_context_bytes
from app.vnext.agent.instructions import (
    AGENT_INSTRUCTION,
    ANSWER_INSTRUCTION,
    DEGRADED_ANSWER_INSTRUCTION,
    PRODUCT_INSTRUCTION,
)
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.protocol import (
    FinalMessage,
    ModelRequest,
    ModelResponse,
    SystemMessage,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools import ToolRegistry


class _StrictModel:
    def __init__(self, responses: list[ModelResponse | Exception]) -> None:
        self.responses = list(responses)
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request.model_copy(deep=True))
        if not self.responses:
            raise AssertionError("identity test model script was exhausted")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _product_runtime(
    monkeypatch: pytest.MonkeyPatch,
    model: _StrictModel,
    *,
    limits: AgentLimits | None = None,
) -> AgentRuntime:
    monkeypatch.setattr(
        composition,
        "OpenAICompatibleModelClient",
        lambda **_: model,
    )
    settings = composition.VNextSettings(
        agent_limits=limits or AgentLimits(application_max_output_tokens=4096)
    )
    return composition.build_vnext_runtime(
        settings=settings,
        services=composition.VNextServices(),
    )


def _run(awaitable: Any) -> Any:
    return asyncio.run(asyncio.wait_for(awaitable, timeout=5))


def _system_text(request: ModelRequest) -> str:
    return "\n".join(
        message.content for message in request.messages if isinstance(message, SystemMessage)
    )


def _assert_identity_once(request: ModelRequest) -> None:
    assert _system_text(request).count(PRODUCT_INSTRUCTION) == 1


def _message_text(request: ModelRequest) -> str:
    return "\n".join(
        message.content
        for message in request.messages
        if isinstance(message, (SystemMessage, UserMessage, FinalMessage))
    )


def test_product_composition_shares_identity_with_execution_and_primary_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _StrictModel(
        [ModelResponse.from_final("execution draft"), ModelResponse.from_final("answer")]
    )
    limits = AgentLimits(
        deadline_seconds=5,
        answer_timeout_seconds=5,
        context_window_tokens=100_000,
        application_max_output_tokens=512,
        context_safety_margin_tokens=128,
        context_estimate_bytes_per_token=1,
    )
    runtime = _product_runtime(monkeypatch, model, limits=limits)
    history = SessionExecutionHistory()
    request_id = uuid4()
    messages = history.begin_request(request_id, "hello")
    trace = AgentTraceCollector()

    result = _run(
        runtime.run(
            messages,
            execution_history=history,
            request_id=request_id,
            trace_collector=trace,
        )
    )

    assert result.content == "answer"
    assert len(model.requests) == 2
    execution_request, answer_request = model.requests
    _assert_identity_once(execution_request)
    _assert_identity_once(answer_request)
    assert AGENT_INSTRUCTION in _system_text(execution_request)
    assert "Use only the tools declared in the current tool catalog." not in _message_text(
        answer_request
    )
    assert ANSWER_INSTRUCTION in _system_text(answer_request)

    execution_capacity = next(
        item["capacity"]
        for item in trace.snapshot()["context_capacity_checks"]
        if item["stage"] == "execution" and item["phase"] == "before_model"
    )
    measured = measure_request_context_bytes(execution_request)
    without_identity = execution_request.model_copy(
        update={
            "messages": [
                message.model_copy(
                    update={"content": message.content.replace(PRODUCT_INSTRUCTION, "")}
                )
                if isinstance(message, SystemMessage)
                else message.model_copy(deep=True)
                for message in execution_request.messages
            ]
        }
    )
    assert execution_capacity["context_bytes"] == measured
    assert measured > measure_request_context_bytes(without_identity)

    persisted_text = "\n".join(
        [
            *(message.model_dump_json() for message in history.effective_messages()),
            *(record.message.model_dump_json() for record in history.records),
        ]
    )
    assert PRODUCT_INSTRUCTION not in persisted_text
    assert AGENT_INSTRUCTION not in persisted_text


def test_degraded_answer_keeps_identity_without_execution_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _StrictModel(
        [
            ModelResponse.from_final("execution draft"),
            RuntimeError("synthetic primary failure"),
            ModelResponse.from_final("concise fallback"),
        ]
    )
    runtime = _product_runtime(monkeypatch, model)

    result = _run(runtime.run([UserMessage(content="hello")]))

    assert result.content == "concise fallback"
    assert len(model.requests) == 3
    execution_request, primary_request, degraded_request = model.requests
    _assert_identity_once(execution_request)
    _assert_identity_once(primary_request)
    _assert_identity_once(degraded_request)
    assert ANSWER_INSTRUCTION in _system_text(primary_request)
    assert DEGRADED_ANSWER_INSTRUCTION in _system_text(degraded_request)
    for answer_request in (primary_request, degraded_request):
        assert "Use only the tools declared in the current tool catalog." not in _message_text(
            answer_request
        )


def test_compaction_rebuild_does_not_duplicate_or_persist_product_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _StrictModel(
        [
            ModelResponse.from_final("summary", finish_reason="stop"),
            ModelResponse.from_final("execution"),
            ModelResponse.from_final("answer"),
        ]
    )
    limits = AgentLimits(
        deadline_seconds=5,
        answer_timeout_seconds=5,
        application_max_output_tokens=4096,
        compaction_keep_recent_tokens=1,
        compaction_max_input_bytes=10_000,
        compaction_reserve_tokens=160,
    )
    runtime = _product_runtime(monkeypatch, model, limits=limits)
    history = SessionExecutionHistory()
    request_id = uuid4()
    messages = history.begin_request(
        request_id,
        "current question",
        initial_messages=[
            UserMessage(content="older question"),
            FinalMessage(content="older answer " + "context " * 40),
        ],
    )

    result = _run(
        runtime.run(
            messages,
            execution_history=history,
            request_id=request_id,
            compact_before_steps=(1,),
        )
    )

    assert result.content == "answer"
    compaction_requests = [
        request
        for request in model.requests
        if request.metadata.get("purpose") == "context_compaction"
    ]
    business_requests = [
        request
        for request in model.requests
        if request.metadata.get("purpose") != "context_compaction"
    ]
    assert len(compaction_requests) == 1
    assert PRODUCT_INSTRUCTION not in _system_text(compaction_requests[0])
    assert len(business_requests) == 2
    for request in business_requests:
        _assert_identity_once(request)
    assert AGENT_INSTRUCTION in _system_text(business_requests[0])
    assert "Use only the tools declared in the current tool catalog." not in _message_text(
        business_requests[1]
    )
    assert all(
        PRODUCT_INSTRUCTION not in record.message.model_dump_json() for record in history.records
    )


def test_general_runtime_remains_usable_without_product_identity() -> None:
    model = _StrictModel(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(deadline_seconds=5, application_max_output_tokens=4096),
    )

    result = _run(runtime.run([UserMessage(content="hello")]))

    assert result.content == "answer"
    assert len(model.requests) == 2
    assert all("DotaMind" not in _system_text(request) for request in model.requests)
