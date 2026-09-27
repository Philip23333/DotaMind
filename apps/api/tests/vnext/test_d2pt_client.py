from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from datetime import UTC
from email.message import Message
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from app.vnext.providers.d2pt import (
    D2PTClient,
    D2PTHTTPError,
    D2PTJSONError,
    D2PTResponse,
    D2PTResponseTooLargeError,
    D2PTSchemaError,
    D2PTTimeoutError,
    D2PTTransportError,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "d2pt"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
EXPECTED_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "referer": "https://dota2protracker.com/",
    "accept": "application/json",
}


@pytest.fixture(autouse=True)
def block_real_urlopen(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> None:
        pytest.fail("unexpected real urllib.request.urlopen call")

    monkeypatch.setattr(urllib.request, "urlopen", fail_if_called)


class FakeResponse:
    def __init__(
        self,
        body: bytes = b"[]",
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        read_error: BaseException | None = None,
    ) -> None:
        self.body = body
        self.status = status
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value
        self.read_error = read_error
        self.read_sizes: list[int] = []
        self.closed = False

    def getcode(self) -> int:
        return self.status

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if self.read_error is not None:
            raise self.read_error
        return self.body if size < 0 else self.body[:size]

    def close(self) -> None:
        self.closed = True


class FakeOpener:
    def __init__(self, *outcomes: object) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[urllib.request.Request, float]] = []

    def __call__(self, request: urllib.request.Request, *, timeout: float) -> object:
        self.calls.append((request, timeout))
        outcome = self.outcomes[len(self.calls) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _json_response(data: object, **kwargs: Any) -> FakeResponse:
    return FakeResponse(json.dumps(data, separators=(",", ":")).encode(), **kwargs)


def _request_headers(request: urllib.request.Request) -> dict[str, str]:
    return {name.lower(): value for name, value in request.header_items()}


def _pub_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {"hero_id": 18, "position": "pos 1", "build_data": {}}
    row.update(overrides)
    return row


def _pro_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {"hero_id": 18, "position": "pos 1"}
    row.update(overrides)
    return row


def _call_with_response(
    method: str,
    data: object,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> tuple[D2PTResponse, FakeOpener, FakeResponse]:
    response = _json_response(data, status=status, headers=headers)
    opener = FakeOpener(response)
    result = getattr(D2PTClient(opener=opener), method)(18, 1) if method == "pub_builds" else None
    if method == "pro_builds":
        result = D2PTClient(opener=opener).pro_builds(18)
    assert isinstance(result, D2PTResponse)
    return result, opener, response


def test_three_methods_build_exact_get_urls_headers_and_default_timeout() -> None:
    opener = FakeOpener(_json_response([{"hero_id": 18}]), FakeResponse(), FakeResponse())
    client = D2PTClient(opener=opener)

    client.heroes_list()
    client.pub_builds(18, 1)
    client.pro_builds(18)

    assert [request.full_url for request, _ in opener.calls] == [
        "https://dota2protracker.com/api/heroes/list",
        "https://dota2protracker.com/api/hero/18/builds?position=pos%201",
        "https://dota2protracker.com/api/hero/18/pro-builds",
    ]
    assert all(request.get_method() == "GET" for request, _ in opener.calls)
    assert all(_request_headers(request) == EXPECTED_HEADERS for request, _ in opener.calls)
    assert all(timeout == 30.0 for _, timeout in opener.calls)
    assert all("accept-encoding" not in _request_headers(request) for request, _ in opener.calls)


def test_custom_positive_timeout_is_passed_to_opener() -> None:
    opener = FakeOpener(_json_response([{"hero_id": 18}]))

    D2PTClient(timeout_seconds=2.5, opener=opener).heroes_list()

    assert opener.calls[0][1] == 2.5


@pytest.mark.parametrize("hero_id", [0, -1, True, 18.0, "18"])
def test_invalid_hero_ids_fail_before_opener(hero_id: object) -> None:
    opener = FakeOpener(FakeResponse())
    client = D2PTClient(opener=opener)

    with pytest.raises(ValueError):
        client.pub_builds(hero_id, 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        client.pro_builds(hero_id)  # type: ignore[arg-type]

    assert opener.calls == []


@pytest.mark.parametrize("position", [0, 6, True, 1.0, "1"])
def test_invalid_positions_fail_before_opener(position: object) -> None:
    opener = FakeOpener(FakeResponse())

    with pytest.raises(ValueError):
        D2PTClient(opener=opener).pub_builds(18, position)  # type: ignore[arg-type]

    assert opener.calls == []


@pytest.mark.parametrize(
    "timeout",
    [0, -1, True, math.inf, math.nan, "1", pytest.param(10**10000, id="oversized-int")],
)
def test_invalid_timeout_fails_at_construction(timeout: object) -> None:
    with pytest.raises(ValueError):
        D2PTClient(timeout_seconds=timeout)  # type: ignore[arg-type]


def test_default_opener_and_construction_do_not_make_a_request() -> None:
    client = D2PTClient()

    assert isinstance(client, D2PTClient)


def test_pub_and_pro_fixture_bodies_are_preserved_without_reencoding() -> None:
    for method, fixture_name in (
        ("pub_builds", "pub_sven_pos1.json"),
        ("pro_builds", "pro_sven.json"),
    ):
        raw = (FIXTURE_DIR / fixture_name).read_bytes()
        response = FakeResponse(raw, headers={"Content-Type": "application/json"})
        opener = FakeOpener(response)
        client = D2PTClient(opener=opener)
        result = client.pub_builds(18, 1) if method == "pub_builds" else client.pro_builds(18)

        assert result.raw_body == raw
        assert result.data == json.loads(raw)
        assert result.content_type == "application/json"
        assert result.retrieved_at.tzinfo is UTC
        assert response.read_sizes == [MAX_RESPONSE_BYTES + 1]
        assert response.closed
        assert len(opener.calls) == 1


def test_source_records_preserve_unknown_values_and_multiple_build_order() -> None:
    rows = [
        _pub_row(build_id=8, build_data={"x_future": {"v": [None, 0, False]}}),
        _pub_row(build_id=3, build_data={}, local_extension="kept"),
    ]
    result, _, _ = _call_with_response("pub_builds", rows)

    assert [row["build_id"] for row in result.data] == [8, 3]
    assert result.data[0]["build_data"] == {"x_future": {"v": [None, 0, False]}}
    assert result.data[1]["local_extension"] == "kept"


def test_pro_response_can_contain_multiple_positions_and_other_draft_heroes() -> None:
    result, _, _ = _call_with_response(
        "pro_builds",
        [
            _pro_row(position="pos 1", recent_matches=[{"draft": [{"hero_id": 23}]}]),
            _pro_row(position="pos 2", recent_matches=None),
        ],
    )

    assert [row["position"] for row in result.data] == ["pos 1", "pos 2"]
    assert result.data[0]["recent_matches"] == [{"draft": [{"hero_id": 23}]}]
    assert result.data[1]["recent_matches"] is None


@pytest.mark.parametrize("method", ["pub_builds", "pro_builds"])
def test_empty_pub_and_pro_arrays_are_successful(method: str) -> None:
    result, _, response = _call_with_response(method, [])

    assert result.data == []
    assert response.closed


def test_heroes_list_accepts_unknown_fields_and_requires_unique_strict_ids() -> None:
    response = _json_response(
        [{"hero_id": 18, "name": None, "unknown": {"zero": 0}}, {"hero_id": 19}]
    )
    result = D2PTClient(opener=FakeOpener(response)).heroes_list()

    assert result.data[0]["unknown"] == {"zero": 0}
    assert result.data[0]["name"] is None


@pytest.mark.parametrize(
    "payload, reason",
    [
        ({"hero_id": 18}, "invalid_root"),
        ("[]", "invalid_root"),
        (None, "invalid_root"),
        ([None], "invalid_record"),
    ],
)
def test_non_array_roots_and_non_object_rows_fail(payload: object, reason: str) -> None:
    response = _json_response(payload)

    with pytest.raises(D2PTSchemaError) as exc_info:
        D2PTClient(opener=FakeOpener(response)).heroes_list()

    assert exc_info.value.reason == reason
    assert response.closed


@pytest.mark.parametrize("bad_id", [True, 18.0, "18", 0, -1])
def test_response_identity_hero_ids_must_be_strict_positive_integers(bad_id: object) -> None:
    response = _json_response([_pub_row(hero_id=bad_id)])

    with pytest.raises(D2PTSchemaError):
        D2PTClient(opener=FakeOpener(response)).pub_builds(18, 1)

    assert response.closed


def test_second_invalid_record_fails_the_whole_response() -> None:
    response = _json_response([_pub_row(), _pub_row(hero_id=99)])

    with pytest.raises(D2PTSchemaError) as exc_info:
        D2PTClient(opener=FakeOpener(response)).pub_builds(18, 1)

    assert exc_info.value.reason == "hero_mismatch"


def test_pub_position_and_build_data_are_checked_without_statistics_validation() -> None:
    for row, reason in (
        (_pub_row(position="pos 2"), "invalid_position"),
        (_pub_row(build_data=None), "invalid_build_data"),
        (_pub_row(build_data=[]), "invalid_build_data"),
        (_pub_row(build_data={"wins": -2, "win_rate": 100.2}), None),
    ):
        response = _json_response([row])
        if reason is None:
            result = D2PTClient(opener=FakeOpener(response)).pub_builds(18, 1)
            assert result.data[0]["build_data"] == {"wins": -2, "win_rate": 100.2}
        else:
            with pytest.raises(D2PTSchemaError) as exc_info:
                D2PTClient(opener=FakeOpener(response)).pub_builds(18, 1)
            assert exc_info.value.reason == reason
        assert response.closed


@pytest.mark.parametrize("position", ["pos 0", "pos 6", 1, None, [], {}])
def test_pro_rejects_invalid_position(position: object) -> None:
    response = _json_response([_pro_row(position=position)])
    opener = FakeOpener(response)

    with pytest.raises(D2PTSchemaError) as exc_info:
        D2PTClient(opener=opener).pro_builds(18)

    assert exc_info.value.reason == "invalid_position"
    assert response.closed
    assert len(opener.calls) == 1


@pytest.mark.parametrize("recent_matches", ["not-an-array", [None], [1]])
def test_pro_rejects_invalid_recent_matches_members(recent_matches: object) -> None:
    response = _json_response([_pro_row(recent_matches=recent_matches)])

    with pytest.raises(D2PTSchemaError) as exc_info:
        D2PTClient(opener=FakeOpener(response)).pro_builds(18)

    assert exc_info.value.reason == "invalid_recent_matches"


@pytest.mark.parametrize("recent_matches", [None, []])
def test_pro_accepts_null_or_empty_recent_matches(recent_matches: object) -> None:
    result, _, _ = _call_with_response(
        "pro_builds", [_pro_row(recent_matches=recent_matches)]
    )

    assert result.data[0]["recent_matches"] == recent_matches


@pytest.mark.parametrize(
    "payload, reason",
    [
        ([], "heroes_empty"),
        ([{"name": "Sven"}], "invalid_hero_id"),
        ([{"hero_id": True}], "invalid_hero_id"),
        ([{"hero_id": 18.0}], "invalid_hero_id"),
        ([{"hero_id": "18"}], "invalid_hero_id"),
        ([{"hero_id": 18}, {"hero_id": 18}], "duplicate_hero_id"),
    ],
)
def test_heroes_list_rejects_empty_missing_invalid_and_duplicate_ids(
    payload: object, reason: str
) -> None:
    response = _json_response(payload)

    with pytest.raises(D2PTSchemaError) as exc_info:
        D2PTClient(opener=FakeOpener(response)).heroes_list()

    assert exc_info.value.reason == reason


@pytest.mark.parametrize("status", [403, 429, 500])
def test_http_error_status_is_preserved_and_error_body_is_closed(status: int) -> None:
    headers = Message()
    headers["Retry-After"] = "17"
    error = urllib.error.HTTPError(
        "https://dota2protracker.com/safe-url",
        status,
        "upstream text must not escape",
        headers,
        BytesIO(b"private response body marker"),
    )
    opener = FakeOpener(error)

    with pytest.raises(D2PTHTTPError) as exc_info:
        D2PTClient(opener=opener).heroes_list()

    assert exc_info.value.status_code == status
    assert exc_info.value.retry_after == "17"
    assert error.fp is not None and error.fp.closed
    assert len(opener.calls) == 1
    assert "private response body marker" not in str(exc_info.value)
    assert "upstream text" not in repr(exc_info.value)


def test_http_error_without_retry_after_keeps_none_and_closes_body() -> None:
    error = urllib.error.HTTPError(
        "https://dota2protracker.com/safe-url", 403, "denied", Message(), BytesIO(b"body")
    )

    with pytest.raises(D2PTHTTPError) as exc_info:
        D2PTClient(opener=FakeOpener(error)).heroes_list()

    assert exc_info.value.retry_after is None
    assert error.fp is not None and error.fp.closed


def test_non_200_response_object_including_204_is_an_http_error_and_closed() -> None:
    response = FakeResponse(b"[]", status=204, headers={"Retry-After": "3"})

    with pytest.raises(D2PTHTTPError) as exc_info:
        D2PTClient(opener=FakeOpener(response)).heroes_list()

    assert exc_info.value.status_code == 204
    assert exc_info.value.retry_after == "3"
    assert response.read_sizes == []
    assert response.closed


@pytest.mark.parametrize(
    "error, expected_type",
    [
        (TimeoutError("timeout"), D2PTTimeoutError),
        (urllib.error.URLError(TimeoutError("nested timeout")), D2PTTimeoutError),
        (
            urllib.error.URLError(urllib.error.URLError(TimeoutError("deep timeout"))),
            D2PTTimeoutError,
        ),
        (urllib.error.URLError("dns failure"), D2PTTransportError),
        (OSError("connection reset"), D2PTTransportError),
    ],
)
def test_opener_transport_errors_are_sanitized_and_not_retried(
    error: BaseException, expected_type: type[Exception]
) -> None:
    opener = FakeOpener(error)

    with pytest.raises(expected_type) as exc_info:
        D2PTClient(opener=opener).heroes_list()

    assert len(opener.calls) == 1
    assert "dns failure" not in str(exc_info.value)
    assert "connection reset" not in str(exc_info.value)


def test_timeout_while_reading_closes_response() -> None:
    response = FakeResponse(read_error=TimeoutError("private timeout text"))

    with pytest.raises(D2PTTimeoutError) as exc_info:
        D2PTClient(opener=FakeOpener(response)).heroes_list()

    assert response.closed
    assert "private timeout text" not in str(exc_info.value)


@pytest.mark.parametrize(
    "body",
    [b"<html>blocked</html>", b"", b"\xff", b"{not-json}"],
)
def test_non_json_body_fails_with_fixed_error_and_closes(body: bytes) -> None:
    response = FakeResponse(body)

    with pytest.raises(D2PTJSONError):
        D2PTClient(opener=FakeOpener(response)).heroes_list()

    assert response.closed


@pytest.mark.parametrize(
    "body",
    [
        b'[{"v":NaN}]',
        b'[{"v":Infinity}]',
        b'[{"v":-Infinity}]',
        b'[{"v":1e999}]',
        b"NaN",
    ],
)
def test_non_finite_json_numbers_fail(body: bytes) -> None:
    response = FakeResponse(body)

    with pytest.raises(D2PTJSONError):
        D2PTClient(opener=FakeOpener(response)).heroes_list()

    assert response.closed


def test_utf8_bom_is_accepted_and_raw_body_is_unchanged() -> None:
    raw = b"\xef\xbb\xbf[{\"hero_id\":18}]"
    response = FakeResponse(raw)

    result = D2PTClient(opener=FakeOpener(response)).heroes_list()

    assert result.raw_body == raw
    assert result.data == [{"hero_id": 18}]


def test_response_body_is_read_only_to_limit_plus_one_then_rejected() -> None:
    response = FakeResponse(b"x" * (MAX_RESPONSE_BYTES + 2))

    with pytest.raises(D2PTResponseTooLargeError):
        D2PTClient(opener=FakeOpener(response)).heroes_list()

    assert response.read_sizes == [MAX_RESPONSE_BYTES + 1]
    assert response.closed


def test_missing_or_nonstandard_content_type_does_not_block_valid_json() -> None:
    response = FakeResponse(b"[]", headers={"Content-Type": "text/plain"})

    result = D2PTClient(opener=FakeOpener(response)).pub_builds(18, 1)

    assert result.data == []
    assert result.content_type == "text/plain"


def test_arbitrary_programming_errors_are_not_converted_to_transport_errors() -> None:
    opener = FakeOpener(RuntimeError("programming defect"))

    with pytest.raises(RuntimeError, match="programming defect"):
        D2PTClient(opener=opener).heroes_list()

    assert len(opener.calls) == 1


def test_response_repr_does_not_expand_raw_data_or_body_text() -> None:
    marker = "large-private-body-marker"
    response = _json_response([_pub_row(build_data={"text": marker})])
    result = D2PTClient(opener=FakeOpener(response)).pub_builds(18, 1)

    assert marker not in repr(result)
    assert "raw_body=<" in repr(result)
