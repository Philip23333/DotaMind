"""Small injected-catalog resolvers for canonical artifact construction."""

from .ability import AbilityResolver
from .hero import HeroResolver
from .item import ItemResolver

__all__ = ["AbilityResolver", "HeroResolver", "ItemResolver"]
