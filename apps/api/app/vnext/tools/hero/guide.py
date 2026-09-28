"""Model-facing query for cached Dota 2 hero guides."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.vnext.capabilities.hero.guide import HeroGuideInput, HeroGuideResult
from app.vnext.capabilities.hero.service import HeroGuideQueryError
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.errors import StructuredToolError
from app.vnext.tools.registry import ToolRegistry

HeroGuideHandler = Callable[[HeroGuideInput], Awaitable[HeroGuideResult]]

HERO_GUIDE_DESCRIPTION = """\
Look up the cached Dota 2 guide for one Valve hero ID and position (1 through 5).
Choose `all`, `items`, `skills`, or `pro_examples` with `section`. Pub builds are
the primary guide; Pro results are separate examples from recent professional
matches. Pub item builds and skill sequences are independent candidates, not
paired routes. Skill sequences may cover only some skill points and are not a
complete level-by-level plan. Either source can be missing or stale; a cache miss
does not trigger a refresh. Source statistics may use different units and must
not all be described as percentages. Totals count hero-position candidates before
section projection. Returned entries include English and Chinese names from the
local Valve catalog, with source and snapshot version in `catalog_version`. An
`unknown` name means the catalog did not resolve that ID; it does not mean the
source event is absent. Zero-valued skill events are preserved without an
asserted ability name. Do not call `catalog.lookup` for IDs already included in
this result. Large results may be stored as an Artifact for further reading with
artifact.read or artifact.grep.
"""


def register_hero_guide_tool(registry: ToolRegistry, lookup: HeroGuideHandler) -> None:
    async def handler(args: HeroGuideInput) -> HeroGuideResult:
        try:
            return await lookup(args)
        except HeroGuideQueryError as exc:
            raise StructuredToolError(
                "tool_execution_error",
                "Hero guide cache could not be read.",
                {"pub_error": exc.pub_error, "pro_error": exc.pro_error},
            ) from None

    registry.register(
        ToolDefinition(
            name="hero.guide",
            description=HERO_GUIDE_DESCRIPTION,
            input_model=HeroGuideInput,
            output_model=HeroGuideResult,
            handler=handler,
            read_only=True,
            parallel_safe=True,
            metadata={"game": "dota2", "domain": "hero", "provider": "d2pt"},
        )
    )


__all__ = ["HERO_GUIDE_DESCRIPTION", "HeroGuideHandler", "register_hero_guide_tool"]
