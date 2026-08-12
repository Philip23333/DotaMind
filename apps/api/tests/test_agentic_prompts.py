import asyncio
import codecs
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from pydantic import BaseModel

import app.agentic.prompts.controller as controller_prompts
from app.agentic.conversation.models import ConversationMessage
from app.agentic.graph import AgentGraphRunner
from app.agentic.planning.contracts import CONTRACT_REGISTRY
from app.agentic.planning.controller import AgentController
from app.agentic.planning.decisions import ToolPlanDecision
from app.agentic.prompts.controller import (
    build_controller_prompt,
    render_controller_messages,
)
from app.agentic.prompts.feedback import (
    render_recovery_feedback,
    render_recovery_rules,
    render_validation_retry_feedback,
)
from app.agentic.prompts.versions import RECOVERY_RULES_VERSION
from app.agentic.runtime.models import RecoveryExecutedCall, RecoveryFeedback
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
            "answer": "hello",
        }


class SequenceCapturingLLM:
    def __init__(self, *payloads: dict) -> None:
        self.payloads = list(payloads)
        self.messages: list[list[dict[str, str]]] = []

    async def complete_json(self, messages, **kwargs):
        self.messages.append([dict(message) for message in messages])
        return self.payloads.pop(0)


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


def test_controller_prompt_declares_catalog_static_and_statistical_boundaries() -> None:
    prompt = AgentController(_registry(), llm_enabled=False)._system_prompt()

    assert "official committed Catalog snapshot queries for current hero attributes" in prompt
    assert "official hero ability definitions" in prompt
    assert "official hero talent trees at levels 10/15/20/25" in prompt
    assert "official item definitions, prices" in prompt
    assert "Never substitute static\n  definitions" in prompt
    assert "return\n  capability_boundary" in prompt
    assert 'dota.hero_abilities(hero_id="$<resolve_call>.data.hero.hero_id")' in prompt
    assert "call resolve_hero exactly once" in prompt
    assert "Hero ability query granularity" in prompt
    assert '"齐天大圣有什么技能"' in prompt
    assert "hero_identity + hero_ability + hero_talent_tree" in prompt
    assert '"棒击大地是什么"' in prompt
    assert "Do not add dota.hero_talent_tree" in prompt
    assert 'dota.item_info(item_id="$<resolve_call>.data.item.item_id")' in prompt


def test_controller_prompt_uses_decision_kind_for_unsupported_scope() -> None:
    prompt = AgentController(_registry(), llm_enabled=False)._system_prompt()

    assert "return\n  capability_boundary and state the filter is unavailable" in prompt
    assert "return\n  insufficient_tools and state the filter is unavailable" not in prompt


def test_controller_prompt_uses_one_generic_history_first_decision_order() -> None:
    prompt = AgentController(_registry(), llm_enabled=False)._system_prompt()

    assert "Decision priority (evaluate in this order):" in prompt
    assert "return direct_answer" in prompt
    assert "return direct_answer and stop" in prompt
    assert "Rules that describe which\ntools a query needs apply only after step 4" in prompt
    assert "Once tool_plan is selected" in prompt
    assert "After tool_plan has been selected for fresh evidence" in prompt
    assert "For a fresh complete ability-list tool plan" in prompt
    assert "This direct answer does not create an EvidenceGraph" in prompt
    assert "The length or formatting of a historical answer is not a refresh trigger" in prompt
    assert "every\n  statistical metric and value requested" in prompt
    assert "If even one requested metric is\n  absent, choose tool_plan" in prompt
    assert "a further query would be needed" in prompt
    assert "perform that\n  query through tool_plan instead" in prompt
    assert "Completeness example:" in prompt
    assert "preserving that property or action" in prompt
    assert "full historical\n  answer unless they ask for it" in prompt
    assert "Answer only the selected subject's value" in prompt
    assert "A direct_answer must address the reconstructed current request only" in prompt
    assert "Decision validity invariants:" in prompt
    assert "A tool_plan is invalid when the available conversation explicitly" in prompt
    assert "A direct_answer must address the reconstructed current request only" in prompt
    assert "Final decision gate (apply immediately before returning JSON):" in prompt
    assert "returning tool_plan is invalid" in prompt
    assert "Selecting a subject does not widen the inherited request" in prompt
    assert "history_grounded_answer" not in prompt
    assert "quote_user_query" not in prompt
    assert "recall_assistant_summary" not in prompt
    assert "does not create current\n  Dota evidence" not in prompt
    assert "狼人的冷却时间：召狼30秒" not in prompt
    assert prompt.count("Decision priority (evaluate in this order):") == 1


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

    first = render_controller_messages("first query", "dota2", [])
    second = render_controller_messages(
        "second query",
        "other-game",
        [ConversationMessage(turn_index=1, role="user", content="older")],
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
    assert sent_system.startswith(controller._system_prompt())
    assert "Runtime context:\n- game: dota2" in sent_system
    assert manifest["controller.system.sha256"] == hashlib.sha256(
        controller._system_prompt().encode("utf-8")
    ).hexdigest()
    assert manifest["controller.recovery_rules"] == "v1"
    assert state.response["runtime"]["attempts"][0].get("prompt_versions") is None


def test_controller_runtime_context_exposes_stable_freshness_signals() -> None:
    registry = _registry()
    llm = CapturingLLM()
    controller = AgentController(
        registry,
        llm=llm,
        llm_enabled=True,
        runtime_context={
            "current_catalog_patch": "7.41e",
            "catalog_snapshot_generated_at": "2026-08-09T19:05:36+00:00",
        },
    )

    asyncio.run(
        AgentGraphRunner(controller, registry).run(AgentRunState(query="hello", game="dota2"))
    )

    sent_system = llm.messages[0][0]["content"]
    assert "- request_time: " in sent_system
    assert "- current_catalog_patch: 7.41e" in sent_system
    assert "- catalog_snapshot_generated_at: 2026-08-09T19:05:36+00:00" in sent_system


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


def test_recovery_rules_are_versioned_but_not_in_system_prompt() -> None:
    controller = AgentController(_registry(), llm_enabled=False)

    assert RECOVERY_RULES_VERSION == "v1"
    assert render_recovery_rules() not in controller._system_prompt()
    assert controller.prompt_versions["controller.recovery_rules"] == "v1"
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
        "Preserve intent, goal, output contract, context, constraints, and required\n"
        "  evidence exactly",
        "Do not use changed call ids",
    ):
        assert clause in recovery_rules

    root = Path(__file__).resolve().parents[1]
    for statement in (
        "import app.agentic.prompts.controller; import app.agentic.planning.controller",
        "import app.agentic.planning.controller; import app.agentic.prompts.controller",
    ):
        subprocess.run([sys.executable, "-c", statement], cwd=root, check=True)


