"""Run the v2.5 LLM planner and execute the returned plan."""

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
        "plan": result.plan.model_dump(mode="json") if result.plan else None,
        "tool_results": [
            item.model_dump(mode="json") for item in result.tool_results
        ],
        "evidence_graph": (
            result.evidence_graph.model_dump(mode="json")
            if result.evidence_graph
            else None
        ),
        "errors": result.errors,
    }
    import json

    print(json.dumps(print_json, ensure_ascii=False, indent=2))
    return 0 if result.status in {"ok", "insufficient_tools"} else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the v2.5 LLM planner.")
    parser.add_argument("--query", required=True, help="Natural language Dota 2 query.")
    parser.add_argument("--game", default="dota2", help="Game id. Defaults to dota2.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
