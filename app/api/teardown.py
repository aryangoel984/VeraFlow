"""Optional POST /v1/teardown — per challenge-testing-brief.md §11, the judge
may call this at the end of a test; the bot must wipe all state on receipt."""
from fastapi import APIRouter

from app.storage.state import state

router = APIRouter()


@router.post("/v1/teardown")
async def teardown() -> dict:
    state.reset()
    return {"ok": True}
