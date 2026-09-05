# Artifacts

## Purpose

Artifacts keep a complete logical tool response outside model context when it
exceeds the inline size bound. They are temporary session data, not domain
entities, provider caches, or a durable evidence store.

## Lifecycle and references

Each chat session owns its own in-memory Artifact store. A new session cannot
read another session's temporary response. Tool-response references are opaque
strings of the form `artifact:tool:<uuid4-hex>`; they locate one document and
must never be reconstructed as an identity.

Static manuals, if introduced by a future capability, must be explicitly
allowlisted and use the same generic read/grep contract.

## Spill contract

Tools first construct their complete logical response. Small responses stay
inline. Large responses are stored at the Artifact root and return a bounded
structural observation plus `artifact_ref`. A preview's `_artifact_path` is
copied unchanged into `artifact.read(mode="read", path=...)`; `outline` is only
needed when the document structure is unknown. The default registry uses
`INLINE_TOOL_RESPONSE_MAX_BYTES` (12 KiB) as the spill threshold and caps the
model-facing observation at `MAX_MODEL_TOOL_OBSERVATION_BYTES` (8 KiB). Artifact
retrieval tools explicitly bypass this processor so their read/grep payloads
remain directly usable.

## Retrieval contract

```text
artifact.read(ref, mode, path?, offset?, limit?)
artifact.grep(ref, pattern, limit?)
```

`outline` omits path, offset, and limit. `read` requires one dotted path; list
offset and limit apply only to that selected value. `grep` is a literal,
case-insensitive search in one document. Neither operation searches a corpus,
infers business meaning, resolves identities, or fetches a provider.

## Non-goals

Artifacts do not define stable entity identities, domain schemas, provider
navigation, hidden persistence, or scenario-specific aggregation. Failed-run
traces may retain bounded observations without archiving temporary Artifact
bodies.
