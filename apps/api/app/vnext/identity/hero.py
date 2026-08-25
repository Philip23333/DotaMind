"""Hero-name resolution for canonical artifact construction."""

from collections.abc import Mapping

from app.vnext.artifacts.game_summary import Hero
from app.vnext.domain.refs import HeroRef


class HeroResolver:
    """Resolve a native hero ID against an injected name catalog."""

    def __init__(self, catalog: Mapping[int, str]) -> None:
        self._catalog = catalog

    def resolve(self, ref: HeroRef) -> Hero:
        return Hero(id=ref.valve_hero_id, name=self._catalog.get(ref.valve_hero_id))
