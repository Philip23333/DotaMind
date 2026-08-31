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

The core search suite covers:

| Concern | Required assertion |
| --- | --- |
| Public schema | `kind` required; exactly six kinds; no legacy `within`, locator, `recent`, `all`, or Game discovery input |
| Endpoint allowlist | each kind reaches its intended PandaScore discovery route; no Game discovery endpoint is called |
| Lifecycle | dedicated lifecycle endpoint rows are not status-filtered again; Team-to-Matches uses correct local filtering; ordering and `truncated` stay explicit |
| Query | full source-document text can match embedded League/Series/Tournament/Opponent facts; native name filtering cannot cause a false negative |
| Team constraint | exact Team identity reports not-found/ambiguous argument errors; unique identities use AND semantics across `/teams/{id}/matches` results |
| Match enrichment | a single Match-level resolver call; deterministic outcomes are retained and OpenDota failure degrades every game to `resolution="unavailable"` |
| Artifact boundary | only final, deduplicated results are externalized; all writes success is non-partial; partial success contains valid records and warnings; all writes failing is `artifact_error` |
| Error mapping | invalid arguments, provider failure, and artifact failure map to the documented tool codes without secrets |

Focused implementation tests live under `apps/api/tests/vnext/` alongside the
capability.  Run the focused set before the full vNext non-agent-eval suite.

The recorded-game detail suite additionally checks:

| Concern | Required assertion |
| --- | --- |
| Default tool surface | Exactly `esports.search`, `game.detail`, `artifact.grep`, and `artifact.read` are model-visible; legacy `artifact.search` is `unknown_tool` |
| Public schema | `game.detail` accepts exactly one positive `valve_game_id` |
| Source fidelity | Unknown top-level and nested OpenDota business fields survive Adapter, Artifact, and `artifact.read` |
| Identity and failures | Returned `match_id` mismatch and OpenDota timeout/HTTP/schema failure are `provider_error`; write failure is `artifact_error` |
| Artifact identity | `game_detail:1:<valve_game_id>` is stable; public and professional games use the same Artifact type |
| Generic retrieval | `artifact.read` and `artifact.grep` read source-document and game-detail Artifacts without source-specific behavior |

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
contracts are already protected.  They should request source-backed facts,
follow returned ArtifactRefs with `artifact.read/grep` where details are needed,
and distinguish:

- execution status;
- source business result and candidate count;
- resolution status for Valve IDs;
- whether the required evidence reached the final answer.

Model knowledge does not substitute for a fresh source observation when the
question asks for current esports information.
