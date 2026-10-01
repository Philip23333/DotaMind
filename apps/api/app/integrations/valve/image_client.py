"""Bounded, single-attempt downloads of Valve Dota 2 catalog PNGs."""

from __future__ import annotations

import re
import urllib.request
from collections.abc import Callable
from typing import Any, Literal
from urllib.error import HTTPError

VALVE_IMAGE_ROOT = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ImageKind = Literal["heroes", "items", "abilities"]

_IMAGE_PREFIXES: dict[ImageKind, str] = {
    "heroes": "npc_dota_hero_",
    "items": "item_",
    "abilities": "",
}


class ValveImageError(RuntimeError):
    """A safe image-download error with a stable reason code."""

    def __init__(
        self,
        reason: Literal["download_failed", "image_too_large", "invalid_image", "invalid_target"],
    ) -> None:
        messages = {
            "download_failed": "Valve image download failed",
            "image_too_large": "Valve image exceeds the size limit",
            "invalid_image": "Valve image is not a valid PNG response",
            "invalid_target": "Valve image target is invalid",
        }
        self.reason = reason
        super().__init__(messages[reason])


def image_asset_slug(internal_name: str, prefix: str) -> str:
    """Validate one Valve internal name and remove its kind-specific prefix."""

    if not isinstance(internal_name, str):
        raise ValueError("invalid image asset name")
    slug = internal_name.removeprefix(prefix)
    if not slug or re.fullmatch(r"[a-z0-9_]+", slug) is None:
        raise ValueError("invalid image asset name")
    return slug


def build_image_url(
    kind: ImageKind,
    internal_name: str,
    *,
    image_root: str = VALVE_IMAGE_ROOT,
) -> str:
    """Build the fixed Valve CDN URL for a validated catalog entity."""

    prefix = _IMAGE_PREFIXES.get(kind)
    if prefix is None:
        raise ValveImageError("invalid_target")
    slug = image_asset_slug(internal_name, prefix)
    filename = internal_name if kind == "abilities" else slug
    return f"{image_root}/{kind}/{filename}.png"


class ValveImageClient:
    """Fetch raw PNG bytes from the fixed Valve CDN with an injectable opener."""

    def __init__(
        self,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self._opener = urllib.request.urlopen if opener is None else opener

    def fetch_png(self, kind: ImageKind, internal_name: str) -> bytes:
        try:
            url = build_image_url(kind, internal_name)
        except (TypeError, ValueError, ValveImageError):
            raise ValveImageError("invalid_target") from None

        request = urllib.request.Request(
            url,
            headers={"User-Agent": "DotaMind catalog sync"},
        )
        response: Any | None = None
        failure: ValveImageError | None = None
        payload: object = b""
        try:
            response = self._opener(request, timeout=30)
            if getattr(response, "status", 200) != 200:
                failure = ValveImageError("download_failed")
            else:
                payload = response.read(MAX_IMAGE_BYTES + 1)
        except HTTPError as exc:
            response = exc
            failure = ValveImageError("download_failed")
        except Exception:
            failure = ValveImageError("download_failed")
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    failure = ValveImageError("download_failed")

        if failure is not None:
            raise failure from None
        if not isinstance(payload, bytes):
            raise ValveImageError("invalid_image")
        if len(payload) > MAX_IMAGE_BYTES:
            raise ValveImageError("image_too_large")
        if not payload.startswith(PNG_SIGNATURE):
            raise ValveImageError("invalid_image")
        return payload


__all__ = [
    "ImageKind",
    "MAX_IMAGE_BYTES",
    "PNG_SIGNATURE",
    "VALVE_IMAGE_ROOT",
    "ValveImageClient",
    "ValveImageError",
    "build_image_url",
    "image_asset_slug",
]
