import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.v1.routes import router as v1_router
from app.core.config import get_settings

settings = get_settings()
PLAN_CONSOLE_PATH = Path(__file__).parent / "resources" / "plan_console.html"


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

app = FastAPI(
    title=settings.app_name,
    description="Composable esports intelligence reports for humans and agents.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.get("/debug/plan", include_in_schema=False, response_class=FileResponse)
def plan_console() -> FileResponse:
    return FileResponse(PLAN_CONSOLE_PATH)
