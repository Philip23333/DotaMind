"""Image-only batches use calibrated coordinates, bounded resources and exact windows."""

import asyncio
import hashlib
import json
import threading
from copy import deepcopy

import pytest
from PIL import Image

from app.integrations.valve.catalog_repository import DotaCatalogRepository
from app.vnext.capabilities.game.heatmap_models import HeatmapInput, HeatmapSettings
from app.vnext.capabilities.game.heatmap_render import HeatmapUnavailable, render_batch
from app.vnext.capabilities.game.heatmaps import GameHeatmapService
from app.vnext.providers.stratz.heatmaps import StratzHeatmapAdapter


def frame(duration=610):
    return {
        "id": 8960991322,
        "durationSeconds": duration,
        "gameVersionId": 189,
        "players": [
            {
                "playerSlot": slot,
                "heroId": 1,
                "steamAccountId": slot + 100,
                "playbackData": {
                    "playerUpdatePositionEvents": [
                        {"time": -10, "x": 50, "y": 50},
                        {"time": 0, "x": 50, "y": 50},
                        {"time": 301, "x": 50, "y": 50},
                        {"time": 601, "x": 60, "y": 60},
                    ]
                },
            }
            for slot in [0, 1, 2, 3, 4, 128, 129, 130, 131, 132]
        ],
    }


def settings(tmp_path, **kw):
    asset = tmp_path / "map.png"
    Image.new("RGB", (256, 256), (30, 40, 30)).save(asset)
    manifest = tmp_path / "maps.json"
    manifest.write_text(
        json.dumps(
            {
                "maps": [
                    {
                        "game_version_ids": [189],
                        "verified": True,
                        "evidence": "Synthetic test calibration only, never a production map",
                        "image": "map.png",
                        "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
                        "x_min": 0,
                        "x_max": 100,
                        "y_min": 0,
                        "y_max": 100,
                        "flip_y": True,
                    }
                ]
            }
        )
    )
    return HeatmapSettings(directory=tmp_path / "outputs", map_manifest=manifest, **kw)


class Provider:
    def __init__(self, source=None):
        self.calls = 0
        self.source = source or frame()

    async def consume_positions(self, game, consumer):
        self.calls += 1
        return await consumer(deepcopy(self.source), "2026-10-19T00:00:00+00:00")


def test_renderer_cumulative_windows_include_final_once_and_ignore_pregame(tmp_path):
    output = []
    metadata = []
    render_batch(
        frame(),
        settings(tmp_path),
        threading.Event(),
        lambda player, time, count, png: output.append((player["playerSlot"], time, count, png)),
        lambda version, expected: metadata.append((version, expected)),
    )
    assert len(output) == 30 and metadata[0][1] == 30
    assert [(t, count) for slot, t, count, _ in output if slot == 0] == [
        (300, 1),
        (600, 2),
        (610, 3),
    ]
    import io

    assert Image.open(io.BytesIO(output[0][3])).size == (256, 256)
    output.clear()
    render_batch(
        frame(600),
        settings(tmp_path),
        threading.Event(),
        lambda *args: output.append(args),
        lambda *_: None,
    )
    assert len(output) == 20


def test_no_unknown_map_or_out_of_bounds_sample_is_published(tmp_path):
    s = settings(tmp_path)
    raw = frame()
    raw["gameVersionId"] = 999
    with pytest.raises(HeatmapUnavailable, match="map_not_calibrated"):
        render_batch(
            raw, s, threading.Event(), lambda *_: pytest.fail("unexpected image"), lambda *_: None
        )
    raw = frame()
    raw["players"][0]["playbackData"]["playerUpdatePositionEvents"][1]["x"] = 101
    with pytest.raises(HeatmapUnavailable, match="outside_calibrated"):
        render_batch(
            raw, s, threading.Event(), lambda *_: pytest.fail("unexpected image"), lambda *_: None
        )


