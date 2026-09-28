# Evals

Evaluation separates deterministic mechanical acceptance from real-model
quality review. A successful tool execution or completed Runtime workflow is
not, by itself, evidence that an answer is correct.

## Current tool surface

The normal vNext registry composes the generic Artifact tools, the currently
accepted esports capabilities, and request-scoped task planning when a
`TaskStateCoordinator` is supplied. The model-facing names are:

```text
artifact.grep
artifact.read
esports.league.search
esports.series.search
esports.series.teams
esports.tournament.search
esports.match.search
esports.team.search
esports.player.search
web.search                 # only when Tavily MCP discovery succeeds
task.plan                 # when task-state coordination is enabled
task.checkpoint           # when task-state coordination is enabled
```

The Context Governance evaluation adds only its local `fixture.edition.lookup`
fixture tool to that evaluation's registry. It does not register live esports
providers, and it does not change the product registry.

## Three evaluation layers

1. **Deterministic tests** use local fakes and fixed payloads to verify schemas,
   Artifact bounds and retrieval, Runtime state transitions, context accounting,
   failure behavior, and tracing. They make no provider calls.
2. **Real model with fixed synthetic data** evaluates model behavior against
   stable, explicitly synthetic tournament records. The Context Governance
   harness uses real Runtime, SessionHistory, task-state tools, Artifact
   externalization, and `artifact.read` / `artifact.grep`; only the model API is
   live. The fixture is not TI history and must not be reported as real esports
   evidence.
3. **Real model with real data sources** evaluates the end-to-end product
   against live capability providers and current esports data. This is a later
   evaluation step; provider volatility and outages are not deterministic test
   failures.

## Context Governance harness

Run commands from `apps/api`. Without `--execute`, the command validates the
selected profile and fixture, prints a redacted run summary, and makes no model
call or output artifacts:

```bash
UV_CACHE_DIR=/tmp/dotamind-uv-cache uv run --locked --no-sync python -m \
  tests.vnext.evals.context_governance_runner \
  --profile pressure \
  --output-dir /tmp/dotamind-context-eval/dry-run
```

To explicitly allow one bounded real-model evaluation, add `--execute` and use
a new output directory:

```bash
UV_CACHE_DIR=/tmp/dotamind-uv-cache uv run --locked --no-sync python -m \
  tests.vnext.evals.context_governance_runner \
  --profile pressure \
  --output-dir /tmp/dotamind-context-eval/run-001 \
  --execute
```

Each invocation runs exactly one profile (`baseline`, `current`, or `pressure`)
and the same two fixed follow-up questions in one session. Profiles are not
automatically iterated. `current` and `pressure` require a configured context
window. `baseline` disables automatic capacity management but the evaluator
client applies the same business output-token cap as other profiles. `pressure`
sets `context_compaction_test_trigger_percent=1` and a recent-history target
equivalent to 4096 serialized bytes, rounded up using the configured
`context_estimate_bytes_per_token` (2048 estimated tokens at the default ratio
of 2); these are pressure-test overrides, not product recommendations. The
`baseline` profile clears both the configured context window and test trigger.
`current` preserves actual configuration, including any explicitly configured
test percentage, so it does not necessarily represent the pure production
threshold. `pressure` reports its effective test percentage and recent-history
budget in the run report and manifest.

With no test override, production compaction starts when the estimated input
exceeds `context_window_tokens - compaction_reserve_tokens`. A test percentage
is rounded up from the input capacity remaining after the current request's
output reserve and safety margin; the effective threshold is the earlier of
the production and test thresholds. Capacity estimates use configured UTF-8
bytes-per-token ratios rather than an exact tokenizer. The summary input is
still limited by `compaction_max_input_bytes` (currently 256 KiB), regardless
of the configured model window.

The default shared limits are at most 12 model calls (including summary and
retry calls) and 180 wall-clock seconds for both questions together. CLI
overrides may lower or raise these bounds for a deliberate run. There are no
automatic provider retries beyond Runtime behavior, no repeated runs, and no
automatic profile sweep. Provider usage is reported separately for business
and summary requests; missing usage is unknown, byte estimates are not token
counts, and no cost is estimated without price data.

`DOTAMIND_COMPACTION_MAX_RETRIES` applies only to classified transient summary
errors, independently per summary segment; every actual retry is a separate
model call charged to this shared evaluation budget. Retry waits consume the
existing Runtime stage deadline. Truncation and other deterministic summary
failures do not retry, and summary retries do not add another provider-overflow
recovery allowance.

