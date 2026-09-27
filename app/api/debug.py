"""Temporary diagnostic endpoint — not part of the judge's required API
surface. Attempts one real LLM call and reports exactly what happened,
instead of the silent fallback the production path uses. Safe to leave in
(costs nothing when not called, exposes no secrets — only a short prefix of
the key), but fine to remove once deployment issues are resolved."""
from fastapi import APIRouter

from app.llm import client as llm_client

router = APIRouter()


@router.get("/v1/debug/llm")
async def debug_llm() -> dict:
    return await llm_client.diagnostic_ping()
