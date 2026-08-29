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


def test_esports_search_uses_exact_team_constraint_when_name_search_is_insufficient() -> None:
    series_service, match_service, panda, opendota = fixture_services()
    registry = build_vnext_registry(
        fixture_vnext_services(series_service, match_service, panda, opendota)
    )

    async def exercise():
        query_only = await registry.execute(
            ToolCall(
                id="query-only",
                name="esports.search",
                arguments={"query": "Team Alpha Team Beta", "time_scope": "recent"},
            )
        )
        constrained = await registry.execute(
            ToolCall(
                id="team-constraint",
                name="esports.search",
                arguments={
                    "teams": ["Team Alpha", "Team Beta"],
                    "time_scope": "recent",
                },
            )
        )
        return query_only, constrained

    query_only, constrained = asyncio.run(exercise())

    assert query_only.status == constrained.status == "ok"
    assert not any(record["kind"] == "match" for record in query_only.content["records"])
    assert [record["facts"]["name"] for record in constrained.content["records"]] == [
        "Grand Final: Alpha vs Beta"
    ]


def test_esports_search_navigates_league_series_match_and_game() -> None:
    series_service, match_service, panda, opendota = fixture_services()
    registry = build_vnext_registry(
        fixture_vnext_services(series_service, match_service, panda, opendota)
    )
    assert {"series.search", "series.list_matches", "matches.search"}.isdisjoint(
        {tool.name for tool in registry.list()}
    )

    async def exercise():
        discovery = await registry.execute(
            ToolCall(
                id="league-discovery",
                name="esports.search",
                arguments={"query": "The International"},
            )
        )
        league = next(
            record["locator"]
            for record in discovery.content["records"]
            if record["kind"] == "league" and record["facts"]["name"] == "The International"
        )
        series = await registry.execute(
            ToolCall(
                id="league-series",
                name="esports.search",
                arguments={"within": league},
            )
        )
        series_locator = next(
            record["locator"]
            for record in series.content["records"]
            if record["kind"] == "series" and record["facts"]["name"] == "The International 2026"
        )
        matches = await registry.execute(
            ToolCall(
                id="series-matches",
                name="esports.search",
                arguments={"within": series_locator, "time_scope": "recent"},
            )
        )
        match_locator = next(
            record["locator"]
            for record in matches.content["records"]
            if record["kind"] == "match"
        )
        games = await registry.execute(
            ToolCall(
                id="match-games",
                name="esports.search",
                arguments={"within": match_locator},
            )
        )
        return discovery, series, matches, games

    discovery, series, matches, games = asyncio.run(exercise())

    assert all(
        result.status == "ok"
        for result in (discovery, series, matches, games)
    )
    assert {record["kind"] for record in games.content["records"]} == {"game"}
    assert panda.get_calls == []


def test_esports_search_cold_match_locator_fetches_once_then_reuses_snapshot() -> None:
    series_service, match_service, panda, opendota = fixture_services()
    registry = build_vnext_registry(
        fixture_vnext_services(series_service, match_service, panda, opendota)
    )
    locator = match_service.locator_index.make("match", 30004)

    async def exercise():
        games = await registry.execute(
            ToolCall(
                id="cold-match-games",
                name="esports.search",
                arguments={"within": locator.model_dump()},
            )
        )
        detail = await registry.execute(
            ToolCall(
                id="cold-match-detail",
                name="matches.get_detail",
                arguments={"locator": locator.model_dump()},
            )
        )
        return games, detail

    games, detail = asyncio.run(exercise())

    assert games.status == detail.status == "ok"
    assert len(games.content["records"]) == 3
    assert panda.get_calls == [30004]


def test_esports_search_rejects_unknown_or_wrong_source_locators() -> None:
    series_service, match_service, panda, opendota = fixture_services()
    registry = build_vnext_registry(
        fixture_vnext_services(series_service, match_service, panda, opendota)
    )

    async def exercise():
        discovery = await registry.execute(
            ToolCall(
                id="discover-locator",
                name="esports.search",
                arguments={"query": "The International 2026"},
            )
        )
        unknown = await registry.execute(
            ToolCall(
                id="unknown-locator",
                name="esports.search",
                arguments={
                    "within": {"source": "pandascore", "kind": "series", "value": "src:missing"}
                },
            )
        )
        wrong_source = await registry.execute(
            ToolCall(
                id="wrong-source",
                name="esports.search",
                arguments={
                    "within": {"source": "opendota", "kind": "series", "value": "src:missing"}
                },
            )
        )
        series_locator = next(
            record["locator"]
            for record in discovery.content["records"]
            if record["kind"] == "series"
        )
        wrong_kind = await registry.execute(
            ToolCall(
                id="wrong-kind",
                name="esports.search",
                arguments={
                    "within": {**series_locator, "kind": "match"},
                },
            )
        )
        return unknown, wrong_source, wrong_kind

    unknown, wrong_source, wrong_kind = asyncio.run(exercise())

    assert unknown.status == wrong_source.status == wrong_kind.status == "error"
    assert unknown.error is not None
    assert wrong_source.error is not None
    assert wrong_kind.error is not None
    assert (
        unknown.error.code
        == wrong_source.error.code
        == wrong_kind.error.code
        == "invalid_source_locator"
    )
