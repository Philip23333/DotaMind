"""Provider-neutral models used by the artifact store."""

from pydantic import BaseModel, ConfigDict, Field


class ArtifactRef(BaseModel):
    """Stable identity and schema information for one artifact."""

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "description": (
                "Artifact reference object. Pass the complete object returned by artifact.search. "
                "Do not pass one field as a bare string or JSON-encode this object into a string."
            ),
            "examples": [
                {
                    "id": "game_summary:3:8123456789",
                    "artifact_type": "game_summary",
                    "schema_version": "3",
                }
            ],
        },
    )

    id: str = Field(description="Artifact identity inside this reference object.")
    artifact_type: str = Field(description="Artifact type inside this reference object.")
    schema_version: str = Field(description="Artifact schema version inside this reference object.")


def game_summary_artifact_ref(valve_match_id: int) -> ArtifactRef:
    """Build the deterministic reference for a schema version 3 game summary."""

    return ArtifactRef(
        id=f"game_summary:3:{valve_match_id}",
        artifact_type="game_summary",
        schema_version="3",
    )


__all__ = ["ArtifactRef", "game_summary_artifact_ref"]
