# Tools

## Design rules

Agent-visible tools are independent Dota domain capabilities. They accept
domain references or user-facing queries and return normalized, bounded views
of domain data. They do not expose provider endpoints, provider identifier
conversion, raw provider payloads, or a hard-coded multi-step workflow.

Tool descriptions state only capability, input, output, and material data
limits. A tool result does not necessarily contain the complete artifact
content. Large or sectioned data is intended to be exposed through canonical
artifact references and independent retrieval capabilities when those
capabilities are available.

The model may compose capabilities according to the question. No tool or tool
description requires a fixed sequence such as search, then detail, then read.
Provider selection, ID conversion, normalization, and cross-source mapping
happen inside domain and provider layers.

## Implemented Phase 2 and Artifact Retrieval Surface

These are the six implemented agent-visible tools. They remain independent
capabilities; the artifact tools do not create a required workflow around the
match tools.

| Tool | Purpose | Important contract |
| --- | --- | --- |
| `competitions.search` | Find a competition or edition | Preserves candidate ambiguity |
| `competitions.list_matches` | List matches for a competition | Returns bounded schedule facts |
| `matches.search` | Find a series or game | Does not guess a unique match |
| `matches.get_detail` | Return detail for a resolved match or game | Resolved games include `valve_match_id` and guarantee local artifact production |
| `artifact.search` | Find stored GameSummary artifacts | Accepts canonical Valve IDs; returns refs and missing IDs without reading or producing |
| `artifact.read` | Read a bounded canonical artifact view | Accepts an exact ref, structural path, and bounded list pagination |

The domain tools preserve explicit ambiguity, resolution, provenance, freshness,
and availability boundaries. `matches.get_detail` production is owned by the
application composition boundary, not by `MatchService` or the model.

## Future target surface

The following capabilities remain proposed and are not implemented.

| Tool | Purpose | Input | Proposed output | Boundary |
| --- | --- | --- | --- | --- |
| `teams.search` | Find a professional team | Query | Team candidates | Name collisions remain explicit |
| `teams.list_matches` | Show team schedule or recent results | Team reference, time scope | Bounded match summaries | No aggregated meta analysis |
| `teams.get_roster` | Show known roster context | Team reference | Players and roster metadata | Source freshness is disclosed |
| `players.search` | Find a professional player | Query, optional team context | Player candidates | Identity ambiguity remains explicit |
| `players.list_matches` | Show a player's match record | Player reference, time scope | Bounded matches and participation | Coverage depends on provider data |
| `players.get_match_performance` | Show one player's game performance | Player and game references | Bounded stats, hero, and result context | Only recorded game facts |
| `players.get_match_build` | Show one player's build | Player and game references | Bounded items, skill upgrades, talents, and timing | Missing parse data is explicit |
| `catalog.get_hero` | Explain a hero | Hero query or reference | Hero, abilities, and talents | Static facts only |
| `catalog.get_item` | Explain an item | Item query or reference | Item, recipe, and attributes | Static facts only |

## Artifact Inspection Tools

These implemented independent data-access capabilities let the model decide
whether a stored canonical artifact is useful. Neither tool is a scenario
workflow, and neither requires the other to be called first.

| Tool | Inputs | Output | Boundary |
| --- | --- | --- | --- |
| `artifact.search` | `artifact_type=game_summary`, up to 100 canonical Valve match IDs | `refs` and ordered `missing_valve_match_ids` | Existence checks only; no content read, provider call, or production |
| `artifact.read` | Exact `ArtifactRef`, optional dotted path, `offset`, `limit` | Outline or serialized bounded value with list bounds | Object fields and list indexes only; list limit is at most 100 |

With `path=null`, `artifact.read` returns top-level scalar metadata and one-level
section descriptors. A dotted path may address object fields and positional list
indexes; invalid paths remain explicit errors. A missing reference remains an
explicit tool error rather than triggering discovery or production.

Retrieval failures preserve stable model-visible categories: `artifact_not_found`
for a missing reference, `artifact_path_not_found` for an invalid structural path,
and `artifact_type_mismatch` when stored artifact metadata does not match the
provided reference. Unexpected failures remain `tool_execution_error`.

## Response boundaries

- Return canonical identity, summary, provenance, freshness, coverage, and
  explicit missing data where relevant.
- Prefer bounded lists, summaries, section references, and slices over complete
  large objects.
- Make truncation or incomplete coverage explicit.
- Never place raw provider JSON or provider-specific identifiers in a
  model-facing response.
- Keep inventory, economy, skill history, and similar sections as artifact
  views rather than creating one scenario tool for each question.
- Add a new capability only for an independent domain or data-access need with
  explicit evaluation coverage.
