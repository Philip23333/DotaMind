from __future__ import annotations

from typing import Any

import pytest

from app.integrations.valve.image_client import MAX_IMAGE_BYTES, PNG_SIGNATURE
from app.vnext.providers.pandascore.team_image_client import (
    PandaScoreTeamImageClient,
    TeamImageError,
)


class FakeResponse:
    status = 200

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.read_limit: int | None = None
        self.closed = False

    def read(self, limit: int) -> bytes:
        self.read_limit = limit
        return self.payload

    def close(self) -> None:
        self.closed = True


def test_download_uses_public_request_without_authorization_and_closes_response() -> None:
    response = FakeResponse(PNG_SIGNATURE + b"png-data")
    captured: list[tuple[Any, float]] = []

    def opener(request, *, timeout):
        captured.append((request, timeout))
        return response

    payload = PandaScoreTeamImageClient(opener=opener).fetch_png(
        "https://cdn.pandascore.test/team.png"
    )

    assert payload == PNG_SIGNATURE + b"png-data"
    request, timeout = captured[0]
    assert timeout == 30
    assert request.get_header("Authorization") is None
    assert request.get_header("User-agent") == "DotaMind team display refresh"
    assert response.read_limit == MAX_IMAGE_BYTES + 1
    assert response.closed is True


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (b"<html>not a png</html>", "invalid_image"),
        (PNG_SIGNATURE + b"x" * (MAX_IMAGE_BYTES + 1), "image_too_large"),
    ],
)
def test_download_rejects_non_png_and_oversized_payloads(payload: bytes, reason: str) -> None:
    response = FakeResponse(payload)

    with pytest.raises(TeamImageError) as raised:
        PandaScoreTeamImageClient(opener=lambda *_args, **_kwargs: response).fetch_png(
            "https://cdn.pandascore.test/team.png"
        )

    assert raised.value.reason == reason
    assert response.closed is True


@pytest.mark.parametrize(
    "url",
    ["http://cdn.pandascore.test/team.png", "https://[invalid/team.png"],
)
def test_invalid_url_is_rejected_without_opening_a_request(url: str) -> None:
    calls = 0

    def opener(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("invalid URL must not be opened")

    client = PandaScoreTeamImageClient(opener=opener)
    with pytest.raises(TeamImageError) as raised:
        client.fetch_png(url)

    assert raised.value.reason == "invalid_url"
    assert calls == 0


def test_timeout_must_be_finite_and_positive() -> None:
    for timeout in (float("nan"), 0, 10**1000):
        with pytest.raises(ValueError):
            PandaScoreTeamImageClient(timeout_seconds=timeout)
