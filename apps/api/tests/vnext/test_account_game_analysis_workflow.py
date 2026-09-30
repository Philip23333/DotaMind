from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.agentic.conversation.models import DialogueTurn
from app.application.chat_repository import ChatDialogueTurnResult
from app.integrations.valve.catalog_repository import load_default_catalog_repository
from app.vnext.agent.instructions import AGENT_INSTRUCTION, PRODUCT_INSTRUCTION
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.capabilities.game.detail import GameDetailInput, GameDetailResult
from app.vnext.capabilities.player.profile import PlayerProfileInput, PlayerProfileResult
from app.vnext.capabilities.player.recent_games import (
    PlayerRecentGame,
    PlayerRecentGamesInput,
    PlayerRecentGamesResult,
)
from app.vnext.composition import VNextServices, VNextSettings, build_vnext_registry
from app.vnext.llm.protocol import (
    AssistantMessage,
    ModelRequest,
    ModelResponse,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.product.chat import VNextChatService
from app.vnext.product.context import ConversationContextBuilder
from app.vnext.product.presentation import DotaVisualEntityEnricher
from app.vnext.providers.valve.catalog_lookup import ValveCatalogLookupAdapter
from app.vnext.tools.errors import StructuredToolError
from tests.vnext.fakes import ScriptedTranscriptModelClient

ACCOUNT_ID = 7654321
_NOW = datetime(2026, 9, 27, tzinfo=UTC)


class _MemoryChatRepository:
    def __init__(self) -> None:
        self.dialogue: list[DialogueTurn] = []
        self.appended: list[dict[str, object]] = []

    async def lookup_dialogue_request(self, *_args):
        return None

    async def get_all_dialogue_turns(self, *_args):
        return self.dialogue, len(self.dialogue) + 1

    async def append_dialogue_turn(self, **kwargs):
        self.appended.append(kwargs)
        turn_index = len(self.dialogue) + 1
        self.dialogue.append(
            DialogueTurn(
                turn_index=turn_index,
                user_message=str(kwargs["user_query"]),
                assistant_message=str(kwargs["assistant_message"]),
            )
        )
        return ChatDialogueTurnResult(
            status="executed",
            turn_index=turn_index,
            assistant_message=str(kwargs["assistant_message"]),
        )


def _tool_turn(call: ToolCall, *more_calls: ToolCall) -> ModelResponse:
    return ModelResponse.from_assistant(AssistantMessage(tool_calls=[call, *more_calls]))


def _services(
    *,
    profile=None,
    recent_games=None,
    game_detail=None,
) -> VNextServices:
    catalog = ValveCatalogLookupAdapter(load_default_catalog_repository)
    return VNextServices(
        player_profile=profile,
        player_recent_games=recent_games,
        game_detail=game_detail,
        catalog_lookup=catalog.lookup,
    )


def _chat(
    model: ScriptedTranscriptModelClient,
    services: VNextServices,
    *,
    detail_enabled: bool = True,
) -> tuple[VNextChatService, _MemoryChatRepository, set[str]]:
    settings = VNextSettings(stratz_token="synthetic", opendota_enabled=detail_enabled)
    registry = build_vnext_registry(services, settings=settings)
    tool_names = {tool.name for tool in registry.schemas()}
    runtime = AgentRuntime(
        model,
        registry,
        limits=AgentLimits(deadline_seconds=5, answer_timeout_seconds=5),
        system_instruction=AGENT_INSTRUCTION,
        shared_instruction=PRODUCT_INSTRUCTION,
    )
    repository = _MemoryChatRepository()
    service = VNextChatService(
        repository,  # type: ignore[arg-type]
        runtime,
        ConversationContextBuilder(),
        DotaVisualEntityEnricher(),
    )
    return service, repository, tool_names


async def _run_turn(service: VNextChatService, session_id: UUID, query: str):
    prepared = await service.prepare_turn(
        browser_id="synthetic-browser",
        session_id=session_id,
        request_id=uuid4(),
        query=query,
    )
    states = [state async for state in service.stream_turn_states(prepared)]
    assert states[-1].state.status == "completed", states
    return states[-1]


def _recent_result(ids: list[int], account_id: int = ACCOUNT_ID) -> PlayerRecentGamesResult:
    return PlayerRecentGamesResult(
        steam_account_id=account_id,
        provider="stratz",
        retrieved_at=_NOW,
        limit=max(1, len(ids)),
        games=[
            PlayerRecentGame(
                valve_game_id=game_id,
                data={
                    "match_id": game_id,
                    "players": [{"steamAccountId": account_id, "isWinner": True}],
                },
            )
            for game_id in ids
        ],
    )


def _tool_results(request: ModelRequest) -> list[ToolResultMessage]:
    return [message for message in request.messages if isinstance(message, ToolResultMessage)]


def _tool_content(message: ToolResultMessage) -> dict[str, object]:
    if isinstance(message.content, str):
        return json.loads(message.content)
    return message.content


def _last_user(request: ModelRequest) -> str:
    return next(
        message.content
        for message in reversed(request.messages)
        if isinstance(message, UserMessage)
    )


def test_profile_question_uses_profile_without_recent_games_or_game_detail() -> None:
    calls: list[str] = []

    async def profile(query: PlayerProfileInput) -> PlayerProfileResult:
        calls.append("profile")
        return PlayerProfileResult(
            steam_account_id=query.steam_account_id,
            provider="stratz",
            retrieved_at=_NOW,
            found=True,
            profile={"steamAccountId": query.steam_account_id},
        )

    async def recent(_query: PlayerRecentGamesInput) -> PlayerRecentGamesResult:
        calls.append("recent")
        return _recent_result([7001])

    async def detail(_query: GameDetailInput) -> GameDetailResult:
        calls.append("detail")
        raise AssertionError("profile lookup must not fetch game details")

    model = ScriptedTranscriptModelClient(
        [
            lambda _request: _tool_turn(
                ToolCall(
                    id="profile-call",
                    name="player.profile",
                    arguments={"steam_account_id": ACCOUNT_ID},
                )
            ),
            lambda _request: ModelResponse.from_final("profile execution"),
            lambda _request: ModelResponse.from_final("profile answer"),
        ]
    )
    service, repository, _tool_names = _chat(
        model, _services(profile=profile, recent_games=recent, game_detail=detail)
    )

    async def run():
        state = await _run_turn(service, uuid4(), f"Show profile for Steam32 {ACCOUNT_ID}")
        return state

    state = asyncio.run(run())
    assert state.state.answer.text == "profile answer"
    assert calls == ["profile"]
    assert len(repository.appended) == 1


def test_recent_games_selects_one_game_reads_exact_player_artifact_and_catalog_names() -> None:
    recent_calls: list[int] = []
    detail_calls: list[int] = []
    source_data: dict[str, object] = {}
    recent_ids = [8101, 8102, 8103, 8104, 8105]

    async def recent(query: PlayerRecentGamesInput) -> PlayerRecentGamesResult:
        recent_calls.append(query.steam_account_id)
        assert query.limit == 5
        return _recent_result(recent_ids, query.steam_account_id)

    async def profile(_query: PlayerProfileInput) -> PlayerProfileResult:
        raise AssertionError("recent-game-only requests should not call player.profile")

    async def detail(query: GameDetailInput) -> GameDetailResult:
        detail_calls.append(query.valve_game_id)
        players = [
            {
                "account_id": ACCOUNT_ID + index + 1,
                "personaname": f"Synthetic player {index}",
                "hero_id": 2,
                "kills": index,
                "payload": "synthetic-only " * 220,
            }
            for index in range(7)
        ]
        players[5] = {
            "account_id": ACCOUNT_ID,
            "personaname": "Synthetic target",
            "hero_id": 1,
            "kills": 5,
            "deaths": 2,
            "assists": 9,
            "win": 0,
            "item_0": 1,
            "payload": "synthetic-only " * 220,
        }
        source_data.update(
            {
                "match_id": query.valve_game_id,
                "radiant_win": False,
                "duration": 2400,
                "players": players,
            }
        )
        return GameDetailResult(
            valve_game_id=query.valve_game_id,
            provider="opendota",
            retrieved_at=_NOW,
            data=source_data,
        )

    def recent_tool(request: ModelRequest) -> ModelResponse:
        assert _last_user(request).endswith(str(ACCOUNT_ID))
        assert "player.profile" in {tool.name for tool in request.tools}
        return _tool_turn(
            ToolCall(
                id="recent-call",
                name="player.recent_games",
                arguments={"steam_account_id": ACCOUNT_ID},
            )
        )

    def selected_detail(request: ModelRequest) -> ModelResponse:
        recent_output = _tool_results(request)[-1].content
        assert [entry["valve_game_id"] for entry in recent_output["games"]] == recent_ids
        return _tool_turn(
            ToolCall(
                id="detail-call",
                name="game.detail",
                arguments={"valve_game_id": recent_ids[0]},
            )
        )

    def read_target_player(request: ModelRequest) -> ModelResponse:
        detail_output = _tool_results(request)[-1].content
        assert detail_output["externalized"] is True
        assert "players" in detail_output["value"]["data"]
        return _tool_turn(
            ToolCall(
                id="target-read",
                name="artifact.read",
                arguments={
                    "ref": detail_output["artifact_ref"],
                    "mode": "read",
                    "path": "data.players.5",
                },
            )
        )

    def lookup_names(request: ModelRequest) -> ModelResponse:
        read_result = _tool_results(request)[-1].content
        target = read_result["value"]
        assert target["account_id"] == ACCOUNT_ID
        assert target["hero_id"] == 1
        assert target["win"] == 0
        assert target["item_0"] == 1
        assert "purchase_log" not in source_data
        return _tool_turn(
            ToolCall(
                id="hero-name",
                name="catalog.lookup",
                arguments={"kind": "hero", "ids": [1, 999999]},
            ),
            ToolCall(
                id="item-name",
                name="catalog.lookup",
                arguments={"kind": "item", "ids": [1]},
            ),
        )

    def final_execution(request: ModelRequest) -> ModelResponse:
        results = _tool_results(request)
        catalog_results = results[-2:]
        assert catalog_results[0].content["entries"][0]["status"] == "found"
        assert catalog_results[0].content["entries"][1] == {
            "id": 999999,
            "status": "unknown",
            "name_en": None,
            "name_zh": None,
        }
        assert catalog_results[1].content["entries"][0]["id"] == 1
        assert any(
            entry["data"]["players"][0]["isWinner"] is True
            for result in results
            if isinstance(result.content, dict) and "games" in result.content
            for entry in result.content["games"]
        )
        assert "game.parse" not in {tool.name for tool in request.tools}
        return ModelResponse.from_final("synthetic match evidence organized")

    def final_answer(request: ModelRequest) -> ModelResponse:
        assert not request.tools
        assert any(
            isinstance(message, UserMessage)
            and message.content == f"Analyze the latest game for Steam32 {ACCOUNT_ID}"
            for message in request.messages
        )
        assert any(
            isinstance(message, ToolResultMessage)
            and message.content.get("value", {}).get("account_id") == ACCOUNT_ID
            for message in request.messages
            if isinstance(message.content, dict)
        )
        return ModelResponse.from_final("Synthetic target stats reviewed; timeline unavailable.")

    model = ScriptedTranscriptModelClient(
        [
            recent_tool,
            selected_detail,
            read_target_player,
            lookup_names,
            final_execution,
            final_answer,
        ]
    )
    service, repository, tool_names = _chat(
        model,
        _services(profile=profile, recent_games=recent, game_detail=detail),
    )

    async def run():
        return await _run_turn(
            service,
            uuid4(),
            f"Analyze the latest game for Steam32 {ACCOUNT_ID}",
        )

    completed = asyncio.run(run())
    assert completed.state.answer.text == "Synthetic target stats reviewed; timeline unavailable."
    assert recent_calls == [ACCOUNT_ID]
    assert detail_calls == [recent_ids[0]]
    assert "game.parse" not in tool_names
    assert source_data["players"][5]["win"] == 0
    assert "name_en" not in source_data["players"][5]
    assert len(repository.appended) == 1


def test_second_game_followup_uses_original_list_after_new_game_appears() -> None:
    old_ids = [8201, 8202, 8203, 8204, 8205]
    current_ids = list(old_ids)
    recent_calls = 0
    detail_calls: list[int] = []

    async def recent(query: PlayerRecentGamesInput) -> PlayerRecentGamesResult:
        nonlocal recent_calls
        recent_calls += 1
        return _recent_result(current_ids, query.steam_account_id)

    async def detail(query: GameDetailInput) -> GameDetailResult:
        detail_calls.append(query.valve_game_id)
        return GameDetailResult(
            valve_game_id=query.valve_game_id,
            provider="opendota",
            retrieved_at=_NOW,
            data={
                "match_id": query.valve_game_id,
                "players": [{"account_id": ACCOUNT_ID, "hero_id": 2, "win": 1}],
            },
        )

    def initial_list(request: ModelRequest) -> ModelResponse:
        assert _last_user(request) == "Show my recent five games"
        return _tool_turn(
            ToolCall(
                id="old-list",
                name="player.recent_games",
                arguments={"steam_account_id": ACCOUNT_ID},
            )
        )

    def first_execution(_request: ModelRequest) -> ModelResponse:
        return ModelResponse.from_final("Here are the five recent synthetic games.")

    def first_answer(_request: ModelRequest) -> ModelResponse:
        return ModelResponse.from_final("Five synthetic game records listed.")

    def second_game(request: ModelRequest) -> ModelResponse:
        assert _last_user(request) == "Analyze the second game"
        assert (
            sum(
                message == UserMessage(content="Analyze the second game")
                for message in request.messages
            )
            == 1
        )
        historical = next(
            result.content
            for result in _tool_results(request)
            if isinstance(result.content, dict)
            and result.content.get("steam_account_id") == ACCOUNT_ID
        )
        assert [game["valve_game_id"] for game in historical["games"]] == old_ids
        return _tool_turn(
            ToolCall(
                id="second-detail",
                name="game.detail",
                arguments={"valve_game_id": old_ids[1]},
            )
        )

    def second_execution(request: ModelRequest) -> ModelResponse:
        assert _tool_results(request)[-1].content["valve_game_id"] == old_ids[1]
        return ModelResponse.from_final("Second game detail read.")

    def second_answer(_request: ModelRequest) -> ModelResponse:
        return ModelResponse.from_final("Second game reviewed from the earlier list.")

    model = ScriptedTranscriptModelClient(
        [initial_list, first_execution, first_answer, second_game, second_execution, second_answer]
    )
    service, repository, _ = _chat(model, _services(recent_games=recent, game_detail=detail))
    session_id = uuid4()

    async def run():
        first = await _run_turn(service, session_id, "Show my recent five games")
        current_ids.insert(0, 9000)
        second = await _run_turn(service, session_id, "Analyze the second game")
        return first, second

    first, second = asyncio.run(run())
    assert first.state.answer.text == "Five synthetic game records listed."
    assert second.state.answer.text == "Second game reviewed from the earlier list."
    assert recent_calls == 1
    assert detail_calls == [old_ids[1]]
    assert len(repository.appended) == 2


def test_profile_failure_does_not_block_independent_recent_games_lookup() -> None:
    calls: list[str] = []

    async def profile(_query: PlayerProfileInput) -> PlayerProfileResult:
        calls.append("profile")
        raise StructuredToolError("provider_error", "synthetic profile unavailable")

    async def recent(query: PlayerRecentGamesInput) -> PlayerRecentGamesResult:
        calls.append("recent")
        return _recent_result([8301], query.steam_account_id)

    async def detail(_query: GameDetailInput) -> GameDetailResult:
        calls.append("detail")
        raise AssertionError("recent-game request should not fetch detail")

    def ask_profile(request: ModelRequest) -> ModelResponse:
        return _tool_turn(
            ToolCall(
                id="failed-profile",
                name="player.profile",
                arguments={"steam_account_id": ACCOUNT_ID},
            )
        )

    def continue_with_recent(request: ModelRequest) -> ModelResponse:
        error = _tool_results(request)[-1]
        assert error.status == "error"
        assert error.error is not None and error.error.code == "provider_error"
        return _tool_turn(
            ToolCall(
                id="recent-after-error",
                name="player.recent_games",
                arguments={"steam_account_id": ACCOUNT_ID},
            )
        )

    model = ScriptedTranscriptModelClient(
        [
            ask_profile,
            continue_with_recent,
            lambda _request: ModelResponse.from_final(
                "Profile unavailable; recent match obtained."
            ),
            lambda _request: ModelResponse.from_final(
                "Recent game is available despite profile error."
            ),
        ]
    )
    service, _repository, _ = _chat(
        model,
        _services(profile=profile, recent_games=recent, game_detail=detail),
    )

    async def run():
        return await _run_turn(
            service,
            uuid4(),
            f"Show profile and recent games for Steam32 {ACCOUNT_ID}",
        )

    completed = asyncio.run(run())
    assert completed.state.answer.text == "Recent game is available despite profile error."
    assert calls == ["profile", "recent"]


def test_missing_target_account_and_timeline_are_not_filled_from_similar_player() -> None:
    detail_calls: list[int] = []

    async def recent(query: PlayerRecentGamesInput) -> PlayerRecentGamesResult:
        return _recent_result([8401], query.steam_account_id)

    async def detail(query: GameDetailInput) -> GameDetailResult:
        detail_calls.append(query.valve_game_id)
        return GameDetailResult(
            valve_game_id=query.valve_game_id,
            provider="opendota",
            retrieved_at=_NOW,
            data={
                "match_id": query.valve_game_id,
                "players": [
                    {"account_id": ACCOUNT_ID + 1, "personaname": str(ACCOUNT_ID), "hero_id": 1},
                    {"account_id": ACCOUNT_ID + 2, "personaname": "Synthetic target", "hero_id": 2},
                ],
            },
        )

    def get_recent(_request: ModelRequest) -> ModelResponse:
        return _tool_turn(
            ToolCall(
                id="recent-target-missing",
                name="player.recent_games",
                arguments={"steam_account_id": ACCOUNT_ID},
            )
        )

    def get_detail(_request: ModelRequest) -> ModelResponse:
        return _tool_turn(
            ToolCall(
                id="detail-target-missing",
                name="game.detail",
                arguments={"valve_game_id": 8401},
            )
        )

    def report_gap(request: ModelRequest) -> ModelResponse:
        detail_result = _tool_content(_tool_results(request)[-1])
        assert detail_result["data"]["players"][0]["account_id"] == ACCOUNT_ID + 1
        assert all(row["account_id"] != ACCOUNT_ID for row in detail_result["data"]["players"])
        assert "purchase_log" not in detail_result["data"]
        instruction = " ".join(
            " ".join(
                message.content
                for message in request.messages
                if isinstance(message, SystemMessage)
            ).split()
        )
        assert "never use the first player as a fallback" in instruction
        assert "exact `account_id`" in instruction
        assert "game.parse" not in {tool.name for tool in request.tools}
        return ModelResponse.from_final(
            "The target account and timeline are not present in this response."
        )

    model = ScriptedTranscriptModelClient(
        [
            get_recent,
            get_detail,
            report_gap,
            lambda _request: ModelResponse.from_final(
                "I cannot confirm this account's match data or event timeline."
            ),
        ]
    )
    service, _repository, tool_names = _chat(
        model,
        _services(recent_games=recent, game_detail=detail),
    )

    async def run():
        return await _run_turn(
            service,
            uuid4(),
            f"Analyze game 8401 for Steam32 {ACCOUNT_ID}",
        )

    completed = asyncio.run(run())
    assert (
        completed.state.answer.text
        == "I cannot confirm this account's match data or event timeline."
    )
    assert detail_calls == [8401]
    assert "game.parse" not in tool_names


def test_disabled_game_detail_is_absent_from_runtime_tool_catalog() -> None:
    calls: list[int] = []

    async def detail(query: GameDetailInput) -> GameDetailResult:
        calls.append(query.valve_game_id)
        raise AssertionError("disabled detail capability must not be invoked")

    def answer_without_missing_tool(request: ModelRequest) -> ModelResponse:
        assert "game.detail" not in {tool.name for tool in request.tools}
        return ModelResponse.from_final("Game details are not enabled in this runtime.")

    model = ScriptedTranscriptModelClient(
        [
            answer_without_missing_tool,
            lambda _request: ModelResponse.from_final("Details unavailable."),
        ]
    )
    service, _repository, tool_names = _chat(
        model,
        _services(game_detail=detail),
        detail_enabled=False,
    )

    async def run():
        return await _run_turn(service, uuid4(), "Analyze Valve game 8501")

    completed = asyncio.run(run())
    assert completed.state.answer.text == "Details unavailable."
    assert "game.detail" not in tool_names
    assert calls == []
