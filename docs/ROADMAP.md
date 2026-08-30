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

### 1. Esports discovery

Keep `esports.search` as the sole broad esports discovery entry point.

- Require `kind`: League, Series, Tournament, Match, Team, or Player.
- Keep `teams` as a Match-only exact-identity AND constraint.
- Keep `time_scope` only for Series, Tournament, and Match.
- Keep query as complete source-document textual discovery; do not narrow it to
  provider name search unless that is provably semantics-preserving.
- Store final result documents as Artifacts and return ArtifactRefs plus bounded
  observations. Preserve usable records as partial success when only some final
  Artifact writes fail.
- Preserve PandaScore source-shaped facts; do not reintroduce canonical
  League/Series/Match/Team DTOs or source-locator navigation.
- Enrich Match game rows with a canonical Valve ID only through the existing
  deterministic resolver.

### 2. Recorded-game detail

Use `game.detail(valve_match_id)` for full recorded-game data.  It is a separate
capability from esports discovery and is currently implemented by OpenDota after
the required PandaScore-to-Valve resolution.

Keep provider-specific document shapes under the shared Artifact substrate.
Do not create `esports.search(kind="game")` merely to reproduce a provider
endpoint.

### 3. Generic Artifact exploration

Keep `artifact.read`, `artifact.grep`, and `artifact.search` generic.  They
retrieve already stored evidence and never perform hidden provider fetches.

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
