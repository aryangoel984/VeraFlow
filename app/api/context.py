import json
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.models.schemas import ContextPushRequest, Scope
from app.storage.state import state

router = APIRouter()

VALID_SCOPES = set(Scope.__args__)  # {"category", "merchant", "customer", "trigger"}
MAX_PAYLOAD_BYTES = 500 * 1024


@router.post("/v1/context")
async def push_context(request: Request):
    raw = await request.body()
    if len(raw) > MAX_PAYLOAD_BYTES:
        return JSONResponse(status_code=400, content={
            "accepted": False, "reason": "payload_too_large",
            "details": f"payload is {len(raw)} bytes, max is {MAX_PAYLOAD_BYTES}",
        })

    try:
        body = ContextPushRequest.model_validate_json(raw)
    except Exception as exc:
        return JSONResponse(status_code=400, content={
            "accepted": False, "reason": "malformed_request", "details": str(exc),
        })

    if body.scope not in VALID_SCOPES:
        return JSONResponse(status_code=400, content={
            "accepted": False, "reason": "invalid_scope",
            "details": f"scope must be one of {sorted(VALID_SCOPES)}",
        })

    accepted, info = state.push_context(body.scope, body.context_id, body.version, body.payload)
    if not accepted:
        return JSONResponse(status_code=409, content={
            "accepted": False, "reason": info.get("reason", "stale_version"),
            "current_version": info.get("current_version"),
        })

    return JSONResponse(status_code=200, content={
        "accepted": True, "ack_id": info["ack_id"],
        "stored_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "") + "Z",
    })
