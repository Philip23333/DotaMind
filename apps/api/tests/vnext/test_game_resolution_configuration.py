from __future__ import annotations

import pytest

from app.vnext import composition
from app.vnext.composition import (
    VNextServices,
    VNextSettings,
    build_vnext_registry,
    build_vnext_services,
)

_RESOLUTION_ENV = (
    "DOTAMIND_GAME_RESOLUTION_ENABLED",
    "DOTAMIND_GAME_RESOLUTION_START_TOLERANCE_SECONDS",
    "DOTAMIND_GAME_RESOLUTION_DURATION_TOLERANCE_SECONDS",
    "DOTAMIND_GAME_RESOLUTION_MAX_LEAGUES",
    "DOTAMIND_GAME_RESOLUTION_MAX_CANDIDATE_DETAILS",
    "DOTAMIND_GAME_RESOLUTION_MAX_REQUESTS",
    "DOTAMIND_OPENDOTA_ENABLED",
    "DOTAMIND_PANDASCORE_TOKEN",
)


def _isolate(monkeypatch: pytest.MonkeyPatch, env_path) -> None:
    monkeypatch.setattr(composition, "_VNEXT_ENV_PATH", env_path)
    for name in _RESOLUTION_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS", "4096")


def test_game_resolution_defaults_are_disabled_and_have_finite_policy(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate(monkeypatch, tmp_path / "missing.env")

    settings = VNextSettings.from_env()

    assert settings.game_resolution_enabled is False
    policy = settings.game_resolution_read_policy
    assert (
        policy.start_time_tolerance_seconds,
        policy.duration_tolerance_seconds,
        policy.max_leagues,
        policy.max_candidate_details,
        policy.max_requests,
    ) == (1800, 5, 20, 8, 30)
    services = build_vnext_services(settings)
    assert services.game_resolution is None


def test_dotenv_values_and_process_environment_override(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "DOTAMIND_GAME_RESOLUTION_ENABLED=true\n"
        "DOTAMIND_GAME_RESOLUTION_START_TOLERANCE_SECONDS=900\n"
        "DOTAMIND_GAME_RESOLUTION_DURATION_TOLERANCE_SECONDS=4\n"
        "DOTAMIND_GAME_RESOLUTION_MAX_LEAGUES=5\n"
        "DOTAMIND_GAME_RESOLUTION_MAX_CANDIDATE_DETAILS=7\n"
        "DOTAMIND_GAME_RESOLUTION_MAX_REQUESTS=12\n",
        encoding="utf-8",
    )
    _isolate(monkeypatch, env_path)
    monkeypatch.setenv("DOTAMIND_GAME_RESOLUTION_START_TOLERANCE_SECONDS", "0")
    monkeypatch.setenv("DOTAMIND_GAME_RESOLUTION_MAX_REQUESTS", "3")

    settings = VNextSettings.from_env()

    assert settings.game_resolution_enabled is True
    assert settings.game_resolution_read_policy.start_time_tolerance_seconds == 0
    assert settings.game_resolution_read_policy.duration_tolerance_seconds == 4
    assert settings.game_resolution_read_policy.max_leagues == 5
    assert settings.game_resolution_read_policy.max_candidate_details == 7
    assert settings.game_resolution_read_policy.max_requests == 3


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DOTAMIND_GAME_RESOLUTION_ENABLED", "yes"),
        ("DOTAMIND_GAME_RESOLUTION_START_TOLERANCE_SECONDS", ""),
        ("DOTAMIND_GAME_RESOLUTION_START_TOLERANCE_SECONDS", "-1"),
        ("DOTAMIND_GAME_RESOLUTION_DURATION_TOLERANCE_SECONDS", "1.5"),
        ("DOTAMIND_GAME_RESOLUTION_MAX_LEAGUES", "0"),
        ("DOTAMIND_GAME_RESOLUTION_MAX_CANDIDATE_DETAILS", "-1"),
        ("DOTAMIND_GAME_RESOLUTION_MAX_REQUESTS", "NaN"),
    ],
)
def test_invalid_game_resolution_environment_values_name_the_setting(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    _isolate(monkeypatch, tmp_path / "missing.env")
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        VNextSettings.from_env()


@pytest.mark.parametrize(
    ("token", "opendota_enabled", "message"),
    [
        ("  \t", True, "DOTAMIND_PANDASCORE_TOKEN"),
        ("configured", False, "DOTAMIND_OPENDOTA_ENABLED"),
    ],
)
def test_enabled_composition_requires_both_provider_configurations(
    token: str,
    opendota_enabled: bool,
    message: str,
) -> None:
    settings = VNextSettings(
        game_resolution_enabled=True,
        pandascore_token=token,
        opendota_enabled=opendota_enabled,
    )

    with pytest.raises(ValueError, match=message):
        build_vnext_services(settings)


def test_direct_settings_require_strict_boolean_enable_flag() -> None:
    with pytest.raises(ValueError, match="DOTAMIND_GAME_RESOLUTION_ENABLED"):
        VNextSettings(game_resolution_enabled=1)  # type: ignore[arg-type]


def test_enabled_registry_rejects_missing_required_services() -> None:
    settings = VNextSettings(
        game_resolution_enabled=True,
        pandascore_token="configured-token",
        opendota_enabled=True,
    )

    with pytest.raises(ValueError, match="esports.match.search.*game_resolution.*game.detail"):
        build_vnext_registry(VNextServices(), settings=settings)
