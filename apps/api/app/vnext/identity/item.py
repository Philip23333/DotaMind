"""Item-name resolution for canonical artifact construction."""

from collections.abc import Mapping

from app.vnext.artifacts.game_summary import CanonicalItem
from app.vnext.domain.refs import ItemRef


class ItemResolver:
    """Resolve a native item ID against an injected name catalog."""

    def __init__(self, catalog: Mapping[int, str]) -> None:
        self._catalog = catalog

    def resolve(self, ref: ItemRef) -> CanonicalItem:
        return CanonicalItem(id=ref.valve_item_id, name=self._catalog.get(ref.valve_item_id))
