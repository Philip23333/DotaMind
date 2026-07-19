"""Run the v2.5 Controller and execute any returned tool plan."""

from __future__ import annotations

import argparse
import asyncio

from app.application.plan_service import PlanService


def main() -> int:
    args = parse_args()
    result = asyncio.run(PlanService().run(args.query, args.game))
    print_json = {
        "query": result.query,
        "game": result.game,
        "status": result.status,
        "reason": result.reason,
        "decision_kind": result.decision_kind,
        "planner_required_evidence": result.planner_required_evidence,
        "effective_required_evidence": result.effective_required_evidence,
        "required_evidence_sources": result.required_evidence_sources,
        "plan": result.plan.model_dump(mode="json") if result.plan else None,
        "tool_results": [
            item.model_dump(mode="json") for item in result.tool_results
        ],
        "evidence_graph": (
            result.evidence_graph.model_dump(mode="json")
            if result.evidence_graph
            else None
        ),
        "answer": result.answer.model_dump(mode="json") if result.answer else None,
        "review": result.review.model_dump(mode="json") if result.review else None,
        "errors": result.errors,
        "trace": [item.model_dump(mode="json") for item in result.trace],
    }
    import json

    print(json.dumps(print_json, ensure_ascii=False, indent=2))
    return 0 if result.status not in {"error", "insufficient_evidence"} else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the v2.5 LLM Controller.")
    parser.add_argument("--query", required=True, help="Natural language Dota 2 query.")
    parser.add_argument("--game", default="dota2", help="Game id. Defaults to dota2.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