An executed run creates `manifest.json`, `calls.jsonl`, `traces.json`, and
`report.md`. Existing files with those names are never overwritten. Requests,
responses, usages, errors (type only), durations, and partial traces are kept
for review; credentials, authorization headers, full settings, and authenticated
URLs are not recorded. Failed and budget-terminated runs retain collected
artifacts and exit nonzero. A pressure run without a successful compaction says
that it did not evaluate post-compaction model behavior.

Review the actual answers, evidence observations, and traces manually. The
report's checklist starts as **待人工评审**; a completed workflow does not mark
the answer correct. For a real-model run, confirm the selected model, configured
window, output artifacts, and spend limits before passing `--execute`.

The runner reads model and AgentLimits configuration using
`VNextSettings.from_env()`. It does not edit `.env`, infer a provider's actual
window, or make the local token heuristic an exact tokenizer. Real evaluation
results do not become product defaults without a separate review.

## General agent checks

Agent-level evaluation should verify that the model follows the rendered tool
catalog, uses declared arguments and returned references, stops when evidence
is sufficient, and does not claim facts unsupported by collected observations.
Task-plan generalization covers temporal, entity, player, competition, hybrid,
and single-deep cases without prescribing exact task keys or a fixed retrieval
sequence. A deterministic checkpoint-source regression also covers eight
synthetic inline match records under the 12 KiB inline bound: the current task
checkpoints them by their original query call ID, advances to the second task,
and reaches a final answer without `artifact.read` or creating an Artifact.
Companion checks reject externalized previews, control results, failures,
receipts, deferred results, stale IDs, and cross-task ownership while retaining
the existing raw `artifact.read` checkpoint path. These checks verify Runtime
source eligibility and lifecycle only; checkpoint success does not certify
business facts.

### Steam player and game-detail checks

Deterministic contract tests cover strict Steam32 and Valve game-ID inputs,
closed outer schemas, provenance literals, timezone-aware retrieval timestamps,
profile-presence semantics, recent-game count and duplicate-ID bounds, and
lossless JSON-compatible source fields. A composition check passes a game ID
from a recent-game result directly into the detail input. MockTransport tests
exercise both STRATZ player queries and their source validation/error paths,
Artifact externalization/retrieval, and token-gated registration without
network access; shared-client cancellation cleanup remains covered by the
profile/client regression tests. A live cross-check for `8960882635` matched
STRATZ `Match.id` with OpenDota `match_id`, start time, and duration. A raw live
`player.matches` query for one participant returned 20 rows in nonincreasing
timestamp order with only that player's row; the supplied match was older than
the returned sample. This is one-account evidence, not a universal guarantee.
`player.profile` and `player.recent_games` register with a STRATZ token;
`game.detail` registers only when OpenDota is explicitly enabled.
`game.detail` is covered by deterministic OpenDota MockTransport tests and is
opt-in at composition; no live OpenDota request was made for this
implementation. The earlier cross-source ID observation is limited to
`8960882635`. Later live or fixture-backed
cross-source evaluation must verify any proposed relationship between a
Steam32 account and a PandaScore professional player from explicit evidence;
the shared appearance of a player or event is not sufficient. These tests do
not establish general current STRATZ availability or every source business
meaning.

The account-to-game workflow tests use the real Runtime, registry, session
history, Artifact externalization/read path, and local Valve catalog with
scripted model responses and synthetic provider data. They verify selected
Valve IDs, exact `account_id` matching, ordinal follow-ups against the prior
list, and preservation of missing or conflicting source values. These tests
verify orchestration and evidence handling only; they do not establish that a
real model will choose the tools correctly or produce an accurate analysis.
No real STRATZ, OpenDota, or model request is made by this workflow suite.

Context Governance evaluation measures answer omissions, complete-request
peaks, summary and locator overhead, successful compactions, recovery attempts,
Artifact rereads, provider-reported tokens, and latency. A provider-confirmed
context-window overflow has a shared allowance of **at most one recovery per
user request**; execution and primary answer share it, while summary calls and
degraded answers do not start recovery. Recovery does not replay completed
business tools.

Deterministic tests protect state and protocol invariants. Traces from real
models assess summary quality and recovery behavior; byte accounting remains a
heuristic input measure rather than a precise token count. The stage status and
known limitations are maintained in
[`agent/context_governance_evidence_lifecycle.md`](agent/context_governance_evidence_lifecycle.md).

## Live source checks

Live source smoke tests are separate from both deterministic tests and the
fixed-fixture model evaluation. Use them only for a concrete current integration
question. Provider outages, expired credentials, and changing schedules must
not turn into deterministic test failures.

