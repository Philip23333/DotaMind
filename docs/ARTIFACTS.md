# Artifacts

## Status

This document defines the vNext target contract for canonical artifacts and
bounded retrieval. It does not claim that an Artifact Store, artifact
persistence, or `artifacts.search` and `artifacts.read` are implemented.

## Definition

An artifact is defined as a canonical DotaMind data object that a future
artifact layer could create from normalized facts from one or more providers.
It answers:

    What data has been collected about this entity?

An artifact is not a provider response cache. Provider schemas and raw provider
JSON would be normalized below the artifact boundary. Canonical artifacts would
use DotaMind references, normalized values, provenance, and quality metadata.
They would not expose provider-specific identifiers.

## Canonical objects

Domain objects identify entities and express stable meaning:

- Competition
- Series or Match
- Game
- Team
- Professional Player
- Hero, Item, and Ability

Artifact objects would hold reusable, potentially sectioned data about those
entities:

- `GameArtifact`
- `PlayerMatchArtifact`
- `DraftArtifact`
- `TimelineArtifact`

These objects are data boundaries, not user-scenario workflows. Inventory,
economy, skill history, and similar sections would remain views of a suitable
artifact rather than separate scenario-specific capabilities.

## Examples

### GameArtifact

```text
GameArtifact
  artifact_ref: artifact:game:...
  identity:
    game_ref: game:...
    match_ref: match:...
  summary:
    teams: ...
    winner: ...
    duration: ...
  sections:
    players: ...
    draft: ...
    economy: ...
    inventory: ...
    events: ...
  quality:
    source: [normalized competition and match sources]
    fetched_at: ...
    schema_version: ...
    coverage: [scoreboard, draft, inventory]
    completeness: partial
    missing: [replay_timeline]
```

The example intentionally contains canonical references and normalized
sections, not provider IDs or raw payloads. A section may be absent, partial,
or stale; the quality metadata would preserve that fact.

## Artifact vs DTO

| | Domain DTO | Artifact |
| --- | --- | --- |
| Primary purpose | Communicate a bounded domain result | Store or retrieve reusable canonical data |
| Primary question | What is this? | What data is available about this? |
| Typical size | Small and bounded | Potentially large and sectioned |
| Intended lifetime | Request or operation scope | Reusable cache or store scope; backend is not prescribed here |
| Default model exposure | Suitable as a bounded tool view | Not exposed in full; referenced and read in bounded slices |
| Contents | Identity, normalized facts, resolution state | Canonical sections, provenance, coverage, completeness, and missing data |

An artifact reference would be a handle to canonical data, not permission to
place the whole artifact into model context.

## Quality metadata

The proposed canonical artifact contract would preserve, when applicable:

- `source`: the provider or normalized source set behind the facts
- `fetched_at`: when the source data was obtained
- `schema_version`: the canonical artifact schema version
- `coverage`: sections or fact families available
- `completeness`: complete, partial, or otherwise limited state
- `missing`: known sections or facts that are unavailable

Quality metadata would let a model distinguish “not present in this artifact”
from “not checked” or “not known.” It would prevent a short summary from
implying that all underlying data was collected.

## Access pattern

The proposed target boundary is a bounded tool view containing identity,
summary, coverage, and an artifact reference. The model would decide whether
that view is enough to answer the question. If more detail is useful and a
retrieval capability is available, the model could choose a bounded search or
read against the reference.

For example, a question about a player's inventory could be answered from the
summary if inventory coverage were already present. Otherwise, the model could
choose an artifact search or read for the relevant section and limit the
returned slice. If the reference or section were unavailable, the retrieval
result would preserve that state.

This is an access pattern, not a required A-to-B-to-C workflow. Calls could be
made independently when a valid reference is already available; an artifact
could be reused across turns; and a tool could answer directly without
retrieval. The model would choose when to retrieve. Code would enforce
reference validity, access boundaries, response limits, and data quality. Agent
Runtime would transport the conversation but would not own artifact storage or
lifecycle.

## Proposed retrieval capabilities

The future retrieval surface would consist of independent data-access
capabilities:

- `artifacts.search` would find bounded matching sections or references within
  a canonical artifact.
- `artifacts.read` would return a bounded section or path from a canonical
  artifact.

Neither capability would return the entire artifact by default. Neither
capability would be a scenario tool, and neither would require the other to be
called first. The capabilities are proposed for Phase 3 and are not currently
implemented.
