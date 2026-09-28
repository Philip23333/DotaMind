import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.vnext.providers.d2pt.parsers import parse_pro_examples

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "d2pt"


def _load_fixture(name: str) -> tuple[bytes, list[dict[str, object]]]:
    raw = (FIXTURE_DIR / name).read_bytes()
    parsed = json.loads(raw)
    assert isinstance(parsed, list)
    assert parsed
    assert all(isinstance(row, dict) for row in parsed)
    return raw, parsed


def test_fixture_sizes_and_sha256_match_readme() -> None:
    readme = (FIXTURE_DIR / "README.md").read_text()
    for name in (
        "pub_sven_pos1.json",
        "pro_sven.json",
        "pro_antimage.json",
        "pro_axe.json",
        "pro_crystal_maiden.json",
    ):
        raw, _ = _load_fixture(name)
        digest = hashlib.sha256(raw).hexdigest()
        row = next(line for line in readme.splitlines() if f"`{name}`" in line)
        assert f"{len(raw):,}" in row
        assert digest in row


def test_fixtures_are_nonempty_source_arrays_for_sven() -> None:
    _, pub = _load_fixture("pub_sven_pos1.json")
    _, pro = _load_fixture("pro_sven.json")

    assert all(row["hero_id"] == 18 for row in pub)
    assert all(row["hero_id"] == 18 for row in pro)
    assert len(pub[0]["build_data"]["abilities_new"]) == 5
    assert len(pro[0]["recent_matches"]) == 5


def test_pub_and_pro_fixtures_keep_distinct_source_shapes() -> None:
    _, pub = _load_fixture("pub_sven_pos1.json")
    _, pro = _load_fixture("pro_sven.json")

    assert "build_data" in pub[0]
    assert "build_data" not in pro[0]
    assert "recent_matches" in pro[0]
    assert "recent_matches" not in pub[0]


@pytest.mark.parametrize(
    ("name", "hero_id", "zero_count"),
    [
        ("pro_antimage.json", 1, 7),
        ("pro_axe.json", 2, 67),
        ("pro_crystal_maiden.json", 5, 9),
    ],
)
def test_real_pro_zero_id_fixtures_parse_every_match_and_ability_event(
    name: str,
    hero_id: int,
    zero_count: int,
) -> None:
    _, rows = _load_fixture(name)
    before = deepcopy(rows)

    examples = parse_pro_examples(rows, hero_id=hero_id)

    expected_match_count = sum(len(row.get("recent_matches", [])) for row in rows)
    assert len(examples) == expected_match_count
    assert rows == before

    example_index = 0
    for row_index, row in enumerate(rows):
        for match_index, match in enumerate(row.get("recent_matches", [])):
            example = examples[example_index]
            example_index += 1
            assert example.source_path == f"$[{row_index}].recent_matches[{match_index}]"
            source_abilities = match.get("abilities", [])
            assert len(example.ability_timeline) == len(source_abilities)
            for source_event, parsed_event in zip(
                source_abilities,
                example.ability_timeline,
                strict=True,
            ):
                assert parsed_event.ability_id == source_event["ability_id"]
                assert parsed_event.source_fields == source_event
    assert example_index == len(examples)
    assert sum(
        event.ability_id == 0
        for example in examples
        for event in example.ability_timeline
    ) == zero_count
