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
sets `context_compaction_trigger_percent=1` and
`compaction_recent_history_bytes=4096`; these are pressure-test overrides, not
product recommendations.

The default shared limits are at most 12 model calls (including summary and
retry calls) and 180 wall-clock seconds for both questions together. CLI
overrides may lower or raise these bounds for a deliberate run. There are no
automatic provider retries beyond Runtime behavior, no repeated runs, and no
automatic profile sweep. Provider usage is reported separately for business
and summary requests; missing usage is unknown, byte estimates are not token
counts, and no cost is estimated without price data.

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
