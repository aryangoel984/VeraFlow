from fastapi import APIRouter

from app.llm import client as llm_client
from app.models.schemas import ContextsLoaded, HealthzResponse
from app.storage.state import state

router = APIRouter()


@router.get("/v1/healthz", response_model=HealthzResponse)
async def healthz() -> HealthzResponse:
    counts = state.contexts_loaded_counts()
    return HealthzResponse(status="ok", uptime_seconds=state.uptime_seconds(),
                            contexts_loaded=ContextsLoaded(**counts),
                            llm_configured=llm_client.is_available())
