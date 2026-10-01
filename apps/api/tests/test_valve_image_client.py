from __future__ import annotations

from io import BytesIO
from typing import Any
from urllib.error import HTTPError

import pytest

from app.integrations.valve.image_client import (
    MAX_IMAGE_BYTES,
    PNG_SIGNATURE,
    ValveImageClient,
    ValveImageError,
    build_image_url,
)


class FakeResponse:
    def __init__(self, payload: bytes, *, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.read_sizes: list[int] = []
        self.close_calls = 0

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        return self.payload[:size]

    def close(self) -> None:
        self.close_calls += 1


def test_client_fetches_raw_png_from_fixed_valve_url_and_closes_response() -> None:
    payload = PNG_SIGNATURE + b"raw-png-data"
    response = FakeResponse(payload)
    calls: list[tuple[Any, float]] = []

    def opener(request: Any, *, timeout: float) -> FakeResponse:
        calls.append((request, timeout))
        return response

    client = ValveImageClient(opener)
    assert client.fetch_png("heroes", "npc_dota_hero_sven") == payload

    assert len(calls) == 1
    request, timeout = calls[0]
    assert request.full_url == (
        "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/"
        "heroes/sven.png"
    )
    assert timeout == 30
    assert response.read_sizes == [MAX_IMAGE_BYTES + 1]
    assert response.close_calls == 1


@pytest.mark.parametrize(
    ("kind", "name", "expected"),
    [
        ("items", "item_blink", "items/blink.png"),
        ("abilities", "sven_storm_bolt", "abilities/sven_storm_bolt.png"),
    ],
)
def test_image_urls_keep_existing_valve_asset_paths(
    kind: str,
    name: str,
    expected: str,
) -> None:
    assert build_image_url(kind, name).endswith(expected)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (b"", "invalid_image"),
        (b"not-png", "invalid_image"),
        (PNG_SIGNATURE + b"x" * MAX_IMAGE_BYTES, "image_too_large"),
    ],
)
def test_client_rejects_invalid_payloads_and_closes_response(
    payload: bytes,
    reason: str,
) -> None:
    response = FakeResponse(payload)
    calls = 0

    def opener(*_args: Any, **_kwargs: Any) -> FakeResponse:
        nonlocal calls
        calls += 1
        return response

    with pytest.raises(ValveImageError) as raised:
        ValveImageClient(opener).fetch_png("heroes", "npc_dota_hero_sven")

    assert raised.value.reason == reason
    assert calls == 1
    assert response.close_calls == 1
    assert response.read_sizes == [MAX_IMAGE_BYTES + 1]


@pytest.mark.parametrize("failure", [OSError("secret URL"), TimeoutError("secret")])
def test_client_maps_transport_failures_without_retry_or_details(failure: Exception) -> None:
    calls = 0

    def opener(*_args: Any, **_kwargs: Any) -> FakeResponse:
        nonlocal calls
        calls += 1
        raise failure

    with pytest.raises(ValveImageError) as raised:
        ValveImageClient(opener).fetch_png("items", "item_blink")

    assert raised.value.reason == "download_failed"
    assert str(raised.value) == "Valve image download failed"
    assert "secret" not in str(raised.value)
    assert calls == 1


def test_client_rejects_http_error_and_invalid_target_safely() -> None:
    response = FakeResponse(PNG_SIGNATURE, status=404)
    calls: list[Any] = []
    client = ValveImageClient(lambda request, **_kwargs: (calls.append(request), response)[1])

    with pytest.raises(ValveImageError, match="download failed") as raised:
        client.fetch_png("heroes", "npc_dota_hero_sven")
    assert raised.value.reason == "download_failed"
    assert response.close_calls == 1
    assert response.read_sizes == []

    with pytest.raises(ValveImageError) as invalid:
        client.fetch_png("heroes", "../secret")
    assert invalid.value.reason == "invalid_target"
    assert len(calls) == 1


@pytest.mark.parametrize("status", [404, 500])
def test_http_error_response_body_is_closed_without_reading_or_leaking(
    status: int,
) -> None:
    body = BytesIO(b"sensitive response body")
    calls = 0
    url = "https://cdn.example.invalid/private?token=sensitive-url"

    def opener(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise HTTPError(
            url=url,
            code=status,
            msg="sensitive HTTP message",
            hdrs=None,
            fp=body,
        )

    with pytest.raises(ValveImageError) as raised:
        ValveImageClient(opener).fetch_png("heroes", "npc_dota_hero_sven")

    assert raised.value.reason == "download_failed"
    assert str(raised.value) == "Valve image download failed"
    assert "sensitive" not in str(raised.value)
    assert "cdn.example.invalid" not in str(raised.value)
    assert calls == 1
    assert body.closed
