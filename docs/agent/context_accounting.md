# Context Accounting

Context Accounting is the measurement layer for the authoritative
[`context_governance_evidence_lifecycle.md`](context_governance_evidence_lifecycle.md)
design. Its v1 behavior remains measurement-only; later governance phases may
consume these measurements to trigger compression without changing the meaning
of the recorded metrics.

## Purpose

Context Accounting makes the model-visible context footprint observable before
Context Governance starts changing it.

v1 is measurement only. It does not:

- prune or compact history;
- summarize tool observations;
- evict artifacts;
- change `RuntimeContext.context_pressure`;
- change phase transitions, tool availability, or model guidance.

`context_pressure` therefore remains `normal` until a later policy layer is
explicitly designed and validated.

## Measurement

The accounting unit is deterministic canonical JSON serialized as UTF-8 bytes:

```text
json.dumps(
    value,
    ensure_ascii=False,
    separators=(",", ":"),
    sort_keys=True,
).encode("utf-8")
```

This is a provider-neutral logical size metric, not provider wire size and not a
token estimate. In particular, v1 deliberately does not use heuristics such as
`bytes / 4`, which are unreliable across CJK content, tool schemas, and provider
tokenizers.

Provider-reported prompt-token usage may still be recorded after a request by
provider-specific code. That is a different, post-hoc measurement and should not
be treated as interchangeable with Context Accounting.

## Per-invocation trace shape

Each model invocation records:

```json
{
  "context_accounting": {
    "measurement": "canonical_json_utf8_bytes",
    "stable_messages": {
      "count": 12,
      "serialized_bytes": 125000,
      "by_role": {
        "assistant": {"count": 4, "serialized_bytes": 22000},
        "system": {"count": 1, "serialized_bytes": 6000},
        "tool": {"count": 5, "serialized_bytes": 95800},
        "user": {"count": 2, "serialized_bytes": 1200}
      }
    },
    "task_context": {
      "present": true,
      "serialized_bytes": 8421,
      "task_state": {"count": 3, "serialized_bytes": 7210},
      "active_manifest": {"count": 2, "serialized_bytes": 476}
    },
    "tool_schemas": {
      "count": 9,
      "serialized_bytes": 18000
    },
    "runtime_prompt": {
      "present": true,
      "serialized_bytes": 430
    },
    "artifact_observations": {
      "active_raw": {"count": 3, "serialized_bytes": 58720},
      "receipts": {"count": 9, "serialized_bytes": 1812}
    },
    "effective_request": {
      "message_count": 12,
      "tool_count": 9,
      "serialized_bytes": 143900
    }
  }
}
```

### Stable messages

`stable_messages` is the transcript that the Runtime carries between model
invocations. It excludes the ephemeral Runtime Prompt. Role-level accounting
makes tool observations directly measurable instead of hiding them inside one
history total.

`task_context` measures the separate ephemeral TaskState projection. It is
computed from the intermediate request that contains Task Context but not the
Runtime Prompt, so its bytes are not misattributed to `runtime_prompt`.
`task_state` and `active_manifest` are measured from the structured payload
provided by `TaskStateCoordinator`, not by parsing model-facing text.

### Tool schemas

`tool_schemas` measures only the tools exposed to that invocation. During forced
finalization this can therefore be zero even though the run's initial trace
contains the full registered tool surface.

### Runtime Prompt

The trace still does not persist Runtime Prompt text. `runtime_prompt` records
only whether the effective transcript differs from the stable transcript and
the additional canonical serialized message bytes caused by that ephemeral
injection.

This works for both Runtime Prompt injection forms currently supported by the
Runtime:

- inserting a temporary system message when no system message exists;
- appending the temporary instruction to the existing system message.

The Runtime passes both intermediate boundaries to accounting:

```text
stable conversation messages
  -> task_context_messages
  -> effective request messages
```

Therefore `task_context.serialized_bytes` is the Task Context increment and
`runtime_prompt.serialized_bytes` is only the Runtime Prompt increment.

### Artifact observation working set

`artifact_observations` is measured over stable conversation messages. A
successful `artifact.read` result that is not a lifecycle receipt contributes
to `active_raw`; a result whose `_artifact_observation.state` is
`receipt_only` contributes to `receipts`. Each byte value is the canonical JSON
size of the complete `ToolResultMessage`, including role and tool-call pairing.

Lifecycle rewrite events also record `raw_bytes`, `receipt_bytes`, and
`saved_bytes` (`max(0, raw_bytes - receipt_bytes)`) for duplicate, superseded,
and checkpointed replacements. Successful and failed `task.checkpoint` tool
turns add only compact metrics (`checkpoint_id`, key, source count, and value
bytes) to the trace; checkpoint values and source IDs are not copied there.

### Effective request

`effective_request.serialized_bytes` measures the provider-neutral logical
context object made from the actual request's `messages` and `tools`. Runtime
metadata such as `step` is intentionally excluded because it is execution state,
not model context.

Component byte values are diagnostic partitions. The effective request includes
JSON container/key framing, so it is not required to equal the arithmetic sum of
all component values.

## Trace invariant

The Runtime passes the request boundaries needed by accounting to the trace layer:

```text
actual ModelRequest
+
conversation_messages without Runtime Prompt
+
task_context_messages without Runtime Prompt
```

Accounting is computed from those same objects at `model_request` capture time.
There is no reconstruction from later trace data, and the Runtime Prompt text is
not added to stable history. Task Context text is likewise not persisted in the
trace's `model_request`; only its structured byte metrics are retained.

## Next policy layer

The Context Governance design now defines that later policy: classify
`context_pressure`, issue typed `CompressionRequest` values, and keep the hard
Materialization Budget as the final guardrail. Those phases are target design,
not an assertion that Context Accounting v1 already changes runtime behavior.
