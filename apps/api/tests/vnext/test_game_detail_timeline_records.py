from __future__ import annotations

from typing import get_args

import pytest
from pydantic import BaseModel, ValidationError

from app.vnext.capabilities.game.data import (
    AbilityUpgradeEvent,
    BuybackEvent,
    EconomyData,
    EconomyMinute,
    EventsData,
    FirstBloodData,
    HeroDeath,
    InventoryEvent,
    MinuteData,
    NeutralItemEvent,
    ObjectiveEvent,
    PlayerBuild,
    PlayerData,
    PurchaseEvent,
)
from tests.vnext.test_stratz_detail_projection import primary, project, supplement

TIMELINES = [
    (PlayerData, "minute_timeline", MinuteData),
    (EconomyData, "minute_timeline", EconomyMinute),
    (PlayerBuild, "purchase_events", PurchaseEvent),
    (PlayerBuild, "inventory_events", InventoryEvent),
    (PlayerBuild, "ability_upgrade_events", AbilityUpgradeEvent),
    (PlayerBuild, "neutral_item_history", NeutralItemEvent),
    (EventsData, "hero_deaths", HeroDeath),
    (EventsData, "buybacks", BuybackEvent),
    (EventsData, "building_destructions", ObjectiveEvent),
    (EventsData, "roshan_kills", ObjectiveEvent),
    (EventsData, "aegis_pickups", ObjectiveEvent),
    (FirstBloodData, "objective_events", ObjectiveEvent),
    (EventsData, "other_objectives", ObjectiveEvent),
]


@pytest.mark.parametrize("owner,field,node", TIMELINES)
def test_every_public_timeline_uses_time_bound_records(owner, field, node) -> None:
    variants = get_args(owner.model_fields[field].annotation)
    assert list[node] in variants
    assert "time_seconds" in node.model_fields and "time_label" in node.model_fields
    payload = {"inventory": [None] * 6, "backpack": [None] * 3} if node is InventoryEvent else {}
    assert node(time_seconds=-89, **payload).model_dump()["time_label"] == "-01:29"
    with pytest.raises(ValidationError):
        node(time_seconds=[-89, 0], **payload)


def _models(value):
    if isinstance(value, BaseModel):
        yield value
        for field in type(value).model_fields:
            yield from _models(getattr(value, field))
    elif isinstance(value, list):
        for item in value:
            yield from _models(item)


def test_full_projected_game_contains_no_parallel_time_arrays_or_label_arrays() -> None:
    source = primary(9040460429)
    detail = project(source, supplement(source))
    seen = set()
    for model in _models(detail):
        fields = type(model).model_fields
        assert "times" not in fields and "time_labels" not in fields
        if "time_seconds" in fields:
            value = model.time_seconds
            assert value is None or type(value) in (int, float)
            seen.add(type(model))
        for owner, field, node in TIMELINES:
            if type(model) is owner:
                rows = getattr(model, field)
                assert rows is None or all(type(row) is node for row in rows)
    assert {MinuteData, EconomyMinute, PurchaseEvent, InventoryEvent,
            AbilityUpgradeEvent, NeutralItemEvent, HeroDeath, ObjectiveEvent} <= seen
    assert set(detail.economy.model_dump()) == {"minute_timeline"}
