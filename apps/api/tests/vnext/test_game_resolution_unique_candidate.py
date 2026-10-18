"""Replay trace identity fields through real adapters and the public tool chain."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from app.vnext import composition
from app.vnext.composition import VNextSettings, build_vnext_registry, build_vnext_services
from app.vnext.llm.protocol import ToolCall
from app.vnext.providers.opendota.client import OpenDotaClient
from app.vnext.providers.pandascore.client import PandaScoreClient
from app.vnext.providers.source_reads import source_read_scope

_FIXTURE = Path(__file__).parent / "fixtures/game_resolution/epl_final_1606806_identity.json"


@pytest.mark.parametrize("unaligned_name", [False, True])
def test_trace_final_three_games_resolve_and_continue_to_governed_detail(
    monkeypatch: pytest.MonkeyPatch,
    unaligned_name: bool,
) -> None:
    async def scenario():
        fixture = json.loads(_FIXTURE.read_text())
        requests = []

        async def handle(request):
            requests.append(request)
            if request.url.host == "pandascore.test":
                assert request.url.params["filter[id]"] == "1606806"
                value = fixture["context"]
                return httpx.Response(200, json=[value], request=request)
            if request.url.path == "/api/leagues":
                value = fixture["leagues"]
            elif request.url.path == "/api/leagues/19944/matches":
                value = [game["row"] for game in fixture["games"]]
            else:
                valve_id = int(request.url.path.rsplit("/", 1)[1])
                value = deepcopy(
                    next(
                        g["detail"] for g in fixture["games"] if g["detail"]["match_id"] == valve_id
                    )
                )
                if unaligned_name:  # Synthetic fault, not another captured Provider fact.
                    for side in ("radiant", "dire"):
                        if value[f"{side}_team"]["name"] == "Level UP esports":
                            value[f"{side}_team"]["name"] = "Unaligned source label"
            return httpx.Response(200, json=value, request=request)

        transport = httpx.MockTransport(handle)
        monkeypatch.setattr(
            composition,
            "PandaScoreClient",
            lambda **kw: PandaScoreClient(
                **kw,
                transport=transport,
            ),
        )
        monkeypatch.setattr(
            composition,
            "OpenDotaClient",
            lambda **kw: OpenDotaClient(
                **kw,
                transport=transport,
            ),
        )
        settings = VNextSettings(
            pandascore_token="offline-test",
            pandascore_base_url="https://pandascore.test",
            opendota_enabled=True,
            opendota_base_url="https://opendota.test/api",
            game_resolution_enabled=True,
        )
        registry = build_vnext_registry(build_vnext_services(settings), settings=settings)
        search = await registry.execute(
            ToolCall(
                id="search",
                name="esports.match.search",
                arguments={"id": 1606806, "limit": 1},
            )
        )
        assert search.status == "ok"
        match_ref = search.content["artifact_ref"]
        with source_read_scope() as cache:
            for game in fixture["games"]:
                result = await registry.execute(
                    ToolCall(
                        id=f"resolve-{game['position']}",
                        name="esports.game.resolve",
                        arguments={
                            "match_artifact_ref": match_ref,
                            "match_path": "items.0",
                            "game_position": game["position"],
                        },
                    )
                )
                assert result.status == "ok"
                value = result.content["value"]
                assert value["status"] == "resolved"
                assert value["valve_game_id"] == game["detail"]["match_id"]
                assert value["selection_basis"] == (
                    "unique_candidate" if unaligned_name else "verified_identity"
                )
                if unaligned_name:
                    assert "participant_names_unaligned" in value["warnings"]
                else:
                    assert value["warnings"] == []
                    assessment = value["data"]["resolution_result"]["candidate_assessments"][0]
                    evidence = assessment["league_assessments"][0]["assessment"][
                        "identity_evidence"
                    ]
                    assert any(
                        a["name_match_method"] == "common_suffix"
                        for a in evidence["participant_associations"]
                    )
                stored = await registry._result_processor._externalizer._store.get(
                    result.content["artifact_ref"]
                )
                assert stored["warnings"] == value["warnings"]
                detail = await registry.execute(
                    ToolCall(
                        id=f"detail-{game['position']}",
                        name="game.detail",
                        arguments={
                            "valve_game_id": value["valve_game_id"],
                        },
                    )
                )
                assert detail.status == "ok"
                detail_value = detail.content.get("value", detail.content)
                assert detail_value["valve_game_id"] == value["valve_game_id"]
                assert set(detail_value["data"]) == {
                    "match",
                    "draft",
                    "players",
                    "economy",
                    "builds",
                    "events",
                    "interactions",
                    "coverage",
                }
            assert (cache.remote_reads, cache.cache_hits) == (6, 9)
        assert len(requests) == 7  # Search + context/directory/list + three details.

    asyncio.run(scenario())
