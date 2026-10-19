"""Image-only heatmap contracts; no model or index can contain positions."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field, StrictInt, StrictStr

from .data import EntityData, _Data, _TimedData


@dataclass(frozen=True)
class HeatmapSettings:
    directory: Path
    map_manifest: Path | None = None
    retention_seconds: int = 7 * 24 * 3600
    max_bytes: int = 512 * 1024 * 1024
    max_jobs: int = 8
    max_points: int = 500000
    max_duration_seconds: int = 4 * 3600

    def __post_init__(self):
        if not self.directory.is_absolute():
            raise ValueError("Heatmap directory must be absolute")
        if self.map_manifest is not None and not self.map_manifest.is_absolute():
            raise ValueError("Heatmap manifest must be absolute")
        for key in (
            "retention_seconds",
            "max_bytes",
            "max_jobs",
            "max_points",
            "max_duration_seconds",
        ):
            if type(getattr(self, key)) is not int or getattr(self, key) <= 0:
                raise ValueError(f"Heatmap {key} must be a positive integer")


class HeatmapInput(_Data):
    valve_game_id: StrictInt = Field(gt=0)
    action: Literal["get", "retry", "cancel"] = "get"
    offset: StrictInt = Field(default=0, ge=0)
    limit: StrictInt = Field(default=20, ge=1, le=30)


class HeatmapImage(_TimedData):
    player_slot: StrictInt
    account_id: StrictInt | None = None
    hero: EntityData | None = None
    start_seconds: Literal[0] = 0
    time_seconds: StrictInt
    image_ref: StrictStr
    width: Literal[256] = 256
    height: Literal[256] = 256
    sha256: StrictStr
    bytes: StrictInt
    sample_count: StrictInt


class HeatmapResult(_Data):
    valve_game_id: StrictInt
    status: Literal["queued", "running", "ready", "partial", "failed", "cancelled", "unavailable"]
    batch_id: str | None = None
    reason: str | None = None
    source: Literal["stratz"] = "stratz"
    retrieved_at: str | None = None
    expires_at: str | None = None
    game_version_id: int | None = None
    map_version: str | None = None
    render_version: Literal["sample-density-v1"] = "sample-density-v1"
    density_semantics: str = (
        "Cumulative recorded-position sample count, shared same-game colour scale; "
        "not dwell time. Source positions may include dead heroes."
    )
    expected_images: int | None = None
    total_images: int = 0
    offset: int = 0
    returned: int = 0
    next_offset: int | None = None
    images: list[HeatmapImage] = Field(default_factory=list)
