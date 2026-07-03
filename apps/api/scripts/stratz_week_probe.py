"""One-off probe: determine the real semantics of STRATZ `week`.

Verifies, against the live API, whether `week` is single-bucket (one week of
data) or lower-bound (since-week inclusive), and what `null` means. Covers all
three production endpoints that take `week`: heroStats.stats,
heroStats.laneOutcome, heroStats.heroVsHeroMatchup.

Run from anywhere; reads apps/api/.env directly. Delete after the semantics are
settled and recorded in docs/design/time_patch_filtering.md.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Callable

from app.integrations.stratz.transport import StratzTransport

_STATS_QUERY = """
query ProbeStats($bracketBasicIds: [RankBracketBasicEnum!], $week: Long) {
  heroStats { stats(groupByPosition: true, bracketBasicIds: $bracketBasicIds, week: $week) {
    heroId position matchCount } } }
"""

_LANE_QUERY = """
query ProbeLane($isWith: Boolean!, $bracketBasicIds: [RankBracketBasicEnum!], $week: Long) {
  heroStats { laneOutcome(isWith: $isWith, bracketBasicIds: $bracketBasicIds, week: $week) {
    heroId1 heroId2 matchCount winCount } } }
"""

_MATCHUP_QUERY = """
query ProbeMatchup($heroId: Short!, $take: Int, $bracketBasicIds: [RankBracketBasicEnum!], $week: Long) {
  heroStats { heroVsHeroMatchup(heroId: $heroId, take: $take, bracketBasicIds: $bracketBasicIds, week: $week) {
    advantage { heroId matchCountVs vs { heroId1 heroId2 matchCount winCount } }
    disadvantage { heroId matchCountVs vs { heroId1 heroId2 matchCount winCount } } } } }
"""

WEEK_SECONDS = 604_800


def _load_env() -> tuple[str, str]:
    # apps/api/scripts/x.py -> apps/api is parents[1]; that holds the real .env.
    api_root = Path(__file__).resolve().parents[1]
    env_path = api_root / ".env"
    token = ""
    url = "https://api.stratz.com/graphql"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key == "METAMIND_STRATZ_TOKEN":
            token = value
        elif key == "METAMIND_STRATZ_GRAPHQL_URL":
            url = value
    if not token:
        raise SystemExit("METAMIND_STRATZ_TOKEN not found in apps/api/.env")
    return url, token


def _sum_stats(payload: dict[str, Any]) -> tuple[int, int]:
    rows = payload["data"]["heroStats"]["stats"] or []
    return len(rows), sum(int(r.get("matchCount") or 0) for r in rows)


def _sum_lane(payload: dict[str, Any]) -> tuple[int, int]:
    rows = payload["data"]["heroStats"]["laneOutcome"] or []
    return len(rows), sum(int(r.get("matchCount") or 0) for r in rows)


def _sum_matchup(payload: dict[str, Any]) -> tuple[int, int]:
    node = payload["data"]["heroStats"]["heroVsHeroMatchup"] or {}
    rows: list[dict[str, Any]] = []
    for side in ("advantage", "disadvantage"):
        for group in node.get(side) or []:
            rows.extend(group.get("vs") or [])
    return len(rows), sum(int(r.get("matchCount") or 0) for r in rows)


async def _graphql_with_retry(
    transport: StratzTransport,
    operation_name: str,
    query: str,
    variables: dict[str, Any],
    *,
    attempts: int = 4,
    backoff: float = 2.0,
) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return await transport.graphql(operation_name, query, variables)
        except Exception as exc:  # noqa: BLE001 - probe must survive flaky network
            last_exc = exc
            await asyncio.sleep(backoff * (attempt + 1))
    assert last_exc is not None
    raise last_exc


async def _probe_endpoint(
    transport: StratzTransport,
    name: str,
    query: str,
    variables: dict[str, Any],
    summarizer: Callable[[dict[str, Any]], tuple[int, int]],
    week_targets: list[tuple[str, int | None]],
) -> list[dict[str, Any]]:
    print(f"\n=== {name} ===")
    results: list[dict[str, Any]] = []
    for label, week in week_targets:
        variables["week"] = week
        try:
            payload = await _graphql_with_retry(
                transport, "Probe" + name, query, variables
            )
        except Exception as exc:  # noqa: BLE001
            print(f"{label:>14}  week={str(week):>12}  ERROR: {type(exc).__name__}: {exc}")
            results.append({"label": label, "week": week, "rows": 0, "total": 0, "error": str(exc)})
            await asyncio.sleep(1.0)
            continue
        rows, total = summarizer(payload)
        results.append({"label": label, "week": week, "rows": rows, "total": total})
        print(
            f"{label:>14}  week={str(week):>12}  "
            f"rows={rows:>5}  total={total:>14,}"
        )
        await asyncio.sleep(1.0)  # be gentle on STRATZ rate limits
    return results


def _interpret(results: list[dict[str, Any]]) -> str:
    by_label = {r["label"]: r["total"] for r in results}
    null_total = by_label.get("all_time_null")
    prev1 = by_label.get("prev1")
    prev2 = by_label.get("prev2")
    prev4 = by_label.get("prev4")
    current = by_label.get("current")
    lines = []
    if null_total is not None and prev1 is not None:
        lines.append(
            f"null == prev1 ?  {null_total:,} vs {prev1:,}  =>  "
            f"{'YES (null = latest completed week)' if null_total == prev1 else 'NO'}"
        )
    if prev1 and prev2 and prev4:
        lines.append(
            f"prev1/prev2/prev4 distinct ?  {prev1:,} / {prev2:,} / {prev4:,}"
        )
    if current is not None and prev1:
        ratio = (prev1 / current) if current else float("inf")
        lines.append(
            f"prev1/current = {ratio:.2f}  (current is partial week if >>1)"
        )
    return "\n  ".join(lines)


async def main() -> int:
    url, token = _load_env()
    transport = StratzTransport(url, token)

    now = time.time()
    idx = int(now // WEEK_SECONDS)
    targets: list[tuple[str, int | None]] = [
        ("all_time_null", None),
        ("current", idx * WEEK_SECONDS),
        ("prev1", (idx - 1) * WEEK_SECONDS),
        ("prev2", (idx - 2) * WEEK_SECONDS),
        ("prev4", (idx - 4) * WEEK_SECONDS),
    ]

    print(f"now epoch      = {int(now)}")
    print(f"current week idx = {idx}  epoch = {idx * WEEK_SECONDS}  ({time.strftime('%Y-%m-%d', time.gmtime(idx * WEEK_SECONDS))} UTC)")
    print(f"STRATZ url     = {url}")

    all_results: dict[str, list[dict[str, Any]]] = {}
    try:
        all_results["stats"] = await _probe_endpoint(
            transport, "stats", _STATS_QUERY,
            {"bracketBasicIds": ["DIVINE_IMMORTAL"]}, _sum_stats, targets,
        )
        all_results["laneOutcome"] = await _probe_endpoint(
            transport, "laneOutcome", _LANE_QUERY,
            {"isWith": True, "bracketBasicIds": ["DIVINE_IMMORTAL"]}, _sum_lane, targets,
        )
        all_results["heroVsHeroMatchup"] = await _probe_endpoint(
            transport, "heroVsHeroMatchup", _MATCHUP_QUERY,
            {"heroId": 44, "take": 50, "bracketBasicIds": ["DIVINE_IMMORTAL"]},
            _sum_matchup, targets,
        )
    finally:
        await transport.aclose()

    print("\n=== Interpretation per endpoint ===")
    for name, results in all_results.items():
        print(f"\n[{name}]")
        print("  " + _interpret(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
