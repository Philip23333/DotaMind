"""Localized ability resolution for GameSummaryArtifact version 4."""

from collections.abc import Mapping

from app.vnext.artifacts.game_summary_v4 import AbilityUpgrade
from app.vnext.domain.refs import AbilityUpgradeRef

from .localized import LocalizedName


class AbilityResolverV4:
    """Resolve catalog names while retaining the native source upgrade event."""

    def __init__(self, catalog: Mapping[int, LocalizedName]) -> None:
        self._catalog = catalog

    def resolve(self, ref: AbilityUpgradeRef) -> AbilityUpgrade:
        value = self._catalog.get(ref.valve_ability_id)
        return AbilityUpgrade(
            level=ref.level,
            time_seconds=ref.time_seconds,
            ability_id=ref.valve_ability_id,
            ability_name_en=value.name_en if value else None,
            ability_name_zh=value.name_zh if value else None,
        )


__all__ = ["AbilityResolverV4"]
