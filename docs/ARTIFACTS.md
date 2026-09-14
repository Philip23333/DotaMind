# Artifacts

## Purpose

Artifacts retain a complete logical tool response separately from the model
transcript when it exceeds the inline size bound. The bounded observation may
nevertheless include small scalar leaves from that response. Artifacts are
temporary session data, not domain entities, provider caches, or a durable
evidence store.

## Lifecycle and references

In the product chat composition, each active chat session owns an in-memory
Artifact store through its session-specific runtime. A new session cannot read
another session's temporary response. The store is process-local: restarting
the process loses its bodies, and deleting the chat session discards its runtime
and stored Artifacts. Tool-response references are opaque strings of the form
`artifact:tool:<uuid4-hex>`; they locate one document and must never be
reconstructed as an identity.

Static manuals, if introduced by a future capability, must be explicitly
allowlisted and use the same generic read/grep contract.

## Spill contract

Tools first construct and validate their complete logical response. Small
responses stay inline. A response larger than
`INLINE_TOOL_RESPONSE_MAX_BYTES` (12 KiB) is stored at the Artifact root and
returns a bounded structural observation plus `artifact_ref`. The model
observation bound is `MAX_MODEL_TOOL_OBSERVATION_BYTES` (35 KiB), so the
observation can still include small scalar leaves even after the full response
has been externalized. A preview's `_artifact_path` is copied unchanged into
`artifact.read(mode="read", path=...)`; `outline` is only needed when the
document structure is unknown. Artifact retrieval tools explicitly bypass the
generic spill processor: `artifact.read` enforces the same 35 KiB serialized
result bound itself, while `artifact.grep` is bounded by match and preview
limits but has no separate serialized-result byte budget.

## Retrieval contract

```text
artifact.read(ref, mode, path?, offset?, limit?)
artifact.grep(ref, pattern, limit?)
```

`outline` omits path, offset, and limit. `read` requires one dotted path; list
offset and limit apply only to that selected value. `grep` is a literal,
case-insensitive search in one document, with a maximum pattern length of 256
characters, at most 100 matches, and previews of at most 200 characters.
Neither operation searches a corpus, infers business meaning, resolves
identities, or fetches a provider.

## Non-goals

Artifacts do not define stable entity identities, domain schemas, provider
navigation, cross-turn context restoration, hidden durable persistence, or
scenario-specific aggregation. There is no Artifact TTL, eviction, or memory
budget in the current store; its lifecycle is process-local and session-bound.
Failed-run traces may retain bounded observations without archiving temporary
Artifact bodies.
