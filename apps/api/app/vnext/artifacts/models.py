"""Provider-neutral models used by the artifact store."""

from pydantic import BaseModel, ConfigDict


class ArtifactRef(BaseModel):
    """Stable identity and schema information for one artifact."""

    model_config = ConfigDict(frozen=True)

    id: str
    artifact_type: str
    schema_version: str


def game_summary_artifact_ref(valve_match_id: int) -> ArtifactRef:
    """Build the deterministic reference for a schema version 3 game summary."""

    return ArtifactRef(
        id=f"game_summary:3:{valve_match_id}",
        artifact_type="game_summary",
        schema_version="3",
    )


__all__ = ["ArtifactRef", "game_summary_artifact_ref"]
