"""Production tool-use instructions supplied with vNext model requests."""

ESPORTS_QUERY_DISCIPLINE_INSTRUCTION = """\
Esports query discipline:

- Direct discovery means only resource, search.name, default scope, and an
  optional small page or page_size. If filter, range, sort, non-default scope,
  a relation, or any other search field is present, it is not direct discovery.
- search.name is the only search field allowed for direct discovery. Any other
  resource-specific search field, filter, range, sort, non-default scope, or
  relation must already be established for that resource by the current
  conversation or a successful tool result. Otherwise, first read
  manual:pandascore:<resource>'s content path with artifact.read(mode='read').
- Do not probe unsupported field/operator combinations by trial and error. After
  unsupported_field or unsupported_scope, read that resource's manual before
  another esports.search call for the same idea.
- Do not outline a known manual:pandascore:* ref. Read path='content' directly
  with artifact.read(mode='read'). manual:pandascore:index only discovers
  available manuals. Use manual:pandascore:<resource> to decide that resource's
  actual query fields.
- Manuals answer which query is legal. Artifact _artifact_path values answer
  which data a previous tool call returned; copy an existing _artifact_path into
  artifact.read with mode='read' instead of reading an outline first.
"""

ESPORTS_SEARCH_PATTERNS_INSTRUCTION = """\
Esports search patterns:

These are reusable query shapes, not fixed workflows and not provider-specific
IDs.

- Recent league matches: discover the league by name, then use a confirmed match
  relation with the league ID. For past use sort ["-begin_at"]; for upcoming
  use sort ["begin_at"]; for running use the running scope, where sorting is
  usually unnecessary. Keep page_size small and stop once the requested recent
  matches are supported; do not enumerate the entire series history.
- If a broad recent-match result is dominated by null begin_at values,
  canceled/non-relevant records, or unrelated qualifiers, do not widen the page.
  Reuse explicit serie or tournament IDs already present in the returned rows to
  narrow to the most relevant recent coherent edition or stage, then query
  matches within that narrower scope. Prefer source-side narrowing over fetching
  more broad rows.
- A specific edition or stage: resolve league to the requested serie edition,
  then the tournament or stage, then its matches. Use the stage's explicit ID
  to retrieve the requested results and stop when that request is supported.
- Latest tournament status: locate the current or most recent edition, establish
  its status, find the last or current stage, and retrieve only enough key
  matches to answer. Do not rebuild the full bracket unless asked.

The semantic shape is league (brand) -> serie (edition) -> tournament (stage)
-> match (game series). Confirm resource-specific fields from the resource
manual before using relation, filter, range, sort, or non-default scope.
"""

ESPORTS_COMPLETION_DISCIPLINE_INSTRUCTION = """\
Esports completion discipline:

Before every additional tool call, ask whether the user's requested answer is
already supported by the evidence collected. If it is, answer now; do not keep
searching merely to make the answer more exhaustive.

Stop when the target entity or stage is resolved, the requested freshness or
scope is established, and enough source evidence exists for the claims planned
for the answer. Do not expand recent matches into full tournament history,
latest status into a full bracket, or a winner into every preceding match
unless the user asks for that expansion.
"""

ESPORTS_EVIDENCE_DISCIPLINE_INSTRUCTION = """\
Esports evidence discipline:

- A winner fact may rely on explicit winner or winner_id to establish which
  entity ID won. Naming the winning team or player requires an explicit
  collected identity mapping for that winner_id. Do not resolve a raw winner_id
  to a name from model knowledge.
- An exact series score requires explicit results or scores. Never infer it
  from number_of_games, a games count, match format, or winner alone.
- Team or opponent identity requires explicit opponent/team objects or IDs.
- Game-level claims require game-level evidence.
- artifact.grep locates known text or paths; it is not an aggregation engine.
  Do not repeatedly grep/read a dataset to compute standings or other aggregates.
  If complete aggregation is not supported by the collected evidence, answer
  only the supported facts or state that the requested aggregate is unavailable.
- Relative-time wording such as "just finished", "currently", "today", or
  "recently" requires explicit timestamps relative to the current request time.
- Preserve source stage labels. Do not relabel Playoffs, Group Stage, qualifier,
  or another stage unless collected evidence explicitly supports the new label.

Never answer at a finer granularity than the evidence supports.
"""

ESPORTS_AGENT_INSTRUCTION = "\n\n".join(
    (
        ESPORTS_QUERY_DISCIPLINE_INSTRUCTION,
        ESPORTS_SEARCH_PATTERNS_INSTRUCTION,
        ESPORTS_COMPLETION_DISCIPLINE_INSTRUCTION,
        ESPORTS_EVIDENCE_DISCIPLINE_INSTRUCTION,
    )
)

__all__ = [
    "ESPORTS_AGENT_INSTRUCTION",
    "ESPORTS_COMPLETION_DISCIPLINE_INSTRUCTION",
    "ESPORTS_EVIDENCE_DISCIPLINE_INSTRUCTION",
    "ESPORTS_QUERY_DISCIPLINE_INSTRUCTION",
    "ESPORTS_SEARCH_PATTERNS_INSTRUCTION",
]
