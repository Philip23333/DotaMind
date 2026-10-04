from __future__ import annotations

import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest

import app.vnext.composition as composition
from app.vnext.agent.instructions import (
    AGENT_INSTRUCTION,
    ANSWER_INSTRUCTION,
    DEGRADED_ANSWER_INSTRUCTION,
    PRODUCT_INSTRUCTION,
)
from app.vnext.agent.limits import AgentLimits
from app.vnext.capabilities.hero.guide import (
    GuideSourceMetadata,
    HeroGuideInput,
    HeroGuideResult,
    PubGuide,
    SkillSequenceOption,
)
from app.vnext.llm.errors import ModelContextWindowError
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    ModelRequest,
    ModelResponse,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools import ToolRegistry
from tests.vnext.fakes import ScriptedModelClient, ScriptedTranscriptModelClient

INVENTORY_HEADER = "Enabled tools for this run:\n"
STAGE_BOUNDARY = (
    "During the answer stage, tool calls are disabled because execution\n"
    "has ended; this does not mean these capabilities are absent from the product."
)


def _inventory(text: str) -> list[str]:
    assert text.count(INVENTORY_HEADER) == 1
    listing = text.split(INVENTORY_HEADER, 1)[1].split("\n\n", 1)[0]
    if listing == "none":
        return []
    lines = listing.splitlines()
    assert all(line.startswith("- ") for line in lines)
    return [line[2:] for line in lines]


def _system_text(request: ModelRequest) -> str:
    return "\n".join(
        message.content for message in request.messages if isinstance(message, SystemMessage)
    )


def _assert_inventory(request: ModelRequest, names: list[str]) -> None:
    text = _system_text(request)
    assert _inventory(text) == names
    assert len(names) == len(set(names))
    assert text.count(PRODUCT_INSTRUCTION) == 1
    assert STAGE_BOUNDARY in text
    assert "The inventory is not evidence that any lookup succeeded." in text
    assert "they do not override the current inventory" in text


async def _offline_guide(query: HeroGuideInput) -> HeroGuideResult:
    return HeroGuideResult(
        hero_id=query.hero_id,
        position=query.position,
        section=query.section,
        pub_metadata=GuideSourceMetadata(
            provider="d2pt",
            sample_type="pub",
            availability="available",
            stale=False,
        ),
        pro_metadata=GuideSourceMetadata(
            provider="d2pt",
            sample_type="pro",
            availability="missing",
            stale=False,
        ),
        pub_guides=[
            PubGuide(
                build_id=1,
                skill_sequences=[
                    SkillSequenceOption(
                        ability_ids=[5003, 5004],
                        source_path="offline-fixture.skills",
                    )
                ],
            )
        ],
        pub_guides_total=1,
        pro_examples_total=0,
    )


@pytest.mark.parametrize("guide_enabled", [False, True])
def test_composition_uses_one_registry_for_schemas_and_shared_inventory(
    monkeypatch: pytest.MonkeyPatch,
    guide_enabled: bool,
) -> None:
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )
    monkeypatch.setattr(composition, "OpenAICompatibleModelClient", lambda **_: model)
    original_builder = composition.build_vnext_registry
    built: list[ToolRegistry] = []

    def capture_builder(*args, **kwargs):
        registry = original_builder(*args, **kwargs)
        built.append(registry)
        return registry

    monkeypatch.setattr(composition, "build_vnext_registry", capture_builder)
    runtime = composition.build_vnext_runtime(
        settings=composition.VNextSettings(
            agent_limits=AgentLimits(application_max_output_tokens=4096)
        ),
        services=composition.VNextServices(hero_guide=_offline_guide if guide_enabled else None),
    )
    messages = [UserMessage(content="What can you do?")]
    before = deepcopy(messages)

    result = asyncio.run(runtime.run(messages))

    assert result.content == "answer"
    assert built == [runtime.tools]
    names = [tool.name for tool in runtime.tools.list()]
    assert ("hero.guide" in names) is guide_enabled
    assert _inventory(runtime.shared_instruction) == names
    assert len(model.requests) == 2
    execution, answer = model.requests
    assert [tool.name for tool in execution.tools] == names
    for request in model.requests:
        _assert_inventory(request, names)
    assert answer.tools == []
    assert AGENT_INSTRUCTION not in _system_text(answer)
    assert messages == before


def test_empty_registry_is_explicit_and_is_the_runtime_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ToolRegistry()
    calls = []

    def build_empty(*args, **kwargs):
        calls.append(kwargs)
        return registry

    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )
    monkeypatch.setattr(composition, "OpenAICompatibleModelClient", lambda **_: model)
    monkeypatch.setattr(composition, "build_vnext_registry", build_empty)
    runtime = composition.build_vnext_runtime(
        settings=composition.VNextSettings(
            agent_limits=AgentLimits(application_max_output_tokens=4096)
        ),
        services=composition.VNextServices(),
    )

    asyncio.run(runtime.run([UserMessage(content="hello")]))

    assert len(calls) == 1
    assert calls[0]["task_state_coordinator"] is runtime.task_state_coordinator
    assert runtime.tools is registry
    assert INVENTORY_HEADER + "none\n\n" in runtime.shared_instruction
    for request in model.requests:
        assert request.tools == []
        _assert_inventory(request, [])


