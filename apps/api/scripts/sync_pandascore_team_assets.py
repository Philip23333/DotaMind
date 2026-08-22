"""Synchronize the committed local PandaScore Dota 2 team-logo snapshot."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.core.config import get_policy, get_settings  # noqa: E402
from app.integrations.pandascore.competitions import PandaScoreCompetitions  # noqa: E402
from app.integrations.pandascore.matches import PandaScoreMatches  # noqa: E402
from app.integrations.pandascore.models import PandaScoreTeam  # noqa: E402
from app.integrations.pandascore.teams import PandaScoreTeams  # noqa: E402
from app.integrations.pandascore.transport import PandaScoreTransport  # noqa: E402

ESPORTS_OUTPUT_DIR = API_ROOT / "app" / "data" / "esports"
TEAM_OUTPUT_DIR = ESPORTS_OUTPUT_DIR / "teams"
TEAM_MANIFEST_OUTPUT = TEAM_OUTPUT_DIR / "manifest.json"
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".webp"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--series-limit",
        type=int,
        default=10,
        help="Newest Dota 2 Series whose fixture opponents supply the local team snapshot.",
    )
    parser.add_argument("--force", action="store_true", help="redownload unchanged logo URLs")
    args = parser.parse_args()
    if not 1 <= args.workers <= 32:
        parser.error("--workers must be between 1 and 32")
    if not 1 <= args.series_limit <= 100:
        parser.error("--series-limit must be between 1 and 100")
    asyncio.run(
        _run_sync(
            workers=args.workers,
            force=args.force,
            series_limit=args.series_limit,
        )
    )


async def _run_sync(*, workers: int, force: bool, series_limit: int) -> None:
    settings = get_settings()
    policy = get_policy().pandascore
    transport = PandaScoreTransport(
        settings.pandascore_base_url,
        settings.pandascore_token,
        request_timeout_seconds=policy.request_timeout_seconds,
        default_cache_ttl_seconds=policy.default_cache_ttl_seconds,
        max_page_size=100,
    )
    try:
        competitions = PandaScoreCompetitions(transport)
        matches = PandaScoreMatches(transport, competitions)
        teams_client = PandaScoreTeams(transport)
        series_ids = await competitions.list_recent_series_ids(limit=series_limit)
        if not series_ids:
            raise RuntimeError("PandaScore returned no recent Dota 2 series")
        fixture_groups = await asyncio.gather(
            *(matches.list_matches(series_id) for series_id in series_ids)
        )
        teams = PandaScoreTeams.from_fixtures(
            fixture for fixtures in fixture_groups for fixture in fixtures
        )
        staging_dir, manifest = await _build_staging_snapshot(
            teams_client,
            teams,
            workers=workers,
            force=force,
            series_ids=series_ids,
        )
        try:
            (staging_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            _replace_team_assets(staging_dir)
        except Exception:
            shutil.rmtree(staging_dir.parent, ignore_errors=True)
            raise
    finally:
        await transport.aclose()
    print(
        f"wrote {TEAM_OUTPUT_DIR} ({len(manifest['teams'])} logos from {len(series_ids)} series, "
        f"{manifest['skipped_no_logo']} without logos, "
        f"{manifest['download_failures']} download failures)"
    )


async def _build_staging_snapshot(
    teams_client: PandaScoreTeams,
    teams: list[PandaScoreTeam],
    *,
    workers: int,
    force: bool,
    series_ids: list[int],
) -> tuple[Path, dict[str, object]]:
    ESPORTS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(tempfile.mkdtemp(prefix=".teams-assets-", dir=ESPORTS_OUTPUT_DIR))
    staging_dir = temporary_dir / "teams"
    staging_dir.mkdir(parents=True, exist_ok=True)
    previous = _previous_assets() if not force else {}
    semaphore = asyncio.Semaphore(workers)
    skipped_no_logo = 0
    download_failures = 0
    snapshot: list[dict[str, object]] = []

    async def process(team: PandaScoreTeam) -> tuple[dict[str, object] | None, str | None]:
        nonlocal skipped_no_logo, download_failures
        image_url = team.image_url
        if not image_url or not _valid_image_url(image_url):
            skipped_no_logo += 1
            print(f"warning: skipping team {team.pandascore_team_id} with invalid/no logo URL")
            return None, None
        old = previous.get(team.pandascore_team_id)
        if old is not None and old[0] == image_url and (TEAM_OUTPUT_DIR / old[1]).is_file():
            shutil.copy2(TEAM_OUTPUT_DIR / old[1], staging_dir / old[1])
            extension = Path(old[1]).suffix.lower()
        else:
            try:
                async with semaphore:
                    payload, extension = await teams_client.download_image(image_url)
                filename = f"{team.pandascore_team_id}{extension}"
                (staging_dir / filename).write_bytes(payload)
            except Exception as exc:
                download_failures += 1
                print(
                    f"warning: skipping team {team.pandascore_team_id} logo: {exc}",
                    file=sys.stderr,
                )
                return None, None
        filename = f"{team.pandascore_team_id}{extension}"
        return (
            {
                "pandascore_team_id": team.pandascore_team_id,
                "name": team.name,
                "acronym": team.acronym,
                "source_url": image_url,
                "image_path": f"/api/v1/assets/esports/teams/{filename}",
            },
            filename,
        )

    results = await asyncio.gather(*(process(team) for team in teams))
    for entry, _filename in results:
        if entry is not None:
            snapshot.append(entry)
    snapshot.sort(key=lambda team: int(team["pandascore_team_id"]))
    return staging_dir, {
        "schema_version": 1,
        "source": "PandaScore recent Dota 2 series fixtures",
        "synced_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "series_ids": series_ids,
        "teams": snapshot,
        "skipped_no_logo": skipped_no_logo,
        "download_failures": download_failures,
    }


def _valid_image_url(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.hostname.endswith(".pandascore.co")
        and bool(parsed.path and parsed.path != "/")
    )


def _previous_assets() -> dict[int, tuple[str, str]]:
    try:
        payload = json.loads(TEAM_MANIFEST_OUTPUT.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(payload, dict) or not isinstance(payload.get("teams"), list):
        return {}
    result: dict[int, tuple[str, str]] = {}
    for entry in payload["teams"]:
        if not isinstance(entry, dict):
            continue
        raw_id = entry.get("pandascore_team_id")
        source_url = entry.get("source_url")
        image_path = entry.get("image_path")
        if (
            isinstance(raw_id, int)
            and isinstance(source_url, str)
            and isinstance(image_path, str)
            and image_path.startswith("/api/v1/assets/esports/teams/")
        ):
            filename = Path(image_path).name
            if filename and Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS:
                result[raw_id] = (source_url, filename)
    return result


def _replace_team_assets(staging_dir: Path) -> None:
    backup_dir = ESPORTS_OUTPUT_DIR / ".teams-assets-backup"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    moved_old = False
    try:
        if TEAM_OUTPUT_DIR.exists():
            os.replace(TEAM_OUTPUT_DIR, backup_dir)
            moved_old = True
        os.replace(staging_dir, TEAM_OUTPUT_DIR)
    except Exception:
        if moved_old and not TEAM_OUTPUT_DIR.exists():
            os.replace(backup_dir, TEAM_OUTPUT_DIR)
        raise
    finally:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        if staging_dir.parent.exists():
            shutil.rmtree(staging_dir.parent, ignore_errors=True)


if __name__ == "__main__":
    main()
