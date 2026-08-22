"""PandaScore team listing and image-download integration boundary."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import httpx

from app.integrations.pandascore.models import PandaMatchFixture, PandaScoreTeam
from app.integrations.pandascore.transport import PandaScoreTransport

SUPPORTED_TEAM_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


class PandaScoreTeamImageError(RuntimeError):
    """A team logo could not be downloaded or has an unsupported type."""


class PandaScoreTeams:
    """Extract referenced teams and download their images through the shared transport."""

    def __init__(self, transport: PandaScoreTransport) -> None:
        self.transport = transport

    @staticmethod
    def from_fixtures(fixtures: Iterable[PandaMatchFixture]) -> list[PandaScoreTeam]:
        teams: dict[int, PandaScoreTeam] = {}
        for fixture in fixtures:
            for side in fixture.opponents:
                opponent = side.get("opponent") if isinstance(side, dict) else None
                team = normalize_team(opponent)
                if team is not None:
                    teams.setdefault(team.pandascore_team_id, team)
        return list(teams.values())

    async def download_image(self, image_url: str) -> tuple[bytes, str]:
        try:
            async with httpx.AsyncClient(
                timeout=self.transport.request_timeout_seconds,
                follow_redirects=True,
                headers={"Accept": ", ".join(SUPPORTED_TEAM_IMAGE_TYPES)},
            ) as client:
                response = await client.get(image_url)
        except httpx.HTTPError as exc:
            raise PandaScoreTeamImageError("team logo request failed") from exc
        if response.status_code >= 400:
            raise PandaScoreTeamImageError(f"team logo returned HTTP {response.status_code}")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        extension = SUPPORTED_TEAM_IMAGE_TYPES.get(content_type)
        if extension is None:
            raise PandaScoreTeamImageError(
                f"unsupported team logo content type: {content_type or 'missing'}"
            )
        if not response.content:
            raise PandaScoreTeamImageError("team logo response was empty")
        return response.content, extension


def normalize_team(row: Any) -> PandaScoreTeam | None:
    if not isinstance(row, dict):
        return None
    raw_id = row.get("id")
    name = row.get("name")
    if isinstance(raw_id, bool) or not isinstance(raw_id, (int, str)) or not str(raw_id).isdigit():
        return None
    if not isinstance(name, str) or not name.strip():
        return None
    acronym = row.get("acronym")
    image_url = row.get("image_url")
    return PandaScoreTeam(
        pandascore_team_id=int(raw_id),
        name=name.strip(),
        acronym=acronym.strip() if isinstance(acronym, str) and acronym.strip() else None,
        image_url=image_url.strip() if isinstance(image_url, str) and image_url.strip() else None,
    )
