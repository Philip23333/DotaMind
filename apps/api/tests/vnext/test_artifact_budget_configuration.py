from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import app.vnext.composition as composition
from app.vnext.artifacts import ArtifactLimits, serialized_size
from app.vnext.capabilities.esports.dtos import MatchDTO
from app.vnext.capabilities.esports.match import MatchSearchResult
from app.vnext.composition import VNextServices, VNextSettings, build_vnext_registry
from app.vnext.llm.protocol import ToolCall

_BUDGET_ENV_NAMES = (
    "DOTAMIND_TOOL_INLINE_MAX_BYTES",
    "DOTAMIND_TOOL_OBSERVATION_MAX_BYTES",
)


def _isolate_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(composition, "_VNEXT_ENV_PATH", tmp_path / "missing.env")
    monkeypatch.setenv("DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS", "4096")
    for name in _BUDGET_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_defaults_preserve_existing_artifact_budgets() -> None:
    limits = ArtifactLimits()

    assert limits.inline_max_bytes == 12 * 1024
    assert limits.observation_max_bytes == 35 * 1024


@pytest.mark.parametrize(
    "value",
    [True, False, 0, -1, 1.5, "12288"],
)
def test_artifact_limits_require_strict_positive_integers(value: object) -> None:
    with pytest.raises(ValueError):
        ArtifactLimits(inline_max_bytes=value)  # type: ignore[arg-type]


def test_artifact_limits_require_inline_budget_not_to_exceed_observation() -> None:
    with pytest.raises(ValueError, match="inline_max_bytes"):
        ArtifactLimits(inline_max_bytes=2048, observation_max_bytes=1024)


def test_from_env_uses_defaults_when_limits_are_not_configured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_configuration(monkeypatch, tmp_path)

    settings = VNextSettings.from_env()

    assert settings.artifact_limits == ArtifactLimits()


def test_from_env_reads_file_and_process_environment_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_configuration(monkeypatch, tmp_path)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "DOTAMIND_TOOL_INLINE_MAX_BYTES=7000\n"
        "DOTAMIND_TOOL_OBSERVATION_MAX_BYTES=9000\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(composition, "_VNEXT_ENV_PATH", env_path)
    monkeypatch.setenv("DOTAMIND_TOOL_INLINE_MAX_BYTES", "6000")

    limits = VNextSettings.from_env().artifact_limits

    assert limits == ArtifactLimits(inline_max_bytes=6000, observation_max_bytes=9000)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DOTAMIND_TOOL_INLINE_MAX_BYTES", ""),
        ("DOTAMIND_TOOL_INLINE_MAX_BYTES", "not-an-integer"),
        ("DOTAMIND_TOOL_INLINE_MAX_BYTES", "0"),
        ("DOTAMIND_TOOL_INLINE_MAX_BYTES", "-1"),
        ("DOTAMIND_TOOL_INLINE_MAX_BYTES", "1.5"),
        ("DOTAMIND_TOOL_OBSERVATION_MAX_BYTES", " "),
        ("DOTAMIND_TOOL_OBSERVATION_MAX_BYTES", "true"),
        ("DOTAMIND_TOOL_OBSERVATION_MAX_BYTES", "0"),
    ],
)
def test_from_env_rejects_invalid_artifact_budgets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
    value: str,
) -> None:
    _isolate_configuration(monkeypatch, tmp_path)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        VNextSettings.from_env()


def test_from_env_rejects_explicitly_empty_budget_in_dotenv_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_configuration(monkeypatch, tmp_path)
    env_path = tmp_path / ".env"
    env_path.write_text("DOTAMIND_TOOL_INLINE_MAX_BYTES=\n", encoding="utf-8")
    monkeypatch.setattr(composition, "_VNEXT_ENV_PATH", env_path)

    with pytest.raises(ValueError, match="DOTAMIND_TOOL_INLINE_MAX_BYTES"):
        VNextSettings.from_env()


