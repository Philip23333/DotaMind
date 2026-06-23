from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agentic.evidence import EvidenceGraph, build_evidence_graph
from app.agentic.models import ExecutionPlan, ToolCall, ToolResult
from app.agentic.registry import ToolExecutor

PlanRunStatus = Literal["ok", "error"]


class PlanRunResult(BaseModel):
    plan: ExecutionPlan
    tool_results: list[ToolResult] = Field(default_factory=list)
    evidence_graph: EvidenceGraph | None = None
    status: PlanRunStatus
    errors: list[str] = Field(default_factory=list)


class PlanRunner:
    def __init__(self, executor: ToolExecutor) -> None:
        self.executor = executor

    async def run(self, plan: ExecutionPlan) -> PlanRunResult:
        errors = self._validate_plan(plan)
        if errors:
            return PlanRunResult(
                plan=plan,
                status="error",
                errors=errors,
                evidence_graph=build_evidence_graph(plan, []),
            )

        tool_results: list[ToolResult] = []
        results_by_id: dict[str, ToolResult] = {}
        for call in plan.tool_calls:
            resolved_args, resolve_errors = self._resolve_args(call.args, results_by_id)
            if resolve_errors:
                errors.extend(
                    f"{call.id}: {error}" for error in resolve_errors
                )
                continue

            result = await self.executor.execute(
                ToolCall(id=call.id, tool=call.tool, args=resolved_args)
            )
            tool_results.append(result)
            results_by_id[call.id] = result
            if result.status == "error":
                errors.append(f"{call.id}: {result.error or 'tool execution failed'}")

        return PlanRunResult(
            plan=plan,
            tool_results=tool_results,
            evidence_graph=build_evidence_graph(plan, tool_results),
            status="error" if errors else "ok",
            errors=errors,
        )

    @staticmethod
    def _validate_plan(plan: ExecutionPlan) -> list[str]:
        errors = []
        if len(plan.tool_calls) > plan.constraints.max_tool_calls:
            errors.append(
                "plan exceeds max_tool_calls "
                f"({len(plan.tool_calls)} > {plan.constraints.max_tool_calls})"
            )

        seen = set()
        for call in plan.tool_calls:
            if call.id in seen:
                errors.append(f"duplicate tool call id: {call.id}")
            seen.add(call.id)
        return errors

    def _resolve_args(
        self,
        value: Any,
        results_by_id: dict[str, ToolResult],
    ) -> tuple[Any, list[str]]:
        if isinstance(value, str) and value.startswith("$"):
            return self._resolve_reference(value, results_by_id)
        if isinstance(value, dict):
            resolved: dict[str, Any] = {}
            errors: list[str] = []
            for key, item in value.items():
                resolved_item, item_errors = self._resolve_args(item, results_by_id)
                resolved[key] = resolved_item
                errors.extend(item_errors)
            return resolved, errors
        if isinstance(value, list):
            resolved_items = []
            errors = []
            for item in value:
                resolved_item, item_errors = self._resolve_args(item, results_by_id)
                resolved_items.append(resolved_item)
                errors.extend(item_errors)
            return resolved_items, errors
        return value, []

    @staticmethod
    def _resolve_reference(
        reference: str,
        results_by_id: dict[str, ToolResult],
    ) -> tuple[Any, list[str]]:
        parts = reference.removeprefix("$").split(".")
        if len(parts) < 2:
            return None, [f"invalid reference: {reference}"]

        call_id = parts[0]
        result = results_by_id.get(call_id)
        if result is None:
            return None, [f"reference target is unavailable: {reference}"]
        if result.status != "ok":
            return None, [f"reference target failed: {call_id}"]

        current: Any = result.model_dump(mode="json")
        for part in parts[1:]:
            if isinstance(current, dict) and part in current:
                current = current[part]
                continue
            return None, [f"reference path not found: {reference}"]
        return current, []