def test_recovery_controller_message_uses_original_prompt_and_full_baseline() -> None:
    baseline_payload = _matchup_plan_payload()
    recovered_payload = _matchup_plan_payload()
    recovered_payload["plan"]["tool_calls"].append(
        {
            "id": "get_synergy",
            "tool": "stratz.hero_synergy_ranking",
            "args": {
                "hero_id": "$resolve_target.data.hero.hero_id",
                "side": "with",
                "take": 5,
            },
        }
    )
    llm = SequenceCapturingLLM(baseline_payload, recovered_payload)
    controller = AgentController(
        _registry(),
        llm=llm,
        llm_enabled=True,
        planner_max_retries=0,
    )
    initial = asyncio.run(controller.decide("enemy picked Lina"))
    assert isinstance(initial.decision, ToolPlanDecision)
    feedback = RecoveryFeedback(
        missing_evidence=["sample_size"],
        executed_calls=[
            RecoveryExecutedCall(
                id="get_ranking",
                tool="stratz.hero_matchup_ranking",
            )
        ],
        remaining_tool_budget=5,
    )

    recovered = asyncio.run(
        controller.decide(
            "enemy picked Lina",
            recovery_feedback=feedback,
            recovery_baseline_decision=initial.decision,
        )
    )

    assert recovered.status == "decided"
    recovery_messages = llm.messages[1]
    assert [message["role"] for message in recovery_messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert recovery_messages[0] == llm.messages[0][0]
    assert json.loads(recovery_messages[2]["content"]) == initial.decision.model_dump(
        mode="json"
    )
    assert recovery_messages[3]["content"] == render_recovery_feedback(feedback)


def test_recovery_controller_combines_generic_and_replan_errors() -> None:
    baseline_payload = _matchup_plan_payload()
    invalid_payload = _matchup_plan_payload()
    invalid_payload["plan"]["tool_calls"][0]["tool"] = "debug.unknown"
    llm = SequenceCapturingLLM(baseline_payload, invalid_payload)
    controller = AgentController(
        _registry(),
        llm=llm,
        llm_enabled=True,
        planner_max_retries=0,
    )
    initial = asyncio.run(controller.decide("enemy picked Lina"))
    assert isinstance(initial.decision, ToolPlanDecision)

    result = asyncio.run(
        controller.decide(
            "enemy picked Lina",
            recovery_feedback=RecoveryFeedback(
                missing_evidence=["sample_size"],
                remaining_tool_budget=5,
            ),
            recovery_baseline_decision=initial.decision,
        )
    )

    assert result.status == "error"
    assert any("unknown tool" in error for error in result.errors)
    assert any("exact prefix" in error for error in result.errors)


def _matchup_plan_payload() -> dict:
    return {
        "kind": "tool_plan",
        "plan": {
            "intent": "hero_matchup_ranking",
            "goal": "Fetch Lina matchup ranking evidence.",
            "output_contract": "natural_language_answer",
            "tool_calls": [
                {
                    "id": "resolve_target",
                    "tool": "resolve_hero",
                    "args": {"query": "Lina"},
                },
                {
                    "id": "get_ranking",
                    "tool": "stratz.hero_matchup_ranking",
                    "args": {
                        "hero_id": "$resolve_target.data.hero.hero_id",
                        "side": "vs",
                        "take": 5,
                    },
                },
            ],
            "required_evidence": [
                "hero_identity",
                "matchup_ranking_row",
                "sample_size",
            ],
            "constraints": {"max_tool_calls": 6, "allow_mock": False},
        },
    }
