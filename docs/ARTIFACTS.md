# Artifacts

Artifact storage and retrieval remain governed by this document. The target
Runtime-driven history-compaction lifecycle is defined in
[`agent/context_governance_evidence_lifecycle.md`](agent/context_governance_evidence_lifecycle.md);
compaction changes active context, not the stored Artifact or original history.
The target retains the process-local, session-owned storage contract.

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
responses normally stay inline. A response larger than the configured inline
threshold (12 KiB by default, `DOTAMIND_TOOL_INLINE_MAX_BYTES`) is stored at the
Artifact root and returns a bounded structural observation plus `artifact_ref`.
Tools may explicitly require an Artifact even for a small response; this still
uses the same full-document store and configured observation bound. The
configured model observation bound defaults to 35 KiB
(`DOTAMIND_TOOL_OBSERVATION_MAX_BYTES`), so the observation can still include
small scalar leaves even after the full response has been externalized. When an
explicitly stored response is small enough, its `value` contains the complete
logical response; if the added envelope would exceed the observation bound, the
existing bounded structural observation is used. Stored documents never include
the externalization envelope. A preview's `_artifact_path` is copied unchanged into
`artifact.read(mode="read", path=...)`; `outline` is only needed when the
document structure is unknown. Artifact retrieval tools explicitly bypass the
generic spill processor: `artifact.read` enforces the same configured serialized
result bound itself, while `artifact.grep` is bounded by match and preview
limits but has no separate serialized-result byte budget. Limits use UTF-8
serialized bytes, must be positive, and the inline threshold cannot exceed the
observation budget. Environment values override `.env`; changing them requires
restarting the API process.

The session store may separately record the producing tool name as internal
Artifact metadata. The registry supplies this value from the registered tool
definition; it is not read from or written into the business document. Automatic
large-result spills and explicitly stored small results both retain this source.
Direct anonymous `put()` calls remain readable through the generic retrieval
tools and have no source. Source lookup uses the same opaque reference and
session-local existence boundary as document reads.

These per-operation bounds and externalization control individual tool outputs;
there is no cumulative Raw admission budget across effective history. The accepted
answer-stage policy likewise has no total call or cumulative result-byte quota.
[TOOLS.md](TOOLS.md) owns the permissions and per-result bounds. Overall
context capacity is estimated from the complete model request and managed by
Runtime compaction. Compaction changes effective history without rewriting the
stored Artifact or append-only execution records. Checkpointing records task
progress and evidence sources; it does not release raw results from history.

## Retrieval contract

The currently registered retrieval tools are `artifact.read` and `artifact.grep`.
The structured-query contract below is accepted but not implemented or registered.

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

`read` can select an exact scalar, object or list, but does not filter records by
field values or select several fields in one operation. `grep` searches scalar
values, not JSON member names or path strings. Its literal substring matches do
not establish numeric equality, same-record conditions, or absence of source
facts; nulls and empty containers are not searchable scalar leaves.

## Structured query (accepted target; not implemented)

This section owns the complete `artifact.query` contract. The tool selects
original object records from one existing session Artifact, then returns only
requested direct fields and their original record locations. It stays generic:
no Provider requests, gameplay knowledge, identity inference, arithmetic,
formatting, aggregation, result writeback, or derived Artifacts. Storage and the
governed GameDetail document remain unchanged. Tool usage and stage permissions
are summarized in [TOOLS.md](TOOLS.md).

### Input and query language

| Input | Contract |
| --- | --- |
| `ref` | Required exact existing session Artifact reference; never construct one from a business ID |
| `expression` | Required JSONPath expression, at most 1024 characters |
| `fields` | Required list of 1–16 distinct, nonempty direct member names; literal names, without aliases or nested projection expressions |
| `offset` | Strict integer, default `0`, range `0..10000`; position in the matched sequence after filtering |
| `limit` | Strict integer, default `20`, range `1..100` |

