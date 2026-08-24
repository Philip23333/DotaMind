"""Provider-neutral models used by the artifact store."""

from pydantic import BaseModel, ConfigDict


class ArtifactRef(BaseModel):
    """Stable identity and schema information for one artifact."""

    model_config = ConfigDict(frozen=True)

    id: str
    artifact_type: str
    schema_version: str
