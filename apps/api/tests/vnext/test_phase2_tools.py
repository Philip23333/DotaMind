from __future__ import annotations

import asyncio
import json

from app.vnext.composition import (
    VNextServices,
    VNextSettings,
    build_vnext_registry,
    build_vnext_services,
)
from app.vnext.llm.protocol import ToolCall
from tests.vnext.phase2_support import fixture_services


def test_composition_is_lazy_and_registers_only_the_four_phase2_tools() -> None:
    services = build_vnext_services(VNextSettings(pandascore_token="test-token"))
    assert services.pandascore._client is None  # type: ignore[attr-defined]
    assert services.opendota._client is None  # type: ignore[attr-defined]
    registry = build_vnext_registry(services)
    assert [tool.name for tool in registry.list()] == [
        "competitions.search",
        "competitions.list_matches",
        "matches.search",
        "matches.get_detail",
    ]


def test_registry_executes_all_four_phase2_tools_without_provider_ids() -> None:
    competition_service, match_service, panda, opendota = fixture_services()
    services = VNextServices(panda, opendota, competition_service, match_service)
    registry = build_vnext_registry(services)

    async def exercise():
        competition = await registry.execute(
            ToolCall(
                id="competition-search",
                name="competitions.search",
                arguments={"query": "The International 2026", "year": 2026},
            )
        )
        competition_ref = competition.content["candidates"][0]["ref"]["value"]
        schedule = await registry.execute(
            ToolCall(
                id="competition-matches",
                name="competitions.list_matches",
                arguments={
                    "competition_ref": {"value": competition_ref},
                    "time_scope": "recent",
                },
            )
        )
        match_search = await registry.execute(
            ToolCall(
                id="match-search",
                name="matches.search",
                arguments={"query": "Round 2", "time_scope": "recent"},
            )
        )
        match_ref = match_search.content["candidates"][0]["ref"]["value"]
        detail = await registry.execute(
            ToolCall(
                id="match-detail",
                name="matches.get_detail",
                arguments={"match_ref": {"value": match_ref}},
            )
        )
        return competition, schedule, match_search, detail

    results = asyncio.run(exercise())
    assert all(result.status == "ok" for result in results)
    serialized = json.dumps([result.content for result in results], sort_keys=True)
    for forbidden in (
        "pandascore_id",
        "opendota_id",
        "league_id",
        "raw_response",
        "provider_payload",
    ):
        assert forbidden not in serialized
    assert "30001" not in serialized
    assert "40001" not in serialized


def test_get_detail_requires_exactly_one_domain_reference() -> None:
    _, _, panda, opendota = fixture_services()
    competition_service, match_service, _, _ = fixture_services()
    registry = build_vnext_registry(
        VNextServices(panda, opendota, competition_service, match_service)
    )
    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="invalid-detail",
                name="matches.get_detail",
                arguments={},
            )
        )
    )
    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_arguments"
