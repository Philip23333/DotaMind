from __future__ import annotations

import asyncio
import hashlib
import threading
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.integrations.valve.catalog_repository import load_default_catalog_repository
from app.integrations.valve.image_client import PNG_SIGNATURE
from app.vnext.data_updates.image_assets import store_content_addressed_png
from app.vnext.data_updates.team_directory_store import (
    TeamDirectoryStore,
    TeamDirectoryStoreError,
    TeamDisplayRecord,
)
from app.vnext.data_updates.team_refresh import refresh_team_directory
from app.vnext.entity_display import EntityDisplayDirectory
from app.vnext.providers.pandascore.client import PandaScoreClient
from app.vnext.providers.pandascore.team_directory import (
    PandaScoreTeamDirectoryReader,
    PandaScoreTeamMetadata,
)
from app.vnext.providers.pandascore.team_image_client import TeamImageError

_PNG_A = PNG_SIGNATURE + b"asset-a"
_PNG_B = PNG_SIGNATURE + b"asset-b"
_NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


class FakeMetadataReader:
    def __init__(self, teams: list[PandaScoreTeamMetadata]) -> None:
        self.teams = teams
        self.calls = 0

    async def read_all(self) -> list[PandaScoreTeamMetadata]:
        self.calls += 1
        return self.teams


class FakeImageClient:
    def __init__(self, outcomes: dict[str, bytes | Exception] | None = None) -> None:
        self.outcomes = {} if outcomes is None else dict(outcomes)
        self.calls: list[str] = []
        self.lock = threading.Lock()

    def fetch_png(self, url: str) -> bytes:
        with self.lock:
            self.calls.append(url)
        outcome = self.outcomes.get(url, _PNG_A)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _team(team_id: int, url: str | None) -> PandaScoreTeamMetadata:
    return PandaScoreTeamMetadata(source_id=team_id, label=f"Team {team_id}", image_url=url)


def _stored_record(
    root: Path,
    team_id: int,
    *,
    url: str,
    payload: bytes | None = None,
    month: str = "2026-10",
) -> TeamDisplayRecord:
    asset_payload = payload if payload is not None else PNG_SIGNATURE + f"asset-{team_id}".encode()
    digest = store_content_addressed_png(root / "images" / "assets", asset_payload)
    return TeamDisplayRecord(
        source_id=team_id,
        label=f"Old Team {team_id}",
        observed_image_url=url,
        downloaded_image_url=url,
        image_asset=digest,
        image_downloaded_at="2026-10-01T00:00:00Z",
        monthly_refresh_completed=month,
    )


def _seed(root: Path, records: dict[int, TeamDisplayRecord]) -> bytes:
    store = TeamDirectoryStore(root)
    store.publish(records)
    return store.path.read_bytes()


def test_later_page_failure_does_not_download_or_publish(tmp_path: Path) -> None:
    root = tmp_path / "data"
    original = _seed(root, {900: TeamDisplayRecord(900, "Old")})
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        calls.append(page)
        if page == "1":
            rows = [
                {"id": team_id, "name": f"Team {team_id}", "image_url": "https://img.test/a.png"}
                for team_id in range(1, 101)
            ]
            return httpx.Response(200, json=rows, request=request)
        return httpx.Response(503, json={"error": "upstream"}, request=request)

    client = PandaScoreClient(
        base_url="https://api.pandascore.test",
        token="offline-test-token",
        transport=httpx.MockTransport(handler),
    )
    images = FakeImageClient()

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(
            refresh_team_directory(
                data_root=root,
                metadata_reader=PandaScoreTeamDirectoryReader(client),
                image_client=images,
                clock=lambda: _NOW,
            )
        )

    assert calls == ["1", "2"]
    assert images.calls == []
    assert TeamDirectoryStore(root).path.read_bytes() == original


