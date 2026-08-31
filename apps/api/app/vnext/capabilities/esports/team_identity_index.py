"""Complete PandaScore Team identity index for exact Match constraints."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.vnext.domain.common.models import normalize_text
from app.vnext.providers.pandascore.models import PandaScoreTeam


@dataclass(frozen=True, slots=True)
class TeamIdentityIndex:
    """Exact normalized Team identities, retaining every matching candidate."""

    by_key: dict[str, tuple[PandaScoreTeam, ...]]

    @classmethod
    def build(cls, teams: Iterable[PandaScoreTeam]) -> TeamIdentityIndex:
        candidates_by_key: dict[str, dict[int, PandaScoreTeam]] = {}
        for team in teams:
            for value in (team.name, team.acronym, team.slug):
                key = normalize_text(value or "")
                if key:
                    candidates_by_key.setdefault(key, {}).setdefault(team.provider_id, team)
        return cls(
            by_key={
                key: tuple(candidates.values()) for key, candidates in candidates_by_key.items()
            }
        )

    def lookup(self, query: str) -> list[PandaScoreTeam]:
        return list(self.by_key.get(normalize_text(query), ()))


__all__ = ["TeamIdentityIndex"]
