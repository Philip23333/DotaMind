from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest

import app.vnext.composition as composition
from app.agentic.conversation.models import DialogueTurn
from app.application.chat_repository import ChatDialogueTurnResult
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.capabilities.esports import LeagueDTO, LeagueSearchResult
from app.vnext.composition import VNextServices, VNextSettings, build_vnext_runtime
from app.vnext.llm.protocol import (
    AssistantMessage,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResultMessage,
)
from app.vnext.product.chat import ProductChatCompleted, VNextChatService
from app.vnext.product.context import ConversationContextBuilder

_LIMIT_ENV_NAMES = (
    "DOTAMIND_CONTEXT_WINDOW_TOKENS",
    "DOTAMIND_CONTEXT_OUTPUT_RESERVE_TOKENS",
    "DOTAMIND_CONTEXT_SAFETY_MARGIN_TOKENS",
    "DOTAMIND_CONTEXT_ESTIMATE_BYTES_PER_TOKEN",
    "DOTAMIND_CONTEXT_COMPACTION_TRIGGER_PERCENT",
    "DOTAMIND_COMPACTION_RECENT_HISTORY_BYTES",
    "DOTAMIND_COMPACTION_MAX_INPUT_BYTES",
    "DOTAMIND_COMPACTION_RESERVE_TOKENS",
    "DOTAMIND_COMPACTION_MODEL_MAX_OUTPUT_TOKENS",
    # Legacy names are cleared too, but are deliberately no longer consumed.
    "DOTAMIND_COMPACTION_MAX_OUTPUT_TOKENS",
    "DOTAMIND_COMPACTION_MAX_SUMMARY_BYTES",
)


def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _LIMIT_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _write_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(composition, "_VNEXT_ENV_PATH", env_path)


def test_context_governance_defaults_to_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_env(monkeypatch)
    monkeypatch.setattr(composition, "_VNEXT_ENV_PATH", Path("/does/not/exist"))

    settings = VNextSettings.from_env()

    assert settings.agent_limits.context_window_tokens is None
    assert settings.agent_limits == AgentLimits()


def test_context_governance_reads_all_agent_limit_fields_from_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_env(monkeypatch)
    _write_env(
        monkeypatch,
        tmp_path,
        """
DOTAMIND_CONTEXT_WINDOW_TOKENS=12000
DOTAMIND_CONTEXT_OUTPUT_RESERVE_TOKENS=300
DOTAMIND_CONTEXT_SAFETY_MARGIN_TOKENS=200
DOTAMIND_CONTEXT_ESTIMATE_BYTES_PER_TOKEN=3
DOTAMIND_CONTEXT_COMPACTION_TRIGGER_PERCENT=75
DOTAMIND_COMPACTION_RECENT_HISTORY_BYTES=4000
DOTAMIND_COMPACTION_MAX_INPUT_BYTES=50000
DOTAMIND_COMPACTION_RESERVE_TOKENS=10000
DOTAMIND_COMPACTION_MODEL_MAX_OUTPUT_TOKENS=500
""",
    )

    limits = VNextSettings.from_env().agent_limits

    assert limits.model_dump() == {
        **AgentLimits().model_dump(),
        "context_window_tokens": 12000,
        "context_output_reserve_tokens": 300,
        "context_safety_margin_tokens": 200,
        "context_estimate_bytes_per_token": 3,
        "context_compaction_trigger_percent": 75,
        "compaction_recent_history_bytes": 4000,
        "compaction_max_input_bytes": 50000,
        "compaction_reserve_tokens": 10000,
        "compaction_model_max_output_tokens": 500,
    }


def test_process_environment_overrides_file_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_env(monkeypatch)
    _write_env(
        monkeypatch,
        tmp_path,
        "DOTAMIND_CONTEXT_WINDOW_TOKENS=12000\n"
        "DOTAMIND_COMPACTION_RESERVE_TOKENS=10000\n"
        "DOTAMIND_COMPACTION_MODEL_MAX_OUTPUT_TOKENS=4096\n",
    )
    monkeypatch.setenv("DOTAMIND_CONTEXT_WINDOW_TOKENS", " 15000 ")
    monkeypatch.setenv("DOTAMIND_COMPACTION_RESERVE_TOKENS", "12000")
    monkeypatch.setenv("DOTAMIND_COMPACTION_MODEL_MAX_OUTPUT_TOKENS", "700")

    limits = VNextSettings.from_env().agent_limits

    assert limits.context_window_tokens == 15000
    assert limits.compaction_reserve_tokens == 12000
    assert limits.compaction_model_max_output_tokens == 700


