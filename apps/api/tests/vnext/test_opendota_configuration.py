from __future__ import annotations

import pytest

from app.vnext import composition
from app.vnext.composition import VNextSettings

_ENV_NAMES = (
    "DOTAMIND_OPENDOTA_ENABLED",
    "DOTAMIND_OPENDOTA_BASE_URL",
    "DOTAMIND_OPENDOTA_API_KEY",
    "DOTAMIND_OPENDOTA_TIMEOUT_SECONDS",
)


def _isolate(monkeypatch: pytest.MonkeyPatch, env_file) -> None:
    monkeypatch.setattr(composition, "_VNEXT_ENV_PATH", env_file)
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS", "4096")


def test_opendota_configuration_defaults_and_dotenv_values(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    _isolate(monkeypatch, env_file)

    defaults = VNextSettings.from_env()
    assert defaults.opendota_enabled is False
    assert defaults.opendota_base_url == "https://api.opendota.com/api"
    assert defaults.opendota_api_key == ""
    assert defaults.opendota_timeout_seconds == 20

    env_file.write_text(
        "DOTAMIND_OPENDOTA_ENABLED=true\n"
        "DOTAMIND_OPENDOTA_BASE_URL=https://fixture.invalid/api\n"
        "DOTAMIND_OPENDOTA_API_KEY=fixture-secret\n"
        "DOTAMIND_OPENDOTA_TIMEOUT_SECONDS=8.5\n",
        encoding="utf-8",
    )
    configured = VNextSettings.from_env()
    assert configured.opendota_enabled is True
    assert configured.opendota_base_url == "https://fixture.invalid/api"
    assert configured.opendota_api_key == "fixture-secret"
    assert configured.opendota_timeout_seconds == 8.5
    assert "fixture-secret" not in repr(configured)


def test_process_environment_overrides_dotenv(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DOTAMIND_OPENDOTA_ENABLED=false\n"
        "DOTAMIND_OPENDOTA_BASE_URL=https://dotenv.invalid/api\n"
        "DOTAMIND_OPENDOTA_API_KEY=dotenv-secret\n"
        "DOTAMIND_OPENDOTA_TIMEOUT_SECONDS=7\n",
        encoding="utf-8",
    )
    _isolate(monkeypatch, env_file)
    monkeypatch.setenv("DOTAMIND_OPENDOTA_ENABLED", "1")
    monkeypatch.setenv("DOTAMIND_OPENDOTA_BASE_URL", "https://process.invalid/api")
    monkeypatch.setenv("DOTAMIND_OPENDOTA_API_KEY", "process-secret")
    monkeypatch.setenv("DOTAMIND_OPENDOTA_TIMEOUT_SECONDS", "9")

    configured = VNextSettings.from_env()

    assert configured.opendota_enabled is True
    assert configured.opendota_base_url == "https://process.invalid/api"
    assert configured.opendota_api_key == "process-secret"
    assert configured.opendota_timeout_seconds == 9
    assert "process-secret" not in repr(configured)


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "bad"])
def test_opendota_timeout_from_environment_must_be_finite_positive(
    tmp_path,
    monkeypatch,
    value: str,
) -> None:
    _isolate(monkeypatch, tmp_path / "missing.env")
    monkeypatch.setenv("DOTAMIND_OPENDOTA_TIMEOUT_SECONDS", value)

    with pytest.raises(ValueError, match="DOTAMIND_OPENDOTA_TIMEOUT_SECONDS"):
        VNextSettings.from_env()


@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf")])
def test_direct_opendota_timeout_must_be_finite_positive(value: float) -> None:
    with pytest.raises(ValueError, match="finite positive"):
        VNextSettings(opendota_timeout_seconds=value)


@pytest.mark.parametrize("value", ["maybe", "yes", "enabled"])
def test_opendota_enable_flag_rejects_ambiguous_values(tmp_path, monkeypatch, value: str) -> None:
    _isolate(monkeypatch, tmp_path / "missing.env")
    monkeypatch.setenv("DOTAMIND_OPENDOTA_ENABLED", value)

    with pytest.raises(ValueError, match="DOTAMIND_OPENDOTA_ENABLED"):
        VNextSettings.from_env()
