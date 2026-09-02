# Artifacts

## Purpose

Artifacts keep a complete logical tool response outside model context when that
response exceeds the inline size bound. They are temporary session data, not
domain entities, provider caches, or a durable evidence store.

## Lifecycle and references

Each chat session owns its own in-memory Artifact store. The store is created
with that session's tool registry, remains available across its turns, and is
dropped with the process (or when the session runtime is discarded). A new chat
session cannot read another session's response.

There are only two model-facing reference forms:

```text
manual:pandascore:<name>
artifact:tool:<uuid4-hex>
```

Tool response references are opaque strings. Every spill receives a fresh UUID;
they are not stable query or entity identities and must not be reconstructed.

## Spill contract

Tools first construct their complete logical response. If it is small enough,
that response stays inline. If it is too large, the complete response is stored
at the Artifact root and the tool returns a bounded observation plus
`artifact_ref`.

For example, an externalized `esports.search` response is exactly:

```json
{"resource":"tournament","scope":"all","rows":[...],"has_more":false}
```

It has no Artifact envelope, query copy, source/kind wrapper, schema version, or
synthetic domain DTO. Preview paths therefore start at `rows`, for example
`rows.0.matches`.

## Manuals and retrieval

Generated PandaScore manuals are a small explicit read-only allowlist. They use
the `manual:pandascore:*` references above and do not belong to a chat session.

The only generic inspection tools are:

```text
artifact.read(ref, path?, offset?, limit?)
artifact.grep(ref, pattern, limit?)
```

Both require one exact reference. `artifact.read` supports dotted paths and
bounded list slices. `artifact.grep` is a literal, case-insensitive search in
that one document; there is no corpus search, Artifact type filter, or scope.
Neither tool fetches a provider.

## Non-goals

Artifacts do not define `ArtifactRef` objects, Artifact type/schema contracts,
Redis persistence, TTL, scopes, source documents, GameSummary versions,
provider navigation, or business identity. Failed-run traces preserve their
executed bounded observations but do not archive temporary Artifact bodies.
