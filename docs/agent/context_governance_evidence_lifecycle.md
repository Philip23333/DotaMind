# Context Governance / Evidence Lifecycle

## Status and authority

This document is the design baseline for the next Context Governance phase.
When a later implementation design conflicts with an older v1 document, this
document defines the target semantics. The older documents remain useful for
the currently implemented boundaries and link back here where their scope is
extended.

The design deliberately separates the current implementation from the target:
the existing Artifact Observation Lifecycle, Context Accounting, Lease, Budget,
Checkpoint, and Answer Resolver behavior remains valid until the corresponding
phase below is implemented and accepted.

## 1. Background

The Agent Runtime already has:

- TaskPlan / TaskItem;
- the Artifact system;
- Evidence Lease;
- Materialization Budget;
- Checkpoint;
- Answer Resolver; and
- Current Task Focus.

These components have established that plans can cover complex questions,
Artifacts and leases can manage large results, the materialization budget can
bound active raw evidence, and Answer Resolver can close FULL, PARTIAL, and
FAILURE executions.

The remaining architectural problem is that context lifetime is implicitly
bound to task completion:

```text
TaskPlan -> TaskItem -> task completion -> Checkpoint -> release raw
```

Models naturally continue querying to avoid omissions. Task completion is
therefore not a stable context-cleanup signal. Checkpoints can arrive late,
multiple task items can accumulate raw retrieval before the first checkpoint,
and the Materialization Budget can degrade into a hard blocker for hybrid work.

The goal of this design is:

> Decouple context lifetime from Task Completion and govern it through an
> Evidence Lifecycle.

## 2. Core decision

The old abstraction is:

```text
Task Completion Checkpoint
```

The new abstraction is:

```text
Evidence Compression + Evidence Lifecycle
```

Raw Evidence may leave active context when it has been reliably absorbed into a
traceable Evidence Summary. Summary Commit and Raw Release are separate events.

```text
Raw Evidence
    | semantic compression
    v
Evidence Summary
    | runtime validation
    v
Summary Committed
    | independent raw lifecycle decision
    v
Raw retained or released
```

## 3. Three context layers

### 3.1 Raw Evidence

Raw Evidence is data directly produced or materialized by a tool: match JSON,
series collections, roster results, or tournament data. It is large, often low
density, useful for local analysis, and should have a short active lifetime.
Artifacts remain available for later generic retrieval or audit.

The first lifecycle states are:

```text
ACTIVE_RAW
RELEASED
```

Raw Evidence must not be the default primary input to Answer Context.

### 3.2 Evidence Summary

An Evidence Summary is the structured knowledge state the Agent has absorbed
from raw observations. It is much smaller, can remain active across later
retrieval, preserves source references, and can be used directly by Answer
Context. It is not an untyped model note; it is a traceable intermediate
knowledge state.

### 3.3 Answer State

Answer State is the evidence view consumed by the final answer:

```text
Evidence Summaries
    + Coverage / Gap State
    + a small amount of still-necessary Raw Evidence
```

The final answer should not default to re-reading every raw Artifact.

## 4. TaskPlan positioning

TaskPlan remains, but its semantic role is a Coverage Map rather than an
execution script. It describes the knowledge dimensions the user's question
needs, guides acquisition and summarization, and helps Answer Resolver classify
FULL or PARTIAL coverage.

For example, a multi-year team question may have coverage units `xg_2023`
through `xg_2026`, each with dimensions such as `tournament_results`,
`ti_result`, and `roster`. The plan does not require the model to execute these
nodes in rigid serial order.

TaskPlan must not become a workflow scheduler. Partitioning remains aligned with
independently completable result units, not retrieval stages.

## 5. Evidence Summary model

The first Summary model is intentionally small:

```python
EvidenceSummary:
    id
    coverage_key
    claims
    source_refs
    created_at

SummaryClaim:
    dimension
    value
    source_refs
    status
```

Example:

```json
{
  "dimension": "ti_result",
  "value": {"placement": "7th-8th"},
  "status": "confirmed",
  "source_refs": [{"artifact_id": "artifact_ti_2023"}]
}
```

The first version must not collapse to `summary: str`; Runtime needs to know
which dimensions were compressed, which remain missing, and which Artifact
facts support each claim.

## 6. Semantic and Runtime boundaries

The Model owns semantic reasoning:

```text
Raw Evidence -> understanding -> Structured Claims
```

It identifies events, seasons, rosters, results, and aggregate claims.

Runtime owns deterministic validation:

- source Artifacts exist;
- sources belong to the CompressionRequest;
- source references are legal;
- required dimensions are represented;
- Summary schema is valid; and
- lifecycle state permits the commit.

Semantic correctness belongs to the Model. Referential correctness belongs to
Runtime.

