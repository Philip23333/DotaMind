from typing import Any, Literal

from pydantic import UUID4, BaseModel, Field

SupportedGame = Literal["dota2"]


class PlanRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    game: SupportedGame = "dota2"
    # Provide a UUID v4 to enable multi-turn session memory.
    # Omit (or pass null) for stateless single-turn mode.
    session_id: UUID4 | None = None


class PlanResponse(BaseModel):
    query: str
    game: SupportedGame
    status: Literal["ok", "insufficient_tools", "error"]
    reason: str
    response_type: str | None = None
    error_code: str | None = None
    # Echoed back so clients can continue the conversation.
    session_id: str | None = None
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
