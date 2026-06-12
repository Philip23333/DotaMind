from typing import Literal

from pydantic import BaseModel, Field

SupportedGame = Literal["dota2"]
Verdict = Literal["supported", "partially_supported", "weakly_supported", "unsupported"]


class Source(BaseModel):
    name: str
    kind: str
    url: str | None = None
    status: str = "planned"


class EvidenceItem(BaseModel):
    signal: str
    verdict: Verdict
    detail: str
    source: str


class HeroRecommendation(BaseModel):
    hero: str
    role: str
    win_rate: float = Field(ge=0, le=1)
    pick_rate: float = Field(ge=0, le=1)
    ban_rate: float = Field(ge=0, le=1)
    pro_presence: float = Field(ge=0, le=1)
    meta_score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    recommendation: str
    reasons: list[str]
    practice_advice: list[str]
    evidence: list[EvidenceItem]


class MetaReportRequest(BaseModel):
    game: SupportedGame = "dota2"
    patch: str = "latest"
    role: str = "offlane"


class MetaReportResponse(BaseModel):
    report_type: Literal["meta_report"] = "meta_report"
    game: SupportedGame
    patch: str
    role: str
    summary: str
    top_heroes: list[HeroRecommendation]
    sources: list[Source]
    analysis_steps: list[str]
    confidence: float = Field(ge=0, le=1)


class PatchImpactRequest(BaseModel):
    game: SupportedGame = "dota2"
    patch: str = "latest"
    role: str | None = None


class PatchImpactResponse(BaseModel):
    report_type: Literal["patch_impact"] = "patch_impact"
    game: SupportedGame
    patch: str
    summary: str
    winners: list[str]
    losers: list[str]
    item_impacts: list[str]
    lineup_trends: list[str]
    practice_advice: list[str]
    sources: list[Source]
    confidence: float = Field(ge=0, le=1)


class TeamReportRequest(BaseModel):
    game: SupportedGame = "dota2"
    team_name: str = "Team Spirit"
    time_range: str = "last_30_days"


class TeamReportResponse(BaseModel):
    report_type: Literal["team_report"] = "team_report"
    game: SupportedGame
    team_name: str
    time_range: str
    summary: str
    recent_record: str
    signature_heroes: list[str]
    draft_preferences: list[str]
    win_patterns: list[str]
    loss_patterns: list[str]
    patch_adaptation_score: int = Field(ge=0, le=100)
    key_players: list[str]
    sources: list[Source]
    confidence: float = Field(ge=0, le=1)


class ClaimVerificationRequest(BaseModel):
    game: SupportedGame = "dota2"
    claim: str


class ClaimVerificationResponse(BaseModel):
    report_type: Literal["claim_verification"] = "claim_verification"
    game: SupportedGame
    claim: str
    verdict: Verdict
    evidence: list[EvidenceItem]
    confidence: float = Field(ge=0, le=1)
    missing_data: list[str]


class ServiceDescriptor(BaseModel):
    name: str
    endpoint: str
    price_usdc: float
    description: str
    input_schema: dict[str, str]


class ServiceCatalogResponse(BaseModel):
    services: list[ServiceDescriptor]
    commerce_status: str
    notes: list[str]


class NaturalLanguageQueryRequest(BaseModel):
    query: str
    game: SupportedGame = "dota2"


class PlannedTask(BaseModel):
    agent: str
    action: str
    status: str = "planned"


class NaturalLanguageQueryResponse(BaseModel):
    query: str
    routed_service: str
    tasks: list[PlannedTask]
    result: (
        MetaReportResponse
        | PatchImpactResponse
        | TeamReportResponse
        | ClaimVerificationResponse
    )