## 7. CompressionRequest

Compression is requested through a typed request, not natural-language pressure
instructions:

```python
CompressionRequest:
    id
    reason
    coverage_key
    source_artifact_ids
    required_dimensions
    target_bytes | None
```

The initial reasons are:

```text
coverage_ready
context_pressure
answer_finalization
manual
```

`preserve_raw_ids` is deliberately not part of v1. The current Artifact
lifecycle is artifact-granular, not fragment-granular. Until Artifact slicing,
derived Artifacts, or partial materialization exist, Runtime can only keep or
release a whole Artifact.

## 8. Summary Commit is not Raw Release

Summary Commit makes source Artifacts release-eligible; it does not release all
sources automatically.

```text
SummaryCommitted
    -> source Artifacts become release-eligible
    -> Runtime evaluates each Artifact independently
    -> KEEP or RELEASE
```

An Artifact that is still needed for direct inspection remains `ACTIVE_RAW` even
after its Summary is committed. An already-consumed Artifact may be released.

The smallest release unit is always a complete Artifact:

```text
artifact_a -> keep
artifact_b -> release
```

This version does not release `artifact_a[0:95]` while retaining
`artifact_a[95:100]`.

## 9. Two-phase Summary Commit

Summary generation and release follow this protocol:

```text
CompressionRequest
        |
        v
SummaryCandidate
        |
        v
Runtime Validation
     +--+--+
     |     |
   fail   pass
     |     |
     |     v
     | SummaryCommitted
     |     |
     |     v
     | release eligibility evaluation
     |
     v
keep ACTIVE_RAW
```

If validation fails, the source raw evidence remains available.

Summary lifecycle states are:

```text
PENDING
ACTIVE
INVALID
```

## 10. Compression triggers

The first design has three Runtime triggers plus a manual trigger.

### Coverage-ready

When a coverage unit has a stable, semantically useful group of raw evidence,
Runtime may issue `CompressionRequest(reason=coverage_ready)`. This does not
mean the TaskItem is complete; it means a durable knowledge state is worth
creating.

### Context pressure

The Materialization Budget evolves from only a hard limiter into a pressure
signal:

```text
pressure high
    -> find compressible evidence
    -> CompressionRequest
    -> release eligible raw
    -> retry admission
```

The hard limit remains the final guardrail. If nothing is compressible or the
compressed state still exceeds the bound, the existing deny/defer behavior is
retained.

### Answer finalization

Before Answer Resolver, Runtime may convert a large raw working set into
Evidence Summaries plus a small retained raw set to reduce Answer token
variance.

### Manual

Phase 1 implementation starts with manual compression to validate the complete
closed loop. Automatic triggers are subsequent phases.

## 11. ContextPressureController

ContextPressureController answers only whether proactive compression is needed.
It does not generate summaries, judge claims, decide task completion, or release
Artifacts.

Its inputs may include active materialized bytes, incoming estimate, current
focus, Artifact size and age, coverage key, and Summary availability. Its output
is one of:

```text
NONE
NORMAL
HIGH
CRITICAL
```

Current Task Focus remains a retention and compression-selection signal, not a
task-completion signal.

## 12. Compression selection

Pressure handling must not simply evict the largest Artifact; that may be the
Artifact currently being analyzed. The selector considers:

```text
current_focus_key
coverage_key
artifact_size
materialization_age
existing_summary
```

Recommended priority:

```text
stable raw set from the same coverage
    > non-current-focus evidence
    > evidence already read and understood
    > large Artifact
    > old Artifact
```

## 13. Coverage runtime state

No large Coverage Manager is introduced in v1. Existing TaskItem runtime
metadata may grow into:

```python
TaskItemRuntimeState:
    key
    available_dimensions
    summarized_dimensions
    active_raw_ids
    summary_ids
```

This lets Runtime distinguish what is available, summarized, still raw, and
missing without inferring those facts from prose.

## 14. Answer Resolver

Answer Resolver evolves from raw-oriented to summary-oriented input:

```python
AnswerContext:
    summaries
    retained_raw
    coverage
    gaps
```

The existing `FULL`, `PARTIAL`, and `FAILURE` resolution states remain. The
resolver prefers Evidence Summaries and supplements them with retained raw only
when needed. Source references remain available for traceability.

## 15. Runtime events

The first event vocabulary stays intentionally small:

```text
CompressionRequested
SummaryProduced
SummaryCommitted
RawEvidenceReleased
```

Do not add workflow-style progress events such as
`CompressionStarted`, `CompressionCandidateSelected`, or
`SummaryValidated` unless a concrete diagnostic need is demonstrated.

## 16. Mapping from current to target abstractions

