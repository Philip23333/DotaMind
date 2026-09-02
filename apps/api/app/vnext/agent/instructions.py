"""Production tool-use instructions supplied with vNext model requests."""

ESPORTS_QUERY_DISCIPLINE_INSTRUCTION = """\
Esports query discipline:

- A basic entity discovery using a resource name search and default scope may call
  esports.search directly.
- Do not make a non-trivial esports.search query that uses filter, range, sort,
  a non-default scope, or a resource relation until every intended capability
  for that selected resource is established by the current conversation or a
  successful tool result. Otherwise, first read manual:pandascore:<resource>'s
  content path with artifact.read(mode='read'); an outline alone does not
  establish legal fields.
- Do not probe unsupported field/operator combinations by trial and error. After
  unsupported_field or unsupported_scope, read that resource's manual before
  another esports.search call for the same idea.
- manual:pandascore:index only discovers available manuals. Use
  manual:pandascore:<resource> to decide that resource's actual query fields.
- Manuals answer which query is legal. Artifact _artifact_path values answer
  which data a previous tool call returned; copy an existing _artifact_path into
  artifact.read with mode='read' instead of reading an outline first.
"""

__all__ = ["ESPORTS_QUERY_DISCIPLINE_INSTRUCTION"]
