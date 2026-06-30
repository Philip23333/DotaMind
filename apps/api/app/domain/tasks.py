from dataclasses import dataclass, field
from typing import Literal

from app.core.config import default_patch, default_time_range

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
    patch: str = field(default_factory=default_patch)
    role: str | None = None
    team_name: str | None = None
    team_id: int | None = None
    time_range: str = field(default_factory=default_time_range)
    claim: str | None = None
    trace: list[PlannedTask] = field(default_factory=list)
