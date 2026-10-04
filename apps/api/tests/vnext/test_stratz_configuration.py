from __future__ import annotations

import pytest

from app.vnext import composition
from app.vnext.composition import VNextSettings

_STRATZ_ENV_NAMES = (
    "DOTAMIND_STRATZ_GRAPHQL_URL",
    "DOTAMIND_STRATZ_TOKEN",
    "DOTAMIND_STRATZ_TIMEOUT_SECONDS",
)


def _isolate_environment(monkeypatch: pytest.MonkeyPatch, env_file) -> None:
    monkeypatch.setattr(composition, "_VNEXT_ENV_PATH", env_file)
    for name in _STRATZ_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS", "4096")


def test_stratz_settings_default_and_root_dotenv_are_isolated(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    _isolate_environment(monkeypatch, env_file)

    defaults = VNextSettings.from_env()
    assert defaults.stratz_graphql_url == "https://api.stratz.com/graphql"
    assert defaults.stratz_token == ""
    assert defaults.stratz_timeout_seconds == 20

    env_file.write_text(
        "DOTAMIND_STRATZ_GRAPHQL_URL=https://dotenv.example/graphql\n"
        "DOTAMIND_STRATZ_TOKEN=dotenv-secret\n"
        "DOTAMIND_STRATZ_TIMEOUT_SECONDS=7.5\n",
        encoding="utf-8",
    )
    from_dotenv = VNextSettings.from_env()
    assert from_dotenv.stratz_graphql_url == "https://dotenv.example/graphql"
    assert from_dotenv.stratz_token == "dotenv-secret"
    assert from_dotenv.stratz_timeout_seconds == 7.5
    assert "dotenv-secret" not in repr(from_dotenv)


def test_stratz_process_environment_overrides_dotenv(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DOTAMIND_STRATZ_GRAPHQL_URL=https://dotenv.example/graphql\n"
        "DOTAMIND_STRATZ_TOKEN=dotenv-secret\n"
        "DOTAMIND_STRATZ_TIMEOUT_SECONDS=7.5\n",
        encoding="utf-8",
    )
    _isolate_environment(monkeypatch, env_file)
    monkeypatch.setenv("DOTAMIND_STRATZ_GRAPHQL_URL", "https://process.example/graphql")
    monkeypatch.setenv("DOTAMIND_STRATZ_TOKEN", "process-secret")
    monkeypatch.setenv("DOTAMIND_STRATZ_TIMEOUT_SECONDS", "9")

    settings = VNextSettings.from_env()

    assert settings.stratz_graphql_url == "https://process.example/graphql"
    assert settings.stratz_token == "process-secret"
    assert settings.stratz_timeout_seconds == 9
    assert "process-secret" not in repr(settings)


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "bad"])
def test_stratz_timeout_must_be_finite_and_positive(tmp_path, monkeypatch, value: str) -> None:
    _isolate_environment(monkeypatch, tmp_path / "missing.env")
    monkeypatch.setenv("DOTAMIND_STRATZ_TIMEOUT_SECONDS", value)

    with pytest.raises(ValueError, match="DOTAMIND_STRATZ_TIMEOUT_SECONDS"):
        VNextSettings.from_env()


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_direct_stratz_timeout_configuration_is_also_validated(value: float) -> None:
    with pytest.raises(ValueError, match="finite positive"):
        VNextSettings(stratz_timeout_seconds=value)
