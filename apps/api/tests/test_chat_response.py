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


def test_compact_visual_entities_do_not_treat_player_names_as_hero_names() -> None:
    compact = compact_chat_response(
        {
            "status": "ok",
            "tool_results": [
                {
                    "data": {
                        "name": "Satanic",
                        "hero_name_zh": "自然先知",
                        "hero_name_en": "Nature's Prophet",
                        "hero_image_path": "/api/v1/assets/dota/heroes/53.png",
                    }
                }
            ],
        }
    )

    assert compact["catalog_visual_entities"] == [
        {
            "kind": "hero",
            "imagePath": "/api/v1/assets/dota/heroes/53.png",
            "label": "自然先知",
            "names": ["自然先知", "Nature's Prophet"],
        }
    ]
