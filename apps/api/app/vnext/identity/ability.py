"""Ability-name resolution for canonical artifact construction."""

from collections.abc import Mapping

from app.vnext.artifacts.game_summary import AbilityUpgrade
from app.vnext.domain.refs import AbilityUpgradeRef


class AbilityResolver:
    """Resolve an ability name while retaining the source-native upgrade event."""

    def __init__(self, catalog: Mapping[int, str]) -> None:
        self._catalog = catalog

    def resolve(self, ref: AbilityUpgradeRef) -> AbilityUpgrade:
        return AbilityUpgrade(
            level=ref.level,
            time_seconds=ref.time_seconds,
            ability_id=ref.valve_ability_id,
            ability_name=self._catalog.get(ref.valve_ability_id),
        )
