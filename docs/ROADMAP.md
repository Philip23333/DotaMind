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

### 1. Esports discovery (resource-shaped migration)

The migration proceeds in four phases:

- Phase A: hide the legacy universal `esports.search` entry from the default
  Agent registry while retaining its executor, capabilities, observations,
  Artifact behavior, and isolated tests.
- Phase B: define one closed schema per PandaScore resource from the generated
  capability manuals. Resource relation IDs may be inputs only where the
  corresponding resource contract supports them.
- Phase C: register the six resource-shaped tools:
  `esports.league.search`, `esports.serie.search`,
  `esports.tournament.search`, `esports.match.search`,
  `esports.team.search`, and `esports.player.search`.
- Phase D: after the new path is accepted, remove the legacy universal search
  implementation and its migration-only runtime discipline.

The target keeps provider names, HTTP routes, auth, wire pagination, and adapter
details below the capability boundary. It preserves complete PandaScore
source-shaped facts and uses bounded temporary Artifacts for oversized results.
Do not build a provider router, universal esports DTO, or scenario workflow as a
substitute for the six closed resource contracts.

### 2. Recorded-game detail

Use `game.detail(valve_game_id)` for full recorded-game data.  It is a separate
capability from esports discovery and is currently implemented by OpenDota after
the required PandaScore-to-Valve resolution.

Keep provider-specific document shapes in complete logical tool responses.
Do not create an esports discovery `kind="game"` merely to reproduce a provider
endpoint.

### 3. Generic Artifact exploration

Keep `artifact.read` and `artifact.grep` generic. They retrieve one exact stored
session response or manual and never perform hidden provider fetches.

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
