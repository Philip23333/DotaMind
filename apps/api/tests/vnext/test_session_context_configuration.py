from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

import app.vnext.composition as composition
from app.vnext.agent.limits import AgentLimits
from app.vnext.composition import VNextServices, VNextSettings
from app.vnext.product.chat import VNextChatService
from app.vnext.product.context import ConversationContextBuilder
from app.vnext.session_limits import SessionContextLimits

_SESSION_ENV_FIELDS = {
    "DOTAMIND_HISTORY_BOOTSTRAP_MAX_TURNS": "history_bootstrap_max_turns",
    "DOTAMIND_HISTORY_BOOTSTRAP_MAX_CHARS": "history_bootstrap_max_chars",
    "DOTAMIND_ARTIFACT_LOCATOR_CAPACITY": "artifact_locator_capacity",
    "DOTAMIND_ARTIFACT_LOCATOR_HINT_CHARS": "artifact_locator_hint_chars",
}
_ENV_NAMES = (
    *_SESSION_ENV_FIELDS,
    "DOTAMIND_TOOL_TIMEOUT_SECONDS",
    "DOTAMIND_EXECUTION_DEADLINE_SECONDS",
    "DOTAMIND_ANSWER_DEADLINE_SECONDS",
    "DOTAMIND_CONTEXT_WINDOW_TOKENS",
    "DOTAMIND_MODEL_MAX_OUTPUT_TOKENS",
    "DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS",
    "DOTAMIND_CONTEXT_SAFETY_MARGIN_TOKENS",
    "DOTAMIND_CONTEXT_ESTIMATE_BYTES_PER_TOKEN",
    "DOTAMIND_CONTEXT_COMPACTION_TEST_TRIGGER_PERCENT",
    "DOTAMIND_COMPACTION_KEEP_RECENT_TOKENS",
    "DOTAMIND_COMPACTION_RESERVE_TOKENS",
    "DOTAMIND_COMPACTION_MODEL_MAX_OUTPUT_TOKENS",
    "DOTAMIND_COMPACTION_MAX_RETRIES",
    "DOTAMIND_TOOL_INLINE_MAX_BYTES",
    "DOTAMIND_TOOL_OBSERVATION_MAX_BYTES",
    "DOTAMIND_DIAGNOSTIC_MAX_TOOL_CALLS",
    "DOTAMIND_DIAGNOSTIC_ARGUMENT_MAX_BYTES",
    "DOTAMIND_DIAGNOSTIC_TOTAL_ARGUMENT_MAX_BYTES",
    "DOTAMIND_DIAGNOSTIC_ARGUMENT_EDGE_BYTES",
)


def _isolate_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(composition, "_VNEXT_ENV_PATH", tmp_path / "missing.env")
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS", "4096")


def test_session_context_limits_are_strict_immutable_and_have_existing_defaults() -> None:
    limits = SessionContextLimits()

    assert limits.model_dump() == {
        "history_bootstrap_max_turns": 12,
        "history_bootstrap_max_chars": 40_000,
        "artifact_locator_capacity": 16,
        "artifact_locator_hint_chars": 256,
    }
    with pytest.raises(ValidationError):
        limits.history_bootstrap_max_turns = 20  # type: ignore[misc]
    with pytest.raises(ValidationError):
        SessionContextLimits(extra_limit=1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (field, value)
        for field in _SESSION_ENV_FIELDS.values()
        for value in (True, False, 0, -1, 1.5, "12")
    ],
)
def test_session_context_limits_reject_non_positive_or_non_integer_values(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        SessionContextLimits(**{field: value})


def test_settings_use_unshared_session_defaults_and_existing_default_tool_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_settings(monkeypatch, tmp_path)

    first = VNextSettings.from_env()
    second = VNextSettings.from_env()

    assert first.session_context_limits == SessionContextLimits()
    assert first.session_context_limits is not second.session_context_limits
    assert first.agent_limits.default_tool_timeout == 60


def test_settings_read_session_values_from_env_file_and_process_env_wins(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_settings(monkeypatch, tmp_path)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS=4096",
                "DOTAMIND_HISTORY_BOOTSTRAP_MAX_TURNS=7",
                "DOTAMIND_HISTORY_BOOTSTRAP_MAX_CHARS=30000",
                "DOTAMIND_ARTIFACT_LOCATOR_CAPACITY=8",
                "DOTAMIND_ARTIFACT_LOCATOR_HINT_CHARS=128",
                "DOTAMIND_TOOL_TIMEOUT_SECONDS=12.5",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(composition, "_VNEXT_ENV_PATH", env_path)
    monkeypatch.setenv("DOTAMIND_HISTORY_BOOTSTRAP_MAX_TURNS", "9")
    monkeypatch.setenv("DOTAMIND_ARTIFACT_LOCATOR_CAPACITY", "5")
    monkeypatch.setenv("DOTAMIND_TOOL_TIMEOUT_SECONDS", "3.75")

    settings = VNextSettings.from_env()

    assert settings.session_context_limits == SessionContextLimits(
        history_bootstrap_max_turns=9,
        history_bootstrap_max_chars=30_000,
        artifact_locator_capacity=5,
        artifact_locator_hint_chars=128,
    )
    assert settings.agent_limits.default_tool_timeout == 3.75


def test_environment_tool_timeout_reaches_runtime_limits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("DOTAMIND_TOOL_TIMEOUT_SECONDS", "7.25")

    class _NoCallModel:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def complete(self, _request: object) -> object:
            raise AssertionError("runtime configuration must not call the model")

    monkeypatch.setattr(composition, "OpenAICompatibleModelClient", _NoCallModel)
    settings = VNextSettings.from_env()
    runtime = composition.build_vnext_runtime(settings=settings, services=VNextServices())

    assert runtime.limits.default_tool_timeout == 7.25


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (name, value)
        for name in _SESSION_ENV_FIELDS
        for value in ("", "0", "-1", "1.5", "true")
    ]
    + [
        ("DOTAMIND_TOOL_TIMEOUT_SECONDS", value)
        for value in ("", "0", "-1", "NaN", "inf", "-inf", "not-a-number")
    ],
)
def test_settings_reject_invalid_process_values(
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
    "name",
    [*_SESSION_ENV_FIELDS, "DOTAMIND_TOOL_TIMEOUT_SECONDS"],
)
def test_settings_reject_explicitly_blank_file_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
) -> None:
    _isolate_settings(monkeypatch, tmp_path)
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS=4096\n{name}=\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(composition, "_VNEXT_ENV_PATH", env_path)

    with pytest.raises(ValueError, match=name):
        VNextSettings.from_env()


