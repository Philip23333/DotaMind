from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agentic.models import ExecutionPlan
from app.agentic.runtime.checkpoint import (
    Checkpoint,
    CheckpointOption,
    CheckpointSnapshot,
)
from app.agentic.runtime.models import RunBudget
from app.api.v1.chat_run_schemas import ChatRunResumeRequest


def test_checkpoint_selection_contract_keeps_server_value_structured() -> None:
    checkpoint = Checkpoint(
        checkpoint_type="pandascore_match_selection",
        question="请选择要查看详情的比赛。",
        source_tool_call_id="resolve_games",
        resume_node="tools",
        options=[
            CheckpointOption(
                id="playoffs_2026_08_20",
                label="8 月 20 日 · Playoffs",
                value={"scheduled_date": "2026-08-20"},
            )
        ],
    )

    assert checkpoint.options[0].value == {"scheduled_date": "2026-08-20"}
    assert checkpoint.model_dump(mode="json")["options"][0]["id"] == "playoffs_2026_08_20"


def test_checkpoint_snapshot_excludes_prompt_and_answer_fields() -> None:
    snapshot = CheckpointSnapshot(
        checkpoint=Checkpoint(
            checkpoint_type="pandascore_match_selection",
            question="请选择比赛。",
            source_tool_call_id="resolve_games",
            resume_node="tools",
            options=[
                CheckpointOption(
                    id="group_2026_08_14",
                    label="8 月 14 日 · Group Stage",
                    value={"scheduled_date": "2026-08-14"},
                )
            ],
        ),
        plan=ExecutionPlan(
            intent="match_detail",
            goal="查看比赛详情",
            output_contract="natural_language_answer",
        ),
        run_budget=RunBudget(),
        attempt_index=0,
    )

    dumped = snapshot.model_dump(mode="json")
    assert "prompt" not in dumped
    assert "raw_output" not in dumped
    assert "answer" not in dumped


def test_resume_request_accepts_only_checkpoint_identity_and_option() -> None:
    request = ChatRunResumeRequest(
        checkpoint_type="pandascore_match_selection",
        option_id="playoffs_2026_08_20",
    )

    assert request.model_dump() == {
        "checkpoint_type": "pandascore_match_selection",
        "option_id": "playoffs_2026_08_20",
    }


def test_resume_request_rejects_client_plan_patches() -> None:
    with pytest.raises(ValidationError):
        ChatRunResumeRequest(
            checkpoint_type="pandascore_match_selection",
            option_id="playoffs_2026_08_20",
            scheduled_date="2026-08-20",
        )
