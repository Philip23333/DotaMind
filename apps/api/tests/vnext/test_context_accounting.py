from __future__ import annotations

from app.vnext.agent.context_accounting import build_context_accounting
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.artifacts.retrieval import ArtifactReadResult
from app.vnext.llm.protocol import (
    AssistantMessage,
    Message,
    ModelRequest,
    ModelTool,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)


def _stable_messages() -> list[Message]:
    return [
        SystemMessage(content="Base instruction"),
        UserMessage(content="查一下 TI 比赛"),
        AssistantMessage(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call-1",
                    name="match.search",
                    arguments={"year": 2026},
                )
            ],
        ),
        ToolResultMessage(
            tool_call_id="call-1",
            content={"matches": [{"id": 123, "winner": "Team Spirit"}]},
        ),
    ]


def _tool() -> ModelTool:
    return ModelTool(
        name="match.search",
        description="Search matches.",
        input_schema={
            "type": "object",
            "properties": {"year": {"type": "integer"}},
        },
    )


def test_context_accounting_is_deterministic_and_split_by_role() -> None:
    stable = _stable_messages()
    runtime_prompt = "Runtime state:\nExecution phase:\nexploration"
    effective = list(stable)
    effective[0] = SystemMessage(content=f"{stable[0].content}\n\n{runtime_prompt}")
    request = ModelRequest(messages=effective, tools=[_tool()], step=1)

    first = build_context_accounting(request, stable_messages=stable).to_dict()
    second = build_context_accounting(request, stable_messages=stable).to_dict()

    assert first == second
    assert first["measurement"] == "canonical_json_utf8_bytes"
    assert first["stable_messages"]["count"] == 4
    assert first["stable_messages"]["by_role"]["system"]["count"] == 1
    assert first["stable_messages"]["by_role"]["user"]["count"] == 1
    assert first["stable_messages"]["by_role"]["assistant"]["count"] == 1
    assert first["stable_messages"]["by_role"]["tool"]["count"] == 1
    assert first["stable_messages"]["by_role"]["tool"]["serialized_bytes"] > 0
    assert first["tool_schemas"]["count"] == 1
    assert first["tool_schemas"]["serialized_bytes"] > 0
    assert first["runtime_prompt"]["present"] is True
    assert first["runtime_prompt"]["serialized_bytes"] > 0
    assert first["effective_request"]["message_count"] == 4
    assert first["effective_request"]["tool_count"] == 1
    assert (
        first["effective_request"]["serialized_bytes"]
        > first["stable_messages"]["serialized_bytes"]
    )
    assert first["task_context"] == {
        "present": False,
        "serialized_bytes": 0,
        "task_state": {"count": 0, "serialized_bytes": 0},
        "active_manifest": {"count": 0, "serialized_bytes": 0},
    }
    assert first["artifact_observations"] == {
        "active_raw": {"count": 0, "serialized_bytes": 0},
        "receipts": {"count": 0, "serialized_bytes": 0},
    }


def test_context_accounting_treats_cjk_as_utf8_bytes_without_token_estimation() -> None:
    ascii_request = ModelRequest(messages=[UserMessage(content="abc")], step=1)
    cjk_request = ModelRequest(messages=[UserMessage(content="比赛赛")], step=1)

    ascii_usage = build_context_accounting(ascii_request).to_dict()
    cjk_usage = build_context_accounting(cjk_request).to_dict()

    assert (
        cjk_usage["stable_messages"]["serialized_bytes"]
        > ascii_usage["stable_messages"]["serialized_bytes"]
    )
    assert cjk_usage["runtime_prompt"] == {"present": False, "serialized_bytes": 0}


def test_trace_records_accounting_without_persisting_runtime_prompt_text() -> None:
    stable = [UserMessage(content="hello")]
    runtime_prompt = SystemMessage(content="Runtime state: private ephemeral prompt")
    request = ModelRequest(messages=[runtime_prompt, *stable], tools=[_tool()], step=1)
    collector = AgentTraceCollector()

    collector.model_request(request, conversation_messages=stable)

    step = collector.snapshot()["steps"][0]
    accounting = step["context_accounting"]
    assert accounting["stable_messages"]["count"] == 1
    assert accounting["stable_messages"]["by_role"]["user"]["count"] == 1
    assert accounting["tool_schemas"]["count"] == 1
    assert accounting["runtime_prompt"]["present"] is True
    assert accounting["runtime_prompt"]["serialized_bytes"] > 0
    assert "Runtime state: private ephemeral prompt" not in str(step["model_request"])
    assert "Runtime state: private ephemeral prompt" not in str(accounting)


