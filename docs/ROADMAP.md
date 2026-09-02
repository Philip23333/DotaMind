# Roadmap

## Guiding order

Work one capability boundary at a time:

```text
architecture confirmation
  -> one design unit
  -> implementation
  -> focused acceptance
  -> broader regression
```

Do not expand a capability into a provider-routing framework or a universal
esports DTO until a second real provider demonstrates that need.

## Current capability path

### 1. Esports discovery (PandaScore-oriented tool seam)

The former unified `esports.search` implementation was removed as part of the
vNext cleanup so the replacement is not constrained by it. The current
PandaScore-oriented tool seam provides validated native collection queries:

- One small semantic model-facing contract; no search-engine abstraction, no
  universal search DTO, no scenario routers.
- The model chooses entity types and composes multiple calls; the tool validates
  native query grammar and performs one provider request.
- Provider names, endpoints, pagination, and private IDs stay below the
  capability boundary. The PandaScore HTTP client lives at
  `app/vnext/providers/pandascore/` and is not deleted.
- Preserve PandaScore source-shaped rows; do not reintroduce canonical
  League/Series/Match/Team DTOs or source-locator navigation. Oversized
  response pages are externalized once as complete query/result Artifacts and
  exposed as bounded structural previews.
- Do not reintroduce the removed kind/`time_scope`/`teams` unified contract as
  the new schema; design from the current endpoint allowlist in
  `docs/reference/pandascore-endpoints.md`.

### 2. Recorded-game detail

Use `game.detail(valve_game_id)` for full recorded-game data.  It is a separate
capability from esports discovery and is currently implemented by OpenDota after
the required PandaScore-to-Valve resolution.

Keep provider-specific document shapes under the shared Artifact substrate.
Do not create an esports discovery `kind="game"` merely to reproduce a provider
endpoint.

### 3. Generic Artifact exploration

Keep `artifact.read` and `artifact.grep` generic. They retrieve already stored
evidence and never perform hidden provider fetches.

Use them before adding a source-specific detail tool.  A new tool needs a
distinct capability need, not merely a different field path in an Artifact.

### 4. Transitional deletion

Legacy or transitional navigation tools and canonical Ref hierarchies may remain
only while focused evaluations or a live correctness issue still depend on them.
After the replacement path is accepted, delete them instead of adding
compatibility shims.  Do not spend new work repairing an obsolete locator or
`within` path.

## Near-term acceptance

For each change to this path:

1. Verify the public schema and allowed PandaScore endpoints with deterministic
   inline-transport tests.
2. Verify source attribution, Artifact externalization, resolver status, and
   sanitized failure codes.
3. Run focused vNext tests, then the full non-agent-eval vNext suite.
4. Run a separate live smoke test only when a current provider behavior needs
   confirmation.

## Not planned now

- a multi-provider selection or routing framework;
- a universal esports hierarchy or Team DTO;
- Artifact tools that implicitly fetch PandaScore;
- model-facing provider-private ID inputs;
- scenario-specific workflows or prompt recipes for esports questions.
