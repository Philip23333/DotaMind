from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from app.core.config import get_policy
from app.domain.evidence import EvidenceBundle, EvidenceItem
from app.domain.reports import ReportResult

CriticSeverity = Literal["pass", "warning", "failed"]


@dataclass(frozen=True)
class CriticReview:
    passed: bool
    severity: CriticSeverity
    reasons: list[str]
    metadata: dict[str, Any]

    @classmethod
    def pass_(cls, metadata: dict[str, Any] | None = None) -> "CriticReview":
        return cls(
            passed=True,
            severity="pass",
            reasons=[],
            metadata=metadata or {},
        )

    @classmethod
    def warning(
        cls,
        reasons: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> "CriticReview":
        return cls(
            passed=True,
            severity="warning",
            reasons=reasons,
            metadata=metadata or {},
        )

    @classmethod
    def failed(
        cls,
        reasons: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> "CriticReview":
        return cls(
            passed=False,
            severity="failed",
            reasons=reasons,
            metadata=metadata or {},
        )


class CriticAgent:
    """Rule-first critic. This is the single review boundary before formatting."""

    def __init__(self) -> None:
        self.policy = get_policy().critic

    def review_report(
        self, report: ReportResult, bundle: EvidenceBundle | None = None
    ) -> CriticReview:
        issues = self._quality_issues(report, bundle)
        evidence = self._extract_evidence(report)
        evidence_review = self.review_evidence(evidence) if evidence is not None else None
        if evidence_review and evidence_review.reasons:
            issues.extend(
                {
                    "severity": evidence_review.severity,
                    "reason": reason,
                    "metadata": evidence_review.metadata,
                }
                for reason in evidence_review.reasons
            )

        metadata = self._review_metadata(report, bundle, issues)
        failed = [issue["reason"] for issue in issues if issue["severity"] == "failed"]
        if failed:
            return CriticReview.failed(failed, metadata)

        warnings = [issue["reason"] for issue in issues if issue["severity"] == "warning"]
        if warnings:
            return CriticReview.warning(warnings, metadata)

        if evidence_review:
            return CriticReview.pass_({**metadata, **evidence_review.metadata})
        return CriticReview.pass_(metadata)

    def review_evidence(self, evidence: list[EvidenceItem]) -> CriticReview:
        if self.policy.require_evidence and not evidence:
            return CriticReview.failed(
                ["No evidence items were attached."],
                {"evidence_count": 0},
            )
        if self.policy.require_evidence and len(evidence) < self.policy.min_evidence_items:
            return CriticReview.failed(
                [
                    "Insufficient evidence items: "
                    f"expected {self.policy.min_evidence_items}, got {len(evidence)}."
                ],
                {
                    "evidence_count": len(evidence),
                    "min_evidence_items": self.policy.min_evidence_items,
                },
            )
        if self.policy.reject_unsupported_signals:
            unsupported = [item.signal for item in evidence if item.verdict == "unsupported"]
            if unsupported:
                return CriticReview.failed(
                    [f"Unsupported evidence signals: {', '.join(unsupported)}."],
                    {
                        "evidence_count": len(evidence),
                        "unsupported_signals": unsupported,
                    },
                )
        return CriticReview.pass_({"evidence_count": len(evidence)})

    @staticmethod
    def _extract_evidence(report: ReportResult) -> list[EvidenceItem] | None:
        if report.report_type == "meta_report":
            evidence = []
            for hero in report.top_heroes:
                evidence.extend(hero.evidence)
            return evidence
        if report.report_type == "claim_verification":
            return report.evidence
        return None

    def _quality_issues(
        self, report: ReportResult, bundle: EvidenceBundle | None
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        issues.extend(self._mock_issues(report, bundle))
        issues.extend(self._confidence_issues(report))
        if report.report_type == "team_report":
            issues.extend(self._team_quality_issues(report))
        return issues

    def _mock_issues(
        self, report: ReportResult, bundle: EvidenceBundle | None
    ) -> list[dict[str, Any]]:
        if self.policy.mock_allowed:
            return []
        source_statuses = {source.status for source in getattr(report, "sources", [])}
        source_names = set(bundle.sources) if bundle else set()
        uses_mock = (
            "mocked" in source_statuses
            or "mock" in source_names
            or (bundle is not None and bundle.data_source == "mock")
        )
        if not uses_mock:
            return []

        severity: CriticSeverity = "failed" if report.report_type == "patch_impact" else "warning"
        return [
            {
                "severity": severity,
                "reason": f"{report.report_type} uses mock data while mock_allowed=false.",
                "metadata": {
                    "data_source": bundle.data_source if bundle else None,
                    "sources": sorted(source_names),
                    "source_statuses": sorted(source_statuses),
                },
            }
        ]

    def _confidence_issues(self, report: ReportResult) -> list[dict[str, Any]]:
        confidence = getattr(report, "confidence", None)
        if confidence is None:
            return []
        if confidence < self.policy.hard_min_confidence:
            return [
                {
                    "severity": "failed",
                    "reason": (
                        f"Report confidence {confidence:.2f} is below hard minimum "
                        f"{self.policy.hard_min_confidence:.2f}."
                    ),
                    "metadata": {"confidence": confidence},
                }
            ]
        if confidence < self.policy.min_confidence:
            return [
                {
                    "severity": "warning",
                    "reason": (
                        f"Report confidence {confidence:.2f} is below minimum "
                        f"{self.policy.min_confidence:.2f}."
                    ),
                    "metadata": {"confidence": confidence},
                }
            ]
        return []

    def _team_quality_issues(self, report: ReportResult) -> list[dict[str, Any]]:
        if report.report_type != "team_report":
            return []

        issues: list[dict[str, Any]] = []
        freshness = report.data_freshness
        team_policy = self.policy.team_report
        if not freshness.latest_match_at:
            issues.append(
                {
                    "severity": "warning",
                    "reason": (
                        "Team report has no latest match timestamp; "
                        "data freshness is unknown."
                    ),
                    "metadata": {"latest_match_at": None},
                }
            )
        else:
            age_days = CriticAgent._age_days(freshness.latest_match_at)
            if (
                age_days is not None
                and age_days > team_policy.hard_max_latest_match_age_days
            ):
                issues.append(
                    {
                        "severity": "failed",
                        "reason": (
                            f"Latest team match is {age_days:.0f} days old, above hard maximum "
                            f"{team_policy.hard_max_latest_match_age_days} days."
                        ),
                        "metadata": {"latest_match_age_days": age_days},
                    }
                )
            elif age_days is not None and age_days > team_policy.max_latest_match_age_days:
                issues.append(
                    {
                        "severity": "warning",
                        "reason": (
                            f"Latest team match is {age_days:.0f} days old, above freshness target "
                            f"{team_policy.max_latest_match_age_days} days."
                        ),
                        "metadata": {"latest_match_age_days": age_days},
                    }
                )

        if report.matches_in_window < team_policy.min_matches_in_window:
            issues.append(
                {
                    "severity": "failed",
                    "reason": (
                        "Team report has insufficient match sample: "
                        f"{report.matches_in_window} matches in window, expected at least "
                        f"{team_policy.min_matches_in_window}."
                    ),
                    "metadata": {"matches_in_window": report.matches_in_window},
                }
            )

        if report.match_details_analyzed < team_policy.min_match_details_analyzed:
            issues.append(
                {
                    "severity": "warning",
                    "reason": (
                        "Team report has limited detail sample: "
                        f"{report.match_details_analyzed} match details analyzed, "
                        "expected at least "
                        f"{team_policy.min_match_details_analyzed}."
                    ),
                    "metadata": {"match_details_analyzed": report.match_details_analyzed},
                }
            )

        return issues

    @staticmethod
    def _age_days(value: str) -> float | None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - parsed).total_seconds() / 86400

    @staticmethod
    def _review_metadata(
        report: ReportResult,
        bundle: EvidenceBundle | None,
        issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "report_type": report.report_type,
            "confidence": getattr(report, "confidence", None),
            "issue_count": len(issues),
        }
        if bundle is not None:
            metadata.update(
                {
                    "data_source": bundle.data_source,
                    "sources": bundle.sources,
                    "missing": bundle.missing,
                }
            )
        if report.report_type == "team_report":
            metadata.update(
                {
                    "latest_match_at": report.data_freshness.latest_match_at,
                    "matches_in_window": report.matches_in_window,
                    "match_details_analyzed": report.match_details_analyzed,
                }
            )
        return metadata
