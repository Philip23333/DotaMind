from collections import Counter
from typing import Any

from pydantic import BaseModel, Field

from app.agentic.evidence import EvidenceItem
from app.agentic.models import QueryContext, ToolResult, ToolSource
from app.agentic.tools import ArgContract, ToolDefinition, ToolRegistry
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
            evidence_extractor=patch_records_evidence,
            evidence_kinds=("patch_records", "patch_buff_count", "patch_nerf_count"),
            mandatory_evidence=("patch_records",),
            arg_contracts={
                "patch": ArgContract(description="Patch version, or latest."),
            },
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
            evidence_extractor=patch_hero_changes_evidence,
            evidence_kinds=("hero_patch_changes",),
            mandatory_evidence=("hero_patch_changes",),
            arg_contracts={
                "patch": ArgContract(description="Patch version, or latest."),
                "hero": ArgContract(description="Optional hero name filter."),
            },
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
            evidence_extractor=patch_item_changes_evidence,
            evidence_kinds=("item_patch_changes",),
            mandatory_evidence=("item_patch_changes",),
            arg_contracts={
                "patch": ArgContract(description="Patch version, or latest."),
            },
            metadata={"game": "dota2", "domain": "patch"},
        )
    )


def patch_records_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    return [
        EvidenceItem(
            id=f"{result.tool_call_id}:patch_records:{data.get('patch')}",
            kind="patch_records",
            subject=str(data.get("patch") or "patch"),
            value={
                "patch": data.get("patch"),
                "released_at": data.get("released_at"),
                "change_count": data.get("change_count"),
                "buff_count": data.get("buff_count"),
                "nerf_count": data.get("nerf_count"),
            },
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        ),
        EvidenceItem(
            id=f"{result.tool_call_id}:patch_buff_count:{data.get('patch')}",
            kind="patch_buff_count",
            subject=str(data.get("patch") or "patch"),
            value={"buff_count": data.get("buff_count")},
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        ),
        EvidenceItem(
            id=f"{result.tool_call_id}:patch_nerf_count:{data.get('patch')}",
            kind="patch_nerf_count",
            subject=str(data.get("patch") or "patch"),
            value={"nerf_count": data.get("nerf_count")},
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        ),
    ]


def patch_hero_changes_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    return [
        EvidenceItem(
            id=f"{result.tool_call_id}:hero_patch_changes:{data.get('patch')}",
            kind="hero_patch_changes",
            subject=str(data.get("hero") or "all heroes"),
            value={
                "patch": data.get("patch"),
                "hero": data.get("hero"),
                "hero_count": data.get("hero_count"),
                "change_count": data.get("change_count"),
                "buff_count": data.get("buff_count"),
                "nerf_count": data.get("nerf_count"),
                "changes": data.get("changes", []),
            },
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        )
    ]


def patch_item_changes_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    return [
        EvidenceItem(
            id=f"{result.tool_call_id}:item_patch_changes:{data.get('patch')}",
            kind="item_patch_changes",
            subject="items",
            value={
                "patch": data.get("patch"),
                "change_count": data.get("change_count"),
                "buff_count": data.get("buff_count"),
                "nerf_count": data.get("nerf_count"),
                "target_type_counts": data.get("target_type_counts", {}),
                "changes": data.get("changes", []),
            },
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        )
    ]


def _get_records(args: PatchRecordsInput, context: QueryContext) -> dict[str, Any]:
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


def _hero_changes(args: PatchHeroChangesInput, context: QueryContext) -> dict[str, Any]:
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


def _item_changes(args: PatchItemChangesInput, context: QueryContext) -> dict[str, Any]:
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
