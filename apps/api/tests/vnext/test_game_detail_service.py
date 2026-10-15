from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from app.integrations.valve.catalog_repository import DotaCatalogRepository
from app.vnext.capabilities.game.detail import GameDetailInput, GameDetailResult
from app.vnext.capabilities.game.service import GameDetailService
from app.vnext.catalog import UnitCatalog
from app.vnext.providers.opendota.game_detail import OpenDotaGameRecord
from app.vnext.tools.errors import StructuredToolError

_MATCH_ID = 9_040_460_429


def _record() -> OpenDotaGameRecord:
    return OpenDotaGameRecord(
        match_id=_MATCH_ID,
        retrieved_at=datetime(2026, 10, 14, 8, 0, tzinfo=UTC),
        data={
            "match_id": _MATCH_ID,
            "start_time": 1_791_738_028,
            "duration": 2904,
            "radiant_win": False,
            "radiant_team": {"team_id": 7_119_388, "name": "Team Spirit"},
            "dire_team": {"team_id": 9_823_272, "name": "Team Yandex"},
            "players": [{"account_id": None, "kills": 0, "hero_id": 1}],
            "extension": {"ordered": [0, False, None]},
        },
    )


class _Provider:
    def __init__(self, result: OpenDotaGameRecord | BaseException) -> None:
        self.result = result
        self.calls: list[int] = []

    async def get_game_record(self, match_id: int) -> OpenDotaGameRecord:
        self.calls.append(match_id)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _service(provider, catalog_provider=DotaCatalogRepository.load_default):
    return GameDetailService(provider, catalog_provider, UnitCatalog.load_default())


def test_service_projects_one_internal_record_with_separate_label_provenance() -> None:
    record = _record()
    provider = _Provider(record)
    result = asyncio.run(_service(provider).get_game_detail(
        GameDetailInput(valve_game_id=_MATCH_ID),
    ))

    assert provider.calls == [_MATCH_ID]
    assert type(result) is GameDetailResult
    assert result.valve_game_id == _MATCH_ID and result.retrieved_at == record.retrieved_at
    assert result.catalog_version.patch == DotaCatalogRepository.load_default().manifest.patch
    assert result.unit_mapping_version == UnitCatalog.load_default().version
    assert result.data.match.duration_seconds == 2904
    assert result.data.players[0].identity.hero.name_en == "Anti-Mage"
    assert "extension" not in result.data.model_dump()
    assert record.data["extension"]["ordered"] == [0, False, None]


def test_public_and_internal_nested_data_do_not_share_mutable_values() -> None:
    record = _record()
    before = deepcopy(record)
    result = asyncio.run(_service(_Provider(record)).get_game_detail(
        GameDetailInput(valve_game_id=_MATCH_ID),
    ))
    result.data.players[0].final_stats.kills = 10
    assert record == before
    record.data["radiant_team"]["name"] = "internal-only"
    assert result.data.match.teams.radiant.name == "Team Spirit"
    assert record.data["start_time"] == 1_791_738_028


def test_service_pins_catalog_before_source_read_and_next_query_uses_new_snapshot() -> None:
    old = DotaCatalogRepository.load_default()
    new = deepcopy(old)
    new._heroes[1] = new._heroes[1].model_copy(update={"name_en": "New label"})
    new.manifest = new.manifest.model_copy(update={"patch": "new-patch"})
    current = [old]
    supplier_calls = []

    def supplier():
        supplier_calls.append(current[0])
        return current[0]

    class SwappingProvider(_Provider):
        async def get_game_record(self, match_id):
            current[0] = new
            return await super().get_game_record(match_id)

    provider = SwappingProvider(_record())
    service = _service(provider, supplier)
    first = asyncio.run(service.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))
    second = asyncio.run(service.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))
    assert supplier_calls == [old, new]
    assert first.data.players[0].identity.hero.name_en == "Anti-Mage"
    assert first.catalog_version.patch == old.manifest.patch
    assert second.data.players[0].identity.hero.name_en == "New label"
    assert second.catalog_version.patch == "new-patch"


def test_service_rejects_a_record_for_a_different_request() -> None:
    provider = _Provider(_record().model_copy(update={"match_id": 42}))
    with pytest.raises(StructuredToolError) as caught:
        asyncio.run(_service(provider).get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))
    assert caught.value.code == "provider_schema_error"


@pytest.mark.parametrize(
    "error",
    [
        StructuredToolError("provider_timeout", "timeout", {"provider": "opendota"}),
        StructuredToolError("provider_schema_error", "invalid", {"field": "match_id"}),
        asyncio.CancelledError(),
    ],
)
def test_service_propagates_provider_errors_and_cancellation(error: BaseException) -> None:
    provider = _Provider(error)
    service = _service(provider)

    with pytest.raises(type(error)) as captured:
        asyncio.run(service.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))

    assert captured.value is error
    assert provider.calls == [_MATCH_ID]
