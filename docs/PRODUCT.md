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
