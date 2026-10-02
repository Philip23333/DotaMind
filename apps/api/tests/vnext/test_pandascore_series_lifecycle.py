from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.vnext.providers.pandascore.client import (
    PandaScoreClient,
    PandaScoreConfigurationError,
    PandaScoreProtocolError,
)
from app.vnext.providers.pandascore.series_adapter import PandaScoreSeriesAdapter


def _adapter(
    handler,
    *,
    token: str = "test-token",
) -> PandaScoreSeriesAdapter:
    client = PandaScoreClient(
        base_url="https://api.pandascore.test",
        token=token,
        transport=httpx.MockTransport(handler),
    )
    return PandaScoreSeriesAdapter(client)


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": 10828,
        "league_id": 4106,
        "name": "The International",
        "full_name": "The International 2026",
        "season": "2026",
        "year": 2026,
        "begin_at": "2026-08-01T00:00:00Z",
        "end_at": "2026-09-01T00:00:00Z",
        "winner_id": 123,
        "winner_type": "Team",
        "tier": "s",
        "slug": "the-international-2026",
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("lifecycle", "path", "sort"),
    [
        ("running", "/dota2/series/running", "-begin_at"),
        ("past", "/dota2/series/past", "-end_at"),
    ],
)
def test_lifecycle_read_uses_one_correctly_sorted_paged_request(
    lifecycle: str,
    path: str,
    sort: str,
) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=[_row()], request=request)

    result = asyncio.run(
        _adapter(handler).list_by_lifecycle(
            lifecycle=lifecycle, page=3, limit=17  # type: ignore[arg-type]
        )
    )

    assert calls == [
        (
            path,
            {"page": "3", "per_page": "17", "sort": sort},
        )
    ]
    assert result.page == 3
    assert result.limit == 17
    assert len(result.items) == 1


def test_lifecycle_read_preserves_series_fields_and_normalizes_winner_type() -> None:
    rows = [
        _row(winner_type="  Team  "),
        _row(id=2, winner_type=" Player ", begin_at=None, end_at=None),
        _row(id=3, winner_type=" Referee "),
        _row(id=4, winner_type=""),
        _row(id=5, winner_type="  "),
        _row(id=6, winner_type=123),
        _row(id=7, winner_type=None),
        _row(id=8, winner_type="unknown-kind"),
    ]
    rows.append(_row(id=9))
    rows[-1].pop("winner_type")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows, request=request)

    result = asyncio.run(_adapter(handler).list_by_lifecycle(lifecycle="past"))

    assert result.anomalies == []
    assert [item.id for item in result.items] == [10828, 2, 3, 4, 5, 6, 7, 8, 9]
    first = result.items[0]
    assert first.model_dump(mode="json") == {
        "id": 10828,
        "league_id": 4106,
        "name": "The International",
        "full_name": "The International 2026",
        "year": 2026,
        "season": "2026",
        "begin_at": "2026-08-01T00:00:00Z",
        "end_at": "2026-09-01T00:00:00Z",
        "winner_id": 123,
        "tier": "s",
        "slug": "the-international-2026",
        "winner_type": "Team",
    }
    assert result.items[1].winner_id == 123
    assert result.items[1].begin_at is None
    assert result.items[1].end_at is None
    assert [item.winner_type for item in result.items] == [
        "Team",
        "Player",
        "Referee",
        None,
        None,
        None,
        None,
        "unknown-kind",
        None,
    ]


def test_lifecycle_read_distinguishes_empty_response_from_bad_rows() -> None:
    responses = [[], [None, {"id": 55}, _row(begin_at="not-a-date")]]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.pop(0), request=request)

    adapter = _adapter(handler)
    empty_result = asyncio.run(adapter.list_by_lifecycle(lifecycle="running"))
    bad_result = asyncio.run(adapter.list_by_lifecycle(lifecycle="running"))

    assert empty_result.items == []
    assert empty_result.anomalies == []
    assert bad_result.items == []
    assert [anomaly.path for anomaly in bad_result.anomalies] == [
        "provider.items[0]",
        "provider.items[1]",
        "provider.items[2]",
    ]
    assert [anomaly.reason for anomaly in bad_result.anomalies] == [
        "provider item is not an object",
        "missing required field: league_id",
        "failed to map provider item",
    ]
    assert bad_result.anomalies[1].provider_id == 55


@pytest.mark.parametrize(
    ("lifecycle", "page", "limit"),
    [
        ("upcoming", 1, 10),
        (None, 1, 10),
        ("running", 0, 10),
        ("running", -1, 10),
        ("running", True, 10),
        ("running", 1.0, 10),
        ("past", 1, 0),
        ("past", 1, 101),
        ("past", 1, False),
        ("past", 1, "10"),
    ],
)
def test_invalid_lifecycle_arguments_fail_before_request(
    lifecycle: Any,
    page: Any,
    limit: Any,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=[], request=request)

    with pytest.raises(ValueError):
        asyncio.run(
            _adapter(handler).list_by_lifecycle(
                lifecycle=lifecycle,
                page=page,
                limit=limit,
            )  # type: ignore[arg-type]
        )

    assert calls == 0


def test_lifecycle_read_propagates_http_protocol_and_configuration_errors() -> None:
    def http_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(_adapter(http_error).list_by_lifecycle(lifecycle="running"))

    def protocol_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": []}, request=request)

    with pytest.raises(PandaScoreProtocolError, match="JSON list"):
        asyncio.run(_adapter(protocol_error).list_by_lifecycle(lifecycle="running"))

    calls = 0

    def should_not_call(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=[], request=request)

    with pytest.raises(PandaScoreConfigurationError):
        asyncio.run(
            _adapter(should_not_call, token="").list_by_lifecycle(lifecycle="past")
        )
    assert calls == 0