def test_old_refusals_do_not_hide_guide_schema_or_answer_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = [
        UserMessage(content="Can you provide hero guides?"),
        FinalMessage(content="目前不提供英雄攻略"),
        UserMessage(content="What capabilities are available?"),
        FinalMessage(content="只有网页搜索"),
        UserMessage(content="给我敌法师一号位攻略"),
    ]
    before = deepcopy(messages)
    calls: list[HeroGuideInput] = []

    async def lookup(query: HeroGuideInput) -> HeroGuideResult:
        calls.append(query)
        return await _offline_guide(query)

    def query_guide(request: ModelRequest) -> ModelResponse:
        names = [tool.name for tool in request.tools]
        assert "hero.guide" in names
        _assert_inventory(request, names)
        assert all(message in request.messages for message in before)
        return ModelResponse.from_assistant(
            AssistantMessage(
                tool_calls=[
                    ToolCall(
                        id="guide-call",
                        name="hero.guide",
                        arguments={"hero_id": 1, "position": 1, "section": "all"},
                    )
                ]
            )
        )

    def finish_execution(request: ModelRequest) -> ModelResponse:
        results = [m for m in request.messages if isinstance(m, ToolResultMessage)]
        assert len(results) == 1 and results[0].status == "ok"
        assert results[0].content["pub_guides"][0]["build_id"] == 1
        return ModelResponse.from_final("execution evidence ready")

    def answer(request: ModelRequest) -> ModelResponse:
        assert request.tools == []
        _assert_inventory(request, [tool.name for tool in runtime.tools.list()])
        assert all(message in request.messages for message in before)
        evidence = "\n".join(message.model_dump_json() for message in request.messages)
        assert "offline-fixture" in evidence
        assert AGENT_INSTRUCTION not in _system_text(request)
        return ModelResponse.from_final("offline guide answer")

    model = ScriptedTranscriptModelClient([query_guide, finish_execution, answer])
    monkeypatch.setattr(composition, "OpenAICompatibleModelClient", lambda **_: model)
    runtime = composition.build_vnext_runtime(
        settings=composition.VNextSettings(
            agent_limits=AgentLimits(application_max_output_tokens=4096)
        ),
        services=composition.VNextServices(hero_guide=lookup),
    )

    result = asyncio.run(runtime.run(messages))

    assert result.content == "offline guide answer"
    assert len(model.requests) == 3
    assert calls == [HeroGuideInput(hero_id=1, position=1, section="all")]
    assert messages == before


def test_answer_overflow_retry_and_degraded_answer_keep_inventory_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overflow = ModelContextWindowError(
        provider_code="context_length_exceeded",
        status_code=400,
    )
    model = ScriptedModelClient(
        [
            ModelResponse.from_final("execution"),
            overflow,
            ModelResponse.from_final("compressed earlier background", finish_reason="stop"),
            RuntimeError("synthetic retry failure"),
            ModelResponse.from_final("degraded answer"),
        ]
    )
    monkeypatch.setattr(composition, "OpenAICompatibleModelClient", lambda **_: model)
    limits = AgentLimits(
        deadline_seconds=5,
        answer_timeout_seconds=5,
        compaction_keep_recent_tokens=1,
        compaction_max_input_bytes=100_000,
        compaction_reserve_tokens=160,
        context_window_tokens=100_000,
        application_max_output_tokens=64,
        context_safety_margin_tokens=16,
        context_estimate_bytes_per_token=1,
    )
    runtime = composition.build_vnext_runtime(
        settings=composition.VNextSettings(agent_limits=limits),
        services=composition.VNextServices(hero_guide=_offline_guide),
    )
    history = SessionExecutionHistory()
    request_id = uuid4()
    messages = history.begin_request(
        request_id,
        "current question",
        initial_messages=[
            UserMessage(content="older question"),
            FinalMessage(content="older background " * 40),
            UserMessage(content="current question"),
        ],
    )
    before = deepcopy(messages)

    result = asyncio.run(
        runtime.run(
            messages,
            execution_history=history,
            request_id=request_id,
        )
    )

    assert result.content == "degraded answer"
    assert len(model.requests) == 5
    execution, primary, compaction, retry, degraded = model.requests
    assert compaction.metadata.get("purpose") == "context_compaction"
    assert INVENTORY_HEADER not in _system_text(compaction)
    names = [tool.name for tool in runtime.tools.list()]
    for request in (execution, primary, retry, degraded):
        _assert_inventory(request, names)
    for request in (primary, retry, degraded):
        assert request.tools == []
        assert AGENT_INSTRUCTION not in _system_text(request)
    assert ANSWER_INSTRUCTION in _system_text(primary)
    assert ANSWER_INSTRUCTION in _system_text(retry)
    assert DEGRADED_ANSWER_INSTRUCTION in _system_text(degraded)
    assert messages == before
