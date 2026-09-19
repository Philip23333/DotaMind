# Artifact Observation Lifecycle v1

This document freezes the redundant-observation primitive. The broader target
for semantic compression and independent Raw Evidence release is defined by the
authoritative
[`context_governance_evidence_lifecycle.md`](context_governance_evidence_lifecycle.md).
The v1 receipt rewrite remains valid and is not replaced by Summary lifecycle
semantics.

## Scope

Artifact Observation Lifecycle v1 governs only redundant `artifact.read`
observations already present in the model transcript. It does not change the
`artifact.read` input or output contract, the 35 KiB observation budget,
Artifact storage, runtime deadlines, finalization, context pressure, or
`TaskState`.

The complete validated tool result remains in the Artifact. The transcript
rewrite only changes an older `ToolResultMessage.content` after a later result
mechanically proves that the older evidence is redundant.

## Lifecycle

```text
artifact.read result
        |
        v
   ACTIVE_RAW
        |
        | duplicate or verified full superset
        v
   RECEIPT_ONLY
```

There are exactly two replacement reasons:

- `duplicate`: same reference, path, kind, actual list range (when present),
  and returned value.
- `superseded`: same reference and path, both list slices, and a later slice
  fully covers the earlier actual range with matching values in the covered
  region.

The latest observation always remains raw. A later observation can replace
multiple earlier observations. The replacement is performed on the transcript
message content only; the `AssistantMessage` and its paired
`ToolResultMessage` are never removed.

## Actual returned ranges

For list reads, coverage uses the actual returned item count:

```text
actual_start = result.offset
actual_end   = result.offset + len(result.value)
```

This is deliberately not the requested `limit`. A request for 40 items may
return 17 complete items because the existing model-observation budget trims
whole trailing items. The 17-item range is the evidence that can be compared.

Partial overlap, a new subset of an older read, different references, different
paths, and changed values remain raw. v1 does not perform partial slicing or
merge observations.

## Receipt contract

An old successful observation is replaced with a small, re-readable receipt:

```json
{
  "_artifact_observation": {
    "state": "receipt_only",
    "reason": "superseded",
    "re_readable": true,
    "mode": "read",
    "ref": "artifact:tool:...",
    "path": "rows",
    "offset": 0,
    "limit": 6
  }
}
```

Outline receipts use `mode: "outline"` and retain only the reference. A
receipt does not contain the old value, a summary, a hash, an internal registry
identifier, or a replacement chain. Receipt content is explicitly ignored by
later lifecycle scans, so applying the rewriter repeatedly is idempotent.

The original tool-call/result pairing remains intact:

```text
Assistant tool call A
        |
ToolResult A(receipt)
```

The raw execution result is still recorded in `trace.tool_result`. The next
`trace.model_request` records the receipt-rewritten stable transcript. Rewrite
events contain only the reason and re-read parameters; they never contain raw
payloads.

## Runtime boundary

`AgentRuntime` depends only on the provider-neutral
`TranscriptRewriter` protocol. After a complete tool turn and the existing
deadline/cancellation check, it constructs a candidate transcript and passes it
to the optional rewriter. The default runtime path remains unchanged when no
rewriter is supplied.

The vNext composition root supplies the stateless
`ArtifactObservationTranscriptRewriter`. It rescans the complete transcript on
each turn rather than maintaining a cross-turn registry. This keeps the v1
operation deterministic, idempotent, and free of lifecycle-reset or concurrency
state.

## Non-goals and invariants

The following never trigger replacement in v1:

```text
observation age
context size or context_pressure
time pressure
runtime phase
FINALIZATION
```

v1 prevents redundant evidence retention; it does not bound the working set of
a task whose distinct evidence itself is large. A T8-style sequence of
different, non-overlapping reads therefore remains raw and is expected to keep
its context footprint under the current v1 implementation. Future Summary
compression and Artifact-level release are governed by the Context Governance
design and must preserve the invariants stated there.
