"""Bounded image rendering from transient samples and explicitly calibrated maps."""

import hashlib
import io
import json
import math
from pathlib import Path

from PIL import Image, ImageFilter


class HeatmapUnavailable(ValueError):
    pass


def load_calibration(manifest_path: Path | None, game_version):
    if manifest_path is None:
        raise HeatmapUnavailable("map_not_calibrated")
    manifest = json.loads(manifest_path.read_text())
    entries = [e for e in manifest["maps"] if game_version in e["game_version_ids"]]
    if len(entries) != 1:
        raise HeatmapUnavailable("map_not_calibrated_for_game_version")
    entry = entries[0]
    if entry.get("verified") is not True or not entry.get("evidence"):
        raise HeatmapUnavailable("map_calibration_unverified")
    root = manifest_path.parent.resolve()
    image_path = (root / entry["image"]).resolve()
    if not image_path.is_relative_to(root) or image_path.is_symlink():
        raise HeatmapUnavailable("invalid_map_asset")
    raw = image_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise HeatmapUnavailable("map_asset_hash_mismatch")
    for axis in ("x", "y"):
        a, b = entry[f"{axis}_min"], entry[f"{axis}_max"]
        if (
            type(a) not in (int, float)
            or type(b) not in (int, float)
            or not math.isfinite(a + b)
            or a >= b
        ):
            raise HeatmapUnavailable("invalid_map_calibration")
    if type(entry.get("flip_y")) is not bool:
        raise HeatmapUnavailable("invalid_map_orientation")
    with Image.open(io.BytesIO(raw)) as image:
        if image.width != image.height or image.width > 8192:
            raise HeatmapUnavailable("invalid_map_dimensions")
        background = image.convert("RGB").resize((256, 256))
    version = hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()
    return entry, background, version


def validate_frame(frame, settings):
    duration = frame.get("durationSeconds")
    if type(duration) is not int or not 0 < duration <= settings.max_duration_seconds:
        raise HeatmapUnavailable("unsupported_game_duration")
    players = frame.get("players")
    if not isinstance(players, list) or len(players) != 10:
        raise HeatmapUnavailable("ten_players_required")
    slots = [p.get("playerSlot") for p in players]
    if any(type(s) is not int for s in slots) or set(slots) != {
        0,
        1,
        2,
        3,
        4,
        128,
        129,
        130,
        131,
        132,
    }:
        raise HeatmapUnavailable("ambiguous_player_slots")
    if type(frame.get("gameVersionId")) is not int:
        raise HeatmapUnavailable("unknown_game_version")
    count = 0
    for p in players:
        if type(p.get("heroId")) is not int or p["heroId"] <= 0:
            raise HeatmapUnavailable("unknown_player_hero")
        points = (p.get("playbackData") or {}).get("playerUpdatePositionEvents")
        if not isinstance(points, list):
            raise HeatmapUnavailable("position_series_unavailable")
        count += len(points)
        if count > settings.max_points:
            raise HeatmapUnavailable("position_limit_exceeded")
        for row in points:
            if not isinstance(row, dict) or any(
                type(row.get(k)) not in (int, float) or not math.isfinite(row[k])
                for k in ("time", "x", "y")
            ):
                raise HeatmapUnavailable("invalid_position_sample")
    cutoffs = list(range(300, duration + 1, 300))
    if not cutoffs or cutoffs[-1] != duration:
        cutoffs.append(duration)
    return players, cutoffs


def render_batch(frame, settings, stop, emit, metadata):
    """Runs on one background thread; emit only PNG bytes and small metadata."""
    players, cutoffs = validate_frame(frame, settings)
    calibration, background, version = load_calibration(
        settings.map_manifest, frame.get("gameVersionId")
    )
    metadata(version, len(players) * len(cutoffs))
    prepared = []
    maximum = 0
    for player in players:
        points = []
        final_grid = [0] * 4096
        for row in player["playbackData"]["playerUpdatePositionEvents"]:
            if stop.is_set():
                return
            if not 0 <= row["time"] <= cutoffs[-1]:
                continue
            x = (row["x"] - calibration["x_min"]) / (calibration["x_max"] - calibration["x_min"])
            y = (row["y"] - calibration["y_min"]) / (calibration["y_max"] - calibration["y_min"])
            if not 0 <= x <= 1 or not 0 <= y <= 1:
                raise HeatmapUnavailable("position_outside_calibrated_map")
            if calibration["flip_y"]:
                y = 1 - y
            cell = min(63, int(y * 64)) * 64 + min(63, int(x * 64))
            points.append((row["time"], cell))
            final_grid[cell] += 1
        points.sort()
        maximum = max(maximum, max(final_grid))
        prepared.append((player, points))
    scale = math.sqrt(maximum or 1)
    for player, points in prepared:
        grid = [0] * 4096
        index = 0
        for cutoff in cutoffs:
            if stop.is_set():
                return
            while index < len(points) and points[index][0] <= cutoff:
                grid[points[index][1]] += 1
                index += 1
            if index == 0:
                continue  # no sampled interval: do not publish a fake empty heatmap
            density = Image.frombytes(
                "L", (64, 64), bytes(int(255 * math.sqrt(n) / scale) for n in grid)
            )
            density = density.filter(ImageFilter.GaussianBlur(1.5)).resize(
                (256, 256), Image.Resampling.BILINEAR
            )
            red = density.point([min(255, int(v * 3)) for v in range(256)])
            green = density.point([min(255, max(0, int(2.5 * v - 100))) for v in range(256)])
            blue = density.point([max(0, 180 - int(3 * v)) for v in range(256)])
            heat = Image.merge("RGB", (red, green, blue))
            alpha = density.point([min(210, v * 2) for v in range(256)])
            image = Image.composite(heat, background, alpha)
            out = io.BytesIO()
            image.save(out, format="PNG")
            emit(player, cutoff, index, out.getvalue())
