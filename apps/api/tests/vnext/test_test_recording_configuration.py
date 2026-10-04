from __future__ import annotations

from pathlib import Path

import pytest

import app.vnext.composition as composition
from app.vnext.composition import VNextSettings


def _isolate_settings_file(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(composition, "_VNEXT_ENV_PATH", path)


def _clear_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DOTAMIND_LLM_API_KEY",
        "DOTAMIND_LLM_BASE_URL",
        "DOTAMIND_LLM_MODEL",
        "DOTAMIND_CONTEXT_WINDOW_TOKENS",
        "DOTAMIND_MODEL_MAX_OUTPUT_TOKENS",
        "DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS",
        "DOTAMIND_COMPACTION_RESERVE_TOKENS",
        "DOTAMIND_CONTEXT_COMPACTION_TEST_TRIGGER_PERCENT",
        "VNEXT_TEST_RECORDING_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)


def test_default_settings_path_is_repository_root_env() -> None:
    assert composition._VNEXT_ENV_PATH == (Path(composition.__file__).resolve().parents[4] / ".env")


def test_model_and_context_settings_read_from_temporary_env_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "DOTAMIND_LLM_API_KEY=unit-test-key\n"
        "DOTAMIND_LLM_BASE_URL=https://model.example/v1\n"
        "DOTAMIND_LLM_MODEL=unit-test-model\n"
        "DOTAMIND_CONTEXT_WINDOW_TOKENS=12000\n"
        "DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS=300\n"
        "DOTAMIND_CONTEXT_SAFETY_MARGIN_TOKENS=200\n"
        "DOTAMIND_COMPACTION_RESERVE_TOKENS=10000\n",
        encoding="utf-8",
    )
    _isolate_settings_file(monkeypatch, env_path)
    _clear_settings_environment(monkeypatch)

    settings = VNextSettings.from_env()

    assert settings.llm_api_key == "unit-test-key"
    assert settings.llm_base_url == "https://model.example/v1"
    assert settings.llm_model == "unit-test-model"
    assert settings.agent_limits.context_window_tokens == 12000
    assert settings.agent_limits.application_max_output_tokens == 300
    assert settings.agent_limits.context_safety_margin_tokens == 200


def test_missing_root_env_still_uses_model_and_context_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_settings_file(monkeypatch, tmp_path / "missing.env")
    _clear_settings_environment(monkeypatch)
    monkeypatch.setenv("DOTAMIND_LLM_MODEL", "environment-model")
    monkeypatch.setenv("DOTAMIND_CONTEXT_WINDOW_TOKENS", "20000")
    monkeypatch.setenv("DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS", "4096")

    settings = VNextSettings.from_env()

    assert settings.llm_model == "environment-model"
    assert settings.agent_limits.context_window_tokens == 20000


def test_test_recording_defaults_to_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_settings_file(monkeypatch, tmp_path / "missing.env")
    monkeypatch.delenv("VNEXT_TEST_RECORDING_ENABLED", raising=False)
    monkeypatch.setenv("DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS", "4096")

    assert VNextSettings().test_recording_enabled is False
    assert VNextSettings.from_env().test_recording_enabled is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        (" TRUE ", True),
        ("1", True),
        ("false", False),
        ("False", False),
        (" 0 ", False),
    ],
)
def test_test_recording_accepts_only_documented_boolean_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    value: str,
    expected: bool,
) -> None:
    _isolate_settings_file(monkeypatch, tmp_path / "missing.env")
    monkeypatch.setenv("VNEXT_TEST_RECORDING_ENABLED", value)
    monkeypatch.setenv("DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS", "4096")

    assert VNextSettings.from_env().test_recording_enabled is expected


def test_environment_overrides_vnext_dotenv_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_path = tmp_path / "root.env"
    env_path.write_text(
        "VNEXT_TEST_RECORDING_ENABLED=false\n"
        "DOTAMIND_LLM_MODEL=file-model\n"
        "DOTAMIND_CONTEXT_WINDOW_TOKENS=12000\n"
        "DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS=4096\n"
        "DOTAMIND_COMPACTION_RESERVE_TOKENS=10000\n",
        encoding="utf-8",
    )
    _isolate_settings_file(monkeypatch, env_path)
    _clear_settings_environment(monkeypatch)
    monkeypatch.setenv("VNEXT_TEST_RECORDING_ENABLED", "true")
    monkeypatch.setenv("DOTAMIND_LLM_MODEL", "environment-model")
    monkeypatch.setenv("DOTAMIND_CONTEXT_WINDOW_TOKENS", "15000")

    settings = VNextSettings.from_env()

    assert settings.test_recording_enabled is True
    assert settings.llm_model == "environment-model"
    assert settings.agent_limits.context_window_tokens == 15000


@pytest.mark.parametrize("value", ["", "yes", "enabled", "2"])
def test_invalid_test_recording_value_is_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    value: str,
) -> None:
    _isolate_settings_file(monkeypatch, tmp_path / "missing.env")
    monkeypatch.setenv("VNEXT_TEST_RECORDING_ENABLED", value)
    monkeypatch.setenv("DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS", "4096")

    with pytest.raises(ValueError, match="VNEXT_TEST_RECORDING_ENABLED"):
        VNextSettings.from_env()


def test_enabled_test_recording_requires_redis_at_startup() -> None:
    from app.main import _require_trace_recording_redis

    with pytest.raises(RuntimeError, match="requires DOTAMIND_REDIS_URL"):
        _require_trace_recording_redis(VNextSettings(test_recording_enabled=True), None)

    _require_trace_recording_redis(VNextSettings(test_recording_enabled=False), None)
