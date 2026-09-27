"""Pydantic request/response models — mirrors challenge-testing-brief.md section 2-3 exactly."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Scope = Literal["category", "merchant", "customer", "trigger"]


# ---------------------------------------------------------------------------
# /v1/context
# ---------------------------------------------------------------------------

class ContextPushRequest(BaseModel):
    scope: str  # validated manually in the handler so invalid scopes return the spec's 400 shape
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str


class ContextPushAccepted(BaseModel):
    accepted: Literal[True] = True
    ack_id: str
    stored_at: str


class ContextPushRejected(BaseModel):
    accepted: Literal[False] = False
    reason: str
    current_version: Optional[int] = None
    details: Optional[str] = None


# ---------------------------------------------------------------------------
# /v1/tick
# ---------------------------------------------------------------------------

class TickRequest(BaseModel):
    now: str
    available_triggers: list[str] = Field(default_factory=list)


class TickAction(BaseModel):
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    send_as: Literal["vera", "merchant_on_behalf"]
    trigger_id: str
    template_name: str
    template_params: list[str]
    body: str
    cta: str
    suppression_key: str
    rationale: str


class TickResponse(BaseModel):
    actions: list[TickAction]


# ---------------------------------------------------------------------------
# /v1/reply
# ---------------------------------------------------------------------------

class ReplyRequest(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int


class ReplyResponse(BaseModel):
    action: Literal["send", "wait", "end"]
    body: Optional[str] = None
    cta: Optional[str] = None
    wait_seconds: Optional[int] = None
    rationale: str


# ---------------------------------------------------------------------------
# /v1/healthz, /v1/metadata
# ---------------------------------------------------------------------------

class ContextsLoaded(BaseModel):
    category: int = 0
    merchant: int = 0
    customer: int = 0
    trigger: int = 0


class HealthzResponse(BaseModel):
    status: Literal["ok"] = "ok"
    uptime_seconds: int
    contexts_loaded: ContextsLoaded


class MetadataResponse(BaseModel):
    team_name: str
    team_members: list[str]
    model: str
    approach: str
    contact_email: str
    version: str
    submitted_at: str