def test_from_env_rejects_inline_budget_larger_than_observation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_configuration(monkeypatch, tmp_path)
    monkeypatch.setenv("DOTAMIND_TOOL_INLINE_MAX_BYTES", "2048")
    monkeypatch.setenv("DOTAMIND_TOOL_OBSERVATION_MAX_BYTES", "1024")

    with pytest.raises(ValueError, match="inline_max_bytes"):
        VNextSettings.from_env()


def _match_registry(settings: VNextSettings):
    async def search(query):
        return MatchSearchResult(
            items=[
                MatchDTO(
                    id=index,
                    name=f"Match {index} " + ("x" * 120),
                    status="finished",
                    draw=False,
                    forfeit=False,
                    rescheduled=False,
                )
                for index in range(1, 7)
            ],
            page=query.page,
            limit=query.limit,
        )

    return build_vnext_registry(
        VNextServices(match_search=search),
        settings=settings,
    )


def _execute(registry, call: ToolCall):
    return asyncio.run(registry.execute(call))


def test_composition_injects_environment_limits_into_externalization_and_reads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_configuration(monkeypatch, tmp_path)
    monkeypatch.setenv("DOTAMIND_TOOL_INLINE_MAX_BYTES", "32")
    monkeypatch.setenv("DOTAMIND_TOOL_OBSERVATION_MAX_BYTES", "1200")
    settings = VNextSettings.from_env()
    limits = settings.artifact_limits
    registry = _match_registry(settings)

    preview = _execute(
        registry,
        ToolCall(id="match", name="esports.match.search", arguments={}),
    )

    assert preview.status == "ok"
    assert preview.content["externalized"] is True
    assert serialized_size(preview.content) <= limits.observation_max_bytes
    artifact_ref = preview.content["artifact_ref"]
    read = _execute(
        registry,
        ToolCall(
            id="read",
            name="artifact.read",
            arguments={
                "ref": artifact_ref,
                "mode": "read",
                "path": "items",
                "limit": 100,
            },
        ),
    )

    assert read.status == "ok"
    assert read.content["total"] == 6
    assert read.content["truncated"] is True
    assert 0 < len(read.content["value"]) < 6
    assert serialized_size(read.content) <= limits.observation_max_bytes


def test_composition_fails_instead_of_returning_an_oversized_preview() -> None:
    limits = ArtifactLimits(inline_max_bytes=1, observation_max_bytes=16)
    registry = _match_registry(VNextSettings(artifact_limits=limits))

    result = _execute(
        registry,
        ToolCall(id="match", name="esports.match.search", arguments={}),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "artifact_error"


def test_two_registry_instances_keep_independent_observation_budgets() -> None:
    narrow_limits = ArtifactLimits(inline_max_bytes=1, observation_max_bytes=1_200)
    roomy_limits = ArtifactLimits(inline_max_bytes=1, observation_max_bytes=4_000)
    narrow_registry = _match_registry(VNextSettings(artifact_limits=narrow_limits))
    roomy_registry = _match_registry(VNextSettings(artifact_limits=roomy_limits))

    async def read_items(registry, call_id: str):
        preview = await registry.execute(
            ToolCall(
                id=f"match-{call_id}",
                name="esports.match.search",
                arguments={},
            )
        )
        assert preview.status == "ok"
        read = await registry.execute(
            ToolCall(
                id=f"read-{call_id}",
                name="artifact.read",
                arguments={
                    "ref": preview.content["artifact_ref"],
                    "mode": "read",
                    "path": "items",
                    "limit": 100,
                },
            )
        )
        return preview, read

    narrow_preview, narrow_read = asyncio.run(read_items(narrow_registry, "narrow"))
    roomy_preview, roomy_read = asyncio.run(read_items(roomy_registry, "roomy"))

    assert serialized_size(narrow_preview.content) <= narrow_limits.observation_max_bytes
    assert serialized_size(roomy_preview.content) <= roomy_limits.observation_max_bytes
    assert narrow_read.status == roomy_read.status == "ok"
    assert serialized_size(narrow_read.content) <= narrow_limits.observation_max_bytes
    assert serialized_size(roomy_read.content) <= roomy_limits.observation_max_bytes
    assert len(narrow_read.content["value"]) < len(roomy_read.content["value"])
