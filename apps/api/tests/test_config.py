from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.api.v1.schemas import MetaReportRequest, TeamReportRequest
from app.core.config import DEFAULT_POLICY_PATH, load_policy


def _policy_data() -> dict:
    data = yaml.safe_load(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _write_policy(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


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
    assert policy.llm.orchestrator.max_tokens == 500
    assert policy.llm.hero_analyzer.max_tokens == 1000


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


def test_policy_rejects_hero_weights_that_do_not_sum_to_one(tmp_path: Path) -> None:
    data = deepcopy(_policy_data())
    data["hero_report"]["score_weights"]["trend"] = 0.5

    with pytest.raises(ValidationError, match="weights must sum to 1.0"):
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


def test_api_defaults_come_from_policy_yaml() -> None:
    assert MetaReportRequest().patch == "latest"
    assert TeamReportRequest().time_range == "last_30_days"
