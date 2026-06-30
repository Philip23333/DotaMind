from app.agentic.tools.hero_tools import (
    HeroRecord,
    HeroResolver,
    load_default_hero_resolver,
    normalize_hero_key,
)


def test_normalize_hero_key() -> None:
    assert normalize_hero_key("  Legion-Commander ") == "legion commander"
    assert normalize_hero_key("npc_dota_hero_shadow_fiend") == "npc dota hero shadow fiend"
    assert normalize_hero_key("Nature's Prophet") == "natures prophet"


def test_hero_resolver_resolves_exact_name() -> None:
    resolver = HeroResolver(
        [
            HeroRecord(25, "npc_dota_hero_lina", "Lina", ("火女",)),
            HeroRecord(104, "npc_dota_hero_legion_commander", "Legion Commander", ("lc",)),
        ]
    )

    result = resolver.resolve("Lina")

    assert result["status"] == "resolved"
    assert result["hero"]["hero_id"] == 25
    assert result["method"] == "exact"


def test_hero_resolver_resolves_alias() -> None:
    resolver = HeroResolver(
        [
            HeroRecord(25, "npc_dota_hero_lina", "Lina", ("火女",)),
            HeroRecord(
                104,
                "npc_dota_hero_legion_commander",
                "Legion Commander",
                ("lc", "军团"),
            ),
        ]
    )

    result = resolver.resolve("LC")

    assert result["status"] == "resolved"
    assert result["hero"]["localized_name"] == "Legion Commander"


def test_hero_resolver_returns_ambiguous_alias() -> None:
    resolver = HeroResolver(
        [
            HeroRecord(7, "npc_dota_hero_earthshaker", "Earthshaker", ("es",)),
            HeroRecord(107, "npc_dota_hero_earth_spirit", "Earth Spirit", ("es",)),
        ]
    )

    result = resolver.resolve("es")

    assert result["status"] == "ambiguous"
    assert {candidate["hero_id"] for candidate in result["candidates"]} == {7, 107}


def test_hero_resolver_returns_not_found() -> None:
    resolver = HeroResolver(
        [HeroRecord(25, "npc_dota_hero_lina", "Lina", ("火女",))],
        fuzzy_score_cutoff=0.95,
    )

    result = resolver.resolve("totally unknown")

    assert result["status"] == "not_found"
    assert result["candidates"] == []


def test_default_hero_resolver_supports_common_chinese_aliases() -> None:
    resolver = load_default_hero_resolver()

    assert resolver.resolve("火女")["hero"]["hero_id"] == 25
    assert resolver.resolve("军团")["hero"]["hero_id"] == 104
    assert resolver.resolve("剑圣")["hero"]["hero_id"] == 8
    assert resolver.resolve("屠夫")["hero"]["hero_id"] == 14
    assert resolver.resolve("小鱼人")["hero"]["hero_id"] == 93
    assert resolver.resolve("老奶奶")["hero"]["hero_id"] == 128
