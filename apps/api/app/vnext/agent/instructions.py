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

__all__ = ["ESPORTS_QUERY_DISCIPLINE_INSTRUCTION"]
