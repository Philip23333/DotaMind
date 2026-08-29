# Roadmap

## Phase 0 — Clean-slate documentation

Status: complete.

Goal: replace the Legacy V3 design tree with a small vNext documentation set.

## Phase 1 — Native Agent Runtime

Status: complete.

Goal: establish the minimal provider-neutral native tool-calling loop.

Delivered:

- provider-neutral model protocol;
- validated tool registry/dispatch;
- execution limits, deadlines, cancellation, stable errors;
- native streaming;
- session-neutral runtime.

## Phase 2 — Esports discovery and match resolution

Status: implemented in the older domain-tool shape; now entering capability
simplification.

Delivered:

- PandaScore-backed Series/Match discovery tools;
- deterministic PandaScore Game -> Valve match resolution;
- OpenDota resolved-game detail;
- Team/Player source-backed capabilities.

The existing `League -> Series -> Tournament -> Match -> Game` Domain hierarchy
and its object-specific refs are no longer the target abstraction for future
providers. The verified PandaScore source semantics and resolver remain useful;
the model-facing tool boundary is being simplified.

## Phase 2.x — Source-backed capability and Artifact simplification

Status: in progress.

Goal: expose a small set of broad observation capabilities, keep provider facts
source-attributed, and externalize large results without building a universal
cross-provider object model.

Historical infrastructure already delivered:

- GameSummary schema versions 3, 4, and 5;
- ArtifactStore memory/Redis retention;
- deterministic versioned ArtifactRef;
- automatic resolved-game Artifact production;
- `artifact.search`, `artifact.grep`, and `artifact.read`;
- generic ArtifactScopeStore.

These pieces proved the externalized-document model. The next work changes the
Tool/Provider boundary before extending the current canonical Domain/Artifact
schemas.

### Migration sequence

#### Commit A — source-backed `esports.search`

Define and implement the first capability contract:

- add opaque provider-scoped `SourceLocator`;
- add a thin source-attributed result envelope;
- expose one model-facing `esports.search` capability;
- use PandaScore as the only implementation;
- reuse existing verified PandaScore search/list methods internally;
- keep old Series/Match search tools temporarily for comparison/evals;
- do not add a provider registry/framework with only one implementation.

Acceptance: representative Series/Match discovery questions can be answered
through `esports.search`, source attribution is explicit, and no universal
League/Series/Tournament/Match DTO is required by the new tool.

#### Commit B — retire ontology-shaped esports tools

Migrate current uses of:

- `series.search`;
- `series.list_matches`;
- `matches.search`.

Use `SourceLocator` plus an optional `within` search constraint for continued
source-local navigation. After focused and real-model acceptance, remove old
tool registrations and canonical PandaScore navigation Ref machinery that no
remaining consumer needs.

Do not add `league.search`, `tournament.search`, or a replacement tool family.

#### Commit C — source-backed `game.detail`

Add one model-facing detailed-game capability:

```text
SourceLocator or valve_match_id
  -> deterministic source-to-Valve resolution when needed
  -> OpenDota detail implementation
  -> bounded result + ArtifactRef
```

Reuse the current resolver evidence rules. Keep OpenDota as an implementation
detail and return explicit `source=opendota` provenance.

After focused acceptance, retire `matches.get_detail` as the model-facing detail
surface.

#### Commit D — minimal Catalog tools

Add:

- `catalog.search`;
- bounded batch `catalog.lookup`.

Dynamic game-detail facts keep Valve-native IDs directly. Do not require
Artifact construction to translate every ID into localized names.

#### Commit E — simplify large-result externalization

Replace the old GameConstructionContext/construction-Ref/catalog-enrichment path
with the smallest source-backed Artifact document contract required by
`game.detail`.

Do not assume the replacement must be `GameSummaryArtifactV6`. Prefer a stable
outer document envelope with explicit source plus validated source-shaped facts.

Keep `artifact.grep` and `artifact.read` generic and provider-blind.

#### Commit F — delete obsolete normalization and identity machinery

After the replacement capabilities are accepted, delete unused:

- construction-only Hero/Item/Ability/event Ref wrappers;
- catalog resolvers used solely for old Artifact enrichment;
- canonical PandaScore navigation DTO/ref code with no retained consumer;
- old Series/Match tool handlers;
- compatibility glue no longer exercised by product/evals.

Delete incrementally. Do not retain dead abstractions for hypothetical future
providers.

#### Commit G — real-model acceptance and future-source test

Validate representative research questions through the actual capability
surface:

```text
esports.search
-> game.detail
-> artifact.grep/read
-> catalog.search/lookup when useful
-> answer
```

The model may choose another order. No fixed scenario workflow is added.

As an architecture acceptance test, document how a hypothetical second esports
or game-detail provider would join the existing capability while keeping its own
source-shaped facts. Do not implement a fake provider framework.

### Non-goals

- one model-facing tool namespace per provider;
- one tool per PandaScore hierarchy object;
- universal cross-provider League/Series/Tournament/Match DTOs;
- universal cross-provider game-detail DTOs;
- raw provider-private IDs as model-facing identity;
- semantic/vector search before demonstrated need;
- provider-specific Artifact grep/read logic;
- provider routing/plugin infrastructure before a second real provider exists.

### Acceptance

Phase 2.x is accepted when:

- PandaScore participates through `esports.search` rather than ontology-shaped
  model-facing tools;
- OpenDota participates through `game.detail` rather than an OpenDota-named tool
  or a mandatory universal detail DTO;
- large detail results remain outside model context and are generically
  searchable/readable;
- source provenance and provider failures remain explicit;
- Valve-native IDs and local Catalog remain separate reusable fact spaces;
- old construction/identity machinery is removed after replacement coverage is
  proven.

## Phase 3 — Team, player, and Catalog

Status: Team/Player capabilities implemented; minimal Catalog tools pending as
part of Phase 2.x.

Do not widen the current migration merely to make Team/Player symmetrical with
the new esports tool. Apply the same source-backed capability rule when a real
second provider or a concrete simplification need appears.

## Phase 3.5 — vNext Product Integration

Status: complete.

Delivered:

- request-bound vNext AgentRuntime streaming endpoint;
- browser-owned PostgreSQL session/transcript persistence;
- persisted User and Final Assistant dialogue;
- process-lifetime shared vNext services;
- deterministic visual enrichment after model response.

## Phase 4 — Conversation reliability and eval expansion

Status: in progress.

Delivered:

- bounded ConversationContextBuilder over the complete PostgreSQL transcript;
- failed-run trace retention and downloadable debugging evidence.

Add compaction, durable AgentRun/reconnect/replay, and broader provider-drift
infrastructure only when observed product failures justify them.

## Phase 5 — Product UX

Goal: present source-attributed facts, uncertainty, and structured data clearly
without moving gameplay reasoning out of the model.

## Phase 6 — Legacy deletion

Goal: remove remaining Legacy paths after vNext replacements are proven.

Acceptance: vNext passes its regression/eval suite without Legacy orchestration
or compatibility shims. The `pre-vnext-rewrite` tag remains the historical
reference.
