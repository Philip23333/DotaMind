"""Item-name resolution for canonical artifact construction."""

from collections.abc import Mapping

from app.vnext.artifacts.game_summary import CanonicalItem
from app.vnext.domain.refs import ItemRef


class ItemResolver:
    """Resolve a native item ID against an injected name catalog."""

    def __init__(
        self,
        catalog: Mapping[int, str],
        item_key_to_id: Mapping[str, int] | None = None,
    ) -> None:
        self._catalog = catalog
        self._item_key_to_id = item_key_to_id or {}

    def resolve(self, ref: ItemRef) -> CanonicalItem:
        return CanonicalItem(id=ref.valve_item_id, name=self._catalog.get(ref.valve_item_id))

    def resolve_key(self, item_key: str) -> CanonicalItem | None:
        """Resolve a provider-native item key through an injected identity map."""

        item_id = self._item_key_to_id.get(item_key.strip())
        if item_id is None:
            return None

        return self.resolve(ItemRef(valve_item_id=item_id))
