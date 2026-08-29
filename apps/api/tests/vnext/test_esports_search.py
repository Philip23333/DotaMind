from __future__ import annotations

import asyncio
import json

from app.vnext.composition import build_vnext_registry
from app.vnext.llm.protocol import ToolCall
from tests.vnext.phase2_support import fixture_services, fixture_vnext_services


def _contains_forbidden_key(value: object) -> bool:
    forbidden = {"provider_id", "pandascore_id", "series_id", "match_id"}
    if isinstance(value, dict):
        return any(
            key in forbidden or _contains_forbidden_key(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(child) for child in value)
    return False


def test_esports_search_discovers_source_records_without_provider_ids() -> None:
    series_service, match_service, panda, opendota = fixture_services()
    registry = build_vnext_registry(
        fixture_vnext_services(series_service, match_service, panda, opendota)
    )

    async def exercise():
        series = await registry.execute(
            ToolCall(
                id="esports-series",
                name="esports.search",
                arguments={"query": "The International 2026"},
            )
        )
        matches = await registry.execute(
            ToolCall(
                id="esports-match",
                name="esports.search",
                arguments={"query": "Round 2", "time_scope": "recent"},
            )
        )
        return series, matches

    series, matches = asyncio.run(exercise())

    assert series.status == "ok"
    assert matches.status == "ok"
    series_record = next(
        record
        for record in series.content["records"]
        if record["kind"] == "series" and record["facts"]["name"] == "The International 2026"
    )
    assert series_record["source"] == "pandascore"
    assert series_record["locator"] == {
        "source": "pandascore",
        "kind": "series",
        "value": series_record["locator"]["value"],
    }
    assert series_record["facts"]["league"] == "The International"
    assert any(record["kind"] == "match" for record in matches.content["records"])
    assert not _contains_forbidden_key([series.content, matches.content])
    serialized = json.dumps([series.content, matches.content], sort_keys=True)
    for provider_id in ("20001", "30001", "501"):
        assert provider_id not in serialized


def test_esports_search_reuses_a_series_locator_for_matches() -> None:
    series_service, match_service, panda, opendota = fixture_services()
    registry = build_vnext_registry(
        fixture_vnext_services(series_service, match_service, panda, opendota)
    )

    async def exercise():
        discovery = await registry.execute(
            ToolCall(
                id="discover-series",
                name="esports.search",
                arguments={"query": "The International 2026"},
            )
        )
        locator = next(
            record["locator"]
            for record in discovery.content["records"]
            if record["kind"] == "series" and record["facts"]["name"] == "The International 2026"
        )
        within = await registry.execute(
            ToolCall(
                id="within-series",
                name="esports.search",
                arguments={"within": locator, "time_scope": "recent"},
            )
        )
        return discovery, within

    discovery, within = asyncio.run(exercise())

    assert discovery.status == "ok"
    assert within.status == "ok"
    assert all(record["kind"] == "match" for record in within.content["records"])
    assert any(
        record["facts"]["name"].startswith("Round 2")
        for record in within.content["records"]
    )
    assert panda.list_calls[-1]["series_id"] == 20001


def test_esports_search_preserves_old_series_and_match_tools_for_comparison() -> None:
    series_service, match_service, panda, opendota = fixture_services()
    registry = build_vnext_registry(
        fixture_vnext_services(series_service, match_service, panda, opendota)
    )
    assert {"esports.search", "series.search", "series.list_matches"} <= {
        tool.name for tool in registry.list()
    }

    async def exercise():
        old_series = await registry.execute(
            ToolCall(
                id="old-series",
                name="series.search",
                arguments={"query": "The International 2026", "year": 2026},
            )
        )
        new_series = await registry.execute(
            ToolCall(
                id="new-series",
                name="esports.search",
                arguments={"query": "The International 2026"},
            )
        )
        old_schedule = await registry.execute(
            ToolCall(
                id="old-schedule",
                name="series.list_matches",
                arguments={
                    "series_ref": old_series.content["candidates"][0]["ref"],
                    "time_scope": "recent",
                },
            )
        )
        series_locator = next(
            record["locator"]
            for record in new_series.content["records"]
            if record["kind"] == "series" and record["facts"]["name"] == "The International 2026"
        )
        new_schedule = await registry.execute(
            ToolCall(
                id="new-schedule",
                name="esports.search",
                arguments={"within": series_locator, "time_scope": "recent"},
            )
        )
        return old_series, new_series, old_schedule, new_schedule

    old_series, new_series, old_schedule, new_schedule = asyncio.run(exercise())

    assert all(
        result.status == "ok"
        for result in (old_series, new_series, old_schedule, new_schedule)
    )
    new_series_facts = next(
        record["facts"]
        for record in new_series.content["records"]
        if record["kind"] == "series" and record["facts"]["name"] == "The International 2026"
    )
    assert old_series.content["candidates"][0]["name"] == new_series_facts["name"]
    assert old_series.content["candidates"][0]["year"] == new_series_facts["year"]
    assert [match["name"] for match in old_schedule.content["matches"]] == [
        record["facts"]["name"] for record in new_schedule.content["records"]
    ]
