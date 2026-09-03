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
| Team constraint | exact Team identity uses a complete source corpus, reports not-found/ambiguous argument errors, and reuses a Provider-local bounded-lifetime index for repeated constraints; unique identities use AND semantics across `/teams/{id}/matches` results |
| Match enrichment | batch-scoped shared OpenDota evidence is loaded once per search/unique league; deterministic outcomes are retained and unavailable evidence degrades only dependent games to `resolution="unavailable"` |
| Artifact boundary | oversized final logical tool responses are externalized once in the current session under a fresh opaque ref; previews retain readable structural paths; a failed required write is `artifact_error` |
| Error mapping | invalid arguments, provider failure, and artifact failure map to the documented tool codes without secrets |

Focused implementation tests live under `apps/api/tests/vnext/` alongside the
capability.  Run the focused set before the full vNext non-agent-eval suite.

The recorded-game detail suite additionally checks:

| Concern | Required assertion |
| --- | --- |
| Default tool surface | Exactly `esports.search`, `game.detail`, `artifact.grep`, and `artifact.read` are model-visible; `artifact.search` is `unknown_tool` |
| Public schema | `game.detail` accepts exactly one positive `valve_game_id` |
| Source fidelity | Unknown top-level and nested OpenDota business fields survive Adapter and the complete logical response retrieved by `artifact.read` |
| Identity and failures | Returned `match_id` mismatch and OpenDota timeout/HTTP/schema failure are `provider_error`; externalization failure is `artifact_error` |
| Session isolation | Each oversized response receives a new `artifact:tool:*` ref; another session cannot read it |
| Generic retrieval | `artifact.read` and `artifact.grep` require one exact response/manual ref and have no source-specific behavior |

Esports-discovery acceptance returns when the new PandaScore-oriented tool seam
is implemented; it must not be rebuilt around the removed unified-search
contract.

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
follow returned opaque Artifact refs with `artifact.read/grep` when a bounded
`esports.search` preview omits needed details,
and distinguish:

- execution status;
- source business result and candidate count;
- resolution status for Valve IDs;
- whether the required evidence reached the final answer.

For esports query discipline, record the number of tool calls, model steps,
`unsupported_field`, `invalid_arguments`, and resource-manual reads. A query
must not guess an unestablished resource field before reading that resource's
manual, and must not retry an `unsupported_field` or `unsupported_scope` idea
without that manual. The index manual is not evidence for resource-specific
field support. Layer 3 agent evaluations additionally record calls made after
sufficient evidence and unsupported claims in the final answer. The target for
both metrics is zero. They should cover recent league matches, a specific
edition/stage, latest tournament status, and a multi-row result where
`artifact.grep` must not be used as an aggregation engine.

The evidence checks must reject exact scores inferred from counts, formats, or
a winner alone, and reject game-level claims without game-level evidence. Recent
match checks must verify scope-aware ordering: `past` descending,
`upcoming` ascending, and `running` with the running scope. Winner-name checks
must distinguish an explicit winner ID fact from an explicit ID-to-name mapping.

Model knowledge does not substitute for a fresh source observation when the
question asks for current esports information.
