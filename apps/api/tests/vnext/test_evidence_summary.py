from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.vnext.agent.evidence_summary import (
    CompressionReason,
    CompressionRequest,
    EvidenceSourceRef,
    EvidenceSummary,
    EvidenceSummaryStore,
    SummaryClaim,
    SummaryClaimStatus,
)


def _sources() -> tuple[EvidenceSourceRef, EvidenceSourceRef]:
    return (
        EvidenceSourceRef(
            tool_call_id="read-matches",
            artifact_ref="artifact:tool:matches",
            path="rows",
            actual_start=0,
            actual_end=50,
        ),
        EvidenceSourceRef(
            tool_call_id="read-ti",
            artifact_ref="artifact:tool:ti",
            path=None,
        ),
    )


def _summary(summary_id: str, *, coverage_key: str = "xg_2023") -> EvidenceSummary:
    sources = _sources()
    return EvidenceSummary(
        summary_id=summary_id,
        compression_request_id=f"request:{summary_id}",
        coverage_key=coverage_key,
        reason=CompressionReason.MANUAL,
        claims=(
            SummaryClaim(
                dimension="tournament_results",
                value={"placement": "7th-8th"},
                status=SummaryClaimStatus.CONFIRMED,
                source_refs=(sources[0],),
            ),
            SummaryClaim(
                dimension="ti_result",
                value={"placement": "7th-8th"},
                status=SummaryClaimStatus.PARTIAL,
                source_refs=(sources[1],),
            ),
        ),
        source_refs=sources,
        created_at=datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc),
    )


def test_compression_request_expresses_typed_input_without_execution() -> None:
    request = CompressionRequest(
        request_id="request:one",
        reason=CompressionReason.MANUAL,
        coverage_key="xg_2023",
        source_tool_call_ids=("read-matches", "read-ti"),
        required_dimensions=("tournament_results", "ti_result"),
    )

    assert request.reason is CompressionReason.MANUAL
    assert request.source_tool_call_ids == ("read-matches", "read-ti")
    assert request.target_bytes is None


def test_summary_preserves_canonical_sources_and_actual_slice() -> None:
    summary = _summary("summary:one")

    assert summary.claims[0].source_refs[0].tool_call_id == "read-matches"
    assert summary.source_refs[0].artifact_ref == "artifact:tool:matches"
    assert summary.source_refs[0].actual_start == 0
    assert summary.source_refs[0].actual_end == 50
    assert summary.created_at.tzinfo is timezone.utc


def test_summary_rejects_naive_or_non_utc_created_at() -> None:
    summary = _summary("summary:one")

    with pytest.raises(ValueError, match="timezone-aware UTC"):
        EvidenceSummary(
            summary_id=summary.summary_id,
            compression_request_id=summary.compression_request_id,
            coverage_key=summary.coverage_key,
            reason=summary.reason,
            claims=summary.claims,
            source_refs=summary.source_refs,
            created_at=datetime(2026, 9, 19),
        )


def test_store_put_get_list_and_snapshot_are_deterministic() -> None:
    first = _summary("summary:b")
    second = _summary("summary:a")
    store = EvidenceSummaryStore()

    store.put(first)
    store.put(second)

    assert store.get("summary:b") == first
    assert store.get("summary:b") is not first
    assert store.get("missing") is None
    assert store.list() == [second, first]
    assert list(store.snapshot()) == ["summary:a", "summary:b"]
    assert store.snapshot() == {"summary:a": second, "summary:b": first}


def test_store_allows_multiple_summaries_for_one_coverage_key() -> None:
    store = EvidenceSummaryStore()
    first = _summary("summary:one")
    second = _summary("summary:two")

    store.put(first)
    store.put(second)

    assert [summary.coverage_key for summary in store.list()] == [
        "xg_2023",
        "xg_2023",
    ]


def test_store_rejects_duplicate_summary_id_without_replacement() -> None:
    store = EvidenceSummaryStore()
    original = _summary("summary:one")
    replacement = _summary("summary:one", coverage_key="xg_2024")
    store.put(original)

    with pytest.raises(ValueError, match="summary:one"):
        store.put(replacement)

    assert store.get("summary:one") == original
    assert store.get("summary:one") is not original


def test_store_defensively_copies_mutable_values_on_put() -> None:
    summary = _summary("summary:one")
    store = EvidenceSummaryStore()
    store.put(summary)

    summary.claims[0].value["placement"] = "changed"

    stored = store.get("summary:one")
    assert stored is not None
    assert stored.claims[0].value == {"placement": "7th-8th"}


def test_store_defensively_copies_mutable_values_on_read() -> None:
    store = EvidenceSummaryStore()
    store.put(_summary("summary:one"))

    returned = store.get("summary:one")
    assert returned is not None
    returned.claims[0].value["placement"] = "changed"

    stored = store.get("summary:one")
    assert stored is not None
    assert stored.claims[0].value == {"placement": "7th-8th"}
