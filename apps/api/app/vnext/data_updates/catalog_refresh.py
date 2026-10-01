"""Refresh and atomically publish the persistent Valve catalog snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from app.integrations.valve import game_data_sync
from app.integrations.valve.fetch_session import ValveFetchSession
from app.vnext.data_updates.catalog_store import (
    CatalogSnapshotStore,
    CatalogStoreError,
)

CatalogRefreshAction = Literal["updated", "skipped"]
CatalogRefreshReason = Literal[
    "patch_changed",
    "patch_unchanged",
    "forced",
    "missing",
    "invalid_local",
]


@dataclass(frozen=True)
class CatalogRefreshReport:
    action: CatalogRefreshAction
    reason: CatalogRefreshReason
    previous_patch: str | None
    target_patch: str
    revision: str


def refresh_catalog(
    *,
    data_root: Path,
    session: ValveFetchSession,
    workers: int = 8,
    force: bool = False,
) -> CatalogRefreshReport:
    """Check Valve's latest patch and publish a complete catalog when needed."""

    if type(workers) is not int or not 1 <= workers <= 16:
        raise ValueError("workers must be an integer between 1 and 16")
    if type(force) is not bool:
        raise ValueError("force must be a boolean")

    store = CatalogSnapshotStore(Path(data_root))
    current = None
    local_state: Literal["missing", "invalid", "valid"]
    try:
        current = store.load_current()
    except CatalogStoreError as exc:
        if exc.reason not in {"invalid_pointer", "invalid_snapshot"}:
            raise
        local_state = "invalid"
    else:
        local_state = "missing" if current is None else "valid"

    # A failed remote check is an operation failure, never evidence to skip.
    target_patch = game_data_sync._latest_patch(session)
    previous_patch = (
        current.repository.manifest.patch if current is not None else None
    )

    if local_state == "missing":
        reason: CatalogRefreshReason = "missing"
    elif local_state == "invalid":
        reason = "invalid_local"
    elif force:
        reason = "forced"
    elif previous_patch != target_patch:
        reason = "patch_changed"
    else:
        assert current is not None
        return CatalogRefreshReport(
            action="skipped",
            reason="patch_unchanged",
            previous_patch=previous_patch,
            target_patch=target_patch,
            revision=current.revision,
        )

    bundle = game_data_sync._build_catalog_snapshot(
        session,
        target_patch,
        workers=workers,
    )
    payloads = game_data_sync.serialize_catalog_bundle(bundle)

    catalog_directory = Path(data_root) / "catalog"
    catalog_directory.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".refresh-catalog-", dir=catalog_directory) as temp_name:
        source_directory = Path(temp_name)
        for filename, payload in payloads.items():
            (source_directory / filename).write_bytes(payload)
        snapshot = store.publish_from_directory(source_directory)

    return CatalogRefreshReport(
        action="updated",
        reason=reason,
        previous_patch=previous_patch,
        target_patch=target_patch,
        revision=snapshot.revision,
    )


__all__ = ["CatalogRefreshReport", "refresh_catalog"]
