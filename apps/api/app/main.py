import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.v1.chat_routes import router as chat_router
from app.api.v1.chat_run_routes import router as chat_run_router
from app.api.v1.routes import router as v1_router
from app.api.v1.vnext_chat_routes import router as vnext_chat_router
from app.application.background_run_manager import BackgroundRunManager
from app.application.chat_run_executor import ChatRunExecutor
from app.application.chat_run_runtime import ChatRunRuntime
from app.application.conversation_memory import ConversationMemoryService
from app.application.postgres_chat_repository import PostgresChatRepository
from app.application.postgres_chat_run_repository import PostgresChatRunRepository
from app.application.redis_run_event_bus import RedisRunEventBus
from app.application.redis_session_store import RedisSessionStore
from app.application.run_recovery import RunStaleSweeper
from app.application.session_store_factory import build_session_store
from app.core.config import get_policy, get_settings
from app.persistence.database import (
    close_database,
    create_database_resources,
    ping_database,
)
from app.vnext.artifacts import RedisArtifactStore
from app.vnext.composition import VNextSettings, build_vnext_runtime, build_vnext_services
from app.vnext.product import (
    ConversationContextBuilder,
    DotaVisualEntityEnricher,
    VNextChatService,
)

settings = get_settings()
PLAN_CONSOLE_PATH = Path(__file__).parent / "resources" / "plan_console.html"
CATALOG_IMAGE_DIR = Path(__file__).parent / "data" / "catalog" / "images"
ESPORTS_ASSET_DIR = Path(__file__).parent / "data" / "esports"


class PipeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        millis = int(record.msecs)
        module_name = record.name.rsplit(".", 1)[-1]
        message = record.getMessage()
        return f"{timestamp}.{millis:03d} | {record.levelname:<8} | [{module_name}] {message}"


class QueryStringRedactionFilter(logging.Filter):
    """Remove URL query strings from HTTP client log arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "httpx" or not isinstance(record.args, tuple):
            return True
        record.args = tuple(self._without_query_string(value) for value in record.args)
        return True

    @staticmethod
    def _without_query_string(value: object) -> object:
        rendered = str(value)
        if rendered.startswith(("http://", "https://")) and "?" in rendered:
            return rendered.split("?", 1)[0]
        return value


logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
for handler in logging.getLogger().handlers:
    handler.addFilter(QueryStringRedactionFilter())
    handler.setFormatter(PipeFormatter())

@asynccontextmanager
async def lifespan(app: FastAPI):
    database = create_database_resources(settings.database_url)
    await ping_database(database.engine)
    store = build_session_store(settings, get_policy())
    if isinstance(store, RedisSessionStore):
        await store.ping()
    from app.application.plan_service import PlanService

    app.state.chat_repository = PostgresChatRepository(database.session_factory)
    vnext_redis = None
    artifact_store = None
    if settings.redis_url:
        from redis.asyncio import from_url

        vnext_redis = from_url(settings.redis_url, decode_responses=True)
        await vnext_redis.ping()
        artifact_store = RedisArtifactStore(
            vnext_redis,
            ttl_seconds=VNextSettings.from_env().artifact_ttl_seconds,
        )
    vnext_services = build_vnext_services(
        VNextSettings.from_env(), artifact_store=artifact_store
    )
    app.state.vnext_services = vnext_services
    app.state.vnext_runtime = build_vnext_runtime(services=vnext_services)
    app.state.vnext_chat_service = VNextChatService(
        app.state.chat_repository,
        app.state.vnext_runtime,
        ConversationContextBuilder(),
        DotaVisualEntityEnricher(),
    )
    app.state.chat_run_repository = PostgresChatRunRepository(database.session_factory)
    app.state.session_store = store
    app.state.conversation_memory = ConversationMemoryService(
        chat_repository=app.state.chat_repository,
        session_store=store,
        max_chars=get_policy().conversation.recent_dialogue_max_chars,
    )
    app.state.plan_service = PlanService()
    run_event_bus = None
    run_manager = None
    run_sweeper = None
    if settings.redis_url:
        run_event_bus = RedisRunEventBus(redis_url=settings.redis_url)
        await run_event_bus.ping()
        worker_id = str(uuid4())

        async def mark_shutdown_interrupted(run_id):
            try:
                await app.state.chat_run_repository.mark_interrupted(
                    run_id=run_id,
                    error_code="worker_shutdown",
                    worker_id=worker_id,
                )
            except Exception:
                return

        run_manager = BackgroundRunManager(
            max_concurrent_runs=settings.max_concurrent_chat_runs,
            worker_id=worker_id,
            on_shutdown=mark_shutdown_interrupted,
            cancel_subscriber=run_event_bus.subscribe_cancellations,
        )
        executor = ChatRunExecutor(
            runner=app.state.plan_service.runner,
            run_repository=app.state.chat_run_repository,
            chat_repository=app.state.chat_repository,
            session_store=store,
            memory_service=app.state.conversation_memory,
            event_bus=run_event_bus,
            worker_id=worker_id,
            history_lookup_max_turns=get_policy().conversation.history_lookup_max_turns,
            history_lookup_max_chars=get_policy().conversation.history_lookup_max_chars,
            build_turn=app.state.plan_service._build_turn,
            build_response=lambda state, session_id: app.state.plan_service._public_response(
                state,
                session_id=session_id,
            ),
            heartbeat_interval_seconds=settings.run_heartbeat_seconds,
        )
        app.state.chat_run_runtime = ChatRunRuntime(
            repository=app.state.chat_run_repository,
            manager=run_manager,
            executor=executor,
            event_bus=run_event_bus,
        )
        await run_manager.start()
        run_sweeper = RunStaleSweeper(
            repository=app.state.chat_run_repository,
            stale_after_seconds=settings.run_stale_seconds,
            interval_seconds=settings.run_sweeper_interval_seconds,
        )
        await run_sweeper.start()
    else:
        # The Run API is intentionally unavailable without Redis; no memory
        # event-bus fallback is allowed by the V3.3-2 contract.
        app.state.chat_run_runtime = None
    app.state.chat_run_event_bus = run_event_bus
    try:
        yield
    finally:
        if run_sweeper is not None:
            await run_sweeper.stop()
        if run_manager is not None:
            await run_manager.shutdown()
        if run_event_bus is not None:
            await run_event_bus.aclose()
        if vnext_redis is not None:
            await vnext_redis.aclose()
        await vnext_services.aclose()
        await store.aclose()
        await close_database(database)


app = FastAPI(
    title=settings.app_name,
    description="Composable esports intelligence reports for humans and agents.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router, prefix=settings.api_v1_prefix)
app.include_router(chat_router, prefix=settings.api_v1_prefix)
app.include_router(vnext_chat_router, prefix=settings.api_v1_prefix)
app.include_router(chat_run_router, prefix=settings.api_v1_prefix)
app.mount(
    f"{settings.api_v1_prefix}/assets/dota",
    StaticFiles(directory=CATALOG_IMAGE_DIR, check_dir=False),
    name="dota-catalog-images",
)
app.mount(
    f"{settings.api_v1_prefix}/assets/esports",
    StaticFiles(directory=ESPORTS_ASSET_DIR, check_dir=False),
    name="esports-assets",
)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/debug/plan", include_in_schema=False, response_class=FileResponse)
def plan_console() -> FileResponse:
    return FileResponse(PLAN_CONSOLE_PATH)
