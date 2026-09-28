from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.vnext.capabilities.hero import (
    GuideItem,
    GuideItemObservation,
    GuideSourceMetadata,
    HeroGuideInput,
    HeroGuideResult,
    ItemTiming,
    ProAbilityEvent,
    ProMatchExample,
    PubGuide,
    SkillSequenceOption,
    StartingItemOption,
)

NOW = datetime(2026, 9, 27, 12, tzinfo=UTC)


def source_metadata(sample_type: str, **overrides: object) -> GuideSourceMetadata:
    values: dict[str, object] = {
        "provider": "d2pt",
        "sample_type": sample_type,
        "availability": "available",
        "stale": False,
        "retrieved_at": NOW,
    }
    values.update(overrides)
    return GuideSourceMetadata.model_validate(values)


def empty_result(**overrides: object) -> HeroGuideResult:
    values: dict[str, object] = {
        "hero_id": 18,
        "position": 1,
        "section": "all",
        "pub_metadata": source_metadata("pub"),
        "pro_metadata": source_metadata("pro"),
    }
    values.update(overrides)
    return HeroGuideResult.model_validate(values)


def test_input_accepts_positive_hero_position_and_defaults_to_all() -> None:
    result = HeroGuideInput(hero_id=18, position=1)

    assert result.section == "all"


@pytest.mark.parametrize("section", ["all", "items", "skills", "pro_examples"])
def test_input_accepts_each_section(section: str) -> None:
    assert HeroGuideInput(hero_id=18, position=1, section=section).section == section


@pytest.mark.parametrize("hero_id", [0, -1, True, 18.0, "18"])
def test_input_rejects_non_positive_or_non_strict_hero_id(hero_id: object) -> None:
    with pytest.raises(ValidationError):
        HeroGuideInput(hero_id=hero_id, position=1)


@pytest.mark.parametrize("position", [0, 6, True, 1.0, "1", "pos 1"])
def test_input_rejects_invalid_or_non_strict_position(position: object) -> None:
    with pytest.raises(ValidationError):
        HeroGuideInput(hero_id=18, position=position)


def test_input_rejects_extra_fields_and_unknown_sections() -> None:
    with pytest.raises(ValidationError):
        HeroGuideInput(hero_id=18, position=1, refresh=True)
    with pytest.raises(ValidationError):
        HeroGuideInput(hero_id=18, position=1, section="equipment")


@pytest.mark.parametrize("field", ["retrieved_at", "last_attempt_at"])
def test_non_null_source_timestamps_require_timezone(field: str) -> None:
    with pytest.raises(ValidationError, match="timezone"):
        source_metadata("pub", **{field: datetime(2026, 9, 27, 12)})


def test_source_update_string_is_preserved_without_timezone_inference() -> None:
    metadata = source_metadata("pub", source_updated_at="2026-09-27 08:06:25")

    assert metadata.source_updated_at == "2026-09-27 08:06:25"


def test_stale_available_data_can_include_last_refresh_error() -> None:
    metadata = source_metadata(
        "pub",
        stale=True,
        last_error="upstream_unavailable",
        last_attempt_at=NOW,
    )

    assert metadata.availability == "available"
    assert metadata.stale is True
    assert metadata.last_error == "upstream_unavailable"


@pytest.mark.parametrize("availability", ["missing", "empty", "available"])
def test_source_availability_states_remain_distinct(availability: str) -> None:
    metadata = source_metadata("pub", availability=availability)
    dumped = metadata.model_dump(mode="json")

    assert dumped["availability"] == availability


def test_result_requires_pub_and_pro_metadata_in_matching_slots() -> None:
    with pytest.raises(ValidationError, match="pub_metadata.sample_type"):
        empty_result(pub_metadata=source_metadata("pro"))
    with pytest.raises(ValidationError, match="pro_metadata.sample_type"):
        empty_result(pro_metadata=source_metadata("pub"))


def test_skill_sequences_preserve_order_duplicates_and_arbitrary_length() -> None:
    option = SkillSequenceOption(
        ability_ids=[100, 101, 100],
        source_path="build_data.abilities_new[0]",
    )

    assert option.ability_ids == [100, 101, 100]
    assert len(option.ability_ids) == 3


def test_ability_events_preserve_same_level_entries_and_negative_time() -> None:
    example = ProMatchExample(
        source_match_id=123,
        hero_id=18,
        position_basis="build",
        ability_timeline=[
            ProAbilityEvent(ability_id=100, time_seconds=-5, hero_level=2),
            ProAbilityEvent(ability_id=101, time_seconds=-3, hero_level=2),
        ],
        source_path="recent_matches[0]",
    )

    assert [event.hero_level for event in example.ability_timeline] == [2, 2]
    assert [event.time_seconds for event in example.ability_timeline] == [-5, -3]


def test_pro_ability_event_preserves_zero_as_a_strict_integer() -> None:
    event = ProAbilityEvent(ability_id=0)

    assert event.ability_id == 0
    assert type(event.model_dump(mode="json")["ability_id"]) is int


@pytest.mark.parametrize("ability_id", [-1, True, False, "0", 0.0, None])
def test_pro_ability_event_rejects_invalid_nonnegative_ids(ability_id: object) -> None:
    with pytest.raises(ValidationError):
        ProAbilityEvent(ability_id=ability_id)


def test_pro_ability_event_requires_ability_id() -> None:
    with pytest.raises(ValidationError):
        ProAbilityEvent.model_validate({})


