from collections import Counter
from typing import Any

from pydantic import BaseModel, Field

from app.agentic.models import ToolSource
from app.agentic.registry import ToolDefinition, ToolRegistry
from app.integrations.patch_notes import get_item_changes, load_patch


class PatchRecordsInput(BaseModel):
    patch: str = "latest"


class PatchHeroChangesInput(BaseModel):
    patch: str = "latest"
    hero: str | None = Field(default=None, min_length=1)


class PatchItemChangesInput(BaseModel):
    patch: str = "latest"


def register_patch_tools(registry: ToolRegistry) -> None:
    source = ToolSource(
        name="Local patch records",
        kind="local_json",
        url=None,
        status="live",
    )
    registry.register(
        ToolDefinition(
            name="patch.get_records",
            description="Return local Dota 2 patch records from app/data/patches.",
            input_model=PatchRecordsInput,
            handler=_get_records,
            source=source,
            metadata={"game": "dota2", "domain": "patch"},
        )
    )
    registry.register(
        ToolDefinition(
            name="patch.hero_changes",
            description=(
                "Return local Dota 2 hero changes for a patch, optionally "
                "filtered by hero."
            ),
            input_model=PatchHeroChangesInput,
            handler=_hero_changes,
            source=source,
            metadata={"game": "dota2", "domain": "patch"},
        )
    )
    registry.register(
        ToolDefinition(
            name="patch.item_changes",
            description=(
                "Return local Dota 2 item, neutral item, and enchantment "
                "changes for a patch."
            ),
            input_model=PatchItemChangesInput,
            handler=_item_changes,
            source=source,
            metadata={"game": "dota2", "domain": "patch"},
        )
    )


def _get_records(args: PatchRecordsInput) -> dict[str, Any]:
    data = _load_required_patch(args.patch)
    changes = data.get("changes", [])
    counts = _polarity_counts(changes)
    return {
        "patch": data.get("patch", args.patch),
        "released_at": data.get("released_at"),
        "changes": changes,
        "change_count": len(changes),
        "buff_count": counts["buff"],
        "nerf_count": counts["nerf"],
    }


def _hero_changes(args: PatchHeroChangesInput) -> dict[str, Any]:
    data = _load_required_patch(args.patch)
    changes = [
        change
        for change in data.get("changes", [])
        if change.get("target_type") == "hero"
    ]
    if args.hero:
        wanted = _key(args.hero)
        changes = [change for change in changes if _key(change.get("target")) == wanted]
    counts = _polarity_counts(changes)
    return {
        "patch": data.get("patch", args.patch),
        "hero": args.hero,
        "changes": changes,
        "hero_count": len({change.get("target") for change in changes}),
        "change_count": len(changes),
        "buff_count": counts["buff"],
        "nerf_count": counts["nerf"],
    }


def _item_changes(args: PatchItemChangesInput) -> dict[str, Any]:
    data = _load_required_patch(args.patch)
    changes = get_item_changes(args.patch)
    counts = _polarity_counts(changes)
    return {
        "patch": data.get("patch", args.patch),
        "changes": changes,
        "change_count": len(changes),
        "buff_count": counts["buff"],
        "nerf_count": counts["nerf"],
        "target_type_counts": dict(Counter(change.get("target_type") for change in changes)),
    }


def _load_required_patch(patch: str) -> dict[str, Any]:
    data = load_patch(patch)
    if data is None:
        raise ValueError(f"patch records not found: {patch}")
    if patch != "latest" and _key(data.get("patch")) != _key(patch):
        raise ValueError(f"patch records not found: {patch}")
    return data


def _polarity_counts(changes: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str(change.get("polarity") or "neutral") for change in changes)


def _key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")
