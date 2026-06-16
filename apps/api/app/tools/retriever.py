from dataclasses import dataclass, field
from typing import Any, Literal

TaskType = Literal["meta_report", "patch_impact", "team_report", "claim_verification"]


@dataclass(frozen=True)
class EvidenceBundle:
    task_type: TaskType
    query: dict[str, Any]
    records: list[dict[str, Any]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


class RetrieverTool:
    """Placeholder for deterministic evidence assembly from OpenDota and patch JSON."""

    def bundle(self, task_type: TaskType, **query: Any) -> EvidenceBundle:
        return EvidenceBundle(task_type=task_type, query=query)
