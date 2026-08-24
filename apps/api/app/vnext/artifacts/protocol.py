"""Protocol for objects managed as artifacts."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class Artifact(Protocol):
    """Minimal metadata contract for an object managed as an artifact."""

    artifact_type: str
    schema_version: str
