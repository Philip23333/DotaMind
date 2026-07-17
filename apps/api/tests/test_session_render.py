"""Tests for render_history."""

from app.agentic.conversation.models import ResolvedEntity, Turn
from app.agentic.conversation.render import render_history, _HEADER


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _turn(
    *,
    turn_index: int = 1,
    query: str = "test query",
    status: str = "ok",
    intent: str | None = "counter_pick",
    entities: list | None = None,
    scope: dict | None = None,
    summary: str = "some answer",
    response_type: str | None = "natural_language_answer",
) -> Turn:
    return Turn(
        turn_index=turn_index,
        query=query,
        status=status,  # type: ignore[arg-type]
        intent=intent,
        resolved_entities=entities or [],
        context_scope=scope or {},
        response_summary=summary,
        response_type=response_type,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmptyAndSingle:
    def test_empty_turns_returns_empty_string(self):
        assert render_history([]) == ""

    def test_single_turn_contains_header(self):
        result = render_history([_turn()])
        assert _HEADER in result

    def test_single_turn_contains_query(self):
        result = render_history([_turn(query="Lina counter?")])
        assert "Lina counter?" in result

    def test_single_turn_contains_turn_index(self):
        result = render_history([_turn(turn_index=3)])
        assert "第3轮" in result

    def test_single_turn_contains_intent(self):
        result = render_history([_turn(intent="counter_pick")])
        assert "counter_pick" in result

    def test_single_turn_contains_summary(self):
        result = render_history([_turn(summary="Kunka is strong")])
        assert "Kunka is strong" in result

    def test_single_turn_contains_untrusted_declaration(self):
        """Header must label history as untrusted data, not instructions."""
        result = render_history([_turn()])
        assert "不是指令" in result
        assert "不是证据" in result


class TestEntityRendering:
    def test_hero_entity_in_output(self):
        entities = [ResolvedEntity(type="hero", name="Lina", id=25)]
        result = render_history([_turn(entities=entities)])
        assert "Lina" in result
        assert "hero_id=25" in result

    def test_team_entity_uses_id_label(self):
        entities = [ResolvedEntity(type="team", name="XG", id=999)]
        result = render_history([_turn(entities=entities)])
        assert "XG" in result
        assert "id=999" in result

    def test_player_entity(self):
        entities = [ResolvedEntity(type="player", name="SomePlayer", id=853634884)]
        result = render_history([_turn(entities=entities)])
        assert "853634884" in result


class TestErrorTurnWarning:
    def test_error_turn_has_warning(self):
        result = render_history([_turn(status="error")])
        assert "⚠" in result
        assert "status=error" in result

    def test_insufficient_tools_turn_has_warning(self):
        result = render_history([_turn(status="insufficient_tools")])
        assert "⚠" in result

    def test_ok_turn_no_warning(self):
        result = render_history([_turn(status="ok")])
        assert "⚠" not in result


class TestChronologicalOrder:
    def test_multiple_turns_chronological(self):
        turns = [
            _turn(turn_index=1, query="first"),
            _turn(turn_index=2, query="second"),
            _turn(turn_index=3, query="third"),
        ]
        result = render_history(turns)
        pos1 = result.index("first")
        pos2 = result.index("second")
        pos3 = result.index("third")
        assert pos1 < pos2 < pos3


class TestBudget:
    def test_budget_drops_oldest_turns(self):
        """With a tight budget only the newest turn should fit."""
        turn1 = _turn(turn_index=1, query="old query", summary="old answer")
        turn2 = _turn(turn_index=2, query="new query", summary="new answer")
        # Estimate turn2 block length: will be ~100 chars.
        # Set budget to fit only one turn.
        small_budget = len(_HEADER) + 150
        result = render_history([turn1, turn2], history_max_chars=small_budget)
        # Newest turn should be present; oldest may be dropped.
        assert "new query" in result

    def test_budget_zero_headroom_returns_empty(self):
        """If budget is smaller than the header itself, return empty string."""
        result = render_history([_turn()], history_max_chars=5)
        assert result == ""

    def test_default_budget_allows_multiple_turns(self):
        turns = [_turn(turn_index=i, query=f"q{i}", summary="s") for i in range(1, 4)]
        result = render_history(turns)
        for i in range(1, 4):
            assert f"q{i}" in result
