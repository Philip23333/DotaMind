from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from app.domain.evidence import EvidenceItem, Source, Verdict


@dataclass(frozen=True)
class HeroRecommendation:
    hero: str
    role: str
    win_rate: float
    pick_rate: float
    ban_rate: float
    pro_presence: float
    meta_score: int
    confidence: float
    recommendation: str
    reasons: list[str]
    practice_advice: list[str]
    evidence: list[EvidenceItem]


@dataclass(frozen=True)
class MetaReport:
    report_type: Literal["meta_report"]
    game: str
    patch: str
    role: str
    summary: str
    top_heroes: list[HeroRecommendation]
    sources: list[Source]
    analysis_steps: list[str]
    confidence: float


@dataclass(frozen=True)
class PatchImpactReport:
    report_type: Literal["patch_impact"]
    game: str
    patch: str
    summary: str
    winners: list[str]
    losers: list[str]
    item_impacts: list[str]
    lineup_trends: list[str]
    practice_advice: list[str]
    sources: list[Source]
    confidence: float


@dataclass(frozen=True)
class TeamReport:
    report_type: Literal["team_report"]
    game: str
    team_name: str
    time_range: str
    summary: str
    recent_record: str
    matches_in_window: int
    match_details_analyzed: int
    signature_heroes: list[str]
    draft_preferences: list[str]
    win_patterns: list[str]
    loss_patterns: list[str]
    patch_adaptation_score: int
    key_players: list[str]
    sources: list[Source]
    confidence: float


@dataclass(frozen=True)
class ClaimVerificationReport:
    report_type: Literal["claim_verification"]
    game: str
    claim: str
    verdict: Verdict
    evidence: list[EvidenceItem]
    confidence: float
    missing_data: list[str]


ReportResult: TypeAlias = MetaReport | PatchImpactReport | TeamReport | ClaimVerificationReport


@dataclass(frozen=True)
class ServiceDescriptor:
    name: str
    endpoint: str
    price_usdc: float
    description: str
    input_schema: dict[str, str]


@dataclass(frozen=True)
class ServiceCatalog:
    services: list[ServiceDescriptor]
    commerce_status: str
    notes: list[str] = field(default_factory=list)
