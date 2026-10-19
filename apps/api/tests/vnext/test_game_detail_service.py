from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from app.integrations.valve.catalog_repository import DotaCatalogRepository
from app.vnext.capabilities.game.detail import GameDetailInput, GameDetailResult
from app.vnext.capabilities.game.service import GameDetailService
from app.vnext.catalog import UnitCatalog
from app.vnext.providers.stratz.game_detail import StratzGameRecord
from app.vnext.tools.errors import StructuredToolError

_MATCH_ID = 9_040_460_429


def _record() -> StratzGameRecord:
    return StratzGameRecord(
        match_id=_MATCH_ID,
        retrieved_at=datetime(2026, 10, 14, 8, 0, tzinfo=UTC),
        data={
            "id": _MATCH_ID,
            "startDateTime": 1_791_738_028,
            "durationSeconds": 2904,
            "didRadiantWin": False,
            "radiantTeamId": 7_119_388,
            "direTeamId": 9_823_272,
            "radiantTeam": {"id": 7_119_388, "name": "Team Spirit"},
            "direTeam": {"id": 9_823_272, "name": "Team Yandex"},
            "players": [{"steamAccountId": None, "kills": 0, "heroId": 1}],
            "extension": {"ordered": [0, False, None]},
        },
    )


class _Provider:
    def __init__(self, result: StratzGameRecord | BaseException) -> None:
        self.result = result
        self.calls: list[int] = []

    async def get_game_record(self, match_id: int) -> StratzGameRecord:
        self.calls.append(match_id)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _service(provider, catalog_provider=DotaCatalogRepository.load_default):
    return GameDetailService(provider, catalog_provider, UnitCatalog.load_default())


def test_service_projects_one_internal_record_with_separate_label_provenance() -> None:
    record = _record()
    provider = _Provider(record)
    result = asyncio.run(
        _service(provider).get_game_detail(
            GameDetailInput(valve_game_id=_MATCH_ID),
        )
    )

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
    result = asyncio.run(
        _service(_Provider(record)).get_game_detail(
            GameDetailInput(valve_game_id=_MATCH_ID),
        )
    )
    result.data.players[0].final_stats.kills = 10
    assert record == before
    record.data["radiantTeam"]["name"] = "internal-only"
    assert result.data.match.teams.radiant.name == "Team Spirit"
    assert record.data["startDateTime"] == 1_791_738_028


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


@pytest.mark.parametrize("code", ["provider_timeout", "provider_http_error", "provider_error"])
def test_supplement_unavailability_preserves_primary_and_has_no_successful_source_entry(code):
    primary = _Provider(_record())
    extra = _Provider(StructuredToolError(code, "safe source failure", {"provider": "opendota"}))
    service = GameDetailService(
        primary, DotaCatalogRepository.load_default, UnitCatalog.load_default(), supplement=extra
    )
    result = asyncio.run(service.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))
    assert result.provider == "stratz" and set(result.sources) == {"stratz"}
    assert result.data.players[0].identity.hero.id == 1
    assert result.data.economy.minute_timeline is None
    assert result.data.events.roshan_kills is None
    assert primary.calls == extra.calls == [_MATCH_ID]
    assert any(code in (g.reason or "") for g in result.data.coverage.groups)


@pytest.mark.parametrize(
    "error",
    [
        StructuredToolError("provider_schema_error", "invalid identity", {"provider": "opendota"}),
        asyncio.CancelledError(),
        RuntimeError("programming failure"),
    ],
)
def test_supplement_schema_errors_cancellation_and_bugs_are_not_hidden(error):
    service = GameDetailService(
        _Provider(_record()),
        DotaCatalogRepository.load_default,
        UnitCatalog.load_default(),
        supplement=_Provider(error),
    )
    with pytest.raises(type(error)) as caught:
        asyncio.run(service.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))
    assert caught.value is error


def test_two_successful_reads_keep_separate_timestamps_and_supplement_identity_is_checked():
    from tests.vnext.test_stratz_detail_projection import primary, supplement

    record = primary(9040460429)
    extra = supplement(record)
    extra.retrieved_at = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
    service = GameDetailService(
        _Provider(record),
        DotaCatalogRepository.load_default,
        UnitCatalog.load_default(),
        supplement=_Provider(extra),
    )
    result = asyncio.run(service.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))
    assert result.sources["stratz"].retrieved_at == record.retrieved_at
    assert result.sources["opendota"].retrieved_at == extra.retrieved_at
    assert result.sources["stratz"].retrieved_at != result.sources["opendota"].retrieved_at
    assert GameDetailResult.model_validate_json(result.model_dump_json()) == result
    extra.data["match_id"] = 1
    with pytest.raises(StructuredToolError) as caught:
        asyncio.run(service.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))
    assert caught.value.code == "provider_schema_error"
