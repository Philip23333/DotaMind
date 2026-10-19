"""Thin registration of generic structured Artifact retrieval."""

from app.vnext.artifacts.externalize import serialized_size
from app.vnext.artifacts.query import (
    ArtifactQuerier,
    ArtifactQueryInput,
    ArtifactQueryResult,
    QueryBudgetExceeded,
    QueryFieldsUnavailable,
)
from app.vnext.tools.definition import ToolAccess, ToolDefinition
from app.vnext.tools.errors import StructuredToolError, ToolError
from app.vnext.tools.registry import ToolRegistry


def register_artifact_query_tool(registry: ToolRegistry, querier: ArtifactQuerier) -> None:
    async def handler(args: ArtifactQueryInput) -> ArtifactQueryResult:
        try:
            return await querier.query(args)
        except QueryBudgetExceeded as exc:
            raise StructuredToolError(
                "query_budget_exceeded", str(exc), {"limit": exc.limit, "used": exc.used}
            ) from None
        except QueryFieldsUnavailable as exc:
            details = exc.details
            # Preserve whole field names and the shared error-envelope byte bound.
            for key in ("available_fields", "missing_fields"):
                while details[key] and serialized_size(
                    ToolError(
                        code="invalid_arguments", message=str(exc), details=details
                    ).model_dump(mode="json")
                ) > registry.observation_max_bytes:
                    details[key].pop()
                    details[f"{key}_truncated"] = True
            error = ToolError(code="invalid_arguments", message=str(exc), details=details)
            if serialized_size(error.model_dump(mode="json")) > registry.observation_max_bytes:
                details = {}
            raise StructuredToolError("invalid_arguments", str(exc), details) from None

    registry.register(
        ToolDefinition(
            name="artifact.query",
            description=(
                "Extract selected fields across object records or filter records in one existing "
                "session Artifact using restricted JSONPath. Prefer query over reading complete "
                "records when only a few fields are needed; no filter is required. Returns "
                "requested direct fields and original artifact.read paths. For all players' final "
                "statistics, use expression='$.data.players[*]', "
                "fields=['identity','final_stats']; unrelated minute histories are not returned. "
                "For one player's minute record, use "
                "expression='$.data.players[?@.identity.account_id == 106305042].minute_timeline"
                "[?@.time_seconds == 1500]', "
                "fields=['time_seconds','time_label','cumulative_gold_earned']. "
                "Use original identity/time/metric fields; array offset is not game time. "
                "No functions, recursive descent, slicing, object enumeration or aggregation. "
                "Use field names observed in the records; read one sample when structure is "
                "unknown. A field absent from every record admitted to the returned page fails "
                "the whole call with invalid_arguments, missing_fields, sample_path and the "
                "sample's available_fields. Suggestions are bounded and may be incomplete; "
                "inspect sample_path or correct fields and retry instead of concluding business "
                "facts are absent. Fields missing from only some records stay in per-record "
                "missing_fields; explicit null is a present field and stays null. "
                "No matches does not establish source completeness. Follow next_offset for more "
                "records; results are byte-bounded and may contain fewer than limit. "
                "Work is bounded per query, including nonmatching candidates; "
                "query_budget_exceeded means narrow the selected path or range, "
                "not just the returned fields. No partial result is returned on work exhaustion. "
                "Use artifact.grep to locate unknown fields/content; use artifact.read to "
                "inspect structure or retrieve a complete value or object at a known path. "
                "No external requests, arithmetic, source mutation or inferred facts."
            ),
            input_model=ArtifactQueryInput,
            output_model=ArtifactQueryResult,
            handler=handler,
            parallel_safe=True,
            externalize_result=False,
            access=ToolAccess.LOCAL_ARTIFACT_READ,
        )
    )
