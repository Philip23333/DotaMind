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

## Core user journeys

- Ask what is happening in a tournament, what has finished, and what is next.
- Find a series or game and understand its result, draft, scoreboard, and
  player performance.
- Ask about a team, its next match, recent results, or roster.
- Follow a player from a match to their performance and build.
- Continue with references such as "game two", "that player", or "their previous
  match" without restating the whole question.

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
guarantee. `game.detail` remains contract-only and is not callable yet. “Parse
a game” in this scope means reading and
analyzing an existing game-detail record; submitting a replay for parsing is
not included. The profile query has not been verified against the live STRATZ
API.

## Product boundaries

Answers distinguish provider facts, identity inferences, and model interpretation.
The agent must use tools for current or specific facts and must not invent data
that no tool returned.

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
