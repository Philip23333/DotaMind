from dataclasses import dataclass, field
from typing import Any, Literal

Verdict = Literal["supported", "partially_supported", "weakly_supported", "unsupported"]
DataSource = Literal["opendota", "patch_json", "mock", "mixed", "error", "placeholder"]


@dataclass(frozen=True)
class Source:
    name: str
    kind: str
    url: str | None = None
    status: str = "planned"


@dataclass(frozen=True)
class EvidenceItem:
    signal: str
    verdict: Verdict
    detail: str
    source: str


@dataclass(frozen=True)
class EvidenceBundle:
    task_type: str
    query: dict[str, Any]
    records: list[dict[str, Any]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    data_source: DataSource = "placeholder"
    missing: list[str] = field(default_factory=list)