Use an allowlisted subset of [RFC 9535 JSONPath](https://www.rfc-editor.org/rfc/rfc9535.html):
root `$`, named member access, nonnegative array indexes, array traversal,
and array filters comparing a singular relative member path to a scalar literal
with `==`, `!=`, `<`, `<=`, `>` or `>=`. Combine comparisons with `&&`, `||` and
parentheses. Comparisons follow RFC type and missing-value semantics; do not
coerce numeric strings or booleans into numbers.

Exclude recursive descent, negative indexes, slices, multiple selectors in one
segment, object-child enumeration, functions, regex, arithmetic, sorting,
aggregation, renaming, cross-document joins and custom extensions. A filter's
data operand is an `@`-relative singular path; it cannot run another broad query
or compare two result collections. Final matches must be object records. Reject
an unsupported result shape rather than unwrapping, dropping or reinterpreting
non-object matches. `fields` selects existing direct children of each record;
requested objects/arrays retain their complete values subject to the byte bound.

Initial complexity bounds are 16 segments per path (including relative filter
paths), 32 comparison conditions, and logical nesting depth 8. The query document
may contain at most 100000 JSON nodes, counting each container and scalar once.
Check size without modifying the Artifact and fail when the cap is exceeded.
These accepted initial limits require fixture/performance validation at
implementation; returning few matches does not bound the number of candidates
examined. Keep existing tool timeout, stage deadline and cancellation controls;
do not describe a timeout as proof that a Python worker has been forcibly stopped.

Prefer `python-jsonpath` with `JSONPathEnvironment(strict=True)` plus an explicit
parsed-syntax allowlist, rather than a new parser or query language. Its documented
`finditer` and match `parts` support incremental results and source locations.
Strict RFC mode alone does not disable all features outside this subset.
This is the selected implementation direction, not an installed dependency or a
verified integration. Pin and validate the actual library version and complexity
checks during implementation. See its [API](https://jg-rp.github.io/python-jsonpath/api/)
and [iteration examples](https://jg-rp.github.io/python-jsonpath/quickstart/#finditerpath-data).

### Result and source fidelity

Success returns `ref`, the original `expression` and `fields`, `matches`,
`offset`, requested `limit`, actual `returned`, `next_offset`, and `truncated`.
Each match contains:

| Field | Meaning |
| --- | --- |
| `path` | Program-generated original record path in the existing `artifact.read` dotted format |
| `value` | Object containing requested members that actually exist, with their original names and values |
| `missing_fields` | Requested direct members absent from this record, in requested-field order |

Every returned path must round-trip through `artifact.read` to that same complete
original record. Construct paths from the engine's location components, not by
guessing indexes or rewriting a path string with regex. If a selected location
cannot be represented by the existing read grammar, fail with an unsupported-path
error. This includes an empty root address and member names containing dots or
empty names; do not output an unusable continuation path or extend `read`
silently. Projection changes only this observation, not the stored record.

Preserve explicit null, zero, false, empty string and empty collection values.
An absent requested member is omitted from `value` and listed in `missing_fields`;
do not insert a synthetic null. A record with all requested fields missing is
still a matched record with `value={}`. A valid query with no matches returns
`matches=[]`, `returned=0`, `next_offset=null`, `truncated=false`; this proves only
that the expression matched no records, not that the source fully covers the
requested topic. Syntax/resource failures are not empty successes.

Do not add identity, time or display fields automatically. The caller explicitly
includes relevant keys and existing DTO labels in `fields`. A minute record does
not acquire an ancestor's `account_id`; selection expression and original path
remain visible, and original parent facts can be read separately. The model still
owns the choice of document, predicates and metrics, plus faithful reproduction.

### Ordering, pagination and byte admission

Apply filters before pagination. Preserve original array traversal order without
sorting, inferred time buckets or adjacent-record substitution. `offset` counts
matched records, not source-array indexes, timestamps, or visited nodes. Iterate
matches instead of materializing all matches merely to compute a total; no
`total` field is promised. Look ahead for a further match to establish truncation.

The complete serialized model-facing result, including paths and pagination,
must fit 35 KiB and any smaller configured observation bound, measured in UTF-8.
Return only complete projected records. If bytes permit fewer than `limit`,
`returned` reflects the actual count. Set `truncated=true` only when a further
matched record exists, and `next_offset=offset+returned`; otherwise use
`truncated=false` and `next_offset=null`. Never return an empty truncated page or
split a record/field to fit. If the first projected record or fixed envelope
cannot fit, return an explicit error asking for fewer fields/a narrower query.

Every non-null `next_offset` must be a legal subsequent input. If more records
remain but continuation would exceed the offset cap, fail explicitly as a range
limit rather than emitting an unusable cursor or claiming completion. If resource
controls stop evaluation before pagination/completeness can be established,
return an error rather than a partially verified page. Unknown/unauthorized refs
retain existing Artifact errors; invalid/unsupported syntax, shape, paths or
resource bounds use explicit structured errors. None causes a Provider fallback.

Reuse the existing error envelope and codes; the accepted mapping is:

| Condition | Error behavior |
| --- | --- |
| Unknown, invalid or unavailable-in-this-session reference | Existing `artifact_not_found`; do not reveal another session's existence |
| Invalid arguments, unsupported expression/shape/path, or resource bound | `invalid_arguments`, with a safe reason identifying the failed condition |
| Artifact storage/read failure | Preserve the existing Artifact error path, without replacing it with empty data |
| Tool timeout or stage cancellation/deadline | Existing timeout/control handling, without claiming a complete query |

The target tool stays inline and is classified `local_artifact_read`, read-only.
In answers it follows the same permissions, 35 KiB per-result bound, duplicate
rejection, deadlines and unified context governance as `read`, `grep` and
calculation. The target has no total call or cumulative byte quota; the full
policy remains in [TOOLS.md](TOOLS.md).

### Complete example

The following uses the governed sample for Valve game `9040460429`, Larl at
25:00. Replace the placeholder with a real previously returned reference. This
illustrates the accepted target, not a successful current `artifact.query` call.

```json
{
  "ref": "<existing artifact_ref>",
  "expression": "$.data.players[?@.identity.account_id == 106305042].minute_timeline[?@.time_seconds == 1500]",
  "fields": ["time_seconds", "time_label", "net_worth", "deaths"],
  "offset": 0,
  "limit": 20
}
```

```json
{
  "ref": "<existing artifact_ref>",
  "expression": "$.data.players[?@.identity.account_id == 106305042].minute_timeline[?@.time_seconds == 1500]",
  "fields": ["time_seconds", "time_label", "net_worth", "deaths"],
  "matches": [
    {
      "path": "data.players.2.minute_timeline.25",
      "value": {
        "time_seconds": 1500,
        "time_label": "25:00",
        "net_worth": 10730,
        "deaths": 2
      },
      "missing_fields": []
    }
  ],
  "offset": 0,
  "limit": 20,
  "returned": 1,
  "next_offset": null,
  "truncated": false
}
```

## Explicit display references (implemented)

A `display_ref` remains attached to its entity in the complete tool result and
Artifact. `artifact.read` and `artifact.grep` preserve and return that value as
ordinary document content; they do not resolve it, read images, or download
resources. The shared product prompt permits copying a reference from that same
entity into the final answer. A `display_ref` locates the durable shared display
directory; an `artifact_ref` locates a temporary session tool result. Historical
answer rendering therefore does not depend on an Artifact still existing. The
reference syntax is owned by [`agent/product_run_state.md`](agent/product_run_state.md),
and record/update semantics by [`DATA.md`](DATA.md).

## Non-goals

Artifacts do not define stable entity identities, domain schemas, provider
navigation, cross-turn context restoration, hidden durable persistence, or
scenario-specific aggregation. There is no Artifact TTL, eviction, or memory
budget in the current store; its lifecycle is process-local and session-bound.
The Context Governance target adds history compaction, a bounded FIFO locator
list, and same-session effective-history continuation at the Runtime/product
layer. Locator eviction does not delete bodies. It does not add Artifact
TTL, restart persistence, or general history-search tools. Known valid references
remain readable, but not every historical reference stays discoverable.
