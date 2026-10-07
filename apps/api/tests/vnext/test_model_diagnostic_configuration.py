from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

import app.vnext.composition as composition
from app.vnext.agent.limits import AgentLimits
from app.vnext.composition import VNextServices, VNextSettings
from app.vnext.llm.diagnostic_limits import (
    DEFAULT_MODEL_DIAGNOSTIC_LIMITS,
    ModelDiagnosticLimits,
)

_ENV_FIELDS = {
    "DOTAMIND_DIAGNOSTIC_MAX_TOOL_CALLS": "max_tool_calls",
    "DOTAMIND_DIAGNOSTIC_ARGUMENT_MAX_BYTES": "argument_max_bytes",
    "DOTAMIND_DIAGNOSTIC_TOTAL_ARGUMENT_MAX_BYTES": "total_argument_max_bytes",
    "DOTAMIND_DIAGNOSTIC_ARGUMENT_EDGE_BYTES": "argument_edge_bytes",
}


def _isolate_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(composition, "_VNEXT_ENV_PATH", tmp_path / "missing.env")
    for name in _ENV_FIELDS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS", "4096")


def test_model_diagnostic_limits_have_strict_immutable_defaults() -> None:
    limits = ModelDiagnosticLimits()

    assert limits == DEFAULT_MODEL_DIAGNOSTIC_LIMITS
    assert limits.model_dump() == {
        "max_tool_calls": 64,
        "argument_max_bytes": 65_536,
        "total_argument_max_bytes": 262_144,
        "argument_edge_bytes": 4_096,
    }
    with pytest.raises(ValidationError):
        limits.max_tool_calls = 10  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ModelDiagnosticLimits(unexpected=1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (field, value)
        for field in _ENV_FIELDS.values()
        for value in (True, False, 0, -1, 1.5, "12", None)
    ],
)
def test_model_diagnostic_limits_reject_non_positive_or_non_integer_values(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        ModelDiagnosticLimits(**{field: value})


@pytest.mark.parametrize(
    "values",
    [
        {"argument_max_bytes": 20, "total_argument_max_bytes": 19},
        {"argument_max_bytes": 8, "argument_edge_bytes": 5},
    ],
)
def test_model_diagnostic_limits_enforce_related_byte_budgets(
    values: dict[str, int],
) -> None:
    with pytest.raises(ValidationError):
        ModelDiagnosticLimits(**values)


def test_settings_load_diagnostic_limits_from_environment_with_process_precedence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_settings(monkeypatch, tmp_path)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "DOTAMIND_DIAGNOSTIC_MAX_TOOL_CALLS=8",
                "DOTAMIND_DIAGNOSTIC_ARGUMENT_MAX_BYTES=1024",
                "DOTAMIND_DIAGNOSTIC_TOTAL_ARGUMENT_MAX_BYTES=4096",
                "DOTAMIND_DIAGNOSTIC_ARGUMENT_EDGE_BYTES=128",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(composition, "_VNEXT_ENV_PATH", env_path)
    monkeypatch.setenv("DOTAMIND_DIAGNOSTIC_MAX_TOOL_CALLS", "6")
    monkeypatch.setenv("DOTAMIND_DIAGNOSTIC_ARGUMENT_EDGE_BYTES", "64")

    settings = VNextSettings.from_env()

    assert settings.model_diagnostic_limits == ModelDiagnosticLimits(
        max_tool_calls=6,
        argument_max_bytes=1024,
        total_argument_max_bytes=4096,
        argument_edge_bytes=64,
    )


def test_settings_use_default_diagnostic_limits_without_environment_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_settings(monkeypatch, tmp_path)

    settings = VNextSettings.from_env()
    second = VNextSettings.from_env()

    assert settings.model_diagnostic_limits == DEFAULT_MODEL_DIAGNOSTIC_LIMITS
    assert settings.model_diagnostic_limits is not second.model_diagnostic_limits


@pytest.mark.parametrize("name", _ENV_FIELDS)
@pytest.mark.parametrize("source", ["process", "file"])
def test_settings_reject_explicit_blank_diagnostic_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
    source: str,
) -> None:
    _isolate_settings(monkeypatch, tmp_path)
    if source == "process":
        monkeypatch.setenv(name, "")
    else:
        env_path = tmp_path / ".env"
        env_path.write_text(f"{name}=\n", encoding="utf-8")
        monkeypatch.setattr(composition, "_VNEXT_ENV_PATH", env_path)

    with pytest.raises(ValueError, match=name):
        VNextSettings.from_env()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (name, value)
        for name in _ENV_FIELDS
        for value in ("0", "-1", "1.5", "not-an-integer")
    ],
)
def test_settings_reject_invalid_diagnostic_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
    value: str,
) -> None:
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        VNextSettings.from_env()


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "DOTAMIND_DIAGNOSTIC_ARGUMENT_MAX_BYTES": "300",
            "DOTAMIND_DIAGNOSTIC_TOTAL_ARGUMENT_MAX_BYTES": "299",
        },
        {
            "DOTAMIND_DIAGNOSTIC_ARGUMENT_MAX_BYTES": "8",
            "DOTAMIND_DIAGNOSTIC_ARGUMENT_EDGE_BYTES": "5",
        },
    ],
)
def test_settings_reject_inconsistent_diagnostic_budgets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    overrides: dict[str, str],
) -> None:
    _isolate_settings(monkeypatch, tmp_path)
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValueError):
        VNextSettings.from_env()


def test_runtime_composition_passes_diagnostic_limits_to_model_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limits = ModelDiagnosticLimits(
        max_tool_calls=5,
        argument_max_bytes=100,
        total_argument_max_bytes=300,
        argument_edge_bytes=40,
    )
    captured: dict[str, object] = {}

    class _Model:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        async def complete(self, _request: object) -> object:
            raise AssertionError("configuration should not call the model")

    monkeypatch.setattr(composition, "OpenAICompatibleModelClient", _Model)
    settings = VNextSettings(
        agent_limits=AgentLimits(application_max_output_tokens=4096),
        model_diagnostic_limits=limits,
    )

    composition.build_vnext_runtime(settings=settings, services=VNextServices())

    assert captured["diagnostic_limits"] is limits