def test_background_reuse_pagination_integrity_and_no_raw_files(tmp_path):
    async def run():
        p = Provider()
        s = settings(tmp_path)
        service = GameHeatmapService(p, s, DotaCatalogRepository.load_default)
        first = await service.get(HeatmapInput(valve_game_id=8960991322))
        again = await service.get(HeatmapInput(valve_game_id=8960991322))
        assert first.batch_id == again.batch_id and first.status == "queued"
        await service._batches[8960991322].task
        ready = await service.get(HeatmapInput(valve_game_id=8960991322, limit=20))
        assert ready.status == "ready" and ready.total_images == 30 and ready.next_offset == 20
        page = await service.get(HeatmapInput(valve_game_id=8960991322, offset=20))
        assert page.returned == 10 and page.next_offset is None and p.calls == 1
        row = ready.images[0]
        assert service.read_image(ready.batch_id, row.player_slot, row.time_seconds).startswith(
            b"\x89PNG"
        )
        assert service.read_image("../escape", 0, 300) is None
        saved = list(s.directory.rglob("*"))
        assert all(path.suffix in {".json", ".png"} for path in saved if path.is_file())
        text = "".join(path.read_text() for path in saved if path.suffix == ".json")
        assert not any(
            key in text
            for key in ["playerUpdatePositionEvents", '"x":', '"y":', "grid", "trajectory"]
        )
        await service.aclose()
        recovered = GameHeatmapService(p, s, DotaCatalogRepository.load_default)
        assert (
            await recovered.get(HeatmapInput(valve_game_id=8960991322))
        ).batch_id == ready.batch_id
        assert p.calls == 1
        await recovered.aclose()

    asyncio.run(run())


def test_cancel_before_first_worker_turn_does_not_leave_queued_job(tmp_path):
    async def run():
        p = Provider()
        service = GameHeatmapService(p, settings(tmp_path), DotaCatalogRepository.load_default)
        await service.get(HeatmapInput(valve_game_id=8960991322))
        result = await service.get(HeatmapInput(valve_game_id=8960991322, action="cancel"))
        assert result.status == "cancelled"
        await service.aclose()
        assert p.calls == 0

    asyncio.run(run())


def test_quota_and_expiry_preserve_honest_status(tmp_path):
    async def run():
        s = settings(tmp_path, max_bytes=3000)
        service = GameHeatmapService(Provider(), s, DotaCatalogRepository.load_default)
        await service.get(HeatmapInput(valve_game_id=8960991322))
        await service._batches[8960991322].task
        result = await service.get(HeatmapInput(valve_game_id=8960991322))
        assert (
            result.status in {"partial", "unavailable"} and result.reason == "image_quota_exceeded"
        )
        batch = service._batches[8960991322]
        batch.index.expires_at = "2000-01-01T00:00:00+00:00"
        service._save(batch)
        token = batch.index.batch_id
        assert service.read_image(token, 0, 300) is None
        service._cleanup()
        assert not (s.directory / token).exists()
        await service.aclose()

    asyncio.run(run())


def test_adapter_uses_no_source_cache_and_clears_transient_response():
    class Client:
        def __init__(self):
            self.payload = {"data": {"match": frame()}}

        async def graphql(self, query, variables):
            return self.payload

    async def run():
        c = Client()
        adapter = StratzHeatmapAdapter(c)

        async def consume(raw, stamp):
            assert raw["id"] == 8960991322
            return {"images": []}

        assert await adapter.consume_positions(8960991322, consume) == {"images": []}
        assert c.payload == {}

    asyncio.run(run())


def test_failed_index_write_does_not_publish_an_unreadable_image(tmp_path):
    async def run():
        service = GameHeatmapService(
            Provider(), settings(tmp_path), DotaCatalogRepository.load_default
        )
        save = service._save
        calls = 0

        def fail_on_image(batch):
            nonlocal calls
            calls += 1
            if calls >= 3:
                raise OSError("test storage failure")
            save(batch)

        service._save = fail_on_image
        await service.get(HeatmapInput(valve_game_id=8960991322))
        batch = service._batches[8960991322]
        await batch.task
        assert batch.index.status == "failed" and batch.index.reason == "heatmap_storage_failed"
        assert batch.index.images == []
        assert service.read_image(batch.index.batch_id, 0, 300) is None
        await service.aclose()

    asyncio.run(run())
