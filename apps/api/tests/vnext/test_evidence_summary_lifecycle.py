from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.vnext.agent.evidence_summary import (
    CompressionReason,
    CompressionRequest,
    EvidenceSummaryCandidate,
    SummaryClaimCandidate,
    SummaryClaimStatus,
)
from app.vnext.agent.evidence_summary_lifecycle import (
    EvidenceSummaryCoordinator,
    EvidenceSummaryValidationError,
)
from app.vnext.artifacts.lifecycle import ArtifactObservation


def _request(
    *,
    source_tool_call_ids: tuple[str, ...] = ("read-a", "read-b"),
    required_dimensions: tuple[str, ...] = ("tournament_results", "ti_result"),
) -> CompressionRequest:
    return CompressionRequest(
        request_id="compression:one",
        reason=CompressionReason.MANUAL,
        coverage_key="xg_2023",
        source_tool_call_ids=source_tool_call_ids,
        required_dimensions=required_dimensions,
    )


def _observation(
    tool_call_id: str,
    *,
    ref: str | None = None,
    path: str | None = "rows",
    actual_start: int | None = 0,
    actual_end: int | None = 50,
) -> ArtifactObservation:
    return ArtifactObservation(
        tool_call_id=tool_call_id,
        message_index=1,
        ref=ref or f"artifact:tool:{tool_call_id}",
        path=path,
        value=[{"tool_call_id": tool_call_id}],
        offset=actual_start,
        requested_limit=50,
        actual_start=actual_start,
        actual_end=actual_end,
        kind="list_slice",
    )


def _candidate(
    *,
    compression_request_id: str = "compression:one",
    claims: Sequence[SummaryClaimCandidate] | None = None,
) -> EvidenceSummaryCandidate:
    return EvidenceSummaryCandidate(
        compression_request_id=compression_request_id,
        claims=tuple(
            claims
            or (
                SummaryClaimCandidate(
                    dimension="tournament_results",
                    value={"placement": "7th-8th"},
                    status=SummaryClaimStatus.CONFIRMED,
                    source_tool_call_ids=("read-a",),
                ),
                SummaryClaimCandidate(
                    dimension="ti_result",
                    value={"placement": "7th-8th"},
                    status=SummaryClaimStatus.PARTIAL,
                    source_tool_call_ids=("read-b",),
                ),
            )
        ),
    )


def _assert_error(
    coordinator: EvidenceSummaryCoordinator,
    request: CompressionRequest,
    candidate: EvidenceSummaryCandidate,
    observations: Sequence[ArtifactObservation],
    code: str,
) -> EvidenceSummaryValidationError:
    with pytest.raises(EvidenceSummaryValidationError) as caught:
        coordinator.commit(request, candidate, observations)
    assert caught.value.code == code
    return caught.value


def test_valid_candidate_commits_summary_with_runtime_owned_fields() -> None:
    request = _request()
    coordinator = EvidenceSummaryCoordinator()

    summary = coordinator.commit(
        request,
        _candidate(),
        (_observation("read-a"), _observation("read-b")),
    )

    assert summary.summary_id.startswith("summary:")
    assert summary.compression_request_id == request.request_id
    assert summary.coverage_key == request.coverage_key
    assert summary.reason is request.reason
    assert summary.created_at.utcoffset().total_seconds() == 0
    assert coordinator.store.get(summary.summary_id) == summary


