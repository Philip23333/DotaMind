"""Run local smoke checks against the natural-language query endpoint."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_QUERIES = [
    "How Team BB play lately?",
    "how XG play last 2 months",
    "how XG play last 1 day",
    "what changed in patch 7.41d?",
    "what changed in patch 1.00?",
    "strongest offlane heroes",
]


@dataclass(frozen=True)
class SmokeResult:
    query: str
    ok: bool
    http_status: int
    elapsed_ms: int
    summary: dict[str, Any]
    error: str | None = None


def main() -> int:
    args = parse_args()
    queries = args.query or DEFAULT_QUERIES
    results = [
        run_query(args.base_url.rstrip("/"), query, args.timeout_seconds)
        for query in queries
    ]

    print_results(results)
    failed = [result for result in results if not result.ok]
    return 1 if failed else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-test the local MetaMind /api/v1/query path.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8001",
        help="API base URL. Defaults to http://127.0.0.1:8001.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=90,
        help="Per-query HTTP timeout. Defaults to 90 seconds.",
    )
    parser.add_argument(
        "--query",
        action="append",
        help="Query to run. Can be provided multiple times. Defaults to built-in smoke queries.",
    )
    return parser.parse_args()


def run_query(base_url: str, query: str, timeout_seconds: float) -> SmokeResult:
    started = time.perf_counter()
    payload = json.dumps({"query": query, "game": "dota2"}).encode("utf-8")
    request = Request(
        f"{base_url}/api/v1/query",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
            parsed = json.loads(response_body)
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            return SmokeResult(
                query=query,
                ok=200 <= response.status < 300,
                http_status=response.status,
                elapsed_ms=elapsed_ms,
                summary=summarize_payload(parsed),
            )
    except HTTPError as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        body = exc.read().decode("utf-8", errors="replace")
        parsed = _parse_json(body)
        return SmokeResult(
            query=query,
            ok=_expected_error(exc.code, parsed),
            http_status=exc.code,
            elapsed_ms=elapsed_ms,
            summary=summarize_payload(parsed) if isinstance(parsed, dict) else {},
            error=None if _expected_error(exc.code, parsed) else body[:300],
        )
    except (URLError, TimeoutError, OSError) as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        return SmokeResult(
            query=query,
            ok=False,
            http_status=0,
            elapsed_ms=elapsed_ms,
            summary={},
            error=str(exc),
        )


def summarize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    critic_task = _critic_task(payload.get("tasks", []))
    summary: dict[str, Any] = {
        "routed_service": payload.get("routed_service"),
        "critic_status": critic_task.get("status"),
        "critic_action": critic_task.get("action"),
    }

    if payload.get("error"):
        summary.update(
            {
                "error": payload.get("error"),
                "candidate_count": len(payload.get("candidates", []) or []),
            }
        )

    report_type = result.get("report_type")
    if report_type == "team_report":
        freshness = result.get("data_freshness") or {}
        summary.update(
            {
                "team_name": result.get("team_name"),
                "time_range": result.get("time_range"),
                "recent_record": result.get("recent_record"),
                "matches_in_window": result.get("matches_in_window"),
                "match_details_analyzed": result.get("match_details_analyzed"),
                "latest_match_at": freshness.get("latest_match_at"),
                "sources": _source_statuses(result.get("sources", [])),
            }
        )
    elif report_type == "meta_report":
        summary.update(
            {
                "role": result.get("role"),
                "patch": result.get("patch"),
                "top_heroes": len(result.get("top_heroes", []) or []),
                "sources": _source_statuses(result.get("sources", [])),
            }
        )
    elif report_type == "patch_impact":
        summary.update(
            {
                "patch": result.get("patch"),
                "winners": len(result.get("winners", []) or []),
                "losers": len(result.get("losers", []) or []),
                "sources": _source_statuses(result.get("sources", [])),
            }
        )
    elif report_type == "claim_verification":
        summary.update({"verdict": result.get("verdict")})

    return summary


def print_results(results: list[SmokeResult]) -> None:
    for result in results:
        label = "PASS" if result.ok else "FAIL"
        parts = [
            f"{label:<4}",
            f"{result.http_status:<3}",
            f"{result.elapsed_ms:>6}ms",
            result.query,
        ]
        print("  ".join(parts))
        if result.summary:
            print(f"      {json.dumps(result.summary, ensure_ascii=False, sort_keys=True)}")
        if result.error:
            print(f"      error={result.error}")


def _critic_task(tasks: Any) -> dict[str, Any]:
    if not isinstance(tasks, list):
        return {}
    for task in tasks:
        if isinstance(task, dict) and task.get("agent") == "critic":
            return task
    return {}


def _source_statuses(sources: Any) -> list[str]:
    if not isinstance(sources, list):
        return []
    return [
        f"{source.get('name')}:{source.get('status')}"
        for source in sources
        if isinstance(source, dict)
    ]


def _parse_json(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _expected_error(status_code: int, payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    return status_code in {404, 409} and payload.get("error") in {
        "ambiguous_team",
        "team_not_found",
    }


if __name__ == "__main__":
    sys.exit(main())
