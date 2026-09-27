from __future__ import annotations

from pathlib import Path

import pytest

from app.vnext.composition import VNextSettings


def test_tavily_settings_follow_environment_over_root_env_and_hide_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "isolated.env"
    env_file.write_text(
        "\n".join(
            [
                "DOTAMIND_TAVILY_MCP_ENABLED=false",
                "DOTAMIND_TAVILY_MCP_URL=https://from-file.example/mcp",
                "DOTAMIND_TAVILY_API_KEY=file-key-marker",
                "DOTAMIND_TAVILY_MCP_TIMEOUT_SECONDS=12",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.vnext.composition._VNEXT_ENV_PATH", env_file)
    monkeypatch.setenv("DOTAMIND_TAVILY_MCP_ENABLED", "true")
    monkeypatch.setenv("DOTAMIND_TAVILY_API_KEY", "environment-key-marker")

    settings = VNextSettings.from_env()

    assert settings.tavily_mcp_enabled is True
    assert settings.tavily_mcp_url == "https://from-file.example/mcp"
    assert settings.tavily_api_key == "environment-key-marker"
    assert settings.tavily_mcp_timeout_seconds == 12
    assert "environment-key-marker" not in repr(settings)
    assert "environment-key-marker" not in str(settings)


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Infinity", "not-a-number"])
def test_tavily_timeout_requires_a_finite_positive_number(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    value: str,
) -> None:
    monkeypatch.setattr(
        "app.vnext.composition._VNEXT_ENV_PATH",
        tmp_path / "missing.env",
    )
    monkeypatch.setenv("DOTAMIND_TAVILY_MCP_TIMEOUT_SECONDS", value)
    with pytest.raises(ValueError, match="DOTAMIND_TAVILY_MCP_TIMEOUT_SECONDS"):
        VNextSettings.from_env()


def test_direct_tavily_settings_also_reject_non_finite_timeout() -> None:
    with pytest.raises(ValueError, match="DOTAMIND_TAVILY_MCP_TIMEOUT_SECONDS"):
        VNextSettings(tavily_mcp_timeout_seconds=float("inf"))
