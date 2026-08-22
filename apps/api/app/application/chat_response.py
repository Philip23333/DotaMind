"""Compact public responses retained by durable Chat turns."""

from __future__ import annotations

from typing import Any

_CHAT_RESPONSE_FIELDS = (
    "status",
    "reason",
    "error_code",
    "answer",
    "runtime",
)


def compact_chat_response(response: dict[str, Any]) -> dict[str, Any]:
    """Keep only chat presentation data, plus its small Catalog visual projection."""

    compact = {key: response[key] for key in _CHAT_RESPONSE_FIELDS if key in response}
    visual_entities = response.get("catalog_visual_entities")
    if not isinstance(visual_entities, list):
        visual_entities = _catalog_visual_entities(response.get("tool_results"))
    if visual_entities:
        compact["catalog_visual_entities"] = visual_entities
    return compact


def _catalog_visual_entities(tool_results: Any) -> list[dict[str, Any]]:
    entities: dict[str, dict[str, Any]] = {}

    def add(record: dict[str, Any], *, image_key: str, kind: str) -> None:
        image_path = record.get(image_key)
        if not isinstance(image_path, str) or not image_path.startswith("/api/v1/assets/dota/"):
            return
        name_prefix = "hero" if kind == "hero" else "item"
        names = [
            value.strip()
            for value in (
                record.get(f"{name_prefix}_name_zh"),
                record.get(f"{name_prefix}_name_en"),
                record.get("name_zh"),
                record.get("name_en"),
                record.get("name"),
            )
            if isinstance(value, str) and value.strip()
        ]
        if not names:
            return
        existing = entities.setdefault(
            image_path,
            {
                "kind": kind,
                "imagePath": image_path,
                "label": names[0],
                "names": [],
            },
        )
        existing["names"] = list(dict.fromkeys([*existing["names"], *names]))

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        add(value, image_key="hero_image_path", kind="hero")
        add(value, image_key="item_image_path", kind="item")
        image_path = value.get("image_path")
        if isinstance(image_path, str):
            kind = "item" if "/items/" in image_path else "hero"
            add(value, image_key="image_path", kind=kind)
        for child in value.values():
            visit(child)

    visit(tool_results)
    return list(entities.values())
