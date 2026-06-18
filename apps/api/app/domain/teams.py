from dataclasses import dataclass, field
from typing import Any, Literal

TeamResolutionStatus = Literal["resolved", "ambiguous", "not_found"]


@dataclass(frozen=True)
class TeamResolution:
    status: TeamResolutionStatus
    requested_name: str
    team: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)


class TeamLookupError(Exception):
    code = "team_lookup_error"
    status_code = 500

    def __init__(
        self,
        message: str,
        *,
        requested_team: str,
        candidates: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.requested_team = requested_team
        self.candidates = candidates or []


class TeamNotFoundError(TeamLookupError):
    code = "team_not_found"
    status_code = 404

    def __init__(self, requested_team: str) -> None:
        super().__init__(
            f"No OpenDota team matched '{requested_team}'.",
            requested_team=requested_team,
        )


class AmbiguousTeamError(TeamLookupError):
    code = "ambiguous_team"
    status_code = 409

    def __init__(self, requested_team: str, candidates: list[dict[str, Any]]) -> None:
        super().__init__(
            f"Multiple OpenDota teams matched '{requested_team}'.",
            requested_team=requested_team,
            candidates=candidates,
        )


class TeamDataUnavailableError(TeamLookupError):
    code = "team_data_unavailable"
    status_code = 503

    def __init__(self, requested_team: str, message: str) -> None:
        super().__init__(message, requested_team=requested_team)
