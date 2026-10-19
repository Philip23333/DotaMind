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
In particular, esports.match.search games[].pandascore_game_id must be resolved
through esports.game.resolve; it cannot be renamed or copied into valve_game_id.

A resolved game-resolution result may select a sole candidate with identity
warnings. Read its selection_basis, warnings and evidence before using the ID;
these warnings do not prohibit this lookup. This tool returns facts for the
requested Valve ID and does not independently verify its esports association.
Preserve material association uncertainty when interpreting or reporting facts.

The sole game-fact structure is report: six modules in ONE Artifact. There is
no public data member or internal-DTO retrieval route. Each module has a Chinese
title explaining its scope:
- report.overview: match result, teams and draft.
- report.player_statistics: minute_snapshots and final_players for income,
  level, K/D/A and farming; team_economy_timeline for source gold/XP advantages;
  player_histories for precise level_events and cumulative experience_timeline.
- report.equipment_and_skills: minute_snapshots for inventory, neutral items and
  permanent upgrades; final_players for final_loadout and same-Artifact
  purchase_events_path / ability_upgrade_events_path into this module's
  player_histories, which retain purchases, inventory, neutral, skill and buff events.
- report.support_contributions: minute_snapshots for known support counts;
  final_players for support totals and an events_path to this module's
  player_histories (precise events and totals with provenance).
- report.hero_damage.matrix: attacker-to-target damage and reverse received view.
  player_relations retain kill/healing relations and unassociated damage facts.
- report.events: separate hero_kills_and_deaths, buybacks, building_destructions,
  roshan_kills, aegis_pickups and other_objectives lists with confirmed facts;
  first_blood preserves the explicit reports and any source disagreement.
Use the module for the requested topic; do not read equipment or support tables
just to compare income. Every player row binds its own identity. Each minute table
binds its own time_seconds/time_label; never join players by array position.
For equipment at 30:00, select report.equipment_and_skills.minute_snapshots
whose time_seconds is 1800; its inventory_observation already selects only source
observations at or before that boundary. All minute state values belong to the
snapshot minute; their original observation timestamps are omitted from the minute
view. Use the snapshot time for display. A later observation is future data,
even if closer in seconds. Use the corresponding report module's player_histories
for deeper follow-ups; do not request internal DTO or raw source data.

Hero, item, ability, and event-unit objects
include confirmed IDs where applicable and English/Chinese names from local
catalogs; no separate Catalog call is needed just to decode these entities.
The result uses STRATZ as primary with fixed OpenDota supplements inside the tool.
provider identifies the primary source; sources, report.coverage.groups and event
source_paths attribute the actual facts and retrieval times. You do not need
another Provider lookup to fill these predefined supplemental groups.
Label-resource versions are separate from match-source provenance.
final_loadout uses explicit final source slots, not the minute inventory observation.
Support action ward_placed means this player placed the ward; ward_killed_by_player
means this player destroyed a ward, not that this player's own ward was destroyed.
purchase_record counts observed records, not item quantities. scope=known_events
and scope=source_total have different completeness and are kept separate.
Read report.coverage for limitations; its affected-field paths target report.
The report shows level instead of raw XP; unknown minute assists stay null.
Final cumulative_gold_earned is floor(GPM * formal duration / 60), a derived value;
death_gold_lost is the program sum of all linked explicit death-loss amounts.
known_death_gold_lost is the known-amount subtotal, including unknown-time deaths
whose loss is known; death_gold_lost_count counts deaths with known amounts,
not deaths with known times. Neither is the earned-income/net-worth gap. Cells do not
have to sum to final hero_damage. Module event histories retain their actual times;
minute snapshots do not expose separate observation times.
report.overview.match.match_date is the Beijing calendar date (Asia/Shanghai), so
it may differ from a source UTC date. report.overview.match.score contains
Radiant/Dire hero-kill counts, not series game wins.
report.player_statistics.team_economy_timeline has records with time_seconds,
time_label, radiant_gold_adv and radiant_xp_adv bound to the same minute. Query by
time_seconds rather than aligning separate arrays. radiant_gold_adv preserves the
source gold-advantage metric; do not relabel it as a net-worth difference.
Minute player_statistics cumulative_gold_earned is cumulative earned income,
not wallet balance or remaining net worth; history cumulative_experience is cumulative XP.
Minute net_worth is intentionally excluded. final_stats.earned_gold_net_worth_gap
requires reliable same-final-time inputs and may be null; it is not pure death loss.
known_deaths counts only normalized deaths with known times through that sample;
final_stats.deaths stays the source final total. Check report.coverage.death_counts for
unknown-time facts and missing events. Do not treat a partial known count as a total.
report.coverage.death_counts.unaccounted_deaths is the final total not covered by matched
death facts; it does not count deaths with an unidentified killer.
Equipment-history purchase_events, inventory_events and ability_upgrade_events are separate
source observations. Purchases do not prove assembly, delivery or inventory.
Use explicit objective events: a gold reason named ROSHAN is not a Roshan kill.
Game-relative time fields include program-generated display labels such as
time_label and duration_label (MM:SS, preserving negative and fractional seconds).
Minute timelines and event lists contain records with their own time_seconds and
time_label; do not align timestamps with a separate array of metric values.
Use these labels for display; use the original seconds to match, sort, or calculate.

Missing fields or unconvertible identifiers do not mean an event did not occur
or that a value was zero. Inspect report.coverage for missing data, original unmapped
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
