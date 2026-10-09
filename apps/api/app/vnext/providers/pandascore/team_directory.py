"""Read and validate the complete PandaScore Dota 2 team collection."""

from __future__ import annotations

from dataclasses import dataclass

from app.vnext.providers.pandascore.client import PandaScoreClient

_PAGE_SIZE = 100


class PandaScoreTeamDirectoryError(RuntimeError):
    """A safe, stable schema error while reading PandaScore Teams."""

    _MESSAGES = {
        "invalid_team_row": "PandaScore team collection contains an invalid row",
        "invalid_team_id": "PandaScore team collection contains an invalid ID",
        "invalid_team_name": "PandaScore team collection contains an invalid name",
        "invalid_team_image_url": "PandaScore team collection contains an invalid image URL",
        "duplicate_team_id": "PandaScore team collection contains duplicate IDs",
        "page_too_large": "PandaScore team page exceeded its requested size",
    }

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(self._MESSAGES[reason])


@dataclass(frozen=True, slots=True)
class PandaScoreTeamMetadata:
    source_id: int
    label: str
    image_url: str | None

    def __post_init__(self) -> None:
        if type(self.source_id) is not int or self.source_id <= 0:
            raise ValueError("source_id must be a strict positive integer")
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("label must be a non-empty string")
        object.__setattr__(self, "label", self.label.strip())
        if self.image_url is not None and not isinstance(self.image_url, str):
            raise ValueError("image_url must be a string or null")
        if isinstance(self.image_url, str):
            normalized = self.image_url.strip()
            object.__setattr__(self, "image_url", normalized or None)


class PandaScoreTeamDirectoryReader:
    """Fetch one hundred Teams per serial page without mutating business DTOs."""

    def __init__(self, client: PandaScoreClient) -> None:
        self._client = client

    async def read_all(self) -> list[PandaScoreTeamMetadata]:
        teams: list[PandaScoreTeamMetadata] = []
        seen: set[int] = set()
        page = 1
        while True:
            rows = await self._client.get_list(
                "/dota2/teams",
                params={"page": page, "per_page": _PAGE_SIZE},
            )
            if len(rows) > _PAGE_SIZE:
                raise PandaScoreTeamDirectoryError("page_too_large")
            parsed = [
                _parse_team(row)
                for row in rows
            ]
            for team in parsed:
                if team.source_id in seen:
                    raise PandaScoreTeamDirectoryError("duplicate_team_id")
                seen.add(team.source_id)
            teams.extend(parsed)
            if len(rows) < _PAGE_SIZE:
                return teams
            page += 1


def validate_team_metadata(
    teams: object,
) -> tuple[PandaScoreTeamMetadata, ...]:
    """Validate a complete injected metadata result before image work starts."""

    if not isinstance(teams, list):
        raise PandaScoreTeamDirectoryError("invalid_team_row")
    seen: set[int] = set()
    result: list[PandaScoreTeamMetadata] = []
    for team in teams:
        if not isinstance(team, PandaScoreTeamMetadata):
            raise PandaScoreTeamDirectoryError("invalid_team_row")
        if team.source_id in seen:
            raise PandaScoreTeamDirectoryError("duplicate_team_id")
        seen.add(team.source_id)
        result.append(team)
    return tuple(result)


def _parse_team(row: object) -> PandaScoreTeamMetadata:
    if not isinstance(row, dict):
        raise PandaScoreTeamDirectoryError("invalid_team_row")
    source_id = row.get("id")
    if type(source_id) is not int or source_id <= 0:
        raise PandaScoreTeamDirectoryError("invalid_team_id")
    label = row.get("name")
    if not isinstance(label, str) or not label.strip():
        raise PandaScoreTeamDirectoryError("invalid_team_name")
    image_url = row.get("image_url")
    if image_url is not None and not isinstance(image_url, str):
        raise PandaScoreTeamDirectoryError("invalid_team_image_url")
    try:
        return PandaScoreTeamMetadata(
            source_id=source_id,
            label=label,
            image_url=image_url,
        )
    except ValueError:
        raise PandaScoreTeamDirectoryError("invalid_team_row") from None


__all__ = [
    "PandaScoreTeamDirectoryError",
    "PandaScoreTeamDirectoryReader",
    "PandaScoreTeamMetadata",
    "validate_team_metadata",
]
