"""Read-only repository for the committed PandaScore team asset snapshot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TEAM_ASSET_ROOT = Path(__file__).resolve().parents[2] / "data" / "esports" / "teams"


class PandaScoreTeamAssetRepository:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or TEAM_ASSET_ROOT

    def image_path(self, pandascore_team_id: Any) -> str | None:
        if isinstance(pandascore_team_id, bool):
            return None
        try:
            team_id = int(pandascore_team_id)
        except (TypeError, ValueError):
            return None
        if team_id <= 0:
            return None
        manifest = self._read_manifest()
        for team in manifest.get("teams", []):
            if not isinstance(team, dict) or team.get("pandascore_team_id") != team_id:
                continue
            image_path = team.get("image_path")
            if not isinstance(image_path, str) or not image_path.startswith(
                "/api/v1/assets/esports/teams/"
            ):
                return None
            filename = Path(image_path).name
            if filename != image_path.rsplit("/", 1)[-1] or Path(filename).suffix.lower() not in {
                ".png",
                ".jpg",
                ".webp",
            }:
                return None
            if (self.root / filename).is_file():
                return image_path
            return None
        return None

    def _read_manifest(self) -> dict[str, Any]:
        try:
            payload = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return payload if isinstance(payload, dict) else {}
