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
capabilities are proposed and later delivered.

The model may compose capabilities according to the question. No tool or tool
description requires a fixed sequence such as search, then detail, then read.
Provider selection, ID conversion, normalization, and cross-source mapping
happen inside domain and provider layers.

## Implemented Phase 2 surface

These are the four existing Phase 2 agent-visible tools. Their names and
independent domain capabilities remain unchanged. This list does not imply
that any artifact store or artifact retrieval capability exists.

| Tool | Purpose |
| --- | --- |
| `competitions.search` | Find a competition or edition |
| `competitions.list_matches` | List matches for a competition |
| `matches.search` | Find a series or game |
| `matches.get_detail` | Return detail for a resolved match or game |

They preserve explicit ambiguity, resolution, provenance, freshness, and
availability boundaries. No additional tool is required for a fixed scenario
workflow.

## Future target surface

The following table is a proposed contract, not a claim that these target
shapes are implemented. In particular, a future `matches.get_detail` view is
bounded: it would return identity, summary, available coverage, and artifact
references instead of the full underlying artifact.

| Tool | Purpose | Input | Proposed output | Boundary |
| --- | --- | --- | --- | --- |
| `competitions.search` | Find a competition or edition | Query, optional year | Competition candidates | Ambiguity remains explicit |
| `competitions.list_matches` | List a competition schedule | Competition reference, status or time scope | Scheduled, running, or completed match summaries | Schedules are volatile and bounded |
| `matches.search` | Find a series or game | Teams, competition, time, or query | Match candidates | Does not guess a unique match |
| `matches.get_detail` | Explain a resolved match or game | Match or game reference | Identity, bounded summary, available coverage, and artifact references | Full artifact content would not be returned by default |
| `teams.search` | Find a professional team | Query | Team candidates | Name collisions remain explicit |
| `teams.list_matches` | Show team schedule or recent results | Team reference, time scope | Bounded match summaries | No aggregated meta analysis |
| `teams.get_roster` | Show known roster context | Team reference | Players and roster metadata | Source freshness is disclosed |
| `players.search` | Find a professional player | Query, optional team context | Player candidates | Identity ambiguity remains explicit |
| `players.list_matches` | Show a player's match record | Player reference, time scope | Bounded matches and participation | Coverage depends on provider data |
| `players.get_match_performance` | Show one player's game performance | Player and game references | Bounded stats, hero, and result context | Only recorded game facts |
| `players.get_match_build` | Show one player's build | Player and game references | Bounded items, skill upgrades, talents, and timing | Missing parse data is explicit |
| `catalog.get_hero` | Explain a hero | Hero query or reference | Hero, abilities, and talents | Static facts only |
| `catalog.get_item` | Explain an item | Item query or reference | Item, recipe, and attributes | Static facts only |

## Future artifact retrieval capabilities

Artifact retrieval is an independent data-access capability proposed for a
future retrieval foundation. It is not a scenario tool and does not prescribe
how a question must be answered.

| Tool | Purpose | Input | Proposed output | Boundary |
| --- | --- | --- | --- | --- |
| `artifacts.search` | Find relevant information inside a canonical artifact | Artifact reference, query, optional section and limit | Bounded matching sections or references | Would not return the whole artifact or raw provider data |
| `artifacts.read` | Read a bounded section of a canonical artifact | Artifact reference, path, limit | Requested bounded data slice with coverage metadata | Reference, path, and size limits would be enforced |

The model decides whether the summary and coverage already answer the question
or whether a bounded retrieval call would be useful. Retrieval calls could be
made independently when a valid artifact reference is already available. If a
section is missing or unavailable, the response would preserve that state
rather than manufacture a value.

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
