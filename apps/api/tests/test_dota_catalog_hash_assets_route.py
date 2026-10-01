from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.persistent_image_routes import router
from app.integrations.valve.image_client import MAX_IMAGE_BYTES

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZAAAAABJRU5ErkJggg=="
)


def _client(data_root: Path | None) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    if data_root is not None:
        app.state.persistent_image_data_root = data_root
    return TestClient(app)


def _store_asset(data_root: Path, payload: bytes, *, name_hash: str | None = None) -> str:
    content_hash = hashlib.sha256(payload).hexdigest()
    path_hash = content_hash if name_hash is None else name_hash
    path = data_root / "images" / "assets" / f"{path_hash}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path_hash


def _url(content_hash: str) -> str:
    return f"/api/v1/assets/dota/by-hash/{content_hash}.png"


def test_hash_route_returns_verified_bytes_and_immutable_cache_headers(tmp_path: Path) -> None:
    content_hash = _store_asset(tmp_path, _PNG)

    response = _client(tmp_path).get(_url(content_hash))

    assert response.status_code == 200
    assert response.content == _PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_hash_route_returns_404_without_long_cache_headers(tmp_path: Path) -> None:
    response = _client(tmp_path).get(_url("a" * 64))

    assert response.status_code == 404
    assert "cache-control" not in response.headers


def test_hash_route_requires_configured_data_directory() -> None:
    response = _client(None).get(_url("a" * 64))

    assert response.status_code == 404


def test_hash_route_rejects_invalid_hash_and_corrupt_assets(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get(_url("A" * 64)).status_code == 404
    assert client.get(_url("../" + "a" * 64)).status_code == 404

    invalid_signature_hash = _store_asset(tmp_path, b"not a png")
    assert client.get(_url(invalid_signature_hash)).status_code == 404

    mismatched_hash = _store_asset(tmp_path, _PNG, name_hash="0" * 64)
    assert client.get(_url(mismatched_hash)).status_code == 404


def test_hash_route_rejects_oversized_assets(tmp_path: Path) -> None:
    payload = _PNG + b"x" * (MAX_IMAGE_BYTES + 1)
    content_hash = _store_asset(tmp_path, payload)

    response = _client(tmp_path).get(_url(content_hash))

    assert response.status_code == 404
    assert "cache-control" not in response.headers


def test_hash_route_rejects_asset_symlink_outside_data_directory(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.png"
    outside.write_bytes(_PNG)
    content_hash = hashlib.sha256(_PNG).hexdigest()
    assets = tmp_path / "images" / "assets"
    assets.mkdir(parents=True)
    try:
        os.symlink(outside, assets / f"{content_hash}.png")
    except OSError:
        outside.unlink(missing_ok=True)
        pytest.skip("symlink creation is unavailable")

    response = _client(tmp_path).get(_url(content_hash))

    assert response.status_code == 404
    outside.unlink(missing_ok=True)


def test_historical_hash_remains_readable_after_manifest_switch(tmp_path: Path) -> None:
    old_hash = _store_asset(tmp_path, _PNG)
    new_payload = _PNG + b"new"
    new_hash = _store_asset(tmp_path, new_payload)
    manifest = tmp_path / "images" / "manifest.json"
    manifest.write_text(
        json.dumps({"schema_version": 1, "entries": {"heroes:18": {"content_sha256": new_hash}}}),
        encoding="utf-8",
    )
    client = _client(tmp_path)

    old_response = client.get(_url(old_hash))
    new_response = client.get(_url(new_hash))

    assert old_response.status_code == new_response.status_code == 200
    assert old_response.content == _PNG
    assert new_response.content == new_payload


def test_main_registers_hash_route_before_static_asset_mount() -> None:
    from app.main import app

    routes = list(app.router.routes)
    hash_route_index = next(
        index
        for index, route in enumerate(routes)
        if any(
            child.path == "/assets/dota/by-hash/{content_sha256}.png"
            for child in getattr(getattr(route, "original_router", None), "routes", ())
        )
    )
    static_mount_index = next(
        index
        for index, route in enumerate(routes)
        if getattr(route, "path", None) == "/api/v1/assets/dota"
    )
    assert hash_route_index < static_mount_index


def test_main_hash_route_serves_file_in_persistent_data_mode(tmp_path: Path) -> None:
    from app.main import app

    content_hash = _store_asset(tmp_path, _PNG)
    was_set = hasattr(app.state, "persistent_image_data_root")
    previous_root = getattr(app.state, "persistent_image_data_root", None)
    app.state.persistent_image_data_root = tmp_path

    async def request_image() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get(_url(content_hash))

    try:
        response = asyncio.run(request_image())
    finally:
        if was_set:
            app.state.persistent_image_data_root = previous_root
        else:
            delattr(app.state, "persistent_image_data_root")

    assert response.status_code == 200
    assert response.content == _PNG
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
