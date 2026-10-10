from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.integrations.valve.catalog_repository import load_default_catalog_repository
from app.main import app
from app.vnext.data_updates.team_directory_store import (
    TeamDirectoryStore,
    TeamDisplayRecord,
)
from app.vnext.entity_display import EntityDisplayDirectory


def _install_services(monkeypatch, directory: EntityDisplayDirectory) -> SimpleNamespace:
    services = SimpleNamespace(entity_display_directory=directory)
    monkeypatch.setattr(app.state, "vnext_services", services, raising=False)
    return services


def _publish_team(
    data_root: Path,
    *,
    label: str,
    image: bytes | None = None,
) -> str | None:
    content_hash = hashlib.sha256(image).hexdigest() if image is not None else None
    if content_hash is not None:
        assets = data_root / "images" / "assets"
        assets.mkdir(parents=True, exist_ok=True)
        (assets / f"{content_hash}.png").write_bytes(image)
    TeamDirectoryStore(data_root).publish(
        {
            1669: TeamDisplayRecord(
                source_id=1669,
                label=label,
                observed_image_url="https://cdn.example.invalid/team.png",
                downloaded_image_url=(
                    "https://cdn.example.invalid/team.png"
                    if content_hash is not None
                    else None
                ),
                image_asset=content_hash,
                image_downloaded_at="2026-10-10T00:00:00Z"
                if content_hash is not None
                else None,
            )
        }
    )
    return content_hash


def test_batch_resolves_explicit_mixed_refs_and_omits_unknown_or_invalid(
    tmp_path: Path, monkeypatch
) -> None:
    repository = load_default_catalog_repository()
    hero_id = repository.list_heroes()[0].hero_id
    item_id = repository.list_items()[0].item_id
    ability_id = repository.list_abilities()[0].ability_id
    _publish_team(tmp_path, label="Team Spirit")
    directory = EntityDisplayDirectory(lambda: repository, data_root=tmp_path)
    _install_services(monkeypatch, directory)

    refs = [
        f"display:valve:hero:{hero_id}",
        f"display:valve:item:{item_id}",
        f"display:valve:ability:{ability_id}",
        "display:pandascore:team:1669",
        f"display:valve:hero:{hero_id}",
        "display:valve:hero:2147483647",
        "not-a-display-reference",
    ]
    response = TestClient(app).post("/api/v1/display/resolve", json={"refs": refs})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    entities = response.json()["entities"]
    expected_refs = set(refs[:4])
    assert set(entities) == expected_refs
    assert entities[f"display:valve:hero:{hero_id}"]["kind"] == "hero"
    assert entities[f"display:valve:item:{item_id}"]["kind"] == "item"
    assert entities[f"display:valve:ability:{ability_id}"]["kind"] == "ability"
    assert entities["display:pandascore:team:1669"] == {
        "display_ref": "display:pandascore:team:1669",
        "kind": "team",
        "label": "Team Spirit",
        "image_url": None,
    }


def test_directory_replacement_is_visible_on_next_request_and_uses_local_asset(
    tmp_path: Path, monkeypatch
) -> None:
    repository = load_default_catalog_repository()
    directory = EntityDisplayDirectory(lambda: repository, data_root=tmp_path)
    services = _install_services(monkeypatch, directory)
    first_hash = _publish_team(tmp_path, label="Old Team", image=b"first-local-image")

    client = TestClient(app)
    first = client.post(
        "/api/v1/display/resolve",
        json={"refs": ["display:pandascore:team:1669"]},
    )
    second_hash = _publish_team(
        tmp_path,
        label="Current Team",
        image=b"second-local-image",
    )
    second = client.post(
        "/api/v1/display/resolve",
        json={"refs": ["display:pandascore:team:1669"]},
    )

    assert app.state.vnext_services is services
    assert first.status_code == second.status_code == 200
    assert first.json()["entities"]["display:pandascore:team:1669"]["label"] == (
        "Old Team"
    )
    current = second.json()["entities"]["display:pandascore:team:1669"]
    assert current["label"] == "Current Team"
    assert current["image_url"] == f"/api/v1/assets/dota/by-hash/{second_hash}.png"
    assert first_hash != second_hash
    assert "cdn.example.invalid" not in second.text


def test_empty_batch_and_no_data_root_keep_valve_but_not_team(
    monkeypatch,
) -> None:
    repository = load_default_catalog_repository()
    directory = EntityDisplayDirectory(lambda: repository)
    _install_services(monkeypatch, directory)
    client = TestClient(app)

    empty = client.post("/api/v1/display/resolve", json={"refs": []})
    valve = client.post(
        "/api/v1/display/resolve",
        json={
            "refs": [
                "display:valve:hero:1",
                "display:pandascore:team:1669",
            ]
        },
    )

    assert empty.status_code == 200
    assert empty.json() == {"entities": {}}
    assert valve.status_code == 200
    assert set(valve.json()["entities"]) == {"display:valve:hero:1"}


@pytest.mark.parametrize(
    "body",
    [
        {"refs": [1]},
        {"refs": "display:valve:hero:1"},
        {"refs": ["x" * 129]},
        {"refs": ["display:valve:hero:1"] * 101},
        {"refs": [], "extra": True},
        {},
    ],
)
def test_invalid_request_shape_or_limits_return_422(body, monkeypatch) -> None:
    repository = load_default_catalog_repository()
    _install_services(monkeypatch, EntityDisplayDirectory(lambda: repository))

    response = TestClient(app).post("/api/v1/display/resolve", json=body)

    assert response.status_code == 422


def test_missing_directory_returns_stable_503_and_no_store(monkeypatch) -> None:
    monkeypatch.setattr(
        app.state,
        "vnext_services",
        SimpleNamespace(entity_display_directory=None),
        raising=False,
    )

    response = TestClient(app).post(
        "/api/v1/display/resolve",
        json={"refs": ["display:valve:hero:1"]},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"code": "entity_display_unavailable"}
    }
    assert response.headers["cache-control"] == "no-store"


def test_main_registers_batch_display_resolution_route() -> None:
    assert "/api/v1/display/resolve" in app.openapi()["paths"]
