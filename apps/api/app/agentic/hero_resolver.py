import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

HERO_CONSTANTS_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "heroes" / "dota2_heroes.yaml"
)
ResolutionStatus = Literal["resolved", "ambiguous", "not_found"]


@dataclass(frozen=True)
class HeroRecord:
    id: int
    name: str
    localized_name: str
    aliases: tuple[str, ...]


class HeroResolver:
    def __init__(
        self,
        heroes: list[HeroRecord],
        *,
        fuzzy_score_cutoff: float = 0.72,
        ambiguity_score_delta: float = 0.04,
        candidate_limit: int = 5,
    ) -> None:
        self.heroes = heroes
        self.fuzzy_score_cutoff = fuzzy_score_cutoff
        self.ambiguity_score_delta = ambiguity_score_delta
        self.candidate_limit = candidate_limit
        self._index = self._build_index(heroes)

    def resolve(self, query: str) -> dict[str, Any]:
        normalized = normalize_hero_key(query)
        if not normalized:
            return self._not_found(query)

        exact = self._index.get(normalized, [])
        if len(exact) == 1:
            return self._resolved(query, exact[0], method="exact")
        if len(exact) > 1:
            return self._ambiguous(query, exact, method="exact_alias")

        fuzzy = self._fuzzy_candidates(normalized)
        if not fuzzy:
            return self._not_found(query)

        best_score = fuzzy[0][1]
        close = [
            hero
            for hero, score in fuzzy
            if best_score - score <= self.ambiguity_score_delta
        ]
        if len(close) == 1:
            return self._resolved(query, close[0], method="fuzzy", score=best_score)
        return self._ambiguous(query, close, method="fuzzy", score=best_score)

    def _fuzzy_candidates(self, normalized: str) -> list[tuple[HeroRecord, float]]:
        scored_by_hero: dict[int, tuple[HeroRecord, float]] = {}
        for key, heroes in self._index.items():
            score = SequenceMatcher(None, normalized, key).ratio()
            if score < self.fuzzy_score_cutoff:
                continue
            for hero in heroes:
                current = scored_by_hero.get(hero.id)
                if current is None or score > current[1]:
                    scored_by_hero[hero.id] = (hero, score)

        scored = sorted(
            scored_by_hero.values(),
            key=lambda item: (item[1], item[0].localized_name),
            reverse=True,
        )
        return scored[: self.candidate_limit]

    @staticmethod
    def _build_index(heroes: list[HeroRecord]) -> dict[str, list[HeroRecord]]:
        index: dict[str, list[HeroRecord]] = {}
        for hero in heroes:
            keys = [hero.localized_name, hero.name.removeprefix("npc_dota_hero_")]
            keys.extend(hero.aliases)
            for key in keys:
                normalized = normalize_hero_key(key)
                if normalized:
                    bucket = index.setdefault(normalized, [])
                    if all(existing.id != hero.id for existing in bucket):
                        bucket.append(hero)
        return index

    def _resolved(
        self,
        query: str,
        hero: HeroRecord,
        *,
        method: str,
        score: float | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "resolved",
            "query": query,
            "hero": serialize_hero(hero),
            "candidates": [serialize_hero(hero)],
            "method": method,
            "score": score,
        }

    def _ambiguous(
        self,
        query: str,
        heroes: list[HeroRecord],
        *,
        method: str,
        score: float | None = None,
    ) -> dict[str, Any]:
        candidates = [serialize_hero(hero) for hero in heroes[: self.candidate_limit]]
        return {
            "status": "ambiguous",
            "query": query,
            "hero": None,
            "candidates": candidates,
            "method": method,
            "score": score,
        }

    @staticmethod
    def _not_found(query: str) -> dict[str, Any]:
        return {
            "status": "not_found",
            "query": query,
            "hero": None,
            "candidates": [],
            "method": "none",
            "score": None,
        }


def serialize_hero(hero: HeroRecord) -> dict[str, Any]:
    return {
        "hero_id": hero.id,
        "name": hero.name,
        "localized_name": hero.localized_name,
        "aliases": list(hero.aliases),
    }


def normalize_hero_key(value: str) -> str:
    lowered = value.strip().lower()
    lowered = lowered.replace("'", "")
    lowered = lowered.replace("-", " ")
    lowered = lowered.replace("_", " ")
    return re.sub(r"\s+", " ", lowered).strip()


@lru_cache
def load_default_hero_resolver() -> HeroResolver:
    return HeroResolver(load_hero_constants(HERO_CONSTANTS_PATH))


def load_hero_constants(path: Path) -> list[HeroRecord]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("heroes"), list):
        raise ValueError(f"Hero constants root must contain a heroes list: {path}")

    heroes = []
    for item in raw["heroes"]:
        if not isinstance(item, dict):
            raise ValueError(f"Invalid hero constants entry: {item!r}")
        heroes.append(
            HeroRecord(
                id=int(item["id"]),
                name=str(item["name"]),
                localized_name=str(item["localized_name"]),
                aliases=tuple(str(alias) for alias in item.get("aliases", [])),
            )
        )
    return heroes
