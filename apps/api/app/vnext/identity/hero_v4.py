"""Localized hero resolution for GameSummaryArtifact version 4."""

from collections.abc import Mapping

from app.vnext.artifacts.game_summary_v4 import Hero
from app.vnext.domain.refs import HeroRef

from .localized import LocalizedName


class HeroResolverV4:
    """Resolve a native hero ID against localized catalog identity facts."""

    def __init__(self, catalog: Mapping[int, LocalizedName]) -> None:
        self._catalog = catalog

    def resolve(self, ref: HeroRef) -> Hero:
        value = self._catalog.get(ref.valve_hero_id)
        return Hero(
            id=ref.valve_hero_id,
            name_en=value.name_en if value else None,
            name_zh=value.name_zh if value else None,
        )


__all__ = ["HeroResolverV4"]
