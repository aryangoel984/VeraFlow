import os

from fastapi import APIRouter

from app.llm.client import DEFAULT_MODEL
from app.models.schemas import MetadataResponse

router = APIRouter()

BOT_STARTED_AT = os.environ.get("BOT_SUBMITTED_AT", "2026-04-26T08:00:00Z")


@router.get("/v1/metadata", response_model=MetadataResponse)
async def metadata() -> MetadataResponse:
    return MetadataResponse(
        team_name=os.environ.get("TEAM_NAME", "Aryan Goel"),
        team_members=[m.strip() for m in os.environ.get("TEAM_MEMBERS", "Aryan Goel").split(",") if m.strip()],
        model=os.environ.get("LLM_MODEL", DEFAULT_MODEL),
        approach=os.environ.get(
            "APPROACH",
            "Deterministic signal-selection + strategy engine chooses the one grounded fact, CTA, and "
            "eligibility per trigger kind; an LLM (temperature=0) phrases the decision into a WhatsApp "
            "message; a post-generation validator checks grounding/taboo/URL/single-CTA/repetition and "
            "falls back to a template built from the same facts on any failure.",
        ),
        contact_email=os.environ.get("CONTACT_EMAIL", "aryangoel_23it209@dtu.ac.in"),
        version=os.environ.get("BOT_VERSION", "1.0.0"),
        submitted_at=BOT_STARTED_AT,
    )
