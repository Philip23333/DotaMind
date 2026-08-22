from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agentic.tools.pandascore_tools import _fixture_data
from app.integrations.pandascore.competitions import PandaScoreCompetitions
from app.integrations.pandascore.models import PandaMatchFixture, PandaScoreTeam
from app.integrations.pandascore.team_asset_repository import PandaScoreTeamAssetRepository
from app.integrations.pandascore.teams import PandaScoreTeams, normalize_team
from scripts import sync_pandascore_team_assets


@pytest.mark.anyio
async def test_recent_series_selection_uses_descending_start_time() -> None:
    class FakeTransport:
        max_page_size = 100
        calls: list[dict[str, object]] = []

        async def get(self, path, *, params=None, cache_ttl_seconds=None):
            self.calls.append(
                {"path": path, "params": params, "cache_ttl_seconds": cache_ttl_seconds}
            )
            return [{"id": 3}, {"id": "2"}, {"id": 3}, {"id": None}]

    transport = FakeTransport()
    series_ids = await PandaScoreCompetitions(transport).list_recent_series_ids(limit=10)

    assert series_ids == [3, 2]
    assert [call["params"] for call in transport.calls] == [
        {"sort": "-begin_at", "page[size]": 10},
    ]


def test_fixture_team_extraction_deduplicates_referenced_teams() -> None:
    fixtures = [
        PandaMatchFixture(
            pandascore_match_id=10,
            pandascore_series_id=20,
            name="Alpha vs Beta",
            status="finished",
            opponents=[
                {"opponent": {"id": 1, "name": "Alpha", "image_url": "https://cdn.pandascore.co/1.png"}},
                {"opponent": {"id": 2, "name": "Beta"}},
            ],
        ),
        PandaMatchFixture(
            pandascore_match_id=11,
            pandascore_series_id=21,
            name="Alpha vs Gamma",
            status="finished",
            opponents=[
                {"opponent": {"id": 1, "name": "Alpha Renamed"}},
                {"opponent": {"id": 3, "name": "Gamma", "acronym": "G"}},
            ],
        ),
    ]

    teams = PandaScoreTeams.from_fixtures(fixtures)

    assert teams == [
        PandaScoreTeam(
            pandascore_team_id=1,
            name="Alpha",
            image_url="https://cdn.pandascore.co/1.png",
        ),
        PandaScoreTeam(pandascore_team_id=2, name="Beta"),
        PandaScoreTeam(pandascore_team_id=3, name="Gamma", acronym="G"),
    ]


def test_team_normalization_keeps_only_declared_fields() -> None:
    team = normalize_team(
        {
            "id": "7",
            "name": " Team Seven ",
            "acronym": " T7 ",
            "image_url": " https://cdn.pandascore.co/7.webp ",
            "location": "ignored",
        }
    )
    assert team == PandaScoreTeam(
        pandascore_team_id=7,
        name="Team Seven",
        acronym="T7",
        image_url="https://cdn.pandascore.co/7.webp",
    )
    assert normalize_team({"id": 8, "name": ""}) is None