def test_chat_service_applies_locator_limits_per_instance() -> None:
    first_limits = SessionContextLimits(
        artifact_locator_capacity=1,
        artifact_locator_hint_chars=5,
    )
    second_limits = SessionContextLimits(
        artifact_locator_capacity=3,
        artifact_locator_hint_chars=20,
    )
    first = VNextChatService(
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        ConversationContextBuilder(),
        object(),  # type: ignore[arg-type]
        session_context_limits=first_limits,
    )
    second = VNextChatService(
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        ConversationContextBuilder(),
        object(),  # type: ignore[arg-type]
        session_context_limits=second_limits,
    )

    first_history = first._session_for(uuid4()).history
    second_history = second._session_for(uuid4()).history

    assert first_history._artifact_locator_capacity == 1
    assert first_history._artifact_locator_hint_chars == 5
    assert second_history._artifact_locator_capacity == 3
    assert second_history._artifact_locator_hint_chars == 20


def test_lifespan_reuses_one_loaded_settings_object_for_both_runtime_builds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.application.plan_service as plan_service_module
    import app.main as main_module

    limits = SessionContextLimits(
        history_bootstrap_max_turns=3,
        history_bootstrap_max_chars=1234,
        artifact_locator_capacity=4,
        artifact_locator_hint_chars=55,
    )
    configured = VNextSettings(
        agent_limits=AgentLimits(application_max_output_tokens=4096),
        session_context_limits=limits,
    )
    services = VNextServices()
    database = SimpleNamespace(engine=object(), session_factory=object())
    closed: list[str] = []

    class _Store:
        async def aclose(self) -> None:
            closed.append("store")

    class _PlanService:
        def __init__(self) -> None:
            self.runner = object()

    build_calls: list[tuple[object, object]] = []
    chat_call: dict[str, object] = {}

    def build_runtime(*, settings: object, services: object) -> object:
        build_calls.append((settings, services))
        return object()

    def create_chat(*args: object, **kwargs: object) -> object:
        chat_call["args"] = args
        chat_call["kwargs"] = kwargs
        return object()

    async def close_db(_database: object) -> None:
        closed.append("database")

    async def initialize(_settings: object, _services: object) -> None:
        return None

    monkeypatch.setattr(main_module, "settings", SimpleNamespace(redis_url=None, database_url="db"))
    monkeypatch.setattr(main_module.VNextSettings, "from_env", classmethod(lambda cls: configured))
    monkeypatch.setattr(main_module, "create_database_resources", lambda _url: database)
    monkeypatch.setattr(main_module, "ping_database", lambda _engine: asyncio.sleep(0))
    monkeypatch.setattr(main_module, "close_database", close_db)
    monkeypatch.setattr(main_module, "build_session_store", lambda *_args: _Store())
    monkeypatch.setattr(main_module, "PostgresChatRepository", lambda _factory: object())
    monkeypatch.setattr(main_module, "PostgresChatRunRepository", lambda _factory: object())
    monkeypatch.setattr(main_module, "build_vnext_services", lambda *_args, **_kwargs: services)
    monkeypatch.setattr(main_module, "initialize_vnext_services", initialize)
    monkeypatch.setattr(main_module, "build_vnext_runtime", build_runtime)
    monkeypatch.setattr(main_module, "VNextChatService", create_chat)
    monkeypatch.setattr(main_module, "DotaVisualEntityEnricher", lambda *_args: object())
    monkeypatch.setattr(main_module, "ConversationMemoryService", lambda **_kwargs: object())
    monkeypatch.setattr(plan_service_module, "PlanService", _PlanService)
    monkeypatch.setattr(
        main_module,
        "get_policy",
        lambda: SimpleNamespace(conversation=SimpleNamespace(recent_dialogue_max_chars=100)),
    )
    app = SimpleNamespace(state=SimpleNamespace())

    async def exercise() -> None:
        async with main_module.lifespan(app):
            assert len(build_calls) == 1
            assert build_calls[0][0] is configured
            assert build_calls[0][1] is services
            args = chat_call["args"]
            kwargs = chat_call["kwargs"]
            assert isinstance(args, tuple)
            builder = args[2]
            assert isinstance(builder, ConversationContextBuilder)
            assert builder._max_turns == 3
            assert builder._max_history_chars == 1234
            assert isinstance(kwargs, dict)
            assert kwargs["session_context_limits"] is limits
            kwargs["runtime_factory"]()
            assert len(build_calls) == 2
            assert build_calls[1][0] is configured
            assert build_calls[1][1] is services

    asyncio.run(exercise())
    assert closed == ["store", "database"]
