"""Model-facing lookup for one existing Valve game record."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.vnext.capabilities.game.detail import GameDetailInput, GameDetailResult
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

GameDetailHandler = Callable[[GameDetailInput], Awaitable[GameDetailResult]]

GAME_DETAIL_DESCRIPTION = """\
Look up one existing Dota 2 Game by its positive Valve single-game ID. The ID
may be explicitly provided by the user, returned by player.recent_games, or
returned as valve_game_id by a resolved esports.game.resolve result. A PandaScore
Match, Series, or Game ID is not a Valve Game ID and cannot be passed here.

A resolved game-resolution result may select a sole candidate with identity
warnings. Read its selection_basis, warnings and evidence before using the ID;
these warnings do not prohibit this lookup. This tool returns facts for the
requested Valve ID and does not independently verify its esports association.
Preserve material association uncertainty when interpreting or reporting facts.

Returns eight governed sections: match, draft, players, economy, builds,
events, interactions, and coverage. Hero, item, ability, and event-unit objects
include confirmed IDs where applicable and English/Chinese names from local
catalogs; no separate Catalog call is needed just to decode these entities.
The result uses STRATZ as primary with fixed OpenDota supplements inside the tool.
provider identifies the primary source; sources, coverage.groups and event
source_paths attribute the actual facts and retrieval times. You do not need
another Provider lookup to fill these predefined supplemental groups.
Label-resource versions are separate from match-source provenance.
data.match.match_date is the Beijing calendar date (Asia/Shanghai), so it may differ
from a source UTC date. data.match.score contains Radiant/Dire hero-kill counts, not
series game wins. data.economy.radiant_gold_adv preserves the source gold-advantage
metric; do not relabel it as a net-worth difference.
players[].minute_timeline.cumulative_gold_earned is cumulative earned income,
not wallet balance or remaining net worth; cumulative_experience is cumulative XP.
Minute net_worth is intentionally excluded. final_stats.earned_gold_net_worth_gap
requires reliable same-final-time inputs and may be null; it is not pure death loss.
known_deaths counts only normalized deaths with known times through that sample;
final_stats.deaths stays the source final total. Check coverage.death_counts for
unknown-time facts and missing events. Do not treat a partial known count as a total.
coverage.death_counts.unaccounted_deaths is the final total not covered by matched
death facts; it does not count deaths with an unidentified killer.
Build purchase_events, inventory_events and ability_upgrade_events are separate
source observations. Purchases do not prove assembly, delivery or inventory.
Use explicit objective events: a gold reason named ROSHAN is not a Roshan kill.
Game-relative time fields include program-generated display labels such as
time_label and duration_label (MM:SS, preserving negative and fractional seconds).
Use these labels for display; use the original seconds to match, sort, or calculate.

Missing fields or unconvertible identifiers do not mean an event did not occur
or that a value was zero. Inspect coverage for missing data, original unmapped
scalar identifiers, and source conflicts. The result is not necessarily a
complete event timeline, and this tool does not request replay parsing. Large
results are stored as an Artifact; read only the needed section or player path.
The raw provider response cannot be retrieved from this result.

When analyzing a particular Steam32 account, locate its player row by exact
identity.account_id; do not substitute a row based on nickname, hero, team, or slot.
"""


def register_game_detail_tool(registry: ToolRegistry, lookup: GameDetailHandler) -> None:
    async def handler(args: GameDetailInput) -> GameDetailResult:
        return await lookup(args)

    registry.register(
        ToolDefinition(
            name="game.detail",
            description=GAME_DETAIL_DESCRIPTION,
            input_model=GameDetailInput,
            output_model=GameDetailResult,
            handler=handler,
            read_only=True,
            parallel_safe=True,
            metadata={"game": "dota2", "domain": "game", "provider": "stratz"},
        )
    )


__all__ = ["GAME_DETAIL_DESCRIPTION", "GameDetailHandler", "register_game_detail_tool"]
