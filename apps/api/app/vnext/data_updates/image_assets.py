"""Shared helpers for validated, content-addressed local PNG assets."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from app.integrations.valve.image_client import MAX_IMAGE_BYTES, PNG_SIGNATURE


class ImageAssetError(RuntimeError):
    """A safe local image-asset validation or storage failure."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def is_png_payload(payload: object) -> bool:
    return (
        isinstance(payload, bytes)
        and 0 < len(payload) <= MAX_IMAGE_BYTES
        and payload.startswith(PNG_SIGNATURE)
    )


def content_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def content_asset_is_valid(assets_directory: Path, content_hash: str) -> bool:
    path = Path(assets_directory) / f"{content_hash}.png"
    try:
        payload = path.read_bytes()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ImageAssetError("storage_error") from exc
    return is_png_payload(payload) and content_sha256(payload) == content_hash


def store_content_addressed_png(
    assets_directory: Path,
    payload: bytes,
    *,
    expected_hash: str | None = None,
    atomic_writer: Callable[[Path, bytes], None] | None = None,
) -> str:
    if not is_png_payload(payload):
        raise ImageAssetError("invalid_image")
    content_hash = content_sha256(payload)
    if expected_hash is not None and content_hash != expected_hash:
        raise ImageAssetError("invalid_hash")

    directory = Path(assets_directory)
    path = directory / f"{content_hash}.png"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if content_asset_is_valid(directory, content_hash):
            return content_hash
        writer = atomic_write if atomic_writer is None else atomic_writer
        writer(path, payload)
    except ImageAssetError:
        raise
    except OSError as exc:
        raise ImageAssetError("storage_error") from exc
    return content_hash


def atomic_write(path: Path, content: bytes) -> None:
    descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as temporary_file:
            descriptor = None
            temporary_file.write(content)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink()


__all__ = [
    "ImageAssetError",
    "atomic_write",
    "content_asset_is_valid",
    "content_sha256",
    "is_png_payload",
    "store_content_addressed_png",
]
