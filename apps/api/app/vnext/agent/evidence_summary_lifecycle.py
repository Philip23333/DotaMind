"""Deterministic validation and commit of Evidence Summary candidates."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.vnext.agent.evidence_summary import (
    CompressionRequest,
    EvidenceSourceRef,
    EvidenceSummary,
    EvidenceSummaryCandidate,
    EvidenceSummaryStore,
    SummaryClaim,
    SummaryClaimCandidate,
    SummaryClaimStatus,
)
from app.vnext.artifacts.lifecycle import ArtifactObservation


class EvidenceSummaryValidationError(ValueError):
    """A recoverable validation failure while committing a summary candidate."""

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.details = dict(details or {})
        super().__init__(message)


class EvidenceSummaryCoordinator:
    """Validate candidates and commit canonical summaries without releasing raw evidence."""

    def __init__(self, store: EvidenceSummaryStore | None = None) -> None:
        self.store = store or EvidenceSummaryStore()

    def commit(
        self,
        request: CompressionRequest,
        candidate: EvidenceSummaryCandidate,
        active_observations: Sequence[ArtifactObservation],
    ) -> EvidenceSummary:
        """Validate and commit one candidate against an ACTIVE_RAW snapshot."""

        if candidate.compression_request_id != request.request_id:
            raise EvidenceSummaryValidationError(
                "compression_request_mismatch",
                "summary candidate does not match compression request",
                {
                    "request_id": request.request_id,
                    "candidate_request_id": candidate.compression_request_id,
                },
            )

        request_source_ids = _validate_request_source_ids(request)
        claims = _validate_claims(candidate)
        candidate_dimensions = {claim.dimension for claim in claims}
        missing_dimensions = [
            dimension
            for dimension in request.required_dimensions
            if dimension not in candidate_dimensions
        ]
        if missing_dimensions:
            raise EvidenceSummaryValidationError(
                "missing_summary_dimensions",
                "summary candidate is missing required dimensions",
                {"missing_dimensions": missing_dimensions},
            )

        observation_by_id = _index_active_observations(active_observations)
        inactive_sources = [
            source_id
            for source_id in request_source_ids
            if source_id not in observation_by_id
        ]
        if inactive_sources:
            raise EvidenceSummaryValidationError(
                "inactive_summary_source",
                "compression request contains inactive summary sources",
                {"inactive_sources": inactive_sources},
            )

        request_source_set = set(request_source_ids)
        canonical_by_id = {
            source_id: _canonical_source_ref(observation_by_id[source_id])
            for source_id in request_source_ids
        }
        committed_claims: list[SummaryClaim] = []
        used_source_ids: set[str] = set()
        for claim in claims:
            claim_source_ids = _validate_claim_sources(
                claim,
                request_source_set=request_source_set,
            )
            if (
                claim.status in {SummaryClaimStatus.CONFIRMED, SummaryClaimStatus.PARTIAL}
                and not claim_source_ids
            ):
                raise EvidenceSummaryValidationError(
                    "summary_claim_missing_source",
                    "confirmed or partial summary claims require source references",
                    {"dimension": claim.dimension},
                )

            ordered_source_ids = tuple(
                source_id
                for source_id in request_source_ids
                if source_id in claim_source_ids
            )
            used_source_ids.update(ordered_source_ids)
            committed_claims.append(
                SummaryClaim(
                    dimension=claim.dimension,
                    value=claim.value,
                    status=claim.status,
                    source_refs=tuple(
                        canonical_by_id[source_id] for source_id in ordered_source_ids
                    ),
                )
            )

        summary = EvidenceSummary(
            summary_id=f"summary:{uuid4()}",
            compression_request_id=request.request_id,
            coverage_key=request.coverage_key,
            reason=request.reason,
            claims=tuple(committed_claims),
            source_refs=tuple(
                canonical_by_id[source_id]
                for source_id in request_source_ids
                if source_id in used_source_ids
            ),
            created_at=datetime.now(timezone.utc),
        )
        self.store.put(summary)
        return summary


def _validate_request_source_ids(request: CompressionRequest) -> tuple[str, ...]:
    source_ids = request.source_tool_call_ids
    if not source_ids:
        raise EvidenceSummaryValidationError(
            "invalid_compression_sources",
            "compression request must contain at least one source tool call ID",
        )
    invalid = [
        source_id
        for source_id in source_ids
        if not isinstance(source_id, str) or not source_id
    ]
    if invalid:
        raise EvidenceSummaryValidationError(
            "invalid_compression_sources",
            "compression request source tool call IDs must be non-empty strings",
            {"invalid_sources": invalid},
        )
    duplicates = _duplicates(source_ids)
    if duplicates:
        raise EvidenceSummaryValidationError(
            "duplicate_compression_source",
            "compression request source tool call IDs must be unique",
            {"duplicate_sources": duplicates},
        )
    return tuple(source_ids)


def _validate_claims(candidate: EvidenceSummaryCandidate) -> tuple[SummaryClaimCandidate, ...]:
    claims = candidate.claims
    if not claims:
        raise EvidenceSummaryValidationError(
            "empty_summary_claims",
            "summary candidate must contain at least one claim",
        )

    seen_dimensions: set[str] = set()
    for claim in claims:
        if not isinstance(claim.dimension, str) or not claim.dimension:
            raise EvidenceSummaryValidationError(
                "invalid_summary_dimension",
                "summary claim dimensions must be non-empty strings",
            )
        if claim.dimension in seen_dimensions:
            raise EvidenceSummaryValidationError(
                "duplicate_summary_dimension",
                "summary candidate dimensions must be unique",
                {"dimension": claim.dimension},
            )
        if not isinstance(claim.status, SummaryClaimStatus):
            raise EvidenceSummaryValidationError(
                "invalid_summary_claim_status",
                "summary claim status is invalid",
                {"dimension": claim.dimension},
            )
        seen_dimensions.add(claim.dimension)
    return tuple(claims)


def _validate_claim_sources(
    claim: SummaryClaimCandidate,
    *,
    request_source_set: set[str],
) -> tuple[str, ...]:
    source_ids = claim.source_tool_call_ids
    invalid = [
        source_id
        for source_id in source_ids
        if not isinstance(source_id, str) or not source_id
    ]
    if invalid:
        raise EvidenceSummaryValidationError(
            "invalid_summary_claim_sources",
            "summary claim source tool call IDs must be non-empty strings",
            {"dimension": claim.dimension, "invalid_sources": invalid},
        )
    duplicates = _duplicates(source_ids)
    if duplicates:
        raise EvidenceSummaryValidationError(
            "duplicate_summary_source",
            "summary claim source tool call IDs must be unique",
            {"dimension": claim.dimension, "duplicate_sources": duplicates},
        )
    outside_request = [source_id for source_id in source_ids if source_id not in request_source_set]
    if outside_request:
        raise EvidenceSummaryValidationError(
            "summary_source_outside_request",
            "summary claim references a source outside the compression request",
            {"dimension": claim.dimension, "invalid_sources": outside_request},
        )
    return tuple(source_ids)


def _index_active_observations(
    observations: Sequence[ArtifactObservation],
) -> dict[str, ArtifactObservation]:
    indexed: dict[str, ArtifactObservation] = {}
    for observation in observations:
        if observation.tool_call_id in indexed:
            raise EvidenceSummaryValidationError(
                "duplicate_active_observation",
                "active observations must have unique tool call IDs",
                {"tool_call_id": observation.tool_call_id},
            )
        indexed[observation.tool_call_id] = observation
    return indexed


def _canonical_source_ref(observation: ArtifactObservation) -> EvidenceSourceRef:
    return EvidenceSourceRef(
        tool_call_id=observation.tool_call_id,
        artifact_ref=observation.ref,
        path=observation.path,
        actual_start=observation.actual_start,
        actual_end=observation.actual_end,
    )


def _duplicates(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


__all__ = ["EvidenceSummaryCoordinator", "EvidenceSummaryValidationError"]
