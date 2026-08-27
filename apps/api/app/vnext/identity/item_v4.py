"""Localized item resolution for GameSummaryArtifact version 4."""

from collections.abc import Mapping

from app.vnext.artifacts.game_summary_v4 import CanonicalItem
from app.vnext.domain.refs import ItemRef

from .localized import LocalizedName


class ItemResolverV4:
    """Resolve native item IDs and provider item keys through catalog identities."""

    def __init__(
        self,
        catalog: Mapping[int, LocalizedName],
        item_key_to_id: Mapping[str, int] | None = None,
    ) -> None:
        self._catalog = catalog
        self._item_key_to_id = item_key_to_id or {}

    def resolve(self, ref: ItemRef) -> CanonicalItem:
        value = self._catalog.get(ref.valve_item_id)
        return CanonicalItem(
            id=ref.valve_item_id,
            name_en=value.name_en if value else None,
            name_zh=value.name_zh if value else None,
        )

    def resolve_key(self, item_key: str) -> CanonicalItem | None:
        """Resolve a provider-native item key through the injected identity map."""

        item_id = self._item_key_to_id.get(item_key.strip())
        if item_id is None:
            return None
        return self.resolve(ItemRef(valve_item_id=item_id))


__all__ = ["ItemResolverV4"]
