from __future__ import annotations

import asyncio
import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.integrations.valve.catalog_repository import DotaCatalogRepository
from app.vnext.capabilities.game.data import (
    BuybackEvent,
    EconomyData,
    FirstBloodData,
    GameDetailData,
    HeroDeath,
    MatchData,
    MinuteData,
    NeutralItemEvent,
    ObjectiveEvent,
    PurchaseEvent,
    ScoreData,
    TeamsData,
)
from app.vnext.capabilities.game.service import GameDetailService
from app.vnext.catalog import UnitCatalog
from app.vnext.composition import VNextServices, VNextSettings, build_vnext_registry
from app.vnext.domain.common.time_format import format_game_time
from app.vnext.llm.protocol import ToolCall
from tests.vnext.test_game_detail_projection import FIXTURE, player, project, record, source


@pytest.mark.parametrize(
    ("seconds", "label"),
    [
        (None, None),
        (0, "00:00"),
        (600, "10:00"),
        (1010, "16:50"),
        (3600, "60:00"),
        (6000, "100:00"),
        (-89, "-01:29"),
        (1478.25, "24:38.25"),
        (-89.25, "-01:29.25"),
        (-0.5, "-00:00.5"),
        (-0.0, "00:00"),
        (60.0, "01:00"),
        (59.999, "00:59.999"),
        (1e-7, "00:00.0000001"),
        (1.2345678901234567, "00:01.2345678901234567"),
    ],
)
def test_game_time_format_retains_sign_fraction_and_total_minutes(seconds, label) -> None:
    assert format_game_time(seconds) == label


@pytest.mark.parametrize("seconds", [True, "60", float("nan"), float("inf"), -float("inf")])
def test_game_time_format_rejects_non_numeric_or_non_finite_seconds(seconds) -> None:
    with pytest.raises((TypeError, ValueError)):
        format_game_time(seconds)


@pytest.mark.parametrize(
    "model",
    [
        PurchaseEvent,
        NeutralItemEvent,
        HeroDeath,
        BuybackEvent,
        ObjectiveEvent,
    ],
)
def test_event_labels_preserve_source_seconds_and_missing_values(model) -> None:
    event = model(time_seconds=-0.25)
    assert event.time_seconds == -0.25
    assert event.time_label == "-00:00.25"
    assert model().time_label is None
    assert model.model_validate_json(event.model_dump_json()) == event
    with pytest.raises(ValidationError, match="must match"):
        model(time_seconds=1010, time_label="06:00")


def test_duration_first_blood_and_death_duration_use_the_same_format() -> None:
    match = MatchData(duration_seconds=2904, score=ScoreData(), teams=TeamsData())
    assert match.duration_label == "48:24"
    assert MatchData(score=ScoreData(), teams=TeamsData()).duration_label is None
    assert FirstBloodData(reported_time_seconds=0).reported_time_label == "00:00"
    assert FirstBloodData().reported_time_label is None
    death = HeroDeath(time_seconds=1010, time_dead_seconds=28.125)
    assert death.time_label == "16:50"
    assert death.time_dead_label == "00:28.125"
    assert HeroDeath().time_dead_label is None


def test_minute_nodes_remain_required_integer_seconds_without_minute_buckets() -> None:
    node = MinuteData(time_seconds=1200)
    assert node.time_label == "20:00"
    for arguments in (
        {},
        {"time_seconds": None},
        {"time_seconds": 1200.5},
        {"time_seconds": True},
        {"time_seconds": 1200, "minute": 20},
    ):
        with pytest.raises(ValidationError):
            MinuteData(**arguments)


def test_economy_labels_follow_only_the_verified_axis_including_empty_axis() -> None:
    assert EconomyData().time_labels is None
    assert EconomyData(time_seconds=[]).time_labels == []
    economy = EconomyData(time_seconds=[0, 600, 3600])
    assert economy.time_labels == ["00:00", "10:00", "60:00"]
    assert EconomyData.model_validate_json(economy.model_dump_json()) == economy
    with pytest.raises(ValidationError, match="must match"):
        EconomyData(time_seconds=[600], time_labels=["09:00"])
    with pytest.raises(ValidationError, match="must match"):
        EconomyData(time_seconds=None, time_labels=["00:00"])


def test_projection_does_not_invent_labels_for_unaligned_economy_or_missing_times() -> None:
    data = project(
        record(
            source(
                players=[player(), player(times=[0, 120], purchase_log=[{"key": "manta"}])],
                radiant_gold_adv=[0, 10],
                radiant_xp_adv=[0, 20],
            )
        )
    )
    assert data.economy.time_seconds is None
    assert data.economy.time_labels is None
    assert data.economy.radiant_gold_adv == [0, 10]
    purchase = data.builds.players[1].purchase_events[0]
    assert purchase.time_seconds is None
    assert purchase.time_label is None


def test_saved_game_labels_survive_public_dto_roundtrip_without_changing_source() -> None:
    raw = json.loads(FIXTURE.read_text())
    original = deepcopy(raw)
    data = project(record(raw))
    assert data.match.duration_label == "48:24"
    yatoro = next(p for p in data.players if p.identity.account_id == 321580662)
    assert yatoro.minute_timeline[20].time_seconds == 1200
    assert yatoro.minute_timeline[20].time_label == "20:00"
    assert yatoro.minute_timeline[20].net_worth == 7266
    build = next(b for b in data.builds.players if b.player_slot == 1)
    manta = next(p for p in build.purchase_events if p.item.id == 147)
    assert (manta.time_seconds, manta.time_label) == (1478, "24:38")
    assert all(p.time_label == "-01:29" for p in build.purchase_events if p.time_seconds == -89)
    assert data.events.first_blood.reported_time_label == "00:00"
    assert data.events.first_blood.objective_events[0].time_label == "-00:25"
    assert data.events.building_destructions[-1].time_label == "48:25"
    assert data.events.building_destructions[-1].time_seconds == 2905
    assert data.coverage.conflicts[0].values == [0, -25]
    assert all("label" not in gap.path for gap in data.coverage.missing)
    assert GameDetailData.model_validate_json(data.model_dump_json()) == data
    assert raw == original


def test_time_labels_reach_the_public_tool_artifact_and_narrow_read() -> None:
    original = record(json.loads(FIXTURE.read_text()))

    class Provider:
        async def get_game_record(self, match_id):
            assert match_id == original.match_id
            return original

    service = GameDetailService(
        Provider(),
        DotaCatalogRepository.load_default,
        UnitCatalog.load_default(),
    )
    registry = build_vnext_registry(
        VNextServices(game_detail=service.get_game_detail),
        settings=VNextSettings(opendota_enabled=True),
    )

    async def run():
        detail = await registry.execute(
            ToolCall(
                id="detail",
                name="game.detail",
                arguments={"valve_game_id": original.match_id},
            )
        )
        assert detail.status == "ok"
        assert detail.content["externalized"] is True
        ref = detail.content["artifact_ref"]
        node = await registry.execute(
            ToolCall(
                id="minute",
                name="artifact.read",
                arguments={
                    "ref": ref,
                    "mode": "read",
                    "path": "data.players.1.minute_timeline",
                    "offset": 20,
                    "limit": 1,
                },
            )
        )
        duration = await registry.execute(
            ToolCall(
                id="duration",
                name="artifact.read",
                arguments={"ref": ref, "mode": "read", "path": "data.match.duration_label"},
            )
        )
        assert node.status == duration.status == "ok"
        assert node.content["value"][0]["time_label"] == "20:00"
        assert node.content["value"][0]["time_seconds"] == 1200
        assert duration.content["value"] == "48:24"

    asyncio.run(run())
