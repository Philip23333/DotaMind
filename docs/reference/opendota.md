# OpenDota Reference

## Role

OpenDota is a candidate source for resolved Valve-match detail and recorded
professional-player game data. It also provides league and team records needed
by cross-source identity resolution.

## Data boundary

OpenDota data is used only after a valid domain or Valve match reference exists.
It can provide match result, draft, scoreboard, player statistics, item data,
ability-upgrade information, and parse-status or coverage information when
available.

Provider data can be incomplete, delayed, unparsed, or inconsistent with another
source. The domain layer preserves those limits and never upgrades missing
records to inferred player performance or build facts.

## Identity use

League matches and team participation can disambiguate provider identities in
the PandaScore-to-Valve mapping. The resulting mapping remains an explicit
cross-source inference even when OpenDota supplies the final match detail.

## Maintenance

Endpoint availability, cache behavior, parse coverage, and field semantics are
provider facts. Confirm them against the active adapter and live responses before
making a new vNext contract.