Never commit credentials, authorization headers, request tokens, or material
user data.

## Hero guide evaluation (cache query implemented; refresh and live acceptance pending)

The D2PT probe recorded in [`reference/d2pt.md`](reference/d2pt.md) is a live
connectivity and sample-shape check for one Sven Pub row and one Sven Pro row.
It is not evidence of a full-cache refresh, scheduled execution, parser coverage
for every hero/position, or model answer quality.

The current offline acceptance covers strict DTO inputs, independent Pub/Pro
metadata, source-shaped JSON preservation, byte/hash/shape checks for the two
fixed raw response fixtures, deterministic HTTP-client behavior through an
injected fake opener, Pub/Pro fixture parsing, and the standalone Redis cache.
Client tests cover request URLs and headers, timeout and response-size bounds,
status/error handling, JSON and minimal schema validation, and response closure.
Parser tests cover the observed Sven fields and counts, all-record ordering,
source-position evidence, strict type and identity validation, all-or-nothing
failure, and deep-copy behavior. Cache tests use a fake Redis to verify whole
snapshot replacement, one-command HSET/HGETALL shapes, Pub/Pro key isolation,
raw bytes/source rows/DTO round-trips, failure retention, valid-empty snapshots,
corruption errors, and input/output mutation isolation. Service and tool tests
cover sections, matching, staleness, source metadata, partial read failures,
structured errors, conditional registration, composition injection, and large
result Artifact reads. Application wiring is exercised with fake external
resources. These checks make no network, live Redis, database, or model call;
they do not establish all-hero or all-position parser coverage, deployment
persistence, or AOF recovery.

Remaining acceptance layers are separate:

1. **Refresh coordination:** a clock-controlled test verifies the daily
   03:00 Asia/Shanghai schedule, serial request behavior with a one-second wait
   after each response, shared manual/scheduled entry point, and duplicate-run
   prevention. It does not wait for wall-clock 03:00 or call D2PT.
2. **Redis deployment persistence:** a separate deployment acceptance checks
   the configured Redis AOF and volume across restart. Fake Redis tests do not
   establish this behavior.
3. **Real full refresh:** a separately authorized live-provider acceptance
   verifies the configured hero/position coverage, cache publication, and
   source status. A successful one-hero probe or fixture parser test cannot
   stand in for this check.
4. **Real-model answer:** a separate evaluation checks whether the model answers
   from the cached Pub guide and Pro examples, keeps the sources distinct, and
   avoids unsupported statistical or causal claims. It is not implied by a
   successful provider refresh.

### Tavily MCP smoke check

The offline smoke command is dry unless `--execute` is passed:

```bash
cd apps/api
UV_CACHE_DIR=/tmp/dotamind-uv-cache uv run --locked --no-sync python -m scripts.smoke_tavily_mcp
```

With explicit `--execute`, it performs one startup-style tool discovery and one
bounded search for official TI 2026 information, then prints only status,
source URLs, and elapsed time. It does not exercise a live language model. Do
not run it as part of deterministic tests.

## Product Runtime trace recording

Set `VNEXT_TEST_RECORDING_ENABLED=true` in the API environment to record
successful, failed, and cancelled product chat executions. It defaults to
`false`; when disabled, the existing failure-diagnostic recording remains
available. Enabling full test recording requires `DOTAMIND_REDIS_URL` at API
startup. `DOTAMIND_VNEXT_TRACE_TTL_SECONDS` controls retention and defaults to
72 hours.

Trace records are scoped to the browser and chat session. The expanded
**会话 Trace** panel in chat lists metadata for the 100 most recent records and
offers a manual refresh. A trace can also be downloaded from its completed or
failed assistant message while that message retains its trace metadata. A record
that expires between listing and download returns HTTP 410.

The downloaded ZIP contains `manifest.json` (recording mode, Runtime outcome,
IDs, and timestamps), `trace.json` (the Runtime trace and recorded tool
observations), `model-calls.jsonl` (application-level `ModelRequest` and
`ModelResponse` records when full test recording is enabled), and
`artifact-manifest.json`. It does not contain the complete temporary Artifact
store or raw provider HTTP traffic. Diagnostic-only records may omit full model
call bodies.

`RunTrace.status` describes the Runtime execution: `completed`, `failed`, or
`cancelled`. A completed Runtime trace stays `completed` if persisting its chat
turn later fails; the chat response reports `chat_store_error` separately.
Recording or trace download failures do not replace the original answer or
Runtime error.
