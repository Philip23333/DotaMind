"""Read-only routes for immutable, content-addressed Valve images."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response

from app.integrations.valve.image_client import MAX_IMAGE_BYTES, PNG_SIGNATURE

router = APIRouter()
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_CACHE_CONTROL = "public, max-age=31536000, immutable"


@router.get("/assets/dota/by-hash/{content_sha256}.png", include_in_schema=False)
def read_persistent_dota_image(content_sha256: str, request: Request) -> Response:
    data_root = getattr(request.app.state, "persistent_image_data_root", None)
    if not isinstance(data_root, Path) or _HASH_PATTERN.fullmatch(content_sha256) is None:
        raise HTTPException(status_code=404)

    data_root = data_root.resolve()
    images_directory = data_root / "images"
    assets_directory = images_directory / "assets"
    path = assets_directory / f"{content_sha256}.png"
    try:
        if images_directory.is_symlink() or assets_directory.is_symlink():
            raise OSError
        with open(path, "rb", opener=_open_asset_without_symlinks) as image_file:
            payload = image_file.read(MAX_IMAGE_BYTES + 1)
    except OSError:
        raise HTTPException(status_code=404) from None

    if (
        len(payload) > MAX_IMAGE_BYTES
        or len(payload) <= len(PNG_SIGNATURE)
        or not payload.startswith(PNG_SIGNATURE)
        or hashlib.sha256(payload).hexdigest() != content_sha256
    ):
        raise HTTPException(status_code=404)

    return Response(
        content=payload,
        media_type="image/png",
        headers={"Cache-Control": _CACHE_CONTROL},
    )


def _open_asset_without_symlinks(path: str, flags: int) -> int:
    return os.open(path, flags | getattr(os, "O_NOFOLLOW", 0))