def test_canonical_source_locator_comes_from_active_observation() -> None:
    request = _request(
        source_tool_call_ids=("read-a",),
        required_dimensions=("tournament_results",),
    )
    candidate = _candidate(
        claims=(
            SummaryClaimCandidate(
                dimension="tournament_results",
                value={"placement": "7th-8th"},
                status=SummaryClaimStatus.CONFIRMED,
                source_tool_call_ids=("read-a",),
            ),
        )
    )
    observation = _observation(
        "read-a",
        ref="artifact:tool:actual",
        path="result.rows",
        actual_start=3,
        actual_end=11,
    )

    summary = EvidenceSummaryCoordinator().commit(request, candidate, (observation,))

    assert summary.claims[0].source_refs[0].tool_call_id == "read-a"
    assert summary.claims[0].source_refs[0].artifact_ref == "artifact:tool:actual"
    assert summary.claims[0].source_refs[0].path == "result.rows"
    assert summary.claims[0].source_refs[0].actual_start == 3
    assert summary.claims[0].source_refs[0].actual_end == 11


def test_request_id_mismatch_does_not_change_store() -> None:
    coordinator = EvidenceSummaryCoordinator()

    _assert_error(
        coordinator,
        _request(),
        _candidate(compression_request_id="compression:other"),
        (_observation("read-a"), _observation("read-b")),
        "compression_request_mismatch",
    )

    assert coordinator.store.list() == []


def test_inactive_request_source_is_rejected() -> None:
    request = _request(source_tool_call_ids=("read-a", "read-gone"))
    candidate = _candidate()

    error = _assert_error(
        EvidenceSummaryCoordinator(),
        request,
        candidate,
        (_observation("read-a"),),
        "inactive_summary_source",
    )

    assert error.details == {"inactive_sources": ["read-gone"]}


def test_claim_source_outside_request_is_rejected() -> None:
    request = _request(required_dimensions=("tournament_results",))
    candidate = _candidate(
        claims=(
            SummaryClaimCandidate(
                dimension="tournament_results",
                value={"placement": "7th-8th"},
                status=SummaryClaimStatus.CONFIRMED,
                source_tool_call_ids=("read-c",),
            ),
        )
    )

    error = _assert_error(
        EvidenceSummaryCoordinator(),
        request,
        candidate,
        (_observation("read-a"), _observation("read-b"), _observation("read-c")),
        "summary_source_outside_request",
    )

    assert error.details["invalid_sources"] == ["read-c"]


def test_missing_required_dimension_is_rejected() -> None:
    request = _request(required_dimensions=("tournament_results", "ti_result"))
    candidate = _candidate(
        claims=(
            SummaryClaimCandidate(
                dimension="tournament_results",
                value={"placement": "7th-8th"},
                status=SummaryClaimStatus.CONFIRMED,
                source_tool_call_ids=("read-a",),
            ),
        )
    )

    error = _assert_error(
        EvidenceSummaryCoordinator(),
        request,
        candidate,
        (_observation("read-a"), _observation("read-b")),
        "missing_summary_dimensions",
    )

    assert error.details == {"missing_dimensions": ["ti_result"]}


def test_extra_candidate_dimension_is_allowed() -> None:
    request = _request(required_dimensions=("tournament_results",))
    candidate = _candidate(
        claims=(
            SummaryClaimCandidate(
                dimension="tournament_results",
                value={"placement": "7th-8th"},
                status=SummaryClaimStatus.CONFIRMED,
                source_tool_call_ids=("read-a",),
            ),
            SummaryClaimCandidate(
                dimension="roster",
                value={"status": "unknown"},
                status=SummaryClaimStatus.UNKNOWN,
                source_tool_call_ids=(),
            ),
        )
    )

    summary = EvidenceSummaryCoordinator().commit(
        request,
        candidate,
        (_observation("read-a"), _observation("read-b")),
    )

    assert [claim.dimension for claim in summary.claims] == ["tournament_results", "roster"]


def test_duplicate_candidate_dimension_is_rejected() -> None:
    request = _request(required_dimensions=("tournament_results",))
    candidate = _candidate(
        claims=(
            SummaryClaimCandidate(
                dimension="tournament_results",
                value=1,
                status=SummaryClaimStatus.CONFIRMED,
                source_tool_call_ids=("read-a",),
            ),
            SummaryClaimCandidate(
                dimension="tournament_results",
                value=2,
                status=SummaryClaimStatus.CONFIRMED,
                source_tool_call_ids=("read-b",),
            ),
        )
    )

    _assert_error(
        EvidenceSummaryCoordinator(),
        request,
        candidate,
        (_observation("read-a"), _observation("read-b")),
        "duplicate_summary_dimension",
    )


