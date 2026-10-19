"""Small coalesced background batches; persistent outputs contain images only."""

import asyncio
import hashlib
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.vnext.providers.opendota.detail_entities import DetailEntities
from app.vnext.tools.errors import StructuredToolError

from .data import CoverageData
from .heatmap_models import HeatmapImage, HeatmapResult
from .heatmap_render import HeatmapUnavailable, load_calibration, render_batch

_TOKEN = re.compile(r"[0-9a-f]{32}\Z")


@dataclass
class _Batch:
    index: HeatmapResult
    stop: threading.Event = field(default_factory=threading.Event)
    task: asyncio.Task | None = None


class GameHeatmapService:
    def __init__(self, provider, settings, catalog_provider):
        self.provider = provider
        self.settings = settings
        self.catalog_provider = catalog_provider
        self._batches = {}
        self._gate = asyncio.Semaphore(1)
        self._lock = threading.RLock()
        self._closed = False

    def _root(self):
        root = self.settings.directory
        if root.is_symlink():
            raise OSError("Heatmap directory must not be a symlink")
        root.mkdir(parents=True, exist_ok=True)
        return root.resolve()

    def _folder(self, token):
        if not _TOKEN.fullmatch(token):
            raise ValueError("Invalid heatmap batch ID")
        folder = self._root() / token
        if folder.is_symlink():
            raise OSError("Heatmap batch must not be a symlink")
        return folder

    def _save(self, batch):
        folder = self._folder(batch.index.batch_id)
        folder.mkdir(exist_ok=True)
        temporary = folder / "index.tmp"
        temporary.write_text(batch.index.model_dump_json(), encoding="utf-8")
        temporary.replace(folder / "index.json")

    def _delete(self, folder):
        # Only this store's named image/index files; never follow links or recurse.
        root = self._root()
        if folder.parent != root or folder.is_symlink() or not _TOKEN.fullmatch(folder.name):
            return
        for path in folder.iterdir():
            if path.name in {"index.json", "index.tmp"} or re.fullmatch(r"\d+-\d+\.png", path.name):
                path.unlink(missing_ok=True)
        if not any(folder.iterdir()):
            folder.rmdir()

    def _cleanup(self, required_bytes=0):
        now = datetime.now(UTC)
        active = {b.index.batch_id for b in self._batches.values() if b.task and not b.task.done()}
        records = []
        for folder in self._root().iterdir():
            if not folder.is_dir() or folder.is_symlink() or not _TOKEN.fullmatch(folder.name):
                continue
            try:
                index = HeatmapResult.model_validate_json((folder / "index.json").read_text())
                expires = datetime.fromisoformat(index.expires_at)
            except (ValueError, OSError, TypeError):
                if folder.name not in active:
                    self._delete(folder)
                continue
            if expires <= now and folder.name not in active:
                self._delete(folder)
                continue
            size = sum(p.stat().st_size for p in folder.iterdir() if p.is_file())
            records.append((folder, index, expires, size))
        total = sum(r[3] for r in records)
        for folder, _index, _, size in sorted(records, key=lambda r: r[2]):
            if total + required_bytes <= self.settings.max_bytes:
                break
            if folder.name not in active:
                self._delete(folder)
                total -= size
        for game, batch in list(self._batches.items()):
            if (
                batch.index.batch_id not in active
                and not self._folder(batch.index.batch_id).exists()
            ):
                del self._batches[game]

    async def get(self, query):
        with self._lock:
            self._cleanup()
            batch = self._batches.get(query.valve_game_id)
            if batch is None:
                # Read validated image-only indexes after process restart.
                for folder in self._root().iterdir():
                    if (
                        not folder.is_dir()
                        or folder.is_symlink()
                        or not _TOKEN.fullmatch(folder.name)
                    ):
                        continue
                    index = HeatmapResult.model_validate_json((folder / "index.json").read_text())
                    if index.valve_game_id == query.valve_game_id:
                        if index.status in {"queued", "running"}:
                            index.status = "partial" if index.images else "failed"
                            index.reason = "interrupted_by_restart"
                        batch = _Batch(index)
                        self._batches[query.valve_game_id] = batch
                        break
            if query.action == "cancel" and batch is not None:
                batch.stop.set()
                batch.index.status = "cancelled"
                batch.index.reason = "generation_cancelled"
                self._save(batch)
                if batch.task and not batch.task.done():
                    batch.task.cancel()
            elif query.action == "cancel":
                return HeatmapResult(
                    valve_game_id=query.valve_game_id, status="cancelled", reason="no_active_batch"
                )
            retry = query.action == "retry" and batch and (batch.task is None or batch.task.done())
            if batch is not None and batch.index.status == "ready":
                try:
                    _, _, version = load_calibration(
                        self.settings.map_manifest, batch.index.game_version_id
                    )
                except (HeatmapUnavailable, OSError, ValueError, KeyError, TypeError):
                    version = None
                if version != batch.index.map_version:
                    retry = True
                else:
                    present = [
                        image
                        for image in batch.index.images
                        if self.read_image(
                            batch.index.batch_id, image.player_slot, image.time_seconds
                        )
                        is not None
                    ]
                    if len(present) != len(batch.index.images):
                        batch.index.images = present
                        batch.index.total_images = len(present)
                        batch.index.status = "partial"
                        batch.index.reason = "stored_images_missing_or_corrupt"
                        self._save(batch)
            if batch is None or retry:
                if self._closed:
                    raise StructuredToolError("provider_error", "Heatmap service is closed", {})
                if (
                    sum(b.task is not None and not b.task.done() for b in self._batches.values())
                    >= self.settings.max_jobs
                ):
                    raise StructuredToolError("provider_error", "Heatmap queue is full", {})
                if batch is not None:
                    self._delete(self._folder(batch.index.batch_id))
                token = uuid4().hex
                index = HeatmapResult(
                    valve_game_id=query.valve_game_id,
                    status="queued",
                    batch_id=token,
                    expires_at=(
                        datetime.now(UTC) + timedelta(seconds=self.settings.retention_seconds)
                    ).isoformat(),
                )
                batch = _Batch(index)
                self._batches[query.valve_game_id] = batch
                self._save(batch)
                batch.task = asyncio.create_task(self._run(batch))
            result = batch.index.model_copy(deep=True)
            result.total_images = len(result.images)
            result.offset = query.offset
            result.images = result.images[query.offset : query.offset + query.limit]
            result.returned = len(result.images)
            following = query.offset + result.returned
            result.next_offset = following if following < result.total_images else None
            return result

    async def _run(self, batch):
        index = batch.index
        try:
            async with self._gate:
                if batch.stop.is_set():
                    raise asyncio.CancelledError
                index.status = "running"
                self._save(batch)
                entities = DetailEntities(self.catalog_provider())
                labels = CoverageData()

                def metadata(version, expected):
                    index.map_version = version
                    index.expected_images = expected

                def emit(player, cutoff, count, png):
                    with self._lock:
                        if batch.stop.is_set():
                            return
                        self._cleanup(required_bytes=len(png))
                        size = sum(
                            p.stat().st_size for p in self._root().glob("*/*") if p.is_file()
                        )
                        if size + len(png) > self.settings.max_bytes:
                            raise HeatmapUnavailable("image_quota_exceeded")
                        slot = player["playerSlot"]
                        path = self._folder(index.batch_id) / f"{slot}-{cutoff}.png"
                        path.write_bytes(png)
                        hero = entities.by_id(
                            player.get("heroId"),
                            "hero",
                            "heatmap.hero",
                            "players.heroId",
                            labels,
                            required=False,
                        )
                        index.images.append(
                            HeatmapImage(
                                player_slot=slot,
                                account_id=player.get("steamAccountId"),
                                hero=hero,
                                time_seconds=cutoff,
                                image_ref=f"/api/v1/game/heatmaps/assets/{index.batch_id}/{slot}/{cutoff}.png",
                                sha256=hashlib.sha256(png).hexdigest(),
                                bytes=len(png),
                                sample_count=count,
                            )
                        )
                        index.total_images = len(index.images)
                        self._save(batch)

                async def consume(frame, retrieved):
                    index.retrieved_at = retrieved
                    index.game_version_id = frame.get("gameVersionId")
                    work = asyncio.create_task(
                        asyncio.to_thread(
                            render_batch, frame, self.settings, batch.stop, emit, metadata
                        )
                    )
                    try:
                        await asyncio.shield(work)
                    except asyncio.CancelledError:
                        batch.stop.set()
                        await asyncio.gather(work, return_exceptions=True)
                        raise

                await self.provider.consume_positions(index.valve_game_id, consume)
                index.status = "ready" if len(index.images) == index.expected_images else "partial"
                if index.status == "partial":
                    index.reason = "some_player_windows_have_no_samples"
        except asyncio.CancelledError:
            batch.stop.set()
            index.status = "cancelled"
            index.reason = "generation_cancelled"
        except HeatmapUnavailable as exc:
            index.status = "partial" if index.images else "unavailable"
            index.reason = str(exc)
        except StructuredToolError as exc:
            index.status = "partial" if index.images else "failed"
            index.reason = exc.code
        except (OSError, ValueError, KeyError, TypeError):
            index.status = "partial" if index.images else "failed"
            index.reason = "heatmap_generation_failed"
        finally:
            with self._lock:
                self._save(batch)

    def read_image(self, token, slot, cutoff):
        with self._lock:
            try:
                folder = self._folder(token)
                index = HeatmapResult.model_validate_json((folder / "index.json").read_text())
                if datetime.fromisoformat(index.expires_at) <= datetime.now(UTC):
                    return None
                row = next(
                    (r for r in index.images if r.player_slot == slot and r.time_seconds == cutoff),
                    None,
                )
                path = folder / f"{slot}-{cutoff}.png"
                if row is None or path.is_symlink():
                    return None
                payload = path.read_bytes()
                if len(payload) != row.bytes or hashlib.sha256(payload).hexdigest() != row.sha256:
                    return None
                return payload
            except (ValueError, OSError, TypeError):
                return None

    async def aclose(self):
        self._closed = True
        tasks = []
        for batch in self._batches.values():
            if batch.task and not batch.task.done():
                batch.stop.set()
                batch.index.status = "cancelled"
                batch.index.reason = "service_shutdown"
                self._save(batch)
                batch.task.cancel()
                tasks.append(batch.task)
        await asyncio.gather(*tasks, return_exceptions=True)
