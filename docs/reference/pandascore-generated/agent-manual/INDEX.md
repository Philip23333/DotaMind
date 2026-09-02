<!--
DO NOT EDIT.
Generated from PandaScore endpoint snapshots.
-->

# PandaScore Dota 2 Query Manual

Use this manual when constructing esports search queries.

## Query model

Supported query operators:

- resource
- scope
- filter
- search
- range
- sort
- pagination

Different resources support different fields.

## Resources

| Resource | Supported scopes |
| --- | --- |
| [league](league.md) | all |
| [serie](serie.md) | all, past, running, upcoming |
| [tournament](tournament.md) | all, past, running, upcoming |
| [match](match.md) | all, past, running, upcoming |
| [team](team.md) | all |
| [player](player.md) | all |

## General rules

- `filter` uses exact/value filtering.
- `search` uses PandaScore search semantics.
- `range[field]` takes two values.
- Use `-field` for descending sort.
- IDs returned by previous results can be reused in later queries.
- Do not assume a field supported by one resource exists on another.
- When unsure, read the resource manual before querying.