@pytest.mark.parametrize(
    ("file_cap", "process_cap"),
    [("", None), ("4096", " ")],
)
def test_blank_model_output_cap_means_unknown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    file_cap: str,
    process_cap: str | None,
) -> None:
    _isolate_env(monkeypatch)
    _write_env(
        monkeypatch,
        tmp_path,
        f"DOTAMIND_COMPACTION_MODEL_MAX_OUTPUT_TOKENS={file_cap}\n",
    )
    if process_cap is not None:
        monkeypatch.setenv("DOTAMIND_COMPACTION_MODEL_MAX_OUTPUT_TOKENS", process_cap)

    assert VNextSettings.from_env().agent_limits.compaction_model_max_output_tokens is None


def test_legacy_compaction_output_environment_variables_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_env(monkeypatch)
    monkeypatch.setattr(composition, "_VNEXT_ENV_PATH", Path("/does/not/exist"))
    monkeypatch.setenv("DOTAMIND_COMPACTION_MAX_OUTPUT_TOKENS", "7")
    monkeypatch.setenv("DOTAMIND_COMPACTION_MAX_SUMMARY_BYTES", "9")

    limits = VNextSettings.from_env().agent_limits

    assert limits.compaction_reserve_tokens == 16384
    assert limits.compaction_model_max_output_tokens is None


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_process_window_explicitly_disables_file_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str
) -> None:
    _isolate_env(monkeypatch)
    _write_env(monkeypatch, tmp_path, "DOTAMIND_CONTEXT_WINDOW_TOKENS=12000\n")
    monkeypatch.setenv("DOTAMIND_CONTEXT_WINDOW_TOKENS", value)

    assert VNextSettings.from_env().agent_limits.context_window_tokens is None


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DOTAMIND_CONTEXT_WINDOW_TOKENS", "1.5"),
        ("DOTAMIND_CONTEXT_OUTPUT_RESERVE_TOKENS", "true"),
        ("DOTAMIND_CONTEXT_ESTIMATE_BYTES_PER_TOKEN", "128k"),
        ("DOTAMIND_COMPACTION_MAX_INPUT_BYTES", ""),
        ("DOTAMIND_COMPACTION_RESERVE_TOKENS", ""),
        ("DOTAMIND_COMPACTION_MODEL_MAX_OUTPUT_TOKENS", "1.5"),
    ],
)
def test_invalid_context_governance_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    _isolate_env(monkeypatch)
    monkeypatch.setattr(composition, "_VNEXT_ENV_PATH", Path("/does/not/exist"))
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        VNextSettings.from_env()


@pytest.mark.parametrize(
    "content",
    [
        "DOTAMIND_CONTEXT_WINDOW_TOKENS=0\n",
        "DOTAMIND_CONTEXT_WINDOW_TOKENS=-1\n",
        "DOTAMIND_CONTEXT_COMPACTION_TRIGGER_PERCENT=0\n",
        "DOTAMIND_CONTEXT_COMPACTION_TRIGGER_PERCENT=100\n",
        "DOTAMIND_COMPACTION_RESERVE_TOKENS=1\n",
        "DOTAMIND_COMPACTION_MODEL_MAX_OUTPUT_TOKENS=0\n",
        "DOTAMIND_CONTEXT_WINDOW_TOKENS=1000\n"
        "DOTAMIND_CONTEXT_OUTPUT_RESERVE_TOKENS=600\n"
        "DOTAMIND_CONTEXT_SAFETY_MARGIN_TOKENS=400\n",
    ],
)
def test_agent_limits_constraints_are_not_silently_relaxed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str
) -> None:
    _isolate_env(monkeypatch)
    _write_env(monkeypatch, tmp_path, content)

    with pytest.raises(ValueError):
        VNextSettings.from_env()


def test_settings_default_agent_limits_are_not_shared() -> None:
    first = VNextSettings()
    second = VNextSettings()

    assert first.agent_limits is not second.agent_limits


class _NoCallModel:
    def __init__(self, **_: object) -> None:
        pass

    async def complete(self, _request: ModelRequest) -> ModelResponse:
        raise AssertionError("configuration assembly test must not call the model")


def test_build_runtime_receives_an_isolated_configured_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(composition, "OpenAICompatibleModelClient", _NoCallModel)
    configured = AgentLimits(
        context_window_tokens=12000,
        context_output_reserve_tokens=300,
        context_safety_margin_tokens=200,
        context_estimate_bytes_per_token=3,
        context_compaction_trigger_percent=75,
        compaction_recent_history_bytes=4000,
        compaction_max_input_bytes=50000,
        compaction_reserve_tokens=625,
        compaction_model_max_output_tokens=500,
    )
    settings = VNextSettings(agent_limits=configured)

    first = build_vnext_runtime(settings=settings, services=VNextServices())
    second = build_vnext_runtime(settings=settings, services=VNextServices())

    assert first.limits == configured
    assert first.limits is not configured
    assert second.limits is not first.limits
    assert second.limits == configured


