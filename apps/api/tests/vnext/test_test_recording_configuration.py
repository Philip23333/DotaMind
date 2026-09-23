from __future__ import annotations

from pathlib import Path

import pytest

import app.vnext.composition as composition
from app.vnext.composition import VNextSettings


def _isolate_settings_file(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(composition, "_VNEXT_ENV_PATH", path)


def test_test_recording_defaults_to_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_settings_file(monkeypatch, tmp_path / "missing.env")
    monkeypatch.delenv("VNEXT_TEST_RECORDING_ENABLED", raising=False)

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

    assert VNextSettings.from_env().test_recording_enabled is expected


def test_environment_overrides_vnext_dotenv_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_path = tmp_path / "vnext.env"
    env_path.write_text("VNEXT_TEST_RECORDING_ENABLED=false\n", encoding="utf-8")
    _isolate_settings_file(monkeypatch, env_path)
    monkeypatch.setenv("VNEXT_TEST_RECORDING_ENABLED", "true")

    assert VNextSettings.from_env().test_recording_enabled is True


@pytest.mark.parametrize("value", ["", "yes", "enabled", "2"])
def test_invalid_test_recording_value_is_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    value: str,
) -> None:
    _isolate_settings_file(monkeypatch, tmp_path / "missing.env")
    monkeypatch.setenv("VNEXT_TEST_RECORDING_ENABLED", value)

    with pytest.raises(ValueError, match="VNEXT_TEST_RECORDING_ENABLED"):
        VNextSettings.from_env()


def test_enabled_test_recording_requires_redis_at_startup() -> None:
    from app.main import _require_trace_recording_redis

    with pytest.raises(RuntimeError, match="requires DOTAMIND_REDIS_URL"):
        _require_trace_recording_redis(VNextSettings(test_recording_enabled=True), None)

    _require_trace_recording_redis(VNextSettings(test_recording_enabled=False), None)
