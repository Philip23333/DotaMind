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

### Game-report and heatmap boundary

[The report contract](agent/game_detail_report.md) prepares capability-owned
minute/final/event views without adding game semantics to generic Artifact
tools. Full governed DTOs and complete logical report results follow the
existing externalization and session-ownership rules; this is not a new durable
evidence store or a change to read/grep/query behavior.

Heatmap generation has a stricter input boundary: source coordinates, trajectories
and intermediate grids must never enter Artifacts, raw tool observations, Trace,
logs or source caches. The capability reads them transiently and exposes only
rendered images and a small source/time/version index. An index may be a logical
document, but image files and their lifecycle belong to an explicitly designed
image store, not this JSON body store. The implemented store has its own seven-day
TTL/quota, cleanup, file integrity checks and opaque bearer image references.
Current session expiry rules do not control image expiry. No verified production
map asset is bundled yet; the synthetic-map pipeline tests are not map acceptance.

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
document structure is unknown. Artifact retrieval tools bypass the generic spill
processor: they read an existing document and must not externalize their own
results into another Artifact merely to fit the observation budget. Their normal
size handling and the shared final check are defined below.

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

## Shared tool-result byte budget

The common result exit and configured read/query/ordinary-result budgets are
implemented for both stages. Query no longer clamps independently to 35 KiB and
answering no longer owns a separate size gate. Grep's byte-aware pagination uses
the same injected budget; count/byte overflow normally yields a complete page,
while the shared exit rejects unexpected oversized content in either stage.

Root `.env` provides the two distinct byte settings, with process environment
overrides taking precedence:

```dotenv
DOTAMIND_TOOL_INLINE_MAX_BYTES=12288
DOTAMIND_TOOL_OBSERVATION_MAX_BYTES=35840
DOTAMIND_ARTIFACT_QUERY_MAX_WORK=100000
```

The first is the ordinary-result externalization threshold (12 KiB by default),
not a second model-context ceiling. The second is the maximum single model-visible
result (35 KiB by default). Retain these defaults. Parse and validate the settings
once at composition, keep code fallback defaults in one configuration model, and
inject the same observation budget into result processing, read, query, grep and
the common result exit. Do not add tool-specific clamps or answer-only literals.
Both values must be positive integers and inline must not exceed observation.
Registry construction also rejects an observation budget too small to encode
even its minimal structured rejection, rather than promising an impossible bound.
Changes require an API restart; they do not introduce live configuration reload.

Measure compact JSON serialized with UTF-8 and unescaped Unicode. The budget
covers the complete model-visible success content or structured error, including
references, paths, previews and pagination metadata; it is not only a limit on
the selected business value. Transport message IDs/envelopes are not this byte
measure. It is a per-result bound, not token accounting or a cumulative quota.

| Result kind | Normal behavior when the requested result is too large |
| --- | --- |
| Ordinary capability result | Retain the complete validated logical result in an Artifact and return a budget-fitting observation/ref |
| Read of a list | Return fewer complete list items and mark truncation; continue from the actual returned count |
| Read of an object/scalar | Return an explicit error requesting a narrower path, without silently dropping fields |
| Query | Return fewer complete projected records and a valid next offset; fail if even one record/fixed envelope cannot fit |
| Grep | Return fewer complete matches and a valid next offset; fail if even one match/fixed envelope cannot fit |

After each tool's normal result processing, a common tool-result exit checks the
final content before it enters model-visible history. Apply the same configured
budget in both stages, including local calculation and errors. Unexpected
oversized content becomes a bounded structured error; the exit does not slice
JSON, erase fields or invent pagination. This is an invariant check, not the
normal paging mechanism. Remove the separate answer-only size gate while keeping
answer permissions and request-local duplicate tracking. An otherwise identical
local tool call must not succeed in execution and fail in answering solely due
to a different size policy. Provider tools remain forbidden in answers.

