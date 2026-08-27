from __future__ import annotations

from app.vnext.agent.tool_result_summary import summarize_tool_result


def test_competition_search_summary_preserves_business_status_and_candidates() -> None:
    summary = summarize_tool_result(
        "competitions.search",
        {
            "status": "unique",
            "query": "The International",
            "year": 2026,
            "candidate_count": 1,
            "candidates": [
                {
                    "ref": {"value": "competition:ti2026"},
                    "name": "The International 2026",
                    "year": 2026,
                    "status": "completed",
                    "starts_at": "2026-08-01T00:00:00Z",
                    "ends_at": "2026-08-10T00:00:00Z",
                }
            ],
        },
    )

    assert summary == {
        "status": "unique",
        "query": "The International",
        "year": 2026,
        "candidate_count": 1,
        "candidates": [
            {
                "ref": "competition:ti2026",
                "name": "The International 2026",
                "year": 2026,
                "status": "completed",
                "starts_at": "2026-08-01T00:00:00Z",
                "ends_at": "2026-08-10T00:00:00Z",
            }
        ],
        "candidates_truncated": False,
    }


def test_competition_search_summary_preserves_not_found_separately_from_tool_status() -> None:
    summary = summarize_tool_result(
        "competitions.search",
        {
            "status": "not_found",
            "query": "The International",
            "year": 2026,
            "candidate_count": 0,
            "candidates": [],
        },
    )

    assert summary == {
        "status": "not_found",
        "query": "The International",
        "year": 2026,
        "candidate_count": 0,
        "candidates": [],
        "candidates_truncated": False,
    }


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

    assert summary == {
        "ref": {
            "id": "game_summary:4:40003",
            "artifact_type": "game_summary",
            "schema_version": "4",
        },
        "path": "players",
        "offset": 0,
        "limit": 50,
        "total": 1,
        "truncated": False,
        "value_kind": "list",
        "count": 1,
    }
