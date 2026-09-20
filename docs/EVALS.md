# Evals

## Goal

Evaluation checks externally visible capability behavior, bounded Artifact
observation, generic runtime boundaries, and stable failure semantics. A passing
tool execution is not enough: tests must assert the useful result and the
provenance-bearing stored document.

## Deterministic test style

Tests use small inline payloads and local fakes. They do not depend on provider
accounts, live schedules, or credentials. Each test owns only the source fields
needed to express its rule.

The clean-slate baseline requires:

| Concern | Required assertion |
| --- | --- |
| Registry | The default registry is non-empty and every registered name starts with `artifact.` |
| Prompt | The Controller renders every registered Artifact tool and contains no removed domain rules |
| Query context | `ExecutionPlan.context` accepts only `{}` until a cross-tool contract is introduced |
| Artifact boundary | `artifact.read` and `artifact.grep` require one exact reference and remain schema-neutral |
| Runtime | Unknown tools, invalid arguments, handler failures, budgets, tracing, and persistence use stable generic behavior |

Focused tests live under `apps/api/tests/`. Run the baseline and generic runtime
tests before the full suite.

## Agent evaluations

There is no domain-agent acceptance while the clean-slate registry exposes only
Artifact tools. Domain acceptance resumes when a new closed capability is
registered with its own schema, provider boundary, deterministic tests, and
fresh live smoke coverage where needed.

Agent-level checks must verify that the model follows the rendered catalog,
uses only declared arguments and output references, stops when evidence is
sufficient, and does not claim facts unsupported by collected observations.

Task-plan generalization is evaluated across temporal, entity, player,
competition, hybrid, and single-deep cases. The eval does not prescribe exact
task keys or a fixed execution sequence; it evaluates bounded,
independently-completable result units.

Context Governance evaluations cover Runtime-triggered compaction within one
long user task, summary/boundary replacement, recent-message retention, bounded
FIFO Artifact locators, and same-session follow-ups. Original history and
Artifact bodies remain stored outside active context.

Check that only the current summary reaches execution and answer requests,
the current user message remains verbatim exactly once, and tool call/result
pairs stay valid. Failed or cancelled candidates must not change the effective
boundary. Locator eviction must not delete Artifacts; completed tasks must not
block rereads. Follow-ups retain recent observations with fresh execution state.
Verify session isolation and honest behavior when process-local state is lost.
Overflow recovery is bounded to one attempt for the unresolved incident and
must not repeat completed business tools.

Measure answer quality and omissions, complete-input peaks, summary/locator
cost, compaction/recovery counts, rereads, total tokens, and latency. Compare
against feasible uncompacted task baselines. Deterministic tests cover state
and protocol invariants; model traces assess summary quality and recovery.
Byte accounting is not a precise token count. No structured semantic summary
entities are added without evidence of a concrete behavioral failure.

Distinguish current behavior from target phases not yet accepted. The design,
stage exits, and acceptance matrix are maintained in
[`agent/context_governance_evidence_lifecycle.md`](agent/context_governance_evidence_lifecycle.md).

## Live smoke tests

Live smoke tests are separate from deterministic acceptance. They may validate a
current endpoint or real source payload only when a current integration requires
it. Provider outages, expired credentials, and changing schedules must not turn
into deterministic unit-test failures.

Never commit credentials, authorization headers, request tokens, or material
user data.
