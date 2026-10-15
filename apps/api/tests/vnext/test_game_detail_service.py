from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from app.vnext.capabilities.game.detail import GameDetailInput, GameDetailResult
from app.vnext.capabilities.game.service import GameDetailService
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
            "players": [{"account_id": None, "kills": 0}],
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


def test_service_converts_internal_record_to_unchanged_public_detail() -> None:
    record = _record()
    provider = _Provider(record)
    service = GameDetailService(provider)  # type: ignore[arg-type]

    result = asyncio.run(service.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))

    assert provider.calls == [_MATCH_ID]
    assert type(result) is GameDetailResult
    assert type(record) is OpenDotaGameRecord
    assert result.model_dump() == {
        "valve_game_id": _MATCH_ID,
        "provider": "opendota",
        "retrieved_at": record.retrieved_at,
        "data": record.data,
    }


def test_public_and_internal_nested_data_do_not_share_mutable_values() -> None:
    record = _record()
    before = deepcopy(record)
    service = GameDetailService(_Provider(record))  # type: ignore[arg-type]

    result = asyncio.run(service.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))
    result.data["extension"]["ordered"].append("public-only")
    result.data["players"][0]["kills"] = 10

    assert record == before
    record.data["radiant_team"]["name"] = "internal-only"
    assert result.data["radiant_team"]["name"] == "Team Spirit"
    assert record.data["start_time"] == 1_791_738_028
    assert record.data["dire_team"]["team_id"] == 9_823_272


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
    service = GameDetailService(provider)  # type: ignore[arg-type]

    with pytest.raises(type(error)) as captured:
        asyncio.run(service.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))

    assert captured.value is error
    assert provider.calls == [_MATCH_ID]
