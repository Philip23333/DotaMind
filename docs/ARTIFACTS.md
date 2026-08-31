# Artifacts

## Purpose

An Artifact stores a validated, source-backed JSON-like document outside the
model context.  It prevents a large provider result from becoming a large tool
response while keeping the complete evidence available for generic retrieval.

Artifacts are not a universal Dota object graph and do not fetch from a provider
when they are read.

## Source document contract

The current source-document form is:

```text
SourceDocumentArtifact
  source
  kind
  facts
```

`facts` is the complete validated provider business document. It can preserve
provider-private IDs as evidence, but those IDs are not model-facing inputs.
Pydantic may perform lossless structural normalization, but DotaMind does not
proactively remove business fields; allowed unknown provider fields and complete
Match `games[]` remain in the document. Transport headers, credentials, request
tokens, and pagination envelopes never enter it.

For PandaScore Match documents, the retained game rows additionally contain the
deterministic Valve-resolution outcome:

```text
valve_game_id: int | null
resolution: <resolver decision status>
```

This is an enrichment of the retained source document, not a synthetic
GameSummary schema.

`GameDetailArtifact` is the separate exact-game form:

```text
artifact_type = game_detail
schema_version = 1
source = opendota
valve_game_id
fetched_at
facts  # complete validated OpenDota-shaped document
```

Its canonical reference is `game_detail:1:<valve_game_id>`. The source model
validates identity while retaining allowed unknown business fields, including
nested OpenDota facts. It is not a GameSummary or an input to a GameSummary
builder.

## Production boundary

`esports.search` has three distinct layers:

```text
Tool -> EsportsSearchService -> EsportsSearchProvider -> PandaScoreAdapter
```

The Adapter performs transport and source-model validation.  The Provider
chooses the allowed PandaScore discovery endpoint, filters, orders, enriches
Match games, and returns internal source entities.  The Service validates public
arguments, deduplicates, applies the final limit, and externalizes only those
final records.

Artifact storage is therefore owned by the Service, not by the PandaScore
Provider. A failed final write never creates a record without an ArtifactRef.
If at least one final write succeeds, search returns those valid records with
`partial=true` and one sanitized `artifact_externalization_failed` warning per
failed entity. If every final write fails, search returns `artifact_error`.
Already written Artifacts are retained; there is no transaction or rollback.

For the same provider source, kind, and source identity, an unchanged identity
produces the same ArtifactRef.  A later fetch replaces the document at that
stable address with the current validated facts.

## Model-facing observation

The `esports.search` result contains:

```text
source
kind
artifact_ref
facts
partial
warnings
```

`facts` is a generic bounded observation:

- safe top-level scalar facts are retained;
- long strings are bounded;
- nested objects and collections become structural summaries;
- top-level field count is bounded;
- provider-private identity does not become an observation field.

To inspect the full document, use the generic Artifact primitives:

```text
artifact.read(artifact_ref, path?)
artifact.grep(pattern, artifact_types?, scope?)
```

Artifact exploration has two generic model-facing primitives: read for known
ArtifactRefs and grep for corpus/content discovery. They observe stored documents
only, do not understand esports-specific semantics, and never make a provider
request. The historical GameSummary-specific `artifact.search` is not
model-visible; exact recorded-game retrieval uses `game.detail(valve_game_id)`.

The same generic read and grep primitives explore GameDetailArtifacts. They do
not re-fetch OpenDota.

## Failure semantics

The public error surface remains small and sanitized:

```text
invalid_arguments
provider_error
artifact_error
```

Provider failures expose attribution such as `source` and `kind`, but not URLs,
credentials, raw upstream payloads, or exception traces. A partial-success
warning exposes only stable `code`, `source`, and `kind`; a complete Artifact
externalization failure likewise exposes only source and kind.

## Historical contracts

Historical GameSummary artifact versions remain frozen.  They demonstrate
storage, deterministic references, and generic retrieval, but do not prescribe
the source-backed discovery contract.  Do not mutate them to imitate the
current SourceDocumentArtifact shape.
