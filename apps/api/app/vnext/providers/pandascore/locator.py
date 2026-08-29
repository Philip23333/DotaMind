"""Runtime-scoped opaque locators for PandaScore source objects."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from app.vnext.domain.source import SourceLocator, SourceLocatorError

_SOURCE = "pandascore"


@dataclass(frozen=True, slots=True)
class ResolvedPandaScoreLocator:
    """Internal provider identity recovered from an opaque source locator."""

    kind: str
    provider_id: int
    parent_match_provider_id: int | None = None


class PandaScoreLocatorIndex:
    """Keep process-local PandaScore locator state shared by vNext capabilities."""

    def __init__(self) -> None:
        self._entries: dict[str, ResolvedPandaScoreLocator] = {}

    def make(self, kind: str, provider_id: int) -> SourceLocator:
        value = _locator_value(kind, provider_id)
        self._entries[value] = ResolvedPandaScoreLocator(kind=kind, provider_id=provider_id)
        return SourceLocator(source=_SOURCE, kind=kind, value=value)

    def remember_game_parent(self, game_provider_id: int, match_provider_id: int) -> None:
        value = _locator_value("game", game_provider_id)
        self._entries[value] = ResolvedPandaScoreLocator(
            kind="game",
            provider_id=game_provider_id,
            parent_match_provider_id=match_provider_id,
        )

    def resolve(self, locator: SourceLocator) -> ResolvedPandaScoreLocator:
        if locator.source != _SOURCE:
            raise SourceLocatorError(
                "source locator is not a PandaScore locator",
                details={"source": locator.source, "kind": locator.kind},
            )
        resolved = self._entries.get(locator.value)
        if resolved is None:
            raise SourceLocatorError(
                "source locator is not known to this runtime",
                details={"source": locator.source, "kind": locator.kind},
            )
        if resolved.kind != locator.kind:
            raise SourceLocatorError(
                "source locator kind does not match its runtime entry",
                details={"source": locator.source, "kind": locator.kind},
            )
        return resolved


def _locator_value(kind: str, provider_id: int) -> str:
    payload = f"{_SOURCE}\x1f{kind}\x1f{provider_id}".encode()
    return f"src:{sha256(payload).hexdigest()[:24]}"


__all__ = ["PandaScoreLocatorIndex", "ResolvedPandaScoreLocator"]
