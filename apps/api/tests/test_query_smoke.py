import importlib.util
import sys
from pathlib import Path


def _load_query_smoke():
    path = Path(__file__).resolve().parents[1] / "scripts" / "query_smoke.py"
    spec = importlib.util.spec_from_file_location("query_smoke", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_query_smoke_summarizes_team_report_payload() -> None:
    query_smoke = _load_query_smoke()
    summary = query_smoke.summarize_payload(
        {
            "routed_service": "team_report",
            "tasks": [
                {"agent": "critic", "action": "quality gate passed", "status": "completed"}
            ],
            "result": {
                "report_type": "team_report",
                "team_name": "Xtreme Gaming",
                "time_range": "last_60_days",
                "recent_record": "17-25 in last 42 matches",
                "matches_in_window": 42,
                "match_details_analyzed": 42,
                "data_freshness": {"latest_match_at": "2026-06-20T00:00:00Z"},
                "sources": [{"name": "OpenDota", "status": "live"}],
            },
        }
    )

    assert summary["routed_service"] == "team_report"
    assert summary["critic_status"] == "completed"
    assert summary["team_name"] == "Xtreme Gaming"
    assert summary["matches_in_window"] == 42
    assert summary["sources"] == ["OpenDota:live"]


def test_query_smoke_summarizes_ambiguous_team_payload() -> None:
    query_smoke = _load_query_smoke()
    summary = query_smoke.summarize_payload(
        {
            "error": "ambiguous_team",
            "message": "Multiple teams matched.",
            "candidates": [{"team_id": 1}, {"team_id": 2}],
        }
    )

    assert summary["error"] == "ambiguous_team"
    assert summary["candidate_count"] == 2
