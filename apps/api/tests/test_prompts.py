from app.llm.prompts import render_prompt


def test_render_meta_hero_insights_prompt() -> None:
    prompt = render_prompt(
        "analyzer_meta_hero_insights",
        {
            "role": "offlane",
            "hero_name": "Axe",
            "meta_score": 58,
            "tier": "B",
            "win_rate": "51.2%",
            "pick_rate": "60.6%",
            "pro_presence": "36.0%",
            "patch_impact_score": "+0.15",
        },
    )

    assert "Axe" in prompt
    assert "offlane" in prompt
    assert "{{" not in prompt
    assert "reasons" in prompt
    assert "practice_advice" in prompt
