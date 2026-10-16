import asyncio

import pytest
from pydantic import BaseModel

from app.vnext.agent.answer_tools import AnswerToolSession
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.artifacts import (
    ArtifactGrepper,
    ArtifactReader,
    SessionArtifactStore,
    serialized_size,
)
from app.vnext.artifacts.query import ArtifactQuerier, ArtifactQueryInput
from app.vnext.llm.protocol import (
    AssistantMessage,
    ModelResponse,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.tools.artifacts import register_artifact_tools
from app.vnext.tools.definition import ToolAccess, ToolDefinition
from app.vnext.tools.errors import StructuredToolError
from app.vnext.tools.registry import ToolRegistry
from tests.vnext.fakes import ScriptedModelClient


class Empty(BaseModel):
    pass


class Output(BaseModel):
    value: str


def registry_with_value(value, budget):
    registry = ToolRegistry(observation_max_bytes=budget)
    registry.register(
        ToolDefinition(
            name="local.read",
            description="Local read",
            input_model=Empty,
            output_model=Output,
            handler=lambda _: {"value": value},
            externalize_result=False,
            access=ToolAccess.LOCAL_ARTIFACT_READ,
        )
    )
    return registry


@pytest.mark.parametrize("budget", [512, 64 * 1024])
def test_exact_utf8_boundary_has_same_outcome_in_execution_and_answer(budget):
    # The same content fits exactly, then exceeds by one UTF-8 byte.
    value = "中" * ((budget - serialized_size({"value": ""})) // 3)
    value += "x" * (budget - serialized_size({"value": value}))

    async def exercise():
        for extra in ["", "x"]:
            registry = registry_with_value(value + extra, budget)
            call = ToolCall(id="same", name="local.read", arguments={})
            execution = await registry.execute(call)
            answer = await AnswerToolSession(registry).execute(call, timeout=1)
            assert execution.model_dump() == answer.model_dump()
            if extra:
                assert execution.status == "error"
                assert execution.error.code == "invalid_tool_output"
                assert "byte limit" in execution.error.message
            else:
                assert execution.content == {"value": value}
                assert registry.result_size(execution) == budget
            assert registry.result_size(execution) <= budget

    asyncio.run(exercise())


def test_oversized_tool_error_and_argument_error_share_the_exit():
    registry = ToolRegistry(observation_max_bytes=256)

    def fail(_):
        raise StructuredToolError("invalid_arguments", "中" * 1000, {"large": "x" * 1000})

    registry.register(
        ToolDefinition(
            name="fail",
            description="Fail",
            input_model=Empty,
            output_model=Empty,
            handler=fail,
            access=ToolAccess.LOCAL_ARTIFACT_READ,
        )
    )

    async def exercise():
        for call in [
            ToolCall(id="failure", name="fail", arguments={}),
            ToolCall(id="unknown", name="unknown" * 1000, arguments={}),
            ToolCall(id="arguments", name="fail", arguments={f"field{i}": i for i in range(200)}),
        ]:
            result = await registry.execute(call)
            assert result.status == "error"
            assert result.error.message == "tool result byte limit exceeded"
            assert registry.result_size(result) <= 256

    asyncio.run(exercise())


def test_final_exit_catches_a_broken_result_processor():
    class BrokenProcessor:
        async def process(self, output, **_):
            from app.vnext.artifacts.processor import ProcessedToolResult

            return ProcessedToolResult(content={"value": "x" * 1000})

    registry = ToolRegistry(result_processor=BrokenProcessor(), observation_max_bytes=256)
    registry.register(
        ToolDefinition(
            name="ordinary",
            description="Ordinary",
            input_model=Empty,
            output_model=Output,
            handler=lambda _: {"value": "small"},
        )
    )
    result = asyncio.run(
        registry.execute(
            ToolCall(id="processor", name="ordinary", arguments={}),
        )
    )
    assert result.status == "error"
    assert registry.result_size(result) <= 256


def test_small_unusable_budget_is_rejected_before_dispatch():
    with pytest.raises(ValueError, match="minimal structured error"):
        ToolRegistry(observation_max_bytes=16)


def test_query_accepts_configured_result_above_old_fixed_ceiling():
    async def exercise():
        store = SessionArtifactStore()
        ref = await store.put({"rows": [{"value": "中" * 14000}]})
        args = ArtifactQueryInput(ref=ref, expression="$.rows[*]", fields=["value"])
        result = await ArtifactQuerier(store, observation_max_bytes=64 * 1024).query(args)
        assert 35 * 1024 < serialized_size(result.model_dump(mode="json")) <= 64 * 1024
        assert (await ArtifactReader(store).outline(ref)).ref == ref

    asyncio.run(exercise())


@pytest.mark.parametrize("degraded", [False, True])
def test_runtime_pages_grep_in_execution_answer_and_degraded_continuation(degraded):
    async def exercise():
        store = SessionArtifactStore()
        ref = await store.put({"rows": [{"name": "needle中文" * 20} for _ in range(12)]})
        budget = 1000
        grepper = ArtifactGrepper(store, observation_max_bytes=budget)
        first = await grepper.grep(ref, "needle")
        assert first.truncated and first.next_offset == first.returned
        registry = ToolRegistry(observation_max_bytes=budget)
        register_artifact_tools(
            registry,
            ArtifactReader(store, observation_max_bytes=budget),
            grepper,
        )
        args = {"ref": ref, "pattern": "needle"}

        def response(ident, arguments):
            return ModelResponse(
                message=AssistantMessage(
                    tool_calls=[
                        ToolCall(id=ident, name="artifact.grep", arguments=arguments),
                    ]
                )
            )

        responses = [
            response("execution-page", args),
            ModelResponse.from_final("Execution found the first page."),
            response("answer-recheck", args),
        ]
        if degraded:
            responses.append(RuntimeError("primary answer unavailable"))
        responses.extend(
            [
                response("answer-next-page", {**args, "offset": first.next_offset}),
                ModelResponse.from_final("Verified two pages."),
            ]
        )
        model = ScriptedModelClient(responses)
        answer = await AgentRuntime(
            model,
            registry,
            limits=AgentLimits(application_max_output_tokens=1024),
        ).run([UserMessage(content=f"Read the existing artifact {ref}")])
        assert answer.content == "Verified two pages."
        results = {
            m.tool_call_id: m
            for request in model.requests
            for m in request.messages
            if isinstance(m, ToolResultMessage)
        }
        assert results["execution-page"].content == results["answer-recheck"].content
        assert results["answer-next-page"].content["offset"] == first.next_offset
        assert all(r.status == "ok" and registry.result_size(r) <= budget for r in results.values())
        paths = [
            m["path"]
            for ident in ["execution-page", "answer-next-page"]
            for m in results[ident].content["matches"]
        ]
        assert len(paths) == len(set(paths))
        assert len(store._documents) == 1  # No retrieval-result re-externalization.

    asyncio.run(exercise())
