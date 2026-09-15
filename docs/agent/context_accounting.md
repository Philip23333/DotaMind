# Context Accounting v1

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
    "tool_schemas": {
      "count": 9,
      "serialized_bytes": 18000
    },
    "runtime_prompt": {
      "present": true,
      "serialized_bytes": 430
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

### Effective request

`effective_request.serialized_bytes` measures the provider-neutral logical
context object made from the actual request's `messages` and `tools`. Runtime
metadata such as `step` is intentionally excluded because it is execution state,
not model context.

Component byte values are diagnostic partitions. The effective request includes
JSON container/key framing, so it is not required to equal the arithmetic sum of
all component values.

## Trace invariant

The Runtime already passes both values needed by accounting to the trace layer:

```text
actual ModelRequest
+
conversation_messages without Runtime Prompt
```

Accounting is computed from those same objects at `model_request` capture time.
There is no reconstruction from later trace data, and the Runtime Prompt text is
not added to stable history.

## Next policy layer

A later Context Governance step may consume this measurement to classify
`context_pressure` and decide when to compact or externalize context. That policy
is intentionally outside v1 so thresholds can be based on observed traces rather
than guessed in advance.
