"""Sanitized failure types for the D2PT source client."""

from __future__ import annotations


class D2PTError(RuntimeError):
    """Base class for D2PT failures with a stable public code."""

    code = "d2pt_error"


class D2PTTimeoutError(D2PTError):
    code = "timeout"

    def __init__(self) -> None:
        super().__init__("D2PT request timed out")


class D2PTTransportError(D2PTError):
    code = "transport_error"

    def __init__(self) -> None:
        super().__init__("D2PT transport request failed")


class D2PTHTTPError(D2PTError):
    code = "http_error"

    def __init__(self, status_code: int, retry_after: str | None = None) -> None:
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__("D2PT request failed with an HTTP status")


class D2PTResponseTooLargeError(D2PTError):
    code = "response_too_large"

    def __init__(self) -> None:
        super().__init__("D2PT response exceeded the size limit")


class D2PTJSONError(D2PTError):
    code = "invalid_json"

    def __init__(self) -> None:
        super().__init__("D2PT response was not valid finite UTF-8 JSON")


class D2PTSchemaError(D2PTError):
    code = "invalid_response"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("D2PT response structure was invalid")


class D2PTParseError(D2PTError):
    """A source record could not be projected into the guide DTO contract."""

    code = "invalid_guide_data"
    _REASONS = {
        "invalid_structure",
        "invalid_value",
        "hero_mismatch",
        "position_mismatch",
    }

    def __init__(self, reason: str, source_path: str) -> None:
        if reason not in self._REASONS:
            raise ValueError("unsupported D2PT parse error reason")
        self.reason = reason
        self.source_path = source_path
        super().__init__(f"D2PT guide data invalid ({reason}) at {source_path}")


__all__ = [
    "D2PTError",
    "D2PTHTTPError",
    "D2PTJSONError",
    "D2PTParseError",
    "D2PTSchemaError",
    "D2PTTimeoutError",
    "D2PTTransportError",
    "D2PTResponseTooLargeError",
]
