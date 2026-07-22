import asyncio
import codecs
import hashlib
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from pydantic import BaseModel

import app.agentic.prompts.controller as controller_prompts
from app.agentic.graph import AgentGraphRunner
from app.agentic.planning.contracts import CONTRACT_REGISTRY
from app.agentic.planning.controller import AgentController
from app.agentic.prompts.controller import (
    build_controller_prompt,
    render_controller_user_message,
)
from app.agentic.prompts.feedback import (
    render_recovery_rules,
    render_validation_retry_feedback,
)
from app.agentic.prompts.versions import RECOVERY_RULES_VERSION
from app.agentic.state import AgentRunState
from app.agentic.tools import ToolDefinition
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import Settings, get_policy


class ExtraInput(BaseModel):
    value: str


class CapturingLLM:
    def __init__(self) -> None:
        self.calls = 0
        self.messages: list[list[dict[str, str]]] = []

    async def complete_json(self, messages, **kwargs):
        self.calls += 1
        self.messages.append([dict(message) for message in messages])
        return {
            "kind": "direct_answer",
            "intent": "social",
            "response_mode": "social",
            "basis": [],
            "answer": "hello",
        }


def _registry():
    return build_default_tool_registry(
        Settings(stratz_graphql_url="https://api.stratz.test/graphql", stratz_token="token")
    )


def _extra_definition() -> ToolDefinition:
    return ToolDefinition(
        name="debug.extra",
        description="Extra catalog entry.",
        input_model=ExtraInput,
        handler=lambda args, context: {"value": args.value},
    )


def test_system_prompt_matches_utf8_lf_golden_fixture() -> None:
    controller = AgentController(_registry(), llm_enabled=False)
    fixture = Path(__file__).parent / "fixtures" / "prompts" / "controller_system_v1.txt"
    fixture_bytes = fixture.read_bytes()

    assert not fixture_bytes.startswith(codecs.BOM_UTF8)
    assert b"\r\n" not in fixture_bytes
    assert fixture_bytes == controller._system_prompt().encode("utf-8")
    assert controller.prompt_versions["controller.system.sha256"] == hashlib.sha256(
        fixture_bytes
    ).hexdigest()


def test_prompt_hash_changes_with_rendered_catalog_contract_and_policy(monkeypatch) -> None:
    policy = get_policy()
    baseline = build_controller_prompt(_registry(), policy).prompt_versions[
        "controller.system.sha256"
    ]

    with monkeypatch.context() as scoped:
        scoped.setattr(
            controller_prompts,
            "_PLANNER_SYSTEM_PROMPT",
            controller_prompts._PLANNER_SYSTEM_PROMPT + "\nstatic change",
        )
        assert build_controller_prompt(_registry(), policy).prompt_versions[
            "controller.system.sha256"
        ] != baseline

    tools_registry = _registry()
    tools_registry.register(_extra_definition())
    assert build_controller_prompt(tools_registry, policy).prompt_versions[
        "controller.system.sha256"
    ] != baseline

    tool_name, entry = next(iter(policy.planning.sample_policy.tools.items()))
    policy_with_change = policy.model_copy(
        update={
            "planning": policy.planning.model_copy(
                update={
                    "sample_policy": policy.planning.sample_policy.model_copy(
                        update={
                            "tools": {
                                **policy.planning.sample_policy.tools,
                                tool_name: entry.model_copy(
                                    update={"default": entry.default + 1}
                                ),
                            }
                        }
                    )
                }
            )
        }
    )
    assert build_controller_prompt(_registry(), policy_with_change).prompt_versions[
        "controller.system.sha256"
    ] != baseline

    original = CONTRACT_REGISTRY["natural_language_answer"]
    monkeypatch.setitem(
        CONTRACT_REGISTRY,
        "natural_language_answer",
        replace(original, route="changed-for-test"),
    )
    assert build_controller_prompt(_registry(), policy).prompt_versions[
        "controller.system.sha256"
    ] != baseline


def test_dynamic_user_and_retry_messages_do_not_change_prompt_manifest() -> None:
    controller = AgentController(_registry(), llm_enabled=False)
    before = controller.prompt_versions

    first = render_controller_user_message(
        "first query", "dota2", [], history_max_chars=100
    )
    second = render_controller_user_message(
        "second query", "other-game", [], history_max_chars=1
    )
    assert first != second
    assert render_validation_retry_feedback(["first error"]) != render_validation_retry_feedback(
        ["second error"]
    )
    assert controller.prompt_versions == before


def test_enabled_llm_system_message_matches_run_manifest() -> None:
    registry = _registry()
    llm = CapturingLLM()
    controller = AgentController(registry, llm=llm, llm_enabled=True)

    state = asyncio.run(
        AgentGraphRunner(controller, registry).run(AgentRunState(query="hello", game="dota2"))
    )

    sent_system = llm.messages[0][0]["content"]
    manifest = state.run_context.prompt_versions
    assert hashlib.sha256(sent_system.encode("utf-8")).hexdigest() == manifest[
        "controller.system.sha256"
    ]
    assert "recovery_rules" not in manifest
    assert state.response["runtime"]["attempts"][0].get("prompt_versions") is None


def test_disabled_llm_still_records_prepared_prompt_manifest() -> None:
    registry = _registry()
    llm = CapturingLLM()
    controller = AgentController(registry, llm=llm, llm_enabled=False)

    state = asyncio.run(
        AgentGraphRunner(controller, registry).run(AgentRunState(query="hello", game="dota2"))
    )

    assert llm.calls == 0
    assert state.run_context.prompt_versions == controller.prompt_versions
    assert state.run_context.prompt_versions["controller.validation_retry"] == "v1"


def test_recovery_rules_remain_dormant_and_imports_are_acyclic() -> None:
    controller = AgentController(_registry(), llm_enabled=False)

    assert RECOVERY_RULES_VERSION == "v1"
    assert render_recovery_rules() not in controller._system_prompt()
    assert "recovery_rules" not in controller.prompt_versions
    assert controller.prompt_versions["controller.validation_retry"] == "v1"
    assert render_validation_retry_feedback(["bad field"]) == (
        "Your previous response was rejected. Return the FULL corrected "
        "ControllerDecision JSON again, fixing every issue:\n"
        "- bad field\nDo not explain; only return the corrected JSON."
    )
    recovery_rules = render_recovery_rules()
    for clause in (
        "preserve every successful prior call's\n  id, tool, and args",
        "append only legal evidence-producing calls",
        "Do not weaken the output contract, required evidence, or explicit user\n  constraints",
        "Do not use changed call ids",
    ):
        assert clause in recovery_rules

    root = Path(__file__).resolve().parents[1]
    for statement in (
        "import app.agentic.prompts.controller; import app.agentic.planning.controller",
        "import app.agentic.planning.controller; import app.agentic.prompts.controller",
    ):
        subprocess.run([sys.executable, "-c", statement], cwd=root, check=True)
