"""Immutable Evidence Summary data contracts and in-memory storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any


class CompressionReason(str, Enum):
    """Why a summary compression request was created."""

    MANUAL = "manual"
    COVERAGE_READY = "coverage_ready"
    CONTEXT_PRESSURE = "context_pressure"
    ANSWER_FINALIZATION = "answer_finalization"


class SummaryClaimStatus(str, Enum):
    """Confidence/status of one structured summary claim."""

    CONFIRMED = "confirmed"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class EvidenceSourceRef:
    """Canonical reference to one raw observation or observation slice."""

    tool_call_id: str
    artifact_ref: str
    path: str | None
    actual_start: int | None = None
    actual_end: int | None = None


@dataclass(frozen=True, slots=True)
class CompressionRequest:
    """Typed input describing the evidence a future compression step may use."""

    request_id: str
    reason: CompressionReason
    coverage_key: str | None
    source_tool_call_ids: tuple[str, ...]
    required_dimensions: tuple[str, ...]
    target_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class SummaryClaim:
    """One structured claim with canonical source references."""

    dimension: str
    value: Any
    status: SummaryClaimStatus
    source_refs: tuple[EvidenceSourceRef, ...]


@dataclass(frozen=True, slots=True)
class EvidenceSummary:
    """A committed, traceable summary of raw evidence."""

    summary_id: str
    compression_request_id: str
    coverage_key: str | None
    reason: CompressionReason
    claims: tuple[SummaryClaim, ...]
    source_refs: tuple[EvidenceSourceRef, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        """Require the committed summary timestamp to be timezone-aware UTC."""

        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("evidence summary created_at must be timezone-aware UTC")


class EvidenceSummaryStore:
    """Deterministic in-memory storage for committed Evidence Summaries."""

    def __init__(self) -> None:
        self._summaries: dict[str, EvidenceSummary] = {}

    def put(self, summary: EvidenceSummary) -> None:
        """Store one summary without allowing an existing ID to be replaced."""

        if summary.summary_id in self._summaries:
            raise ValueError(f"evidence summary already exists: {summary.summary_id}")
        self._summaries[summary.summary_id] = summary

    def get(self, summary_id: str) -> EvidenceSummary | None:
        """Return one summary by ID, or ``None`` when it is not stored."""

        return self._summaries.get(summary_id)

    def list(self) -> list[EvidenceSummary]:
        """Return summaries in stable summary-ID order."""

        return [self._summaries[summary_id] for summary_id in sorted(self._summaries)]

    def snapshot(self) -> dict[str, EvidenceSummary]:
        """Return a stable shallow copy keyed in summary-ID order."""

        return {
            summary_id: self._summaries[summary_id]
            for summary_id in sorted(self._summaries)
        }


__all__ = [
    "CompressionReason",
    "CompressionRequest",
    "EvidenceSourceRef",
    "EvidenceSummary",
    "EvidenceSummaryStore",
    "SummaryClaim",
    "SummaryClaimStatus",
]
