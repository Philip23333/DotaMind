"""Model-facing hero capabilities."""

from .guide import (
    HERO_GUIDE_DESCRIPTION,
    HeroGuideHandler,
    register_hero_guide_tool,
)

__all__ = ["HERO_GUIDE_DESCRIPTION", "HeroGuideHandler", "register_hero_guide_tool"]
