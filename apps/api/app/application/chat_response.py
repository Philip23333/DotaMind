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
    else:
        visual_entities = [
            entity
            for entity in visual_entities
            if _is_local_visual_entity(entity)
        ]
    if visual_entities:
        compact["catalog_visual_entities"] = visual_entities
    return compact


def _catalog_visual_entities(tool_results: Any) -> list[dict[str, Any]]:
    entities: dict[str, dict[str, Any]] = {}

    def add(
        record: dict[str, Any],
        *,
        image_key: str,
        kind: str,
        include_generic_names: bool = False,
    ) -> None:
        image_path = record.get(image_key)
        if not isinstance(image_path, str) or _visual_kind_from_path(image_path) != kind:
            return
        name_prefix = kind
        name_values = [
            record.get(f"{name_prefix}_name_zh"),
            record.get(f"{name_prefix}_name_en"),
        ]
        if include_generic_names:
            name_values.extend(
                (
                    record.get("name_zh"),
                    record.get("name_en"),
                    record.get("name"),
                    record.get("acronym"),
                )
            )
        names = [
            value.strip()
            for value in name_values
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
        add(value, image_key="ability_image_path", kind="ability", include_generic_names=True)
        add(value, image_key="team_image_path", kind="team", include_generic_names=True)
        image_path = value.get("image_path")
        if isinstance(image_path, str):
            kind = _visual_kind_from_path(image_path)
            if kind is not None:
                add(value, image_key="image_path", kind=kind, include_generic_names=True)
        for child in value.values():
            visit(child)

    visit(tool_results)
    return list(entities.values())


def _visual_kind_from_path(image_path: str) -> str | None:
    if not image_path.startswith("/api/v1/assets/"):
        return None
    if "/heroes/" in image_path:
        return "hero"
    if "/items/" in image_path:
        return "item"
    if "/abilities/" in image_path:
        return "ability"
    if "/esports/teams/" in image_path:
        return "team"
    return None


def _is_local_visual_entity(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    image_path = value.get("imagePath")
    kind = value.get("kind")
    return (
        isinstance(image_path, str)
        and isinstance(kind, str)
        and _visual_kind_from_path(image_path) == kind
    )
