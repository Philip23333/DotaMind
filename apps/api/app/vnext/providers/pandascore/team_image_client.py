"""Bounded one-shot downloader for public PandaScore Team PNG assets."""

from __future__ import annotations

import math
import urllib.request
from collections.abc import Callable
from typing import Any, Literal
from urllib.error import HTTPError
from urllib.parse import urlsplit

from app.integrations.valve.image_client import MAX_IMAGE_BYTES, PNG_SIGNATURE

TeamImageErrorReason = Literal[
    "download_failed",
    "image_too_large",
    "invalid_image",
    "invalid_url",
]


class TeamImageError(RuntimeError):
    """A safe Team image download error without source URL details."""

    _MESSAGES = {
        "download_failed": "Team image download failed",
        "image_too_large": "Team image exceeds the size limit",
        "invalid_image": "Team image is not a valid PNG response",
        "invalid_url": "Team image URL is invalid",
    }

    def __init__(self, reason: TeamImageErrorReason) -> None:
        self.reason = reason
        super().__init__(self._MESSAGES[reason])


class PandaScoreTeamImageClient:
    """Fetch one bounded PNG without forwarding the PandaScore API token."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise ValueError("timeout_seconds must be finite and positive")
        try:
            normalized_timeout = float(timeout_seconds)
        except (OverflowError, ValueError):
            raise ValueError("timeout_seconds must be finite and positive") from None
        if not math.isfinite(normalized_timeout) or normalized_timeout <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        self._opener = urllib.request.urlopen if opener is None else opener
        self._timeout_seconds = normalized_timeout

    def fetch_png(self, url: str) -> bytes:
        if not isinstance(url, str):
            raise TeamImageError("invalid_url")
        try:
            parsed = urlsplit(url)
        except ValueError:
            raise TeamImageError("invalid_url") from None
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise TeamImageError("invalid_url")

        request = urllib.request.Request(
            url,
            headers={"User-Agent": "DotaMind team display refresh"},
        )
        response: Any | None = None
        failure: TeamImageError | None = None
        payload: object = b""
        try:
            response = self._opener(request, timeout=self._timeout_seconds)
            if getattr(response, "status", 200) != 200:
                failure = TeamImageError("download_failed")
            else:
                payload = response.read(MAX_IMAGE_BYTES + 1)
        except HTTPError as exc:
            response = exc
            failure = TeamImageError("download_failed")
        except Exception:
            failure = TeamImageError("download_failed")
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    failure = TeamImageError("download_failed")

        if failure is not None:
            raise failure from None
        if not isinstance(payload, bytes):
            raise TeamImageError("invalid_image")
        if len(payload) > MAX_IMAGE_BYTES:
            raise TeamImageError("image_too_large")
        if not payload.startswith(PNG_SIGNATURE):
            raise TeamImageError("invalid_image")
        return payload


__all__ = ["PandaScoreTeamImageClient", "TeamImageError", "TeamImageErrorReason"]
