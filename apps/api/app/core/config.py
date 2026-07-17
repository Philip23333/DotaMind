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


class StratzPolicy(StrictPolicyModel):
    # STRATZ `weeks_back` resolution. A STRATZ week is 604800s-aligned; the
    # in-progress current week is always skipped (it is partial). Default 1 =
    # latest completed week; max is a guardrail since N weeks = N STRATZ calls.
    weeks_back_default: int = Field(default=1, ge=1)
    weeks_back_max: int = Field(default=8, ge=1, le=52)


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


class HeroReportPolicy(StrictPolicyModel):
    result_limit: int = Field(ge=1, le=100)
    min_pub_pick: int = Field(ge=0)
    evidence: HeroEvidencePolicy
    normalization: HeroNormalizationPolicy


class PatchReportPolicy(StrictPolicyModel):
    default_patch: str = Field(min_length=1)
    result_limit: int = Field(ge=1, le=100)
    neutral_score: float = Field(ge=0, le=1)
    change_delta: float = Field(gt=0, le=1)


class CriticPolicy(StrictPolicyModel):
    require_evidence: bool
    reject_unsupported_signals: bool
    min_evidence_items: int = Field(ge=1)
    mock_allowed: bool
    min_confidence: float = Field(ge=0, le=1)
    hard_min_confidence: float = Field(ge=0, le=1)
    team_report: "CriticTeamReportPolicy"

    @model_validator(mode="after")
    def validate_confidence_thresholds(self) -> "CriticPolicy":
        if self.hard_min_confidence > self.min_confidence:
            raise ValueError("hard_min_confidence cannot exceed min_confidence")
        return self


class CriticTeamReportPolicy(StrictPolicyModel):
    max_latest_match_age_days: int = Field(ge=0)
    hard_max_latest_match_age_days: int = Field(ge=0)
    min_matches_in_window: int = Field(ge=0)
    min_match_details_analyzed: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_age_thresholds(self) -> "CriticTeamReportPolicy":
        if self.max_latest_match_age_days > self.hard_max_latest_match_age_days:
            raise ValueError(
                "max_latest_match_age_days cannot exceed hard_max_latest_match_age_days"
            )
        return self


class LLMCallPolicy(StrictPolicyModel):
    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(gt=0)


class OrchestratorLLMCallPolicy(LLMCallPolicy):
    # Planner-only knob. 0 disables retry; total attempts = 1 + planner_max_retries.
    planner_max_retries: int = Field(default=2, ge=0, le=5)


class LLMPolicy(StrictPolicyModel):
    orchestrator: OrchestratorLLMCallPolicy


class SamplePolicyToolEntry(StrictPolicyModel):
    """Sample-size threshold policy for one tool.

    `arg` names the input_model field the policy fills (e.g.
    min_sample_size vs min_position_match_count) so apply_sample_policy stays
    generic. The three tiers map to the planner's sample-selection modes:
    relaxed (cold/小样本也行) <= default (normal) <= strict (稳健/大样本). Tool
    input_model Field defaults are kept in sync with `default` — see
    test_stratz_tool_defaults_match_sample_policy.
    """

    arg: str = Field(min_length=1)
    default: int = Field(ge=0)
    relaxed: int = Field(ge=0)
    strict: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_ordering(self) -> "SamplePolicyToolEntry":
        if not (self.relaxed <= self.default <= self.strict):
            raise ValueError(
                f"sample_policy tiers must satisfy relaxed<=default<=strict "
                f"got relaxed={self.relaxed} default={self.default} "
                f"strict={self.strict}"
            )
        return self


class SamplePolicyConfig(StrictPolicyModel):
    # Keyed by registered tool name. Generic (not STRATZ-bound): any tool whose
    # input_model has a sample-size arg can enroll. render_sample_policy verifies
    # each key is a registered tool and `arg` is a real input field.
    tools: dict[str, SamplePolicyToolEntry] = Field(default_factory=dict)


class PlanningPolicy(StrictPolicyModel):
    sample_policy: SamplePolicyConfig


class ConversationPolicy(StrictPolicyModel):
    """Policy for multi-turn session memory (Phase 1: in-memory store).

    All fields have defaults so an existing policy.yaml without a
    ``conversation`` section still loads without validation errors.
    """

    # Number of prior turns injected into the planner prompt.
    history_window: int = Field(default=5, ge=1, le=20)
    # Maximum turns retained per session (excess oldest turns are evicted).
    max_turns_per_session: int = Field(default=50, ge=1, le=500)
    # Maximum number of live sessions (LRU eviction above this threshold).
    max_sessions: int = Field(default=1000, ge=1, le=100_000)
    # Hard cap on answer.summary stored per turn.
    answer_summary_max_chars: int = Field(default=300, ge=50, le=2000)
    # Hard cap on the query string stored per turn.
    turn_query_max_chars: int = Field(default=200, ge=20, le=1000)
    # Hard budget for the entire rendered history block injected into the prompt.
    history_max_chars: int = Field(default=2000, ge=200, le=10_000)

    @model_validator(mode="after")
    def validate_window_vs_max(self) -> "ConversationPolicy":
        if self.history_window > self.max_turns_per_session:
            raise ValueError(
                f"history_window ({self.history_window}) cannot exceed "
                f"max_turns_per_session ({self.max_turns_per_session})"
            )
        return self


class AppPolicy(StrictPolicyModel):
    version: Literal[1]
    opendota: OpenDotaPolicy
    stratz: StratzPolicy
    team_report: TeamReportPolicy
    hero_report: HeroReportPolicy
    patch_report: PatchReportPolicy
    critic: CriticPolicy
    llm: LLMPolicy
    planning: PlanningPolicy
    # Optional: existing policy.yaml files without this section use defaults.
    conversation: ConversationPolicy = Field(default_factory=ConversationPolicy)


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

    llm_provider: str = "deepseek"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_enabled: bool = True

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
