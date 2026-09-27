"""Turns a trigger + the pushed contexts into a full sendable decision:
eligibility (suppression, consent, opt-out, expiry), CTA shape, send_as,
conversation id, and the business rationale. The actual message wording is
produced downstream by composer.py — this module only decides business logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.category import get_category_rules
from app.engine.signal_selector import AnchorResult, select_signal
from app.storage.state import AppState


@dataclass
class Decision:
    send: bool
    merchant_id: str
    trigger_id: str
    skip_reason: str = ""
    conversation_id: str = ""
    customer_id: Optional[str] = None
    send_as: str = "vera"
    cta_type: str = "open_ended"
    anchor: Optional[AnchorResult] = None
    category_rules: Optional[dict] = None
    business_rationale: str = ""
    urgency: int = 1
    template_name: str = ""


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _conversation_id(merchant_id: str, customer_id: Optional[str], trigger_id: str) -> str:
    if customer_id:
        return f"conv_{customer_id}_{trigger_id}"
    return f"conv_{merchant_id}_{trigger_id}"


def _cta_for(trigger: dict, category_rules: dict, anchor: AnchorResult) -> str:
    kind = trigger.get("kind", "")
    if kind == "recall_due":
        slots = (anchor.facts or {}).get("available_slots") or []
        return "multi_choice_slot" if len(slots) > 1 else "binary_yes_no"
    return category_rules.get("cta_bias", {}).get(kind, "open_ended")


def build_decision(trigger_id: str, trigger: dict, category: Optional[dict], merchant: Optional[dict],
                    customer: Optional[dict], now: datetime, state: AppState) -> Decision:
    merchant_id = trigger.get("merchant_id", "")
    scope = trigger.get("scope", "merchant")
    customer_id = trigger.get("customer_id")

    base = Decision(send=False, merchant_id=merchant_id, trigger_id=trigger_id,
                     customer_id=customer_id if scope == "customer" else None)

    if not merchant:
        base.skip_reason = "no merchant context pushed for this trigger's merchant_id"
        return base
    if scope == "customer" and customer is None:
        base.skip_reason = "customer-scoped trigger but no customer context has been pushed"
        return base
    if state.is_merchant_opted_out(merchant_id):
        base.skip_reason = "merchant has opted out / been suppressed after a hostile or hard-no reply"
        return base

    suppression_key = trigger.get("suppression_key", "")
    if suppression_key and state.is_suppressed(suppression_key):
        base.skip_reason = f"suppression_key '{suppression_key}' already sent"
        return base

    expires_at = _parse_iso(trigger.get("expires_at"))
    if expires_at and now > expires_at:
        base.skip_reason = "trigger has expired"
        return base

    anchor = select_signal(trigger, category, merchant, customer, now)
    if not anchor.ok:
        base.skip_reason = anchor.skip_reason
        base.anchor = anchor
        return base

    category_rules = get_category_rules((category or {}).get("slug") or merchant.get("category_slug", ""))
    cta_type = _cta_for(trigger, category_rules, anchor)
    send_as = "merchant_on_behalf" if scope == "customer" else "vera"
    conv_id = _conversation_id(merchant_id, customer_id if scope == "customer" else None, trigger_id)

    urgency = trigger.get("urgency", 1) or 1
    if trigger.get("kind") in ("regulation_change", "supply_alert"):
        urgency = round(urgency * category_rules.get("compliance_urgency_multiplier", 1.0))

    rationale_bits = [f"kind={trigger.get('kind')}", anchor.summary]
    if anchor.merchant_fit_note:
        rationale_bits.append(anchor.merchant_fit_note)
    business_rationale = " ".join(b for b in rationale_bits if b)

    return Decision(
        send=True,
        merchant_id=merchant_id,
        trigger_id=trigger_id,
        conversation_id=conv_id,
        customer_id=customer_id if scope == "customer" else None,
        send_as=send_as,
        cta_type=cta_type,
        anchor=anchor,
        category_rules=category_rules,
        business_rationale=business_rationale,
        urgency=urgency,
        template_name=f"{send_as}_{trigger.get('kind', 'generic')}_v1",
    )


def rank_and_select(trigger_ids: list[str], get_trigger, get_merchant, get_category, get_customer,
                     now: datetime, state: AppState, cap: int = 20) -> list[Decision]:
    """Given the tick's available_triggers hint, rank by urgency and build
    decisions, capping total actions and avoiding more than one new
    merchant-facing conversation per merchant per tick (customer-facing
    threads to distinct customers are independent and each may proceed)."""
    resolved: list[tuple[str, dict]] = []
    for tid in trigger_ids:
        trg = get_trigger(tid)
        if trg:
            resolved.append((tid, trg))
    resolved.sort(key=lambda pair: pair[1].get("urgency", 1) or 1, reverse=True)

    decisions: list[Decision] = []
    merchant_scope_used: set[str] = set()

    for tid, trg in resolved:
        if len(decisions) >= cap:
            break
        merchant_id = trg.get("merchant_id", "")
        scope = trg.get("scope", "merchant")
        if scope == "merchant" and merchant_id in merchant_scope_used:
            continue  # one new merchant-facing conversation per merchant per tick

        merchant = get_merchant(merchant_id)
        category = get_category(merchant.get("category_slug")) if merchant else None
        customer = get_customer(trg.get("customer_id")) if trg.get("customer_id") else None

        decision = build_decision(tid, trg, category, merchant, customer, now, state)
        if decision.send:
            decisions.append(decision)
            if scope == "merchant":
                merchant_scope_used.add(merchant_id)

    return decisions
