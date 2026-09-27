import hashlib
import json
from pathlib import Path

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
    for name in ("pub_sven_pos1.json", "pro_sven.json"):
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
