from app.application.chat_response import compact_chat_response


def test_compact_chat_response_discards_internal_graph_data_and_keeps_visuals() -> None:
    response = {
        "query": "match details",
        "game": "dota2",
        "status": "ok",
        "reason": "done",
        "error_code": None,
        "answer": {"summary": "# 斯温"},
        "runtime": {"duration_ms": 42, "attempts": []},
        "plan": {"tool_calls": ["internal"]},
        "tool_results": [
            {
                "data": {
                    "hero_name_zh": "斯温",
                    "hero_name_en": "Sven",
                    "hero_image_path": "/api/v1/assets/dota/heroes/18.png",
                    "raw_tool_sentinel": "must-not-persist",
                }
            }
        ],
        "evidence_graph": {"evidence_sentinel": "must-not-persist"},
        "trace": ["must-not-persist"],
    }

    compact = compact_chat_response(response)

    assert set(compact) == {
        "status",
        "reason",
        "error_code",
        "answer",
        "runtime",
        "catalog_visual_entities",
    }
    assert "must-not-persist" not in str(compact)
    assert compact["catalog_visual_entities"] == [
        {
            "kind": "hero",
            "imagePath": "/api/v1/assets/dota/heroes/18.png",
            "label": "斯温",
            "names": ["斯温", "Sven"],
        }
    ]
    assert compact_chat_response(compact) == compact