| Current abstraction | Target positioning |
| --- | --- |
| TaskPlan | Coverage Map |
| TaskItem | Coverage Unit |
| Checkpoint | Progress semantics; no longer the core context cleanup boundary |
| Artifact | Raw Evidence Container |
| Evidence Lease | Raw access / ownership lifecycle |
| Materialization Budget | Context pressure plus hard-wall fallback |
| Current Task Focus | Retention / compression selection signal |
| Evidence Summary | Persistent intermediate knowledge |
| Answer Resolver | Summary-oriented evidence resolver |

## 17. Checkpoint positioning

Checkpoint remains useful for task and execution progress. It is not removed in
the first phase, but its raw cleanup responsibility is progressively removed.

Old association:

```text
Task complete -> checkpoint -> release raw
```

Target association:

```text
Evidence compressed -> Summary committed -> raw independently released
```

Task Completion and Context Lifecycle become separate state transitions.

## 18. Materialization Budget semantics

The hard invariant remains:

```text
materialized bytes <= hard budget
```

The target control flow is:

```text
incoming materialization
    -> soft pressure threshold exceeded?
    -> request compression
    -> retry admission
    -> hard bound still exceeded?
    -> deny / defer
```

Budget becomes a governor while retaining its final protection role. This
document does not authorize removing the current hard admission bound.

## 19. Explicit v1 non-goals

The first lifecycle implementation does not include:

- recursive summaries;
- summaries of summaries;
- cross-coverage Summary merge;
- Summary aging, expiry, or refresh;
- semantic deduplication;
- cross-task shared summaries;
- Artifact slicing;
- derived Artifacts;
- partial Artifact release;
- automatic replan;
- complex subagents;
- token-level optimization; or
- model-controlled Artifact deletion.

These remain future work until the basic Evidence Lifecycle is accepted.

## 20. Implementation phases

### Phase 1 — Summary foundation

Add `EvidenceSummary`, `SummaryClaim`, a Summary Store, and deterministic
validation. Do not change Budget or TaskPlan behavior and do not automatically
release raw evidence.

### Phase 2 — Manual compression loop

Implement:

```text
CompressionRequest -> Evidence Summary -> Runtime validation
    -> Summary Commit -> Artifact-level release decision
```

Prove that Summary Commit does not automatically release all source raw.

### Phase 3 — Answer Resolver integration

Make Answer Resolver prefer Summary and supplement with ACTIVE_RAW as needed.
Validate answer quality, FULL/PARTIAL/FAILURE, and source traceability.

### Phase 4 — Context pressure integration

Connect Materialization Budget to ContextPressureController:

```text
pressure high -> compression -> retry admission -> fallback defer
```

### Phase 5 — Weaken Checkpoint dependency

After the lifecycle is stable, reduce the association between Task Completion
and Raw release. Checkpoint retains progress semantics but no longer owns the
Raw lifecycle.

## 21. Live evaluation goals

The existing live matrix remains the acceptance surface.

### Full T8

In addition to first checkpoint step, measure the first useful compression step.
It should occur materially earlier than Task Completion.

### Team temporal

The target is:

```text
xg_2023 raw -> xg_2023 Summary -> release unnecessary raw -> xg_2024
```

### 10-team roster

Raw cleanup should not require the model to find one special checkpoint source.
The model should produce a legal Summary while Runtime validates references.

### Hybrid

Hybrid is the core acceptance case. The target is continued retrieval through
multiple compression/release cycles even before the first TaskItem is complete.

## 22. Core invariants

1. Summary validation failure leaves source Raw available.
2. Summary Commit is not automatic source Raw release.
3. Raw release unit is a complete Artifact until slicing exists.
4. Runtime validates references; the Model interprets semantics.
5. Context pressure may trigger compression, but the hard resource limit remains
   the final guardrail.
6. TaskPlan guides coverage, summarization, and answer gap detection without
   becoming a rigid workflow scheduler.

## 23. Target architecture

```text
Coverage Map
      |
      v
Evidence Acquisition
      |
      v
Raw Evidence
      |
      +-----------------------+
      |                       |
coverage value         context pressure
      |                       |
      +-----------+-----------+
                  |
                  v
        CompressionRequest
                  |
                  v
         Evidence Summary
                  |
                  v
        Runtime Validation
                  |
                  v
        Summary Committed
                  |
                  v
       Raw Lifecycle Decision
            /           \
         retain        release
            \           /
             v         v
           Knowledge State
                  |
                  v
             AnswerContext
                  |
                  v
            Answer Resolver
```

The goal is not to make the Agent execute a stricter workflow. It is to let
Runtime continuously answer:

```text
What raw evidence is still needed?
What knowledge has already been absorbed?
What coverage is missing?
What can safely leave active context?
```

Evidence Lifecycle, rather than Task Completion, is the next Context Governance
design baseline.
