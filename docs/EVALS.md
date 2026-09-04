# Evals

## Goal

vNext evaluation checks externally visible capability behavior, source/provider
boundaries, bounded Artifact observation, and failure semantics.  A passing
tool execution is not enough: tests must assert the useful business result and
the provenance-bearing stored document.

## Deterministic test style

Provider contract tests use small inline PandaScore-shaped payloads and
`httpx.MockTransport`.  They do not depend on deleted large fixture directories
or on a live PandaScore account.  Each test owns only the source fields needed
to express its rule.

The isolated legacy `esports.search` suite preserves the retained native-query
implementation. It is not target-architecture acceptance and must not be read as
the public Agent contract. Its implementation-preservation coverage is kept in
`test_esports_search_tool.py`, `test_esports_search_observation.py`,
`test_pandascore_native_query.py`, `test_pandascore_query_validation.py`, and
`test_pandascore_manual_artifacts.py`, including source routing, native query
validation, bounded observations, Artifact externalization, and stable errors.

Focused implementation tests live under `apps/api/tests/vnext/` alongside the
capability.  Run the focused set before the full vNext non-agent-eval suite.

The recorded-game detail suite additionally checks:

| Concern | Required assertion |
| --- | --- |
| Default tool surface | Exactly `game.detail`, `artifact.grep`, and `artifact.read` are model-visible; legacy `esports.search` and `artifact.search` are `unknown_tool` |
| Public schema | `game.detail` accepts exactly one positive `valve_game_id` |
| Source fidelity | Unknown top-level and nested OpenDota business fields survive Adapter and the complete logical response retrieved by `artifact.read` |
| Identity and failures | Returned `match_id` mismatch and OpenDota timeout/HTTP/schema failure are `provider_error`; externalization failure is `artifact_error` |
| Session isolation | Each oversized response receives a new `artifact:tool:*` ref; another session cannot read it |
| Generic retrieval | `artifact.read` and `artifact.grep` require one exact response/manual ref and have no source-specific behavior |

The default-surface acceptance covers the temporary three-tool runtime. The
legacy `esports.search` tests remain isolated and are not model-surface
acceptance for the target resource-shaped migration.

## Live smoke tests

Live PandaScore smoke tests are separate from deterministic acceptance.  They
may validate a current endpoint, plan entitlement, pagination behavior, or a
real source payload captured under `docs/reference/`; they must not turn a
provider outage, expired credential, or changing esports schedule into a
deterministic unit-test failure.

When recording a live result, retain only sanitized provider business facts.
Never commit credentials, Authorization headers, raw request tokens, or a
complete response that contains material user data.

## Agent evaluations

Agent evaluations test composition and answer behavior after deterministic tool
contracts are already protected. During Phase A/B there is no
esports-discovery Agent acceptance because no esports discovery tool is
model-visible. Agent-level esports acceptance resumes after the six
resource-shaped tools are registered in Phase C. The currently visible Agent
surface should request source-backed facts and distinguish:

- execution status;
- source business result and candidate count;
- resolution status for Valve IDs;
- whether the required evidence reached the final answer.

Layer 3 evaluations may still record tool calls, model steps, invalid arguments,
and unsupported claims for migration comparison, but manual-first behavior is
not a future target contract. The target resource-shaped acceptance records
whether each tool's own JSON Schema expresses only its supported fields, has no
open `resource` selector, and exposes cross-resource relation fields only where
that resource supports them. It should cover recent league matches, a specific
edition/stage, latest tournament status, and a multi-row result where
`artifact.grep` must not be used as an aggregation engine.

The evidence checks must reject exact scores inferred from counts, formats, or
a winner alone, and reject game-level claims without game-level evidence. Recent
match checks must verify scope-aware ordering: `past` descending,
`upcoming` ascending, and `running` with the running scope. Winner-name checks
must distinguish an explicit winner ID fact from an explicit ID-to-name mapping.

Model knowledge does not substitute for a fresh source observation when the
question asks for current esports information.
