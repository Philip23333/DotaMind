from typing import Any, Literal

from pydantic import BaseModel, Field

SupportedGame = Literal["dota2"]


class PlanRequest(BaseModel):
    query: str
    game: SupportedGame = "dota2"


class PlanResponse(BaseModel):
    query: str
    game: SupportedGame
    status: Literal["ok", "insufficient_tools", "error"]
    reason: str
    response_type: str | None = None
    planner_output: dict[str, Any] | None = None
    planner_raw_content: str | None = None
    planner_finish_reason: str | None = None
    planner_prompt_messages: list[dict[str, str]] = Field(default_factory=list)
    plan: dict[str, Any] | None = None
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    evidence_graph: dict[str, Any] | None = None
    answer: dict[str, Any] | None = None
    review: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)