def test_legacy_trace_request_has_zero_runtime_prompt_contribution() -> None:
    collector = AgentTraceCollector()
    request = ModelRequest(messages=[UserMessage(content="hello")], step=1)

    collector.model_request(request)

    accounting = collector.snapshot()["steps"][0]["context_accounting"]
    assert accounting["runtime_prompt"] == {"present": False, "serialized_bytes": 0}
    assert accounting["effective_request"]["message_count"] == 1


def test_context_accounting_splits_task_context_and_runtime_prompt() -> None:
    stable = [
        UserMessage(content="collect"),
        AssistantMessage(
            tool_calls=[
                ToolCall(
                    id="read-1",
                    name="artifact.read",
                    arguments={"ref": "artifact:test", "mode": "read", "path": "rows"},
                ),
                ToolCall(
                    id="read-2",
                    name="artifact.read",
                    arguments={"ref": "artifact:test", "mode": "read", "path": "rows"},
                ),
            ]
        ),
        ToolResultMessage(
            tool_call_id="read-1",
            content=ArtifactReadResult(
                ref="artifact:test", path="rows", value=[{"fact": "raw"}]
            ).model_dump(mode="json"),
        ),
        ToolResultMessage(
            tool_call_id="read-2",
            content={
                "_artifact_observation": {
                    "state": "receipt_only",
                    "reason": "checkpointed",
                    "re_readable": True,
                    "mode": "read",
                    "ref": "artifact:test",
                    "path": "rows",
                    "offset": 0,
                    "limit": 1,
                    "checkpoint_id": "checkpoint:one",
                }
            },
        ),
    ]
    task_context = [
        SystemMessage(
            content=(
                'Task state:\n{"part":{"fact":"saved"}}\n\n'
                'Checkpointable artifact observations:\n[]'
            )
        ),
        *stable,
    ]
    effective = [
        SystemMessage(
            content=(
                'Task state:\n{"part":{"fact":"saved"}}\n\n'
                'Checkpointable artifact observations:\n[]\n\n'
                'Runtime state:\nexploration'
            )
        ),
        *stable,
    ]
    payload = {
        "task_state": {"part": {"fact": "saved"}},
        "active_manifest": [],
    }
    accounting = build_context_accounting(
        ModelRequest(messages=effective, tools=[_tool()], step=1),
        stable_messages=stable,
        task_context_messages=task_context,
        task_context_payload=payload,
    ).to_dict()

    assert accounting["task_context"]["present"] is True
    assert accounting["task_context"]["serialized_bytes"] > 0
    assert accounting["task_context"]["task_state"]["count"] == 1
    assert accounting["task_context"]["task_state"]["serialized_bytes"] > 0
    assert accounting["task_context"]["active_manifest"] == {
        "count": 0,
        "serialized_bytes": 2,
    }
    assert accounting["runtime_prompt"]["present"] is True
    assert accounting["runtime_prompt"]["serialized_bytes"] > 0
    assert accounting["artifact_observations"]["active_raw"]["count"] == 1
    assert accounting["artifact_observations"]["active_raw"]["serialized_bytes"] > 0
    assert accounting["artifact_observations"]["receipts"]["count"] == 1
    assert accounting["artifact_observations"]["receipts"]["serialized_bytes"] > 0


def test_context_accounting_task_context_bytes_are_not_in_runtime_prompt() -> None:
    stable = [UserMessage(content="hello")]
    task_context = [SystemMessage(content="Task state:\n{\"a\":1}"), *stable]
    effective = [
        SystemMessage(content="Task state:\n{\"a\":1}\n\nRuntime state:\nexploration"),
        *stable,
    ]
    accounting = build_context_accounting(
        ModelRequest(messages=effective, step=1),
        stable_messages=stable,
        task_context_messages=task_context,
        task_context_payload={"task_state": {"a": 1}, "active_manifest": []},
    ).to_dict()

    assert accounting["task_context"]["serialized_bytes"] > 0
    assert accounting["runtime_prompt"]["serialized_bytes"] > 0
    assert accounting["runtime_prompt"]["serialized_bytes"] < (
        accounting["task_context"]["serialized_bytes"]
        + accounting["runtime_prompt"]["serialized_bytes"]
    )
