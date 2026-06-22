from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "policy.yaml"


class StrictPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OpenDotaPolicy(StrictPolicyModel):
    request_timeout_seconds: float = Field(gt=0)
    default_cache_ttl_seconds: int = Field(gt=0)


class MatchDetailPolicy(StrictPolicyModel):
    default_sample_size: int = Field(ge=1, le=100)
    max_sample_size: int = Field(ge=1, le=100)
    concurrency: int = Field(ge=1, le=15)
    cache_ttl_seconds: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_sample_sizes(self) -> "MatchDetailPolicy":
        if self.default_sample_size > self.max_sample_size:
            raise ValueError("default_sample_size cannot exceed max_sample_size")
        return self


class TeamResolutionPolicy(StrictPolicyModel):
    generic_words: list[str] = Field(min_length=1)
    fuzzy_score_cutoff: float = Field(ge=0, le=100)
    ambiguity_score_delta: float = Field(ge=0, le=100)
    candidate_limit: int = Field(ge=1, le=20)


class TeamReportPolicy(StrictPolicyModel):
    default_time_range_days: int = Field(gt=0)
    resolution: TeamResolutionPolicy
    match_details: MatchDetailPolicy


class HeroEvidencePolicy(StrictPolicyModel):
    partial_win_rate: float = Field(ge=0, le=1)
    supported_win_rate: float = Field(ge=0, le=1)
    partial_pro_presence: float = Field(ge=0, le=1)
    supported_pro_presence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_thresholds(self) -> "HeroEvidencePolicy":
        if self.partial_win_rate > self.supported_win_rate:
            raise ValueError("partial_win_rate cannot exceed supported_win_rate")
        if self.partial_pro_presence > self.supported_pro_presence:
            raise ValueError(
                "partial_pro_presence cannot exceed supported_pro_presence"
            )
        return self


class HeroNormalizationPolicy(StrictPolicyModel):
    win_rate_low: float = Field(ge=0, le=1)
    win_rate_high: float = Field(ge=0, le=1)
    pick_rate_low: float = Field(ge=0, le=1)
    pick_rate_high: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_ranges(self) -> "HeroNormalizationPolicy":
        if self.win_rate_low >= self.win_rate_high:
            raise ValueError("win_rate_low must be lower than win_rate_high")
        if self.pick_rate_low >= self.pick_rate_high:
            raise ValueError("pick_rate_low must be lower than pick_rate_high")
        return self


class HeroScoreWeights(StrictPolicyModel):
    win_rate: float = Field(ge=0, le=1)
    pick_rate: float = Field(ge=0, le=1)
    pro_presence: float = Field(ge=0, le=1)
    patch_impact: float = Field(ge=0, le=1)
    trend: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_total(self) -> "HeroScoreWeights":
        total = self.win_rate + self.pick_rate + self.pro_presence + self.patch_impact + self.trend
        if abs(total - 1.0) > 1e-9:
            raise ValueError("hero score weights must sum to 1.0")
        return self


class HeroTierPolicy(StrictPolicyModel):
    s: int = Field(ge=0, le=100)
    a: int = Field(ge=0, le=100)
    b: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_order(self) -> "HeroTierPolicy":
        if not self.s > self.a > self.b:
            raise ValueError("hero tier thresholds must satisfy s > a > b")
        return self


class HeroReportPolicy(StrictPolicyModel):
    result_limit: int = Field(ge=1, le=100)
    min_pub_pick: int = Field(ge=0)
    evidence: HeroEvidencePolicy
    normalization: HeroNormalizationPolicy
    score_weights: HeroScoreWeights
    tiers: HeroTierPolicy


class PatchReportPolicy(StrictPolicyModel):
    default_patch: str = Field(min_length=1)
    result_limit: int = Field(ge=1, le=100)
    neutral_score: float = Field(ge=0, le=1)
    change_delta: float = Field(gt=0, le=1)


class CriticPolicy(StrictPolicyModel):
    require_evidence: bool
    reject_unsupported_signals: bool
    min_evidence_items: int = Field(ge=1)


class LLMCallPolicy(StrictPolicyModel):
    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(gt=0)


class LLMPolicy(StrictPolicyModel):
    orchestrator: LLMCallPolicy
    hero_analyzer: LLMCallPolicy


class AppPolicy(StrictPolicyModel):
    version: Literal[1]
    opendota: OpenDotaPolicy
    team_report: TeamReportPolicy
    hero_report: HeroReportPolicy
    patch_report: PatchReportPolicy
    critic: CriticPolicy
    llm: LLMPolicy


class Settings(BaseSettings):
    app_name: str = "MetaMind API"
    environment: str = "local"
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000"]
    policy_path: str | None = None
    opendota_base_url: str = "https://api.opendota.com/api"
    opendota_api_key: str | None = None
    stratz_graphql_url: str = "https://api.stratz.com/graphql"
    stratz_token: str | None = None
    openai_api_key: str | None = None
    database_url: str = "postgresql://metamind:metamind@localhost:5432/metamind"
    redis_url: str = "redis://localhost:6379/0"
    live_data_enabled: bool = False

    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_enabled: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="METAMIND_",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                import json

                return json.loads(stripped)
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return ["http://localhost:3000"]


def load_policy(path: Path) -> AppPolicy:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Policy root must be a mapping: {path}")
    return AppPolicy.model_validate(raw)


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_policy() -> AppPolicy:
    configured_path = get_settings().policy_path
    path = Path(configured_path).expanduser() if configured_path else DEFAULT_POLICY_PATH
    return load_policy(path.resolve())


def default_patch() -> str:
    return get_policy().patch_report.default_patch


def default_time_range() -> str:
    days = get_policy().team_report.default_time_range_days
    return f"last_{days}_days"
