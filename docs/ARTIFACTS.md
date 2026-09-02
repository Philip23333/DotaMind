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

## Esports search-result documents

An oversized `esports.search` page produces one `esports_search_result` Artifact:

```text
artifact_type = esports_search_result
schema_version = 1
source = pandascore
fetched_at
kind = esports_search_result
query     # complete validated public query
result    # complete source-shaped response page
```

The tool returns a bounded structural preview, `total_rows`, and the exact
ArtifactRef. Preview pointers use `artifact.read` dotted paths such as
`result.rows.2.matches`; the full response remains available through generic
read and grep. A failed write returns `artifact_error` rather than an
unrecoverable truncated result. Small pages stay inline and do not create an
Artifact.

## Production boundary

The recorded-game capability has three distinct layers:

```text
Tool -> GameDetailService -> OpenDotaAdapter
```

The Adapter performs transport and source-model validation.  The Service
validates public arguments, fetches through the Adapter, and externalizes the
complete validated document. Artifact storage is owned by the Service, not by
the Provider or Adapter.

The esports discovery seam follows the same boundary:

```text
Tool -> EsportsService -> EsportsProvider -> PandaScoreAdapter
```

The Provider chooses the allowed PandaScore discovery endpoint, filters, orders,
and enriches; the capability tool validates public arguments and externalizes an
oversized final response page. A failed final write must never produce a
truncated observation without an ArtifactRef.

For the same provider source, kind, and source identity, an unchanged identity
produces the same ArtifactRef.  A later fetch replaces the document at that
stable address with the current validated facts.

## Model-facing observation

An esports discovery result (when the seam is implemented) will contain:

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
artifact.grep(pattern, artifact_types?, scope?, ref?)
```

Artifact exploration has two generic model-facing primitives: read for known
ArtifactRefs and grep for corpus/content discovery. Grep may also receive an
exact ArtifactRef to search only that stored document. They observe stored
documents only, do not understand esports-specific semantics, and never make a
provider request. The historical GameSummary-specific `artifact.search` is not
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
