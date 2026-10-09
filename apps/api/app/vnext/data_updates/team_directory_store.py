"""Shared read/write contract for the persistent Team display directory."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType

from app.vnext.data_updates.image_assets import atomic_write

_HASH = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_MONTH = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])\Z", re.ASCII)
_LOCAL_IMAGE_URL = "/api/v1/assets/dota/by-hash/{}.png"
_TEAM_REQUIRED_FIELDS = {
    "source_id",
    "label",
    "observed_image_url",
    "downloaded_image_url",
    "image_asset",
    "image_downloaded_at",
    "monthly_refresh_completed",
}


class TeamDirectoryStoreError(RuntimeError):
    """A safe, stable failure from the Team directory file store."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        messages = {
            "invalid_snapshot": "team display snapshot is invalid",
            "storage_error": "team display storage operation failed",
        }
        super().__init__(messages[reason])


@dataclass(frozen=True, slots=True)
class TeamDisplayRecord:
    source_id: int
    label: str
    observed_image_url: str | None = None
    downloaded_image_url: str | None = None
    image_asset: str | None = None
    image_downloaded_at: str | None = None
    monthly_refresh_completed: str | None = None


@dataclass(frozen=True, slots=True)
class TeamDirectorySnapshot:
    teams: Mapping[int, TeamDisplayRecord]
    assets_directory: Path

    def image_url(self, team: TeamDisplayRecord) -> str | None:
        content_hash = team.image_asset
        if content_hash is None:
            return None
        if not (self.assets_directory / f"{content_hash}.png").is_file():
            return None
        return _LOCAL_IMAGE_URL.format(content_hash)


def parse_team_directory_snapshot(
    raw: bytes,
    *,
    assets_directory: Path,
) -> TeamDirectorySnapshot:
    payload = json.loads(
        raw.decode("utf-8"),
        parse_constant=_reject_json_constant,
        object_pairs_hook=_unique_object_pairs,
    )
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int:
        raise ValueError("team display snapshot root is invalid")
    if payload["schema_version"] != 1:
        raise ValueError("team display snapshot version is unsupported")
    raw_teams = payload.get("teams")
    if not isinstance(raw_teams, dict):
        raise ValueError("team display snapshot teams are invalid")

    teams: dict[int, TeamDisplayRecord] = {}
    for key, raw_team in raw_teams.items():
        if not isinstance(key, str) or not isinstance(raw_team, dict):
            raise ValueError("team display record is invalid")
        if not _TEAM_REQUIRED_FIELDS.issubset(raw_team):
            raise ValueError("team display record is incomplete")
        source_id = raw_team.get("source_id")
        if type(source_id) is not int or source_id <= 0 or key != str(source_id):
            raise ValueError("team display record identity is invalid")
        label = raw_team.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("team display record label is invalid")

        observed_image_url = _optional_nonempty_string(raw_team, "observed_image_url")
        downloaded_image_url = _optional_nonempty_string(raw_team, "downloaded_image_url")
        image_asset = _optional_nonempty_string(raw_team, "image_asset")
        if image_asset is not None and _HASH.fullmatch(image_asset) is None:
            raise ValueError("team image asset hash is invalid")
        image_downloaded_at = _optional_nonempty_string(raw_team, "image_downloaded_at")
        if image_downloaded_at is not None:
            _validate_timestamp(image_downloaded_at)
        monthly_refresh_completed = _optional_nonempty_string(
            raw_team, "monthly_refresh_completed"
        )
        if (
            monthly_refresh_completed is not None
            and _MONTH.fullmatch(monthly_refresh_completed) is None
        ):
            raise ValueError("team monthly refresh marker is invalid")

        teams[source_id] = TeamDisplayRecord(
            source_id=source_id,
            label=label.strip(),
            observed_image_url=observed_image_url,
            downloaded_image_url=downloaded_image_url,
            image_asset=image_asset,
            image_downloaded_at=image_downloaded_at,
            monthly_refresh_completed=monthly_refresh_completed,
        )
    return TeamDirectorySnapshot(
        teams=MappingProxyType(teams),
        assets_directory=Path(assets_directory),
    )


def serialize_team_directory(teams: Mapping[int, TeamDisplayRecord]) -> bytes:
    payload = {
        "schema_version": 1,
        "teams": {
            str(source_id): {
                "source_id": team.source_id,
                "label": team.label,
                "observed_image_url": team.observed_image_url,
                "downloaded_image_url": team.downloaded_image_url,
                "image_asset": team.image_asset,
                "image_downloaded_at": team.image_downloaded_at,
                "monthly_refresh_completed": team.monthly_refresh_completed,
            }
            for source_id, team in sorted(teams.items())
        },
    }
    raw = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    parse_team_directory_snapshot(raw, assets_directory=Path("."))
    return raw


class TeamDirectoryStore:
    """Read and atomically publish complete Team display snapshots."""

    def __init__(self, data_root: Path) -> None:
        root = Path(data_root)
        self.path = root / "display" / "teams.json"
        self.assets_directory = root / "images" / "assets"
        self._lock = threading.Lock()
        self._last_valid: TeamDirectorySnapshot | None = None
        self._empty = TeamDirectorySnapshot(
            teams=MappingProxyType({}),
            assets_directory=self.assets_directory,
        )

    def read_current(self) -> TeamDirectorySnapshot:
        """Return the current valid snapshot or retain the last valid one."""

        with self._lock:
            try:
                snapshot = self._read_file()
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                RecursionError,
                TypeError,
                ValueError,
            ):
                return self._last_valid if self._last_valid is not None else self._empty
            self._last_valid = snapshot
            return snapshot

    def read_for_update(self) -> TeamDirectorySnapshot | None:
        """Read strictly; an invalid existing file must never be overwritten."""

        with self._lock:
            try:
                snapshot = self._read_file()
            except FileNotFoundError:
                return None
            except OSError:
                raise TeamDirectoryStoreError("storage_error") from None
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                RecursionError,
                TypeError,
                ValueError,
            ):
                raise TeamDirectoryStoreError("invalid_snapshot") from None
            self._last_valid = snapshot
            return snapshot

    def publish(self, teams: Mapping[int, TeamDisplayRecord]) -> TeamDirectorySnapshot:
        """Atomically replace the complete Team file and expose it to readers."""

        try:
            raw = serialize_team_directory(teams)
            snapshot = parse_team_directory_snapshot(
                raw,
                assets_directory=self.assets_directory,
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(self.path, raw)
        except OSError:
            raise TeamDirectoryStoreError("storage_error") from None
        except (TypeError, ValueError, RecursionError):
            raise TeamDirectoryStoreError("invalid_snapshot") from None
        with self._lock:
            self._last_valid = snapshot
        return snapshot

    def _read_file(self) -> TeamDirectorySnapshot:
        return parse_team_directory_snapshot(
            self.path.read_bytes(),
            assets_directory=self.assets_directory,
        )


def _optional_nonempty_string(record: dict[str, object], field: str) -> str | None:
    value = record.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"team display field {field} is invalid")
    return value


def _validate_timestamp(value: str) -> None:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("team image timestamp is invalid") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("team image timestamp must include a timezone")


def _unique_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("team display snapshot contains a duplicate key")
        result[key] = value
    return result


def _reject_json_constant(_constant: str) -> None:
    raise ValueError("team display snapshot contains a non-finite number")


__all__ = [
    "TeamDirectorySnapshot",
    "TeamDirectoryStore",
    "TeamDirectoryStoreError",
    "TeamDisplayRecord",
    "parse_team_directory_snapshot",
    "serialize_team_directory",
]