class _ChatRepository:
    def __init__(self) -> None:
        self.dialogue = [
            DialogueTurn(
                turn_index=1,
                user_message="earlier synthetic question",
                assistant_message="earlier synthetic answer",
            )
        ]
        self.appended: list[dict[str, object]] = []

    async def lookup_dialogue_request(
        self, _browser_id: str, _session_id: UUID, _request_id: UUID, _query: str
    ) -> None:
        return None

    async def get_all_dialogue_turns(self, _browser_id: str, _session_id: UUID):
        return self.dialogue, len(self.dialogue) + 1

    async def append_dialogue_turn(self, **kwargs: object) -> ChatDialogueTurnResult:
        self.appended.append(kwargs)
        return ChatDialogueTurnResult(
            status="executed",
            turn_index=len(self.appended),
            assistant_message=str(kwargs["assistant_message"]),
        )


class _TraceStore:
    async def put(self, _trace: object) -> None:
        return None


class _NoVisuals:
    def match(self, _content: str) -> list[object]:
        return []


class _ConfiguredChatModel:
    def __init__(self, **_: object) -> None:
        self.requests: list[ModelRequest] = []
        self.tool_calls = 0

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if request.metadata.get("purpose") == "context_compaction":
            return ModelResponse.from_final(
                "verified compressed session history",
                finish_reason="stop",
            )
        if request.tools and self.tool_calls == 0:
            self.tool_calls += 1
            return ModelResponse.from_assistant(
                AssistantMessage(
                    tool_calls=[
                        ToolCall(
                            id="league-1",
                            name="esports.league.search",
                            arguments={"name": "synthetic league"},
                        )
                    ]
                )
            )
        if request.tools:
            return ModelResponse.from_final("execution completed with verified evidence")
        return ModelResponse.from_final("final answer from the configured chat runtime")


def test_product_chat_entry_uses_environment_configured_context_governance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_env(monkeypatch)
    monkeypatch.setattr(composition, "_VNEXT_ENV_PATH", Path("/does/not/exist"))
    for name, value in {
        "DOTAMIND_CONTEXT_WINDOW_TOKENS": "20000",
        "DOTAMIND_CONTEXT_OUTPUT_RESERVE_TOKENS": "200",
        "DOTAMIND_CONTEXT_SAFETY_MARGIN_TOKENS": "100",
        "DOTAMIND_CONTEXT_ESTIMATE_BYTES_PER_TOKEN": "1",
        "DOTAMIND_CONTEXT_COMPACTION_TRIGGER_PERCENT": "80",
        "DOTAMIND_COMPACTION_RECENT_HISTORY_BYTES": "1",
        "DOTAMIND_COMPACTION_MAX_INPUT_BYTES": "100000",
        "DOTAMIND_COMPACTION_RESERVE_TOKENS": "160",
        "DOTAMIND_COMPACTION_MODEL_MAX_OUTPUT_TOKENS": "128",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(composition, "OpenAICompatibleModelClient", _ConfiguredChatModel)

    async def league_search(_args: object) -> LeagueSearchResult:
        return LeagueSearchResult(
            items=[LeagueDTO(id=1, name="Synthetic League " + "x" * 4_000)],
            page=1,
            limit=20,
        )

    settings = VNextSettings.from_env()
    services = VNextServices(league_search=league_search)
    created: list[AgentRuntime] = []

    def runtime_factory() -> AgentRuntime:
        runtime = build_vnext_runtime(settings=settings, services=services)
        created.append(runtime)
        return runtime

    service = VNextChatService(
        _ChatRepository(),
        build_vnext_runtime(settings=settings, services=services),
        ConversationContextBuilder(),
        _NoVisuals(),  # type: ignore[arg-type]
        trace_store=_TraceStore(),
        runtime_factory=runtime_factory,
    )

    async def run_chat():
        session_id = uuid4()
        prepared = await service.prepare_turn(
            browser_id="browser",
            session_id=session_id,
            request_id=uuid4(),
            query="find the synthetic league",
        )
        return [event async for event in service.stream_turn(prepared)], session_id

    events, session_id = asyncio.run(run_chat())

    assert isinstance(events[-1], ProductChatCompleted)
    assert len(created) == 1
    model = created[0].model
    assert isinstance(model, _ConfiguredChatModel)
    compaction_requests = [
        request
        for request in model.requests
        if request.metadata.get("purpose") == "context_compaction"
    ]
    assert len(compaction_requests) == 1
    assert compaction_requests[0].max_output_tokens == 128
    assert all(
        request.max_output_tokens == 200
        for request in model.requests
        if request.metadata.get("purpose") != "context_compaction"
    )
    assert any(
        request.metadata.get("purpose") == "context_compaction" for request in model.requests
    )
    assert service._sessions[session_id].history.compaction_records
    assert any(
        isinstance(message, ToolResultMessage)
        for request in model.requests
        for message in request.messages
    )
    assert any(
        "verified compressed session history" in getattr(message, "content", "")
        for request in model.requests
        for message in request.messages
    )
    assert model.tool_calls == 1
