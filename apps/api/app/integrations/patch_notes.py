"""
Patch Notes reader.

Reads the hand-curated JSON files in app/data/patches/ and provides
structured access to hero/item changes and polarity (buff/nerf).
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PATCHES_DIR = Path(__file__).resolve().parent.parent / "data" / "patches"

# In-memory cache: patch_id -> parsed data
_cache: dict[str, dict[str, Any]] = {}


def _normalize_patch_id(patch: str) -> str:
    """'7.41d' -> '7_41d', 'latest' -> latest file."""
    return patch.replace(".", "_")


def _find_latest() -> Path | None:
    """Find the most recent patch JSON by filename."""
    files = sorted(_PATCHES_DIR.glob("*.json"), reverse=True)
    return files[0] if files else None


def load_patch(patch: str = "latest") -> dict[str, Any] | None:
    """
    Load a patch JSON file. Returns the parsed dict or None if not found.

    Args:
        patch: patch version like "7.41d" or "latest"
    """
    if patch in _cache:
        return _cache[patch]

    if patch == "latest":
        path = _find_latest()
    else:
        normalized = _normalize_patch_id(patch)
        path = _PATCHES_DIR / f"{normalized}.json"
        if not path.exists():
            path = _find_latest()

    if path is None or not path.exists():
        logger.warning("No patch file found for %s", patch)
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _cache[patch] = data
        return data
    except Exception as exc:
        logger.error("Failed to parse patch file %s: %s", path, exc)
        return None


def get_hero_changes(patch: str = "latest") -> dict[str, list[dict[str, Any]]]:
    """
    Returns {hero_name: [changes...]} for all hero changes in a patch.

    Each change has at least: target, field, polarity, raw
    """
    data = load_patch(patch)
    if data is None:
        return {}

    result: dict[str, list[dict[str, Any]]] = {}
    for change in data.get("changes", []):
        if change.get("target_type") == "hero":
            hero = change["target"]
            result.setdefault(hero, []).append(change)
    return result


def get_item_changes(patch: str = "latest") -> list[dict[str, Any]]:
    """Returns all item/neutral_item/enchantment changes."""
    data = load_patch(patch)
    if data is None:
        return []

    return [
        c
        for c in data.get("changes", [])
        if c.get("target_type") in ("item", "neutral_item", "enchantment")
    ]


def compute_hero_patch_score(
    patch: str = "latest",
    *,
    neutral_score: float = 0.5,
    change_delta: float = 0.15,
) -> dict[str, float]:
    """
    Compute a patch impact score per hero based on buff/nerf count.

    Score range is clamped to 0.0-1.0 around the configured neutral score.

    Logic:
      - Each buff adds change_delta, each nerf subtracts change_delta
      - Clamped to [0.0, 1.0]
    """
    hero_changes = get_hero_changes(patch)
    scores: dict[str, float] = {}

    for hero, changes in hero_changes.items():
        delta = 0.0
        for c in changes:
            polarity = c.get("polarity", "neutral")
            if polarity == "buff":
                delta += change_delta
            elif polarity == "nerf":
                delta -= change_delta
        scores[hero] = max(0.0, min(1.0, neutral_score + delta))

    return scores
