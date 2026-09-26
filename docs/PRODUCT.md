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

## Planned Steam-account and game-detail scope

The next player-data slice is intended to let a user supply a Steam32 account
ID to inspect source-provided profile data and recent games, then read existing
single-game details for analysis. The account need not belong to a professional
player. DotaMind will not automatically associate it with a PandaScore
professional-player identity. “Parse a game” in this scope means reading and
analyzing an existing game-detail record; submitting a replay for parsing is
not included. These contracts are not registered in the product tool catalog
yet, so users cannot call these capabilities at this stage.

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
