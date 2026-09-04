from __future__ import annotations

from app.vnext.agent.tool_result_summary import summarize_tool_result


def test_artifact_read_summary_does_not_persist_its_value_body() -> None:
    summary = summarize_tool_result(
        "artifact.read",
        {
            "ref": {
                "id": "game_summary:4:40003",
                "artifact_type": "game_summary",
                "schema_version": "4",
            },
            "path": "players",
            "value": [{"registered_name": "carry"}],
            "offset": 0,
            "limit": 50,
            "total": 1,
            "truncated": False,
        },
    )

    assert summary["ref"] == {
        "id": "game_summary:4:40003",
        "artifact_type": "game_summary",
        "schema_version": "4",
    }
    assert summary["path"] == "players"
    assert summary["value_kind"] == "list"
    assert summary["count"] == 1
