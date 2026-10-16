"""Thin registration of generic structured Artifact retrieval."""

from app.vnext.artifacts.query import ArtifactQuerier, ArtifactQueryInput, ArtifactQueryResult
from app.vnext.tools.definition import ToolAccess, ToolDefinition
from app.vnext.tools.registry import ToolRegistry


def register_artifact_query_tool(registry: ToolRegistry, querier: ArtifactQuerier) -> None:
    registry.register(
        ToolDefinition(
            name="artifact.query",
            description=(
                "Select original object records in one existing session Artifact using restricted "
                "JSONPath, then return requested direct fields and original artifact.read paths. "
                "Example: $.data.players[?@.identity.account_id == 106305042].minute_timeline"
                "[?@.time_seconds == 1500], fields=['time_seconds','time_label','net_worth']. "
                "Use original identity/time/metric fields; array offset is not game time. "
                "No functions, recursive descent, slicing, object enumeration or aggregation. "
                "Missing members are omitted and listed in missing_fields; "
                "explicit null stays null. "
                "No matches does not establish source completeness. Follow next_offset for more "
                "records; results are byte-bounded and may contain fewer than limit. "
                "No external requests, arithmetic, source mutation or inferred facts."
            ),
            input_model=ArtifactQueryInput,
            output_model=ArtifactQueryResult,
            handler=querier.query,
            parallel_safe=True,
            externalize_result=False,
            access=ToolAccess.LOCAL_ARTIFACT_READ,
        )
    )