def test_team_asset_repository_is_read_only_and_missing_data_is_non_blocking(
    tmp_path: Path,
) -> None:
    root = tmp_path / "teams"
    root.mkdir()
    (root / "1.webp").write_bytes(b"webp")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "teams": [
                    {
                        "pandascore_team_id": 1,
                        "image_path": "/api/v1/assets/esports/teams/1.webp",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    repository = PandaScoreTeamAssetRepository(root)

    assert repository.image_path(1) == "/api/v1/assets/esports/teams/1.webp"
    assert repository.image_path(2) is None
    (root / "manifest.json").write_text("not json", encoding="utf-8")
    assert repository.image_path(1) is None


def test_pandascore_fixture_projection_adds_only_local_team_logo(tmp_path: Path) -> None:
    root = tmp_path / "teams"
    root.mkdir()
    (root / "1.png").write_bytes(b"png")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "teams": [
                    {
                        "pandascore_team_id": 1,
                        "image_path": "/api/v1/assets/esports/teams/1.png",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    fixture = PandaMatchFixture(
        pandascore_match_id=10,
        pandascore_series_id=20,
        name="Alpha vs Beta",
        status="finished",
        opponents=[
            {
                "opponent": {
                    "id": 1,
                    "name": "Alpha",
                    "image_url": "https://cdn.pandascore.co/1.png",
                }
            },
            {
                "opponent": {
                    "id": 2,
                    "name": "Beta",
                    "image_url": "https://cdn.pandascore.co/2.png",
                }
            },
        ],
    )

    data = _fixture_data(fixture, PandaScoreTeamAssetRepository(root))

    assert data["opponents"][0]["opponent"]["team_image_path"] == (
        "/api/v1/assets/esports/teams/1.png"
    )
    assert "image_url" not in data["opponents"][0]["opponent"]
    assert "team_image_path" not in data["opponents"][1]["opponent"]
    assert "image_url" not in data["opponents"][1]["opponent"]
    assert "image_url" not in _fixture_data(fixture)["opponents"][0]["opponent"]
    assert data["opponents"][0]["opponent"]["id"] == 1


@pytest.mark.anyio
async def test_team_snapshot_skips_bad_logos_and_replaces_atomically(
    tmp_path: Path, monkeypatch
) -> None:
    esports_root = tmp_path / "esports"
    team_root = esports_root / "teams"
    team_root.mkdir(parents=True)
    (team_root / "1.png").write_bytes(b"old")
    (team_root / "manifest.json").write_text(
        json.dumps(
            {
                "teams": [
                    {
                        "pandascore_team_id": 1,
                        "source_url": "https://cdn.pandascore.co/1.png",
                        "image_path": "/api/v1/assets/esports/teams/1.png",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sync_pandascore_team_assets, "ESPORTS_OUTPUT_DIR", esports_root)
    monkeypatch.setattr(sync_pandascore_team_assets, "TEAM_OUTPUT_DIR", team_root)
    monkeypatch.setattr(
        sync_pandascore_team_assets,
        "TEAM_MANIFEST_OUTPUT",
        team_root / "manifest.json",
    )

    class FakeTeams:
        async def download_image(self, image_url):
            if image_url.endswith("/3.png"):
                raise RuntimeError("download failed")
            return b"new", ".webp"

    teams = [
        PandaScoreTeam(pandascore_team_id=1, name="Reused", image_url="https://cdn.pandascore.co/1.png"),
        PandaScoreTeam(pandascore_team_id=2, name="Downloaded", image_url="https://cdn.pandascore.co/2.png"),
        PandaScoreTeam(pandascore_team_id=3, name="Failed", image_url="https://cdn.pandascore.co/3.png"),
        PandaScoreTeam(pandascore_team_id=4, name="No Logo"),
    ]

    staging, manifest = await sync_pandascore_team_assets._build_staging_snapshot(
        FakeTeams(), teams, workers=2, force=False, series_ids=[20, 21]
    )
    assert manifest["skipped_no_logo"] == 1
    assert manifest["download_failures"] == 1
    assert manifest["series_ids"] == [20, 21]
    assert {item["pandascore_team_id"] for item in manifest["teams"]} == {1, 2}
    assert (staging / "1.png").read_bytes() == b"old"
    assert (staging / "2.webp").read_bytes() == b"new"

    (staging / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    sync_pandascore_team_assets._replace_team_assets(staging)
    assert (team_root / "manifest.json").is_file()
    assert (team_root / "1.png").read_bytes() == b"old"
    assert (team_root / "2.webp").read_bytes() == b"new"


def test_team_logo_url_validation_is_strict() -> None:
    assert sync_pandascore_team_assets._valid_image_url("https://cdn.pandascore.co/logo.png")
    assert not sync_pandascore_team_assets._valid_image_url("http://cdn.pandascore.co/logo.png")
    assert not sync_pandascore_team_assets._valid_image_url("https://example.com/logo.png")
    assert not sync_pandascore_team_assets._valid_image_url("https://pandascore.co/logo.png")