@pytest.mark.parametrize("status", [SummaryClaimStatus.CONFIRMED, SummaryClaimStatus.PARTIAL])
def test_confirmed_or_partial_claim_requires_source(status: SummaryClaimStatus) -> None:
    request = _request(required_dimensions=("tournament_results",))
    candidate = _candidate(
        claims=(
            SummaryClaimCandidate(
                dimension="tournament_results",
                value={"placement": "unknown"},
                status=status,
                source_tool_call_ids=(),
            ),
        )
    )

    _assert_error(
        EvidenceSummaryCoordinator(),
        request,
        candidate,
        (_observation("read-a"), _observation("read-b")),
        "summary_claim_missing_source",
    )


def test_unknown_claim_without_source_is_allowed() -> None:
    request = _request(required_dimensions=("roster",))
    candidate = _candidate(
        claims=(
            SummaryClaimCandidate(
                dimension="roster",
                value=None,
                status=SummaryClaimStatus.UNKNOWN,
                source_tool_call_ids=(),
            ),
        )
    )

    summary = EvidenceSummaryCoordinator().commit(
        request,
        candidate,
        (_observation("read-a"), _observation("read-b")),
    )

    assert summary.claims[0].source_refs == ()
    assert summary.source_refs == ()


def test_duplicate_source_in_one_claim_is_rejected() -> None:
    request = _request(required_dimensions=("tournament_results",))
    candidate = _candidate(
        claims=(
            SummaryClaimCandidate(
                dimension="tournament_results",
                value={"placement": "7th-8th"},
                status=SummaryClaimStatus.CONFIRMED,
                source_tool_call_ids=("read-a", "read-a"),
            ),
        )
    )

    _assert_error(
        EvidenceSummaryCoordinator(),
        request,
        candidate,
        (_observation("read-a"), _observation("read-b")),
        "duplicate_summary_source",
    )


def test_summary_source_refs_are_union_in_request_order() -> None:
    request = _request(source_tool_call_ids=("read-b", "read-a", "read-c"))
    candidate = _candidate(
        claims=(
            SummaryClaimCandidate(
                dimension="tournament_results",
                value=1,
                status=SummaryClaimStatus.CONFIRMED,
                source_tool_call_ids=("read-a",),
            ),
            SummaryClaimCandidate(
                dimension="ti_result",
                value=2,
                status=SummaryClaimStatus.CONFIRMED,
                source_tool_call_ids=("read-c",),
            ),
        )
    )
    observations = tuple(_observation(source_id) for source_id in ("read-a", "read-b", "read-c"))

    summary = EvidenceSummaryCoordinator().commit(request, candidate, observations)

    assert [ref.tool_call_id for ref in summary.source_refs] == ["read-a", "read-c"]
    assert [ref.tool_call_id for ref in summary.claims[0].source_refs] == ["read-a"]


def test_failed_commit_is_atomic() -> None:
    request = _request()
    coordinator = EvidenceSummaryCoordinator()
    candidate = _candidate(
        claims=(
            SummaryClaimCandidate(
                dimension="tournament_results",
                value=1,
                status=SummaryClaimStatus.CONFIRMED,
                source_tool_call_ids=("read-a", "read-a"),
            ),
            SummaryClaimCandidate(
                dimension="ti_result",
                value=2,
                status=SummaryClaimStatus.CONFIRMED,
                source_tool_call_ids=("read-b",),
            ),
        )
    )

    _assert_error(
        coordinator,
        request,
        candidate,
        (_observation("read-a"), _observation("read-b")),
        "duplicate_summary_source",
    )

    assert coordinator.store.list() == []
