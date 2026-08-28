"""Match DTOs, deterministic cross-source resolution, and match service."""

from importlib import import_module
from typing import Any

_EXPORTS = {
    "SeriesMatchesResult": ("app.vnext.domain.matches.models", "SeriesMatchesResult"),
    "SeriesSummary": ("app.vnext.domain.matches.models", "SeriesSummary"),
    "Game": ("app.vnext.domain.matches.models", "Game"),
    "GameDetail": ("app.vnext.domain.matches.models", "GameDetail"),
    "GameSummary": ("app.vnext.domain.matches.models", "GameSummary"),
    "LeagueSignal": ("app.vnext.domain.matches.resolution", "LeagueSignal"),
    "MatchCandidate": ("app.vnext.domain.matches.models", "MatchCandidate"),
    "MatchDetail": ("app.vnext.domain.matches.models", "MatchDetail"),
    "MatchResolutionService": (
        "app.vnext.domain.matches.resolution",
        "MatchResolutionService",
    ),
    "MatchResult": ("app.vnext.domain.matches.models", "MatchResult"),
    "MatchSearchResult": ("app.vnext.domain.matches.models", "MatchSearchResult"),
    "MatchService": ("app.vnext.domain.matches.service", "MatchService"),
    "MatchSignal": ("app.vnext.domain.matches.resolution", "MatchSignal"),
    "MatchStatus": ("app.vnext.domain.matches.models", "MatchStatus"),
    "MatchSummary": ("app.vnext.domain.matches.models", "MatchSummary"),
    "ResolutionEvidence": ("app.vnext.domain.matches.models", "ResolutionEvidence"),
    "ResolutionStatus": ("app.vnext.domain.matches.models", "ResolutionStatus"),
    "ResolutionSummary": ("app.vnext.domain.matches.models", "ResolutionSummary"),
    "TeamSignal": ("app.vnext.domain.matches.resolution", "TeamSignal"),
    "TimeScope": ("app.vnext.domain.matches.models", "TimeScope"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)
