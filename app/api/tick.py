from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter

from app.engine import composer, validator
from app.engine.strategy import Decision, rank_and_select
from app.models.schemas import TickAction, TickRequest, TickResponse
from app.storage.state import state

router = APIRouter()

MAX_ACTIONS_PER_TICK = 20


def _parse_now(now_str: str) -> datetime:
    try:
        dt = datetime.fromisoformat(now_str.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def _build_brief(decision: Decision, category: Optional[dict], merchant: dict, customer: Optional[dict]) -> dict:
    category = category or {}
    category_rules = decision.category_rules or {}
    return {
        "merchant_name": merchant.get("identity", {}).get("name"),
        "owner_first_name": merchant.get("identity", {}).get("owner_first_name"),
        "locality": merchant.get("identity", {}).get("locality"),
        "languages": merchant.get("identity", {}).get("languages"),
        "active_offers": [o.get("title") for o in merchant.get("offers", []) if o.get("status") == "active"],
        "customer": customer,
        "voice": category.get("voice", {}),
        "register_notes": category_rules.get("register_notes"),
        "customer_facing_notes": category_rules.get("customer_facing_notes") if customer else None,
        "send_as": decision.send_as,
        "cta_type": decision.cta_type,
        "anchor_summary": decision.anchor.summary if decision.anchor else "",
        "anchor_facts": decision.anchor.facts if decision.anchor else {},
        "conversation_context": "",
        "instruction": ("Compose a fresh outbound message from PRIMARY_SIGNAL. This is the first message "
                         "in a new conversation — no prior context to reference."),
    }


@router.post("/v1/tick", response_model=TickResponse)
async def tick(body: TickRequest) -> TickResponse:
    now = _parse_now(body.now)

    def get_trigger(tid: str) -> Optional[dict]:
        return state.get_context("trigger", tid)

    def get_merchant(mid: str) -> Optional[dict]:
        return state.get_context("merchant", mid)

    def get_category(slug: Optional[str]) -> Optional[dict]:
        return state.get_context("category", slug) if slug else None

    def get_customer(cid: Optional[str]) -> Optional[dict]:
        return state.get_context("customer", cid) if cid else None

    decisions = rank_and_select(body.available_triggers, get_trigger, get_merchant, get_category,
                                 get_customer, now, state, cap=MAX_ACTIONS_PER_TICK)

    # Build each decision's compose inputs first (cheap, no I/O), then run all
    # LLM compositions concurrently. Each decision writes to its own
    # conversation, so there's no ordering dependency between them — but at
    # ~1s per real LLM call, doing up to 20 of these sequentially could eat
    # most of the judge's 30s-per-call budget. Concurrently, 20 calls cost
    # about as much wall-clock time as 1.
    prepared = []
    for decision in decisions:
        merchant = get_merchant(decision.merchant_id) or {}
        category = get_category(merchant.get("category_slug"))
        customer = get_customer(decision.customer_id)
        trigger = get_trigger(decision.trigger_id) or {}

        brief = _build_brief(decision, category, merchant, customer)
        grounding_blob = validator.build_grounding_blob(category, merchant, trigger, customer)
        taboo_words = (category or {}).get("voice", {}).get("vocab_taboo", [])
        conv = state.get_or_create_conversation(
            decision.conversation_id, merchant_id=decision.merchant_id,
            customer_id=decision.customer_id, trigger_id=decision.trigger_id, send_as=decision.send_as,
        )
        suppression_key = trigger.get("suppression_key") or f"{decision.trigger_id}:{decision.merchant_id}"
        prepared.append((decision, merchant, customer, brief, grounding_blob, taboo_words, conv, suppression_key))

    results = await asyncio.gather(*(
        composer.compose(brief, grounding_blob, taboo_words, conv.sent_bodies,
                          business_rationale=decision.business_rationale)
        for decision, _, _, brief, grounding_blob, taboo_words, conv, _ in prepared
    ))

    actions: list[TickAction] = []
    for (decision, merchant, customer, brief, _, _, conv, suppression_key), result in zip(prepared, results):
        conv.sent_bodies.append(result["body"])
        conv.turns.append({"from_role": "bot", "message": result["body"]})
        state.mark_sent(suppression_key)

        anchor_facts = decision.anchor.facts if decision.anchor else {}
        name_param = ((customer or {}).get("identity", {}).get("name") if customer else None) \
            or brief.get("owner_first_name") or brief.get("merchant_name") or ""
        template_params = [
            name_param,
            decision.anchor.summary if decision.anchor else "",
            composer.cta_phrase(decision.cta_type, anchor_facts),
        ]

        actions.append(TickAction(
            conversation_id=decision.conversation_id,
            merchant_id=decision.merchant_id,
            customer_id=decision.customer_id,
            send_as=decision.send_as,
            trigger_id=decision.trigger_id,
            template_name=decision.template_name,
            template_params=template_params,
            body=result["body"],
            cta=decision.cta_type,
            suppression_key=suppression_key,
            rationale=result["rationale"],
        ))

    return TickResponse(actions=actions)