def test_pub_skill_sequences_still_reject_zero_ability_ids() -> None:
    with pytest.raises(ValidationError):
        SkillSequenceOption(ability_ids=[0], source_path="$.abilities_new[0]")


def test_open_json_preserves_extensions_null_zero_false_and_large_finite_values() -> None:
    item = GuideItemObservation(
        item_id=1,
        phase="unknown",
        statistics={
            "future_metric": {"nested": [None, 0, False, 100.0215]},
            "unknown_extension": "kept",
        },
        source_path="build_data.anchor_item_stats.1",
    )

    assert item.statistics["future_metric"] == {"nested": [None, 0, False, 100.0215]}
    assert item.statistics["unknown_extension"] == "kept"


@pytest.mark.parametrize("invalid_number", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_are_rejected_in_open_json(invalid_number: float) -> None:
    with pytest.raises(ValidationError):
        SkillSequenceOption(
            ability_ids=[1],
            statistics={"nested": [{"invalid": invalid_number}]},
            source_path="build_data.abilities_new[0]",
        )


def test_open_json_rejects_non_json_objects() -> None:
    with pytest.raises(ValidationError):
        SkillSequenceOption(
            ability_ids=[1],
            statistics={"unsupported": object()},
            source_path="build_data.abilities_new[0]",
        )


def test_item_and_match_identifiers_are_strict() -> None:
    with pytest.raises(ValidationError):
        GuideItem(item_id=True, quantity=1, name=None)
    with pytest.raises(ValidationError):
        GuideItem(item_id=1, quantity=1.0, name=None)
    with pytest.raises(ValidationError):
        ProMatchExample(
            source_match_id="123",
            hero_id=18,
            position_basis="unknown",
            source_path="recent_matches[0]",
        )


def test_steam32_account_id_bounds_are_strict() -> None:
    valid = ProMatchExample(
        source_match_id=123,
        account_id=4_294_967_295,
        hero_id=18,
        position_basis="unknown",
        source_path="recent_matches[0]",
    )
    assert valid.account_id == 4_294_967_295

    for account_id in (-1, 4_294_967_296, True, 7.0, "7"):
        with pytest.raises(ValidationError):
            ProMatchExample(
                source_match_id=123,
                account_id=account_id,
                hero_id=18,
                position_basis="unknown",
                source_path="recent_matches[0]",
            )


def test_pro_match_requires_position_basis_and_strict_win_boolean() -> None:
    with pytest.raises(ValidationError):
        ProMatchExample(source_match_id=123, hero_id=18, source_path="recent_matches[0]")

    with pytest.raises(ValidationError):
        ProMatchExample(
            source_match_id=123,
            hero_id=18,
            position_basis="unknown",
            won=1,
            source_path="recent_matches[0]",
        )


def test_source_ids_allow_only_missing_or_strict_non_negative_integers() -> None:
    assert PubGuide(build_id=None, facet_id=0).build_id is None
    assert PubGuide(build_id=0, facet_id=1).build_id == 0

    for build_id in (-1, True, 1.0, "1"):
        with pytest.raises(ValidationError):
            PubGuide(build_id=build_id)


def test_pub_candidates_remain_independent_without_cross_product() -> None:
    guide = PubGuide(
        starting_options=[
            StartingItemOption(
                items=[GuideItem(item_id=1, quantity=1, name=None)], source_path="a"
            ),
            StartingItemOption(
                items=[GuideItem(item_id=2, quantity=1, name=None)], source_path="b"
            ),
        ],
        skill_sequences=[
            SkillSequenceOption(ability_ids=[100], source_path="c"),
            SkillSequenceOption(ability_ids=[101], source_path="d"),
        ],
    )

    assert len(guide.starting_options) == 2
    assert len(guide.skill_sequences) == 2
    assert "combined_builds" not in guide.model_dump()


def test_item_timing_is_finite_and_does_not_reject_negative_minutes() -> None:
    timing = ItemTiming(kind="average", minute=-1.5, source_path="item.avg_minute")

    assert timing.minute == -1.5
    with pytest.raises(ValidationError):
        ItemTiming(kind="median", minute=float("inf"), source_path="item.minute")


def test_result_round_trip_preserves_json_semantics() -> None:
    result = empty_result(
        pub_guides=[
            PubGuide(
                build_id=0,
                scope={"patch_versions": ["7.41f"]},
                statistics={"win_rate": 0.518, "flag": False},
                skill_sequences=[
                    SkillSequenceOption(
                        ability_ids=[100, 101, 100],
                        statistics={"nested": {"unknown": None}},
                        source_path="build_data.abilities_new[0]",
                    )
                ],
            )
        ],
        pro_examples=[
            ProMatchExample(
                source_match_id=987654,
                hero_id=18,
                position=1,
                position_basis="build",
                won=False,
                ability_timeline=[
                    ProAbilityEvent(ability_id=100, hero_level=2, time_seconds=-3)
                ],
                source_path="recent_matches[0]",
            )
        ],
        pub_guides_total=1,
        pro_examples_total=1,
    )

    revalidated = HeroGuideResult.model_validate(result.model_dump(mode="json"))

    assert revalidated.model_dump(mode="json") == result.model_dump(mode="json")


def test_explicit_items_result_does_not_filter_or_autofill() -> None:
    result = empty_result(section="items", pub_guides_total=None)

    assert result.section == "items"
    assert result.pub_guides == []
    assert result.pub_guides_total is None
