import asyncio

from app.agentic.models import QueryContext, ToolCall
from app.agentic.tools import ToolExecutor, ToolRegistry
from app.agentic.tools.patch_tools import register_patch_tools


def test_patch_get_records_reads_latest_patch() -> None:
    result = asyncio.run(
        _executor().execute(ToolCall(id="p", tool="patch.get_records"), QueryContext())
    )

    assert result.status == "ok"
    assert result.data["patch"] == "7.41d"
    assert result.data["change_count"] > 0


def test_patch_hero_changes_filters_single_hero() -> None:
    result = asyncio.run(
        _executor().execute(
            ToolCall(
                id="h",
                tool="patch.hero_changes",
                args={"patch": "latest", "hero": "Abaddon"},
            ),
            QueryContext(),
        )
    )

    assert result.status == "ok"
    assert all(change["target"] == "abaddon" for change in result.data["changes"])


def test_patch_item_changes_returns_item_groups() -> None:
    result = asyncio.run(
        _executor().execute(ToolCall(id="i", tool="patch.item_changes"), QueryContext())
    )

    assert result.status == "ok"
    assert result.data["change_count"] > 0
    assert "item" in result.data["target_type_counts"]


def test_patch_tool_error_is_exposed() -> None:
    result = asyncio.run(
        _executor().execute(
            ToolCall(
                id="missing",
                tool="patch.get_records",
                args={"patch": "missing_patch"},
            ),
            QueryContext(),
        )
    )

    assert result.status == "error"
    assert "patch records not found" in result.error


def _executor() -> ToolExecutor:
    registry = ToolRegistry()
    register_patch_tools(registry)
    return ToolExecutor(registry)
