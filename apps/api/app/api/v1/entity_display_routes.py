"""Read-only batch resolution for explicit local entity display references."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.vnext.entity_display import EntityDisplayDirectory

_DisplayRefString = Annotated[StrictStr, Field(max_length=128)]

router = APIRouter(prefix="/display", tags=["display"])


class DisplayResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refs: list[_DisplayRefString] = Field(max_length=100)


class ResolvedDisplayEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_ref: StrictStr
    kind: Literal["hero", "item", "ability", "team"]
    label: StrictStr
    image_url: StrictStr | None


class DisplayResolveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entities: dict[StrictStr, ResolvedDisplayEntity]


@router.post(
    "/resolve",
    response_model=DisplayResolveResponse,
    responses={503: {"description": "Entity display directory is unavailable"}},
)
def resolve_display_entities(
    body: DisplayResolveRequest,
    request: Request,
    response: Response,
) -> DisplayResolveResponse | JSONResponse:
    """Resolve one bounded reference batch using the application directory."""

    response.headers["Cache-Control"] = "no-store"
    services = getattr(request.app.state, "vnext_services", None)
    directory = getattr(services, "entity_display_directory", None)
    if not isinstance(directory, EntityDisplayDirectory):
        return JSONResponse(
            status_code=503,
            content={"detail": {"code": "entity_display_unavailable"}},
            headers={"Cache-Control": "no-store"},
        )

    resolved = directory.resolve_many(body.refs)
    return DisplayResolveResponse(
        entities={
            ref: ResolvedDisplayEntity(
                display_ref=entity.display_ref,
                kind=entity.kind,
                label=entity.label,
                image_url=entity.image_url,
            )
            for ref, entity in resolved.items()
        }
    )


__all__ = ["router"]