def test_historical_identity_map_imports_assets_and_directory_reads_them(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    images = FakeImageClient()
    report = asyncio.run(
        refresh_team_directory(
            data_root=root,
            metadata_reader=FakeMetadataReader([]),
            image_client=images,
            clock=lambda: _NOW,
        )
    )

    snapshot = TeamDirectoryStore(root).read_current()
    assert report.migrated_records == 60
    assert report.observed_team_count == 0
    assert report.downloaded == 0
    assert images.calls == []
    assert len(snapshot.teams) == 60
    team = snapshot.teams[1647]
    assert team.label == "Team Liquid"
    assert team.image_downloaded_at is None
    assert team.monthly_refresh_completed is None
    assert team.image_asset is not None
    assert snapshot.image_url(team) == f"/api/v1/assets/dota/by-hash/{team.image_asset}.png"

    directory = EntityDisplayDirectory(
        lambda: load_default_catalog_repository(),
        data_root=root,
    )
    resolved = directory.resolve_many(["display:pandascore:team:1647"])
    assert resolved["display:pandascore:team:1647"].label == "Team Liquid"
    assert resolved["display:pandascore:team:1647"].image_url == snapshot.image_url(team)


def test_failed_changed_url_retains_old_asset_and_next_run_retries(tmp_path: Path) -> None:
    root = tmp_path / "data"
    old_url = "https://cdn.test/old.png"
    new_url = "https://cdn.test/new.png"
    old_record = _stored_record(root, 101, url=old_url)
    _seed(root, {101: old_record})
    failed = FakeImageClient({new_url: TeamImageError("download_failed")})

    first = asyncio.run(
        refresh_team_directory(
            data_root=root,
            metadata_reader=FakeMetadataReader([_team(101, new_url)]),
            image_client=failed,
            clock=lambda: _NOW,
        )
    )
    after_failure = TeamDirectoryStore(root).read_current().teams[101]
    assert first.failures[0].error_code == "download_failed"
    assert after_failure.observed_image_url == new_url
    assert after_failure.downloaded_image_url == old_url
    assert after_failure.image_asset == old_record.image_asset
    assert after_failure.monthly_refresh_completed == "2026-10"

    retry = FakeImageClient({new_url: _PNG_B})
    second = asyncio.run(
        refresh_team_directory(
            data_root=root,
            metadata_reader=FakeMetadataReader([_team(101, new_url)]),
            image_client=retry,
            clock=lambda: _NOW,
        )
    )
    after_success = TeamDirectoryStore(root).read_current().teams[101]
    assert second.downloaded == 1
    assert retry.calls == [new_url]
    assert after_success.downloaded_image_url == new_url
    assert after_success.image_asset == hashlib.sha256(_PNG_B).hexdigest()
    assert after_success.image_asset != old_record.image_asset
    assert after_success.monthly_refresh_completed == "2026-10"


def test_monthly_refresh_and_missing_local_asset_trigger_download(tmp_path: Path) -> None:
    root = tmp_path / "data"
    current_url = "https://cdn.test/current.png"
    monthly_url = "https://cdn.test/monthly.png"
    missing_url = "https://cdn.test/missing.png"
    current = _stored_record(root, 1, url=current_url, month="2026-10")
    monthly = _stored_record(root, 2, url=monthly_url, month="2026-09")
    missing = _stored_record(root, 3, url=missing_url, month="2026-10")
    (root / "images" / "assets" / f"{missing.image_asset}.png").unlink()
    _seed(root, {1: current, 2: monthly, 3: missing})
    client = FakeImageClient(
        {monthly_url: TeamImageError("download_failed"), missing_url: _PNG_B}
    )

    first = asyncio.run(
        refresh_team_directory(
            data_root=root,
            metadata_reader=FakeMetadataReader(
                [_team(1, current_url), _team(2, monthly_url), _team(3, missing_url)]
            ),
            image_client=client,
            clock=lambda: _NOW,
        )
    )

    assert first.skipped == 1
    assert first.downloaded == 1
    assert [(failure.source_id, failure.error_code) for failure in first.failures] == [
        (2, "download_failed")
    ]
    assert set(client.calls) == {monthly_url, missing_url}
    after_failure = TeamDirectoryStore(root).read_current().teams
    assert after_failure[2].monthly_refresh_completed == "2026-09"
    assert after_failure[2].downloaded_image_url == monthly_url
    assert after_failure[3].monthly_refresh_completed == "2026-10"

    retry = FakeImageClient({monthly_url: _PNG_B})
    second = asyncio.run(
        refresh_team_directory(
            data_root=root,
            metadata_reader=FakeMetadataReader(
                [_team(1, current_url), _team(2, monthly_url), _team(3, missing_url)]
            ),
            image_client=retry,
            clock=lambda: _NOW,
        )
    )

    assert second.skipped == 2
    assert second.downloaded == 1
    assert second.failures == ()
    assert retry.calls == [monthly_url]
    after_success = TeamDirectoryStore(root).read_current().teams[2]
    assert after_success.monthly_refresh_completed == "2026-10"
    assert after_success.downloaded_image_url == monthly_url

def test_no_url_keeps_existing_image_and_omitted_teams_are_retained(tmp_path: Path) -> None:
    root = tmp_path / "data"
    saved = _stored_record(root, 5, url="https://cdn.test/old.png")
    _seed(root, {5: saved, 99: TeamDisplayRecord(99, "Keep me")})
    client = FakeImageClient()

    report = asyncio.run(
        refresh_team_directory(
            data_root=root,
            metadata_reader=FakeMetadataReader([_team(5, None)]),
            image_client=client,
            clock=lambda: _NOW,
        )
    )

    result = TeamDirectoryStore(root).read_current()
    assert report.no_url == 1
    assert report.retained_old_records == 1
    assert client.calls == []
    assert result.teams[5].image_asset == saved.image_asset
    assert result.teams[5].downloaded_image_url == saved.downloaded_image_url
    assert result.teams[99].label == "Keep me"


def test_single_image_failure_isolated_and_download_concurrency_is_bounded(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    _seed(root, {})
    urls = {team_id: f"https://cdn.test/{team_id}.png" for team_id in range(1, 4)}
    guard = threading.Lock()
    barrier = threading.Barrier(2)
    active = 0
    peak = 0
    calls: list[str] = []

    class MeasuredClient:
        def fetch_png(self, url: str) -> bytes:
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
                calls.append(url)
                call_number = len(calls)
            try:
                if call_number <= 2:
                    barrier.wait(timeout=5)
                if url == urls[2]:
                    raise TeamImageError("download_failed")
                return _PNG_A
            finally:
                with guard:
                    active -= 1

    teams = [_team(team_id, urls[team_id]) for team_id in range(1, 4)]
    report = asyncio.run(
        refresh_team_directory(
            data_root=root,
            metadata_reader=FakeMetadataReader(teams),
            image_client=MeasuredClient(),
            image_workers=2,
            clock=lambda: _NOW,
        )
    )

    assert peak == 2
    assert set(calls) == set(urls.values())
    assert report.downloaded == 2
    assert [(failure.source_id, failure.error_code) for failure in report.failures] == [
        (2, "download_failed")
    ]
    snapshot = TeamDirectoryStore(root).read_current()
    assert [snapshot.teams[team_id].label for team_id in range(1, 4)] == [
        "Team 1",
        "Team 2",
        "Team 3",
    ]
    assert snapshot.teams[2].image_asset is None


def test_corrupt_existing_directory_stops_before_metadata_or_image_work(tmp_path: Path) -> None:
    root = tmp_path / "data"
    path = root / "display" / "teams.json"
    path.parent.mkdir(parents=True)
    original = b'{"schema_version":1,"teams":{"1":{"source_id":1,"label":"Incomplete"}}}'
    path.write_bytes(original)
    reader = FakeMetadataReader([_team(1, "https://cdn.test/one.png")])
    client = FakeImageClient()

    with pytest.raises(TeamDirectoryStoreError) as raised:
        asyncio.run(
            refresh_team_directory(
                data_root=root,
                metadata_reader=reader,
                image_client=client,
                clock=lambda: _NOW,
            )
        )

    assert raised.value.reason == "invalid_snapshot"
    assert reader.calls == 0
    assert client.calls == []
    assert path.read_bytes() == original


def test_failed_directory_publication_keeps_previous_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    initial = _seed(root, {1: TeamDisplayRecord(1, "Old")})
    from app.vnext.data_updates import team_directory_store

    monkeypatch.setattr(
        team_directory_store,
        "atomic_write",
        lambda *_args: (_ for _ in ()).throw(OSError("private storage detail")),
    )

    with pytest.raises(TeamDirectoryStoreError) as raised:
        TeamDirectoryStore(root).publish({2: TeamDisplayRecord(2, "New")})

    assert raised.value.reason == "storage_error"
    assert TeamDirectoryStore(root).path.read_bytes() == initial
