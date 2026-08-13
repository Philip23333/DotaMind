from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.application.redis_session_store import RedisSessionStore
from app.application.session_store import InMemorySessionStore
from app.application.session_store_factory import build_session_store
from app.core.config import DEFAULT_POLICY_PATH, Settings, load_policy


def _policy_data() -> dict:
    data = yaml.safe_load(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _write_policy(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_settings_use_dotamind_environment_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOTAMIND_APP_NAME", "DotaMind Test API")

    settings = Settings(_env_file=None)

    assert settings.app_name == "DotaMind Test API"
    assert settings.database_url == "postgresql://dotamind:dotamind@localhost:5432/dotamind"
    assert settings.max_concurrent_chat_runs == 2
    assert settings.run_heartbeat_seconds == 5.0
    assert settings.run_stale_seconds == 60


def test_redis_backend_requires_url() -> None:
    with pytest.raises(ValidationError, match="REDIS_URL"):
        Settings(_env_file=None, session_store_backend="redis", redis_url=None)


def test_session_store_factory_selects_only_configured_backend() -> None:
    policy = load_policy(DEFAULT_POLICY_PATH)
    memory = build_session_store(Settings(_env_file=None), policy)
    redis = build_session_store(
        Settings(
            _env_file=None,
            session_store_backend="redis",
            redis_url="redis://localhost:6379/0",
        ),
        policy,
    )

    assert isinstance(memory, InMemorySessionStore)
    assert isinstance(redis, RedisSessionStore)


def test_policy_yaml_loads_all_report_sections() -> None:
    policy = load_policy(DEFAULT_POLICY_PATH)

    assert policy.opendota.request_timeout_seconds == 20
    assert policy.team_report.match_details.default_sample_size == 50
    assert policy.hero_report.result_limit == 10
    assert policy.patch_report.default_patch == "latest"
    assert policy.critic.require_evidence is True
    assert policy.critic.mock_allowed is False
    assert policy.critic.min_confidence == 0.5
    assert policy.critic.hard_min_confidence == 0.35
    assert policy.critic.team_report.max_latest_match_age_days == 30
    assert policy.critic.team_report.hard_max_latest_match_age_days == 90
    assert policy.critic.team_report.min_matches_in_window == 5
    assert policy.critic.team_report.min_match_details_analyzed == 5
    assert policy.llm.orchestrator.max_tokens == 4000
    assert policy.planning.sample_policy.tools["stratz.hero_matchup_ranking"].default == 2000
    assert (
        policy.planning.sample_policy.tools["stratz.filter_ranked_heroes_by_position"].arg
        == "min_position_match_count"
    )
    assert policy.planning.sample_policy.tools["stratz.lane_meta_global"].strict == 3000


def test_policy_rejects_unknown_fields(tmp_path: Path) -> None:
    data = _policy_data()
    data["team_report"]["unknown_setting"] = True

    with pytest.raises(ValidationError):
        load_policy(_write_policy(tmp_path / "policy.yaml", data))


def test_policy_rejects_invalid_sample_size_relationship(tmp_path: Path) -> None:
    data = _policy_data()
    data["team_report"]["match_details"]["default_sample_size"] = 80
    data["team_report"]["match_details"]["max_sample_size"] = 50

    with pytest.raises(ValidationError, match="default_sample_size"):
        load_policy(_write_policy(tmp_path / "policy.yaml", data))


def test_policy_rejects_invalid_critic_confidence_thresholds(tmp_path: Path) -> None:
    data = deepcopy(_policy_data())
    data["critic"]["hard_min_confidence"] = 0.6
    data["critic"]["min_confidence"] = 0.5

    with pytest.raises(ValidationError, match="hard_min_confidence"):
        load_policy(_write_policy(tmp_path / "policy.yaml", data))


def test_policy_rejects_invalid_critic_team_age_thresholds(tmp_path: Path) -> None:
    data = deepcopy(_policy_data())
    data["critic"]["team_report"]["max_latest_match_age_days"] = 120
    data["critic"]["team_report"]["hard_max_latest_match_age_days"] = 90

    with pytest.raises(ValidationError, match="max_latest_match_age_days"):
        load_policy(_write_policy(tmp_path / "policy.yaml", data))


def test_policy_rejects_sample_policy_tiers_out_of_order(tmp_path: Path) -> None:
    data = deepcopy(_policy_data())
    # relaxed (500) > default (200) would already be fine, but break the chain:
    # set default above strict to violate relaxed<=default<=strict.
    data["planning"]["sample_policy"]["tools"]["stratz.hero_matchup_ranking"] = {
        "arg": "min_sample_size",
        "default": 9000,
        "relaxed": 500,
        "strict": 5000,
    }

    with pytest.raises(ValidationError, match="relaxed<=default<=strict"):
        load_policy(_write_policy(tmp_path / "policy.yaml", data))


def test_policy_defaults_come_from_policy_yaml() -> None:
    policy = load_policy(DEFAULT_POLICY_PATH)

    assert policy.patch_report.default_patch == "latest"
    assert policy.team_report.default_time_range_days == 30


def test_runtime_policy_loads_strict_v32_1_defaults() -> None:
    runtime = load_policy(DEFAULT_POLICY_PATH).planning.runtime

    assert runtime.model_dump() == {
        "max_replans": 1,
        "max_tool_calls_total": 8,
        "max_controller_calls": 2,
        "max_answer_calls": 2,
        "max_elapsed_seconds": 60,
    }


def test_runtime_policy_rejects_more_than_one_replan(tmp_path: Path) -> None:
    data = deepcopy(_policy_data())
    data["planning"]["runtime"]["max_replans"] = 2

    with pytest.raises(ValidationError, match="max_replans must equal 1"):
        load_policy(_write_policy(tmp_path / "policy.yaml", data))


# ---------------------------------------------------------------------------
# ConversationPolicy
# ---------------------------------------------------------------------------


def test_conversation_policy_loads_from_yaml() -> None:
    policy = load_policy(DEFAULT_POLICY_PATH)

    assert policy.conversation.recent_dialogue_max_chars == 24000
    assert policy.conversation.history_lookup_max_turns == 8
    assert policy.conversation.history_lookup_max_chars == 12000
    assert policy.conversation.history_lookup_max_per_run == 1
    assert policy.conversation.max_turns_per_session == 50
    assert policy.conversation.max_sessions == 1000
    assert policy.conversation.answer_summary_max_chars == 300
    assert policy.conversation.turn_query_max_chars == 200


def test_conversation_policy_has_defaults_without_yaml_section(tmp_path: Path) -> None:
    """A policy.yaml that omits the conversation section must still load."""
    data = _policy_data()
    data.pop("conversation", None)  # ensure section is absent
    policy = load_policy(_write_policy(tmp_path / "policy.yaml", data))

    # Defaults from ConversationPolicy field declarations
    assert policy.conversation.recent_dialogue_max_chars == 24000
    assert policy.conversation.max_turns_per_session == 50


def test_conversation_policy_explicit_override(tmp_path: Path) -> None:
    data = deepcopy(_policy_data())
    data["conversation"] = {
        "recent_dialogue_max_chars": 10000,
        "history_lookup_max_turns": 4,
        "history_lookup_max_chars": 5000,
        "history_lookup_max_per_run": 1,
        "max_turns_per_session": 20,
        "max_sessions": 500,
        "answer_summary_max_chars": 150,
        "turn_query_max_chars": 100,
    }
    policy = load_policy(_write_policy(tmp_path / "policy.yaml", data))

    assert policy.conversation.recent_dialogue_max_chars == 10000
    assert policy.conversation.history_lookup_max_turns == 4


def test_conversation_policy_rejects_invalid_lookup_budget(tmp_path: Path) -> None:
    data = deepcopy(_policy_data())
    data["conversation"] = {
        "recent_dialogue_max_chars": 30,
        "history_lookup_max_turns": 8,
        "history_lookup_max_chars": 12000,
        "history_lookup_max_per_run": 1,
        "max_turns_per_session": 10,
        "max_sessions": 1000,
        "answer_summary_max_chars": 300,
        "turn_query_max_chars": 200,
    }
    with pytest.raises(ValidationError, match="recent_dialogue_max_chars"):
        load_policy(_write_policy(tmp_path / "policy.yaml", data))


def test_policy_rejects_lookup_budget_without_final_controller_call(tmp_path: Path) -> None:
    data = deepcopy(_policy_data())
    data["conversation"]["history_lookup_max_per_run"] = 2

    with pytest.raises(ValidationError, match="max_controller_calls"):
        load_policy(_write_policy(tmp_path / "policy.yaml", data))
