"""Deterministic local-catalog enrichment tests for product chat presentation."""

import pytest

from app.vnext.product.presentation import DotaVisualEntityEnricher


@pytest.fixture(scope="module")
def enricher() -> DotaVisualEntityEnricher:
    return DotaVisualEntityEnricher()


def test_hero_aliases_resolve_to_one_local_visual_entity(
    enricher: DotaVisualEntityEnricher,
) -> None:
    entities = enricher.match("不朽尸王（Undying，尸王）发挥出色。")

    heroes = [entity for entity in entities if entity.kind == "hero"]
    assert len(heroes) == 1
    assert heroes[0].imagePath == "/api/v1/assets/dota/heroes/85.png"
    assert heroes[0].label == "不朽尸王"
    assert {"不朽尸王", "Undying", "尸王"}.issubset(heroes[0].names)


def test_normal_ability_and_team_alias_resolve_to_local_visual_entities(
    enricher: DotaVisualEntityEnricher,
) -> None:
    entities = enricher.match("Team Spirit（TS）依靠腐朽（Decay）取得优势。")

    assert {(entity.kind, entity.imagePath) for entity in entities} == {
        ("team", "/api/v1/assets/esports/teams/1669.png"),
        ("ability", "/api/v1/assets/dota/abilities/5442.png"),
    }


def test_unknown_text_and_ascii_substrings_do_not_create_visual_entities(
    enricher: DotaVisualEntityEnricher,
) -> None:
    assert enricher.match("mystery teams 的战术与未知英雄无关。") == []
