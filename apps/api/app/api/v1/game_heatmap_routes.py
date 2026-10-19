"""Opaque, expiring image references; this route never starts provider work."""

from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter()


@router.get("/game/heatmaps/assets/{batch_id}/{player_slot}/{cutoff}.png", include_in_schema=False)
def read_game_heatmap(batch_id: str, player_slot: int, cutoff: int, request: Request):
    services = getattr(request.app.state, "vnext_services", None)
    service = getattr(services, "game_heatmaps", None)
    payload = service.read_image(batch_id, player_slot, cutoff) if service is not None else None
    if payload is None:
        raise HTTPException(status_code=404)
    return Response(
        content=payload,
        media_type="image/png",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
