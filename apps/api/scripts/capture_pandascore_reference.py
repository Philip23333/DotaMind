"""Capture bounded, raw PandaScore responses for local integration reference."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.vnext.composition import VNextSettings
from app.vnext.providers.pandascore.adapter import PandaScoreAdapter, PandaScoreProviderError

_PAGE_SIZE = 5
_REFERENCE_ROOT = Path(__file__).resolve().parents[3] / "docs" / "reference"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Save bounded raw PandaScore responses without credentials or headers."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Destination directory. Defaults to a UTC-dated directory under docs/reference.",
    )
    return parser.parse_args()


def _default_output_dir() -> Path:
    date = datetime.now(timezone.utc).date().isoformat()
    return _REFERENCE_ROOT / "pandascore-snapshots" / date


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _request_params(**extra: Any) -> dict[str, Any]:
    return {"page[size]": _PAGE_SIZE, "page[number]": 1, **extra}


def _first_id(payload: Any) -> int | None:
    if not isinstance(payload, list) or not payload:
        return None
    value = payload[0]
    if not isinstance(value, dict):
        return None
    identifier = value.get("id")
    return identifier if isinstance(identifier, int) else None


async def _capture(
    adapter: PandaScoreAdapter,
    output_dir: Path,
    manifest: list[dict[str, Any]],
    *,
    name: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any | None:
    try:
        payload, fetched_at, pagination = await adapter._get_json(path, params=params)
    except PandaScoreProviderError as exc:
        manifest.append(
            {
                "name": name,
                "status": "error",
                "request": {"path": path, "params": params or {}},
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
        )
        return None

    filename = f"{name}.json"
    _write_json(
        output_dir / filename,
        {
            "source": "pandascore",
            "captured_at": fetched_at.isoformat(),
            "request": {"path": path, "params": params or {}},
            "pagination": {
                "page_number": pagination.page_number,
                "page_size": pagination.page_size,
                "total_count": pagination.total_count,
                "has_more": pagination.has_more,
            },
            "response": payload,
        },
    )
    manifest.append(
        {
            "name": name,
            "status": "captured",
            "file": filename,
            "request": {"path": path, "params": params or {}},
        }
    )
    return payload


def _record_embedded(
    output_dir: Path,
    manifest: list[dict[str, Any]],
    *,
    name: str,
    parent: Any,
    key: str,
) -> None:
    if not isinstance(parent, dict) or key not in parent:
        manifest.append(
            {"name": name, "status": "unavailable", "reason": f"{key} was not present"}
        )
        return
    filename = f"{name}.json"
    _write_json(
        output_dir / filename,
        {
            "source": "pandascore",
            "extracted_from": "match_detail.json",
            "response": parent[key],
        },
    )
    manifest.append(
        {"name": name, "status": "embedded", "file": filename, "parent": "match_detail.json"}
    )


def _record_skipped(manifest: list[dict[str, Any]], name: str, reason: str) -> None:
    manifest.append({"name": name, "status": "skipped", "reason": reason})


async def capture(output_dir: Path) -> list[dict[str, Any]]:
    settings = VNextSettings.from_env()
    adapter = PandaScoreAdapter(
        base_url=settings.pandascore_base_url,
        token=settings.pandascore_token,
        request_timeout_seconds=settings.pandascore_timeout_seconds,
        max_page_size=settings.pandascore_max_page_size,
    )
    if adapter.token is None:
        raise RuntimeError("DOTAMIND_PANDASCORE_TOKEN is not configured")

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    try:
        leagues = await _capture(
            adapter,
            output_dir,
            manifest,
            name="leagues_search",
            path="/dota2/leagues",
            params=_request_params(),
        )
        series = await _capture(
            adapter,
            output_dir,
            manifest,
            name="series_search",
            path="/dota2/series",
            params=_request_params(),
        )
        teams = await _capture(
            adapter,
            output_dir,
            manifest,
            name="teams_search",
            path="/dota2/teams",
            params=_request_params(**{"search[name]": "Team Spirit"}),
        )
        players = await _capture(
            adapter,
            output_dir,
            manifest,
            name="players_search",
            path="/dota2/players",
            params=_request_params(**{"search[name]": "Yatoro"}),
        )
        past_matches = await _capture(
            adapter,
            output_dir,
            manifest,
            name="matches_past",
            path="/dota2/matches/past",
            params=_request_params(sort="-scheduled_at"),
        )
        await _capture(
            adapter,
            output_dir,
            manifest,
            name="matches_running",
            path="/dota2/matches/running",
            params=_request_params(sort="scheduled_at"),
        )
        await _capture(
            adapter,
            output_dir,
            manifest,
            name="matches_upcoming",
            path="/dota2/matches/upcoming",
            params=_request_params(sort="scheduled_at"),
        )

        league_id = _first_id(leagues)
        if league_id is None:
            _record_skipped(manifest, "league_series", "no league ID was returned")
        else:
            await _capture(
                adapter,
                output_dir,
                manifest,
                name="league_series",
                path=f"/leagues/{league_id}/series",
                params=_request_params(),
            )

        series_id = _first_id(series)
        if series_id is None:
            _record_skipped(manifest, "series_matches_past", "no series ID was returned")
        else:
            await _capture(
                adapter,
                output_dir,
                manifest,
                name="series_matches_past",
                path=f"/series/{series_id}/matches/past",
                params=_request_params(),
            )

        team_id = _first_id(teams)
        if team_id is None:
            _record_skipped(manifest, "team_detail", "no team ID was returned")
            _record_skipped(manifest, "team_matches", "no team ID was returned")
        else:
            await _capture(
                adapter,
                output_dir,
                manifest,
                name="team_detail",
                path=f"/teams/{team_id}",
            )
            await _capture(
                adapter,
                output_dir,
                manifest,
                name="team_matches",
                path=f"/teams/{team_id}/matches",
                params=_request_params(sort="-scheduled_at"),
            )

        player_id = _first_id(players)
        if player_id is None:
            _record_skipped(manifest, "player_detail", "no player ID was returned")
        else:
            await _capture(
                adapter,
                output_dir,
                manifest,
                name="player_detail",
                path=f"/players/{player_id}",
            )

        match_id = _first_id(past_matches)
        if match_id is None:
            _record_skipped(manifest, "match_detail", "no past match ID was returned")
            _record_skipped(manifest, "embedded_game", "no match detail was returned")
            _record_skipped(manifest, "embedded_tournament", "no match detail was returned")
        else:
            match_detail = await _capture(
                adapter,
                output_dir,
                manifest,
                name="match_detail",
                path=f"/matches/{match_id}",
            )
            _record_embedded(
                output_dir,
                manifest,
                name="embedded_game",
                parent=match_detail,
                key="games",
            )
            _record_embedded(
                output_dir,
                manifest,
                name="embedded_tournament",
                parent=match_detail,
                key="tournament",
            )
    finally:
        await adapter.aclose()
    return manifest


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir or _default_output_dir()
    manifest = asyncio.run(capture(output_dir))
    _write_json(
        output_dir / "manifest.json",
        {
            "purpose": "Bounded raw PandaScore endpoint observations for local reference.",
            "credentials": "Not stored. Request headers are not captured.",
            "entries": manifest,
        },
    )
    captured = sum(entry["status"] == "captured" for entry in manifest)
    errors = sum(entry["status"] == "error" for entry in manifest)
    print(f"Saved {captured} endpoint responses to {output_dir} ({errors} errors).")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
