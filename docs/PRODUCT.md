# Product

## Purpose

DotaMind is a Dota 2 esports agent. It answers questions about professional
competitions, series, games, teams, professional players, and the Dota objects
needed to understand those matches.

It is for fans, analysts, and viewers who want a trustworthy conversational
interface to current esports facts and match context rather than a dashboard of
generic game statistics.

## Core product surface

- Competition discovery, status, and schedule
- Series and game search, results, and match detail
- Team schedule, recent results, and roster context
- Professional-player match records and single-game performance
- Player builds, skill upgrades, talents, and item progression when data exists
- Hero, item, and ability information that explains a match
- Natural follow-up questions grounded in the actual conversation
- Optional web search for current external information, when enabled by the
  deployment

## Core user journeys

- Ask what is happening in a tournament, what has finished, and what is next.
- Find a series or game and understand its result, draft, scoreboard, and
  player performance.
- Ask about a team, its next match, recent results, or roster.
- Follow a player from a match to their performance and build.
- Continue with references such as "game two", "that player", or "their previous
  match" without restating the whole question.

## Hero guides (cache query implemented; refresh pipeline pending)

The hero-guide tool answers a request for one specified Valve hero ID and
position. Pub build data is the primary guide; recent professional matches for
the same hero and position provide separate practical examples. The two sources
remain distinguishable, and a professional example is not presented as
evidence that its player followed a particular Pub build. The query reads the
shared Redis cache only and does not trigger a D2PT request or refresh. When the
cache has not been populated, it reports the source as missing.

The current provider evidence is limited to a one-time D2PT connectivity and
payload probe for Sven (`hero_id=18`, position 1). Both sampled endpoints
returned one non-empty JSON build record in the tested WSL environment. The D2PT
client, parsers, Redis snapshots, and cache-only query capability are now
implemented. The query is registered only when the application injects its
existing Redis connection. This does not mean an all-hero cache has been
populated or a scheduled refresh has run.

This journey is a specified-hero guide lookup. It does not add an all-hero
strength ranking, matchup/counter analysis, or draft recommendation. Pub and Pro
partitions may be independently missing or stale; answers must identify which
source data is available and must not fill gaps with invented facts. A cache
snapshot is shown as stale after 36 hours or when its latest refresh attempt
failed; the stale threshold is a display rule, not the provider's statistics
window.

## Steam-account and game-detail scope

Users can look up a STRATZ player profile by Steam32 account ID when
`DOTAMIND_STRATZ_TOKEN` is configured. The account need not belong to a
professional player. DotaMind does not automatically associate it with a
PandaScore professional-player identity. With the same token configured,
`player.recent_games` can return a bounded latest-first sample for that exact
Steam32 account. A one-match live check confirmed that STRATZ's ID for the
provided match also resolves as the same OpenDota match ID. A live query for
one participant returned 20 rows newest-first; that older final was outside the
bounded sample. This is a single-account check, not a general availability
guarantee. `game.detail` reads an existing OpenDota game record and registers
only when `DOTAMIND_OPENDOTA_ENABLED=true`. Reading a record does not submit a
replay for parsing. The profile query has not been verified against the live
STRATZ API, and the new OpenDota client has not had a live request test.

For the account-to-game journey, a user can provide a Steam32 ID, inspect its
bounded recent-games list, select one returned `valve_game_id`, and request
that game's detail. The account's row in the detail must be matched by exact
`account_id`; names and other player attributes are not identity proof. A
follow-up such as “the second game” refers to the earlier list retained in the
conversation, not a refreshed list with potentially different ordering. The
agent does not fetch every listed game's detail automatically. Static hero and
item labels may be resolved from the bundled Valve catalog; unknown IDs remain
unknown. Missing timelines or purchase data are evidence gaps, not proof that
events or purchases did not occur.

## Product boundaries

Answers distinguish provider facts, identity inferences, and model interpretation.
The agent must use tools for current or specific facts and must not invent data
that no tool returned.

When Tavily MCP search is configured and available, the agent can search the web
and cite URLs actually returned by that search. Search snippets are observations,
not proof that a full page was read; search availability is optional and provider
failures are reported as missing evidence rather than silently substituted.

The product is organized around user value, not around whatever a provider API
happens to expose.

## Non-goals

vNext Core does not include:

- Global ranked meta or hero win-rate dashboards
- Lane analytics, matchup rankings, or synergy rankings
- Hero-strength ranking systems or Wilson-score ranking systems
- Draft recommendation engines or 5v5 scoring
- Provider-specific reports offered solely because a source supports them
- Data scraping or paid-provider workarounds as implicit fallback paths

Any future analytics capability requires a separate product decision and does
not inherit Legacy V3 analytics design.
