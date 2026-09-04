from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "policy.yaml"
DEFAULT_ENV_PATH = Path(__file__).resolve().parents[4] / ".env"


class StrictPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuntimePolicy(StrictPolicyModel):
    max_replans: int = Field(default=1, ge=1)
    max_tool_calls_total: int = Field(default=16, ge=1)
    max_controller_calls: int = Field(default=2, ge=1)
    max_answer_calls: int = Field(default=2, ge=1)
    max_elapsed_seconds: int = Field(default=60, ge=1)

    @field_validator("max_replans")
    @classmethod
    def require_one_replan(cls, value: int) -> int:
        if value != 1:
            raise ValueError("max_replans must equal 1")
        return value


class PlanningPolicy(StrictPolicyModel):
    runtime: RuntimePolicy = Field(default_factory=RuntimePolicy)


class ConversationPolicy(StrictPolicyModel):
    """Policy for recent dialogue cache and bounded session state."""

    recent_dialogue_max_chars: int = Field(default=24_000, ge=1000, le=100_000)
    history_lookup_max_turns: int = Field(default=8, ge=1, le=20)
    history_lookup_max_chars: int = Field(default=12_000, ge=1000, le=50_000)
    history_lookup_max_per_run: int = Field(default=1, ge=1, le=3)
    max_turns_per_session: int = Field(default=50, ge=1, le=500)
    max_sessions: int = Field(default=1000, ge=1, le=100_000)
    answer_summary_max_chars: int = Field(default=300, ge=50, le=2000)
    turn_query_max_chars: int = Field(default=200, ge=20, le=1000)
    request_record_ttl_seconds: int = Field(default=3600, ge=1, le=86_400)
    max_request_records_per_session: int = Field(default=200, ge=1, le=10_000)
    session_ttl_seconds: int = Field(default=86_400, ge=1, le=2_592_000)
    lock_lease_seconds: int = Field(default=90, ge=1, le=600)
    lock_acquire_timeout_seconds: int = Field(default=60, ge=1, le=600)


class LLMCallPolicy(StrictPolicyModel):
    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(gt=0)


class OrchestratorLLMCallPolicy(LLMCallPolicy):
    planner_max_retries: int = Field(default=2, ge=0, le=5)


class LLMPolicy(StrictPolicyModel):
    orchestrator: OrchestratorLLMCallPolicy


class CriticPolicy(StrictPolicyModel):
    require_evidence: bool = True
    reject_unsupported_signals: bool = True
    min_evidence_items: int = Field(default=1, ge=1)
    mock_allowed: bool = False
    min_confidence: float = Field(default=0.5, ge=0, le=1)
    hard_min_confidence: float = Field(default=0.35, ge=0, le=1)

    @model_validator(mode="after")
    def validate_confidence_thresholds(self) -> "CriticPolicy":
        if self.hard_min_confidence > self.min_confidence:
            raise ValueError("hard_min_confidence cannot exceed min_confidence")
        return self


class AppPolicy(StrictPolicyModel):
    version: Literal[1] = 1
    critic: CriticPolicy = Field(default_factory=CriticPolicy)
    llm: LLMPolicy
    planning: PlanningPolicy = Field(default_factory=PlanningPolicy)
    conversation: ConversationPolicy = Field(default_factory=ConversationPolicy)

    @model_validator(mode="after")
    def validate_history_lookup_budget(self) -> "AppPolicy":
        required_controller_calls = self.conversation.history_lookup_max_per_run + 1
        if self.planning.runtime.max_controller_calls < required_controller_calls:
            raise ValueError(
                "planning.runtime.max_controller_calls must be at least "
                "conversation.history_lookup_max_per_run + 1"
            )
        return self


class Settings(BaseSettings):
    app_name: str = "DotaMind API"
    environment: str = "local"
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000"]
    policy_path: str | None = None
    openai_api_key: str | None = None
    database_url: str = "postgresql://dotamind:dotamind@localhost:5432/dotamind"
    session_store_backend: Literal["memory", "redis"] = "memory"
    redis_url: str | None = None
    live_data_enabled: bool = False
    max_concurrent_chat_runs: int = Field(default=2, ge=1)
    run_heartbeat_seconds: float = Field(default=5.0, gt=0)
    run_stale_seconds: int = Field(default=60, gt=0)
    run_sweeper_interval_seconds: float = Field(default=15.0, gt=0)
    llm_provider: str = "deepseek"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_enabled: bool = True
    test_observer_enabled: bool = False

    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_PATH,
        env_prefix="DOTAMIND_",
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

    @model_validator(mode="after")
    def validate_session_store_backend(self) -> "Settings":
        if self.session_store_backend == "redis" and not self.redis_url:
            raise ValueError("DOTAMIND_REDIS_URL is required for redis session storage")
        return self


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
