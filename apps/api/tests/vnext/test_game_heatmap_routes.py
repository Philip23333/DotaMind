"""Opaque references can read images, never trigger a remote generation."""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.game_heatmap_routes import router


def test_image_route_requires_a_valid_returned_reference():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    calls = []

    def read(token, slot, time):
        calls.append((token, slot, time))
        return b"\x89PNG\r\n\x1a\n" if token == "a" * 32 and slot == 0 and time == 300 else None

    app.state.vnext_services = SimpleNamespace(game_heatmaps=SimpleNamespace(read_image=read))
    client = TestClient(app)
    response = client.get("/api/v1/game/heatmaps/assets/" + "a" * 32 + "/0/300.png")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-store"
    assert client.get("/api/v1/game/heatmaps/assets/bad/0/300.png").status_code == 404
    assert len(calls) == 2


def test_absent_heatmap_service_is_404():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    assert TestClient(app).get("/api/v1/game/heatmaps/assets/bad/0/300.png").status_code == 404
