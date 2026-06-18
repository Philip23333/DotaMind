from dataclasses import dataclass, field
from typing import Literal

ReportTask = Literal["meta_report", "patch_impact", "team_report", "claim_verification"]


@dataclass(frozen=True)
class PlannedTask:
    agent: str
    action: str
    status: str = "planned"


@dataclass(frozen=True)
class ReportRequest:
    task_type: ReportTask
    game: str = "dota2"
    query: str | None = None
    patch: str = "latest"
    role: str | None = None
    team_name: str | None = None
    time_range: str = "last_30_days"
    claim: str | None = None
    trace: list[PlannedTask] = field(default_factory=list)