Overall request occupancy and high-watermark compaction remain Runtime-owned,
as specified in [ARCHITECTURE.md](ARCHITECTURE.md#two-stage-context-governance).
No total-call or cumulative-result-byte quota is restored by this contract.

## Retrieval contract

The registered retrieval tools are `artifact.read`, `artifact.grep` and
`artifact.query`. Their selection, simplified grep interface, byte-aware paging
and shared result exit are implemented with deterministic checks. Source
implementation does not imply a running-service restart or deployment.

```text
artifact.read(ref, mode, path?, offset?, limit?)
artifact.grep(ref, pattern, offset=0, limit=20)
```

`outline` omits path, offset, and limit. `read` requires one dotted path; list
offset and limit apply only to that selected value. `grep` is a literal,
case-insensitive search in one document, with a maximum pattern length of 256
characters, at most 100 matches, and previews of at most 200 characters.
Neither operation searches a corpus, infers business meaning, resolves
identities, or fetches a provider.

`read` can select an exact scalar, object or list, but does not filter records by
field values or select several fields in one operation.

List reads return `offset`, requested `limit`, full list `total`, actual
`returned`, `next_offset`, and `truncated` alongside `ref`, `path`, and `value`.
After count and byte trimming, set `returned=len(value)` and
`next_offset=offset+returned` only if more list items remain; otherwise use null.
Continue with that exact `next_offset` and the same ref/path, not the requested
limit. Empty and past-end pages have `returned=0`, `next_offset=null`, and
`truncated=false`. A successful page must not be empty while more items remain;
an oversized first item still requires a narrower path. Include continuation
metadata in the serialized byte check. Non-list reads and outline results use
null for `returned` and `next_offset`; outline arrays are not paginated reads.

`grep` recursively searches member names and scalar values (strings, numbers,
booleans and JSON null) throughout one referenced document. There is no search
mode or `scope` parameter; the model does not choose between keys and values.

Member-name matching includes fields whose values are null, empty arrays or empty
objects. It matches the member's own name, not the full ancestral path: searching
`purchase` returns the `purchase_events` node without also matching every descendant
merely because that ancestor matched. Traversal continues into that node, so a
descendant whose own name or value matches still returns independently. Array
indices are locations, not searchable member names. Traversal follows document
order; a node matching both name and value produces one result.

Each match contains only `ref`, a read-compatible dotted `path`, a preview of at most
200 characters, and `value_type`
(`object`, `array`, `string`, `number`, `boolean`, `null`). Container previews
contain only type and direct item count, never the full nested value. Use `read`
to inspect a discovered path or `query` to select records/fields. For example,
searching `purchase` can discover `data.builds.players.1.purchase_events`, then
query can select the player's specific item events.

Manual text uses the same contract as one `content` string member. JSON member
names must be nonempty strings without dots to produce read-compatible paths;
encountering an unrepresentable name fails explicitly rather than silently
omitting that subtree. Literal/case-insensitive matching, session isolation and
read-only behavior remain unchanged. Numeric equality and same-record conditions
belong to query. Do not add a new zero-match warning obligation to the prompts
as part of this change; tool descriptions should explain actual search behavior.

### Grep pagination and result

Input is `ref`, nonblank literal `pattern` (at most 256 characters), strict
nonnegative integer `offset` (default 0), and strict integer `limit` (default 20,
range 1..100). Offset counts matching nodes after matching, not visited nodes or
source array indexes. Preserve deterministic document traversal order for the
same stored document and pattern; emit one record per matching node, even when
both its name and value match. Do not expose `matched_on`.

Success contains `matches`, `offset`, requested `limit`, actual `returned`,
`next_offset` and `truncated`. For example, one player's discovered purchase array
could appear in a page as:

```json
{
  "matches": [
    {
      "ref": "<existing artifact_ref>",
      "path": "data.builds.players.1.purchase_events",
      "preview": "array (44 items)",
      "value_type": "array"
    }
  ],
  "offset": 0,
  "limit": 20,
  "returned": 1,
  "next_offset": null,
  "truncated": false
}
```

This illustrates a document with only that matching field; the full governed
match can have purchase fields for other players. This is a contract example,
not a claim that grep filters by player.

The complete serialized result must fit the shared configured observation budget.
Stop at the first of the match-count limit or byte limit, preserving whole matches.
Look ahead for a further match: if one exists, set `truncated=true` and
`next_offset=offset+returned`; otherwise set `truncated=false` and
`next_offset=null`. Continue with the same ref/pattern and that returned offset,
not offset plus the requested limit. Every match appears once across pages, with
no omission when byte limits reduce page length. Return no promised total count.

If even the first match/fixed envelope cannot fit, return an explicit structured
error, never an empty truncated page that cannot advance. A valid empty or past-end
page returns no matches, zero returned, null next offset and false truncation.
Do not return a partial path, partial match, or incomplete JSON. Count and byte
limits govern the returned page, not a guarantee about the cost of scanning;
retain tool timeout, stage deadline and cancellation behavior. Unknown refs and
invalid arguments retain existing Artifact/registry errors, not Provider fallback.

## Structured query

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

Complexity bounds are 16 segments per path (including relative filter paths),
32 comparison conditions, and logical nesting depth 8. There is no whole-document
node-count gate or pre-query recursive scan. Query traversal has a fresh budget
per call, configured centrally by `DOTAMIND_ARTIFACT_QUERY_MAX_WORK` in `.env`
(default 100000, strict positive integer), shared by execution and answer stages.
Charge one work unit for each actual named-member/index lookup attempt (including
misses), each visited array wildcard element, and each evaluated filter comparison
or logical operator. Filter failures, intermediate traversal, skipped offset
matches and pagination lookahead count too. Unvisited subtrees do not count;
projecting direct fields does not recursively scan the selected records' other
members. This is an operation budget, not an exact CPU, memory or serialization
cost measure. Existing observation byte bounds still apply independently.
On exhaustion, return `query_budget_exceeded` with `limit` and `used`, no partial
result, and guidance to narrow the selected path/range rather than just fields.
Do not mutate the Artifact. Returning few matches does not bound the number of
candidates examined. Keep existing tool timeout, stage deadline and cancellation controls;
do not describe a timeout as proof that a Python worker has been forcibly stopped.

The implementation pins `python-jsonpath==2.2.1` and uses
`JSONPathEnvironment(strict=True, filter_caching=False)` plus an explicit
parsed-syntax allowlist, rather than a new parser or query language. Its documented
`finditer` and match `parts` support incremental results and source locations.
Strict RFC mode alone does not disable all features outside this subset.
Array-only selector guards reject object enumeration. Evaluation runs in a worker
thread so the caller/event loop can respond to timeout or cancellation; a cancelled
await does not forcibly stop the worker. Finite AST and query-work limits still apply.
See its [API](https://jg-rp.github.io/python-jsonpath/api/)
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
If a requested member is absent from every record on the actual returned page,
fail the whole query with `invalid_arguments`, without a partial success payload.
Determine this after count/byte admission: skipped matches, lookahead and rows
removed by byte trimming do not establish a field's availability on this page.
The error reports `missing_fields`, the first returned record's `sample_path`,
and that sample's observed direct `available_fields`. These are observed names,
not a universal schema or evidence that other records lack a fact. Inspect the
sample or correct the projection and retry. This is a generic document check,
not business-specific validation.

Suggestions preserve source-key order and whole field names. At most 64 direct
names from one sample are considered; `available_fields_truncated` marks omitted
names. Error details must also fit the shared configured UTF-8 result bound:
omit whole available names first, then whole missing names if necessary, marking
`missing_fields_truncated` when that list is shortened. If metadata cannot fit,
retain the error without oversized details, subject to the common result exit.
No unrelated branches or nested field values are scanned for suggestions.

When every requested member occurs in at least one record of this page, retain
per-record absence semantics: omit an absent member from `value` and list it in
that record's `missing_fields`; do not insert a synthetic null. A record with
all requested fields missing can still have `value={}` when other page records
provide those fields. Present null values count as present even if all are null.
A valid query with no matches returns
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
must fit the shared configured observation budget (35 KiB by default), measured
in UTF-8. Query uses that injected value without an independent fixed clamp;
increasing the configured value does not leave a hidden 35 KiB ceiling.
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
| A projected member absent from every actual returned-page record | `invalid_arguments`, bounded `missing_fields`, `sample_path`, `available_fields`; inspect/correct and retry, without inferring business absence |
| Artifact storage/read failure | Preserve the existing Artifact error path, without replacing it with empty data |
| Tool timeout or stage cancellation/deadline | Existing timeout/control handling, without claiming a complete query |

The tool stays inline and is classified `local_artifact_read`, read-only.
In answers it follows the same configured per-result bound (default 35 KiB), duplicate
rejection, deadlines and unified context governance as `read`, `grep` and
calculation. There is no total call or cumulative byte quota; the full
policy remains in [TOOLS.md](TOOLS.md).

### Complete example

The following uses saved facts for Valve game `9040460429`, Larl at 25:00, with
the current GameDetail field names. Replace the placeholder with a real
reference whose document has that schema. This is an illustrative request/result:
existing Artifacts retain their original fields and are not migrated by query.

```json
{
  "ref": "<existing artifact_ref>",
  "expression": "$.data.players[?@.identity.account_id == 106305042].minute_timeline[?@.time_seconds == 1500]",
  "fields": ["time_seconds", "time_label", "cumulative_gold_earned", "known_deaths"],
  "offset": 0,
  "limit": 20
}
```

```json
{
  "ref": "<existing artifact_ref>",
  "expression": "$.data.players[?@.identity.account_id == 106305042].minute_timeline[?@.time_seconds == 1500]",
  "fields": ["time_seconds", "time_label", "cumulative_gold_earned", "known_deaths"],
  "matches": [
    {
      "path": "data.players.2.minute_timeline.25",
      "value": {
        "time_seconds": 1500,
        "time_label": "25:00",
        "cumulative_gold_earned": 10840,
        "known_deaths": 2
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
