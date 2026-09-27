"""Reply-turn state machine for POST /v1/reply.

Classifies the incoming message (auto-reply, hostile, rejection, acceptance/
intent-transition, deferral, or an on/off-topic question) and decides
send / wait / end. When the conversation was opened by our own /v1/tick, the
originating trigger is re-resolved so the LLM composer stays grounded in the
same facts as the opening message; if the conversation is unknown (a
standalone replay-test call), the bot still degrades gracefully.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from app.category import get_category_rules
from app.engine import composer, validator
from app.engine.signal_selector import select_signal
from app.storage.state import AppState, ConversationState

AUTO_REPLY_PATTERNS = [
    "thank you for contacting", "our team will respond", "will get back to you shortly",
    "this is an automated", "automated assistant", "away from my phone",
    "message received", "we have received your message", "shukriya", "team tak pahuncha",
]

HOSTILE_PATTERNS = [
    "useless", "spam", "bothering", "harassment", "harass", "stupid", "idiot", "shut up",
    "fed up", "annoying",
]

GLOBAL_OPT_OUT_PATTERNS = [
    "stop messaging", "stop contacting", "unsubscribe", "don't message", "do not message",
    "stop sending", "block", "remove me",
]

REJECTION_PATTERNS = [
    "not interested", "no thanks", "no thank you", "don't send", "not now permanently", "nahi chahiye",
]

ACCEPTANCE_PATTERNS = [
    "yes", "yes please", "go ahead", "let's do it", "lets do it", "sure", "please send",
    "confirm", "sounds good", "ok do it", "okay do it", "haan bhej do", "theek hai",
]

DEFERRAL_PATTERNS = [
    "later", "next week", "maybe tomorrow", "not now", "remind me", "busy right now",
    "call me later", "after some time",
]


def _contains_any(text: str, patterns: list[str]) -> bool:
    lowered = text.lower()
    return any(p in lowered for p in patterns)


def classify(message: str, conv: ConversationState) -> str:
    lowered = message.strip().lower()
    is_repeat_of_last_bot_or_auto = (
        conv.last_auto_reply_text is not None and lowered == conv.last_auto_reply_text.strip().lower()
    )
    if _contains_any(message, AUTO_REPLY_PATTERNS) or is_repeat_of_last_bot_or_auto:
        return "auto_reply"
    if _contains_any(message, HOSTILE_PATTERNS):
        return "hostile"
    if _contains_any(message, GLOBAL_OPT_OUT_PATTERNS) or _contains_any(message, REJECTION_PATTERNS):
        return "rejection"
    if _contains_any(message, ACCEPTANCE_PATTERNS):
        return "acceptance"
    if _contains_any(message, DEFERRAL_PATTERNS):
        return "deferral"
    return "other"


def _deferral_wait_seconds(message: str) -> int:
    lowered = message.lower()
    if "tomorrow" in lowered:
        return 20 * 3600
    if "next week" in lowered:
        return 7 * 24 * 3600
    return 4 * 3600


def _is_global_opt_out(message: str) -> bool:
    return _contains_any(message, GLOBAL_OPT_OUT_PATTERNS)


def _resolve_grounding(state: AppState, conv: ConversationState) -> dict[str, Any]:
    """Re-derive category/merchant/customer/trigger + anchor for a conversation
    that we opened, so follow-up turns stay grounded in the original facts."""
    merchant = state.get_context("merchant", conv.merchant_id) if conv.merchant_id else None
    customer = state.get_context("customer", conv.customer_id) if conv.customer_id else None
    trigger = state.get_context("trigger", conv.trigger_id) if conv.trigger_id else None
    category = None
    if merchant:
        category = state.get_context("category", merchant.get("category_slug", ""))

    anchor = None
    if trigger and merchant:
        anchor = select_signal(trigger, category, merchant, customer, datetime.now(timezone.utc))
        if not anchor.ok:
            anchor = None

    return {"merchant": merchant, "customer": customer, "trigger": trigger, "category": category, "anchor": anchor}


def _build_brief(ctx: dict[str, Any], instruction: str, cta_type: str, conversation_context: str) -> dict[str, Any]:
    merchant = ctx.get("merchant") or {}
    customer = ctx.get("customer")
    category = ctx.get("category") or {}
    anchor = ctx.get("anchor")
    category_rules = get_category_rules(category.get("slug") or merchant.get("category_slug", ""))

    return {
        "merchant_name": merchant.get("identity", {}).get("name"),
        "owner_first_name": merchant.get("identity", {}).get("owner_first_name"),
        "locality": merchant.get("identity", {}).get("locality"),
        "languages": merchant.get("identity", {}).get("languages"),
        "active_offers": [o.get("title") for o in merchant.get("offers", []) if o.get("status") == "active"],
        "customer": customer,
        "voice": category.get("voice", {}),
        "register_notes": category_rules.get("register_notes"),
        "customer_facing_notes": category_rules.get("customer_facing_notes"),
        "send_as": "merchant_on_behalf" if customer else "vera",
        "cta_type": cta_type,
        "anchor_summary": anchor.summary if anchor else "Continuing the existing conversation.",
        "anchor_facts": anchor.facts if anchor else {},
        "conversation_context": conversation_context,
        "instruction": instruction,
    }


def _conversation_context_text(conv: ConversationState, latest_message: str) -> str:
    tail = conv.turns[-4:]
    lines = [f"{t['from_role']}: {t['message']}" for t in tail]
    lines.append(f"merchant: {latest_message}")
    return "\n".join(lines)


async def handle_reply(conv: ConversationState, message: str, state: AppState) -> dict[str, Any]:
    """Returns a dict matching ReplyResponse fields."""
    conv.turns.append({"from_role": "merchant", "message": message})
    intent = classify(message, conv)
    ctx = _resolve_grounding(state, conv)
    grounding_blob = validator.build_grounding_blob(ctx.get("category"), ctx.get("merchant"),
                                                      ctx.get("trigger"), ctx.get("customer"))
    taboo_words = (ctx.get("category") or {}).get("voice", {}).get("vocab_taboo", [])

    if intent == "auto_reply":
        conv.auto_reply_streak += 1
        conv.last_auto_reply_text = message
        if conv.auto_reply_streak == 1:
            brief = _build_brief(
                ctx,
                instruction=("This looks like a WhatsApp Business auto-reply, not the real owner. Send ONE short "
                             "message asking them to flag this for the owner when seen. Keep it light."),
                cta_type="binary_yes_no",
                conversation_context=_conversation_context_text(conv, message),
            )
            result = await composer.compose(brief, grounding_blob, taboo_words, conv.sent_bodies,
                                             business_rationale="Detected merchant auto-reply; one prompt for the owner to see later.")
            conv.sent_bodies.append(result["body"])
            conv.turns.append({"from_role": "bot", "message": result["body"]})
            return {"action": "send", "body": result["body"], "cta": "binary_yes_no", "rationale": result["rationale"]}
        if conv.auto_reply_streak == 2:
            return {"action": "wait", "wait_seconds": 86400,
                    "rationale": "Same auto-reply twice in a row; owner likely not at phone. Waiting 24h before retry."}
        conv.status = "ended"
        return {"action": "end",
                "rationale": "Auto-reply 3+ times with zero real engagement signal; closing the conversation."}

    if intent == "hostile":
        conv.status = "ended"
        if conv.merchant_id:
            state.opt_out_merchant(conv.merchant_id, seconds=30 * 24 * 3600)
        return {"action": "end", "rationale": "Merchant expressed frustration; closing gracefully and "
                                               "suppressing further outreach to this merchant for 30 days."}

    if intent == "rejection":
        conv.status = "ended"
        if conv.merchant_id and _is_global_opt_out(message):
            state.opt_out_merchant(conv.merchant_id, seconds=30 * 24 * 3600)
            reason = "Merchant explicitly opted out of all messaging; suppressing for 30 days."
        else:
            reason = "Merchant declined this specific offer; closing this conversation without further nudges."
        return {"action": "end", "rationale": reason}

    if intent == "deferral":
        wait_s = _deferral_wait_seconds(message)
        return {"action": "wait", "wait_seconds": wait_s,
                "rationale": f"Merchant asked for time; backing off {wait_s // 3600}h before re-engaging."}

    if intent == "acceptance":
        conv.accepted_intent = True
        brief = _build_brief(
            ctx,
            instruction=("The merchant just explicitly committed/accepted (e.g. said yes / let's do it). Do NOT ask "
                         "another qualifying question. Propose the concrete next step directly and give ONE "
                         "low-friction confirm ask."),
            cta_type="binary_yes_no",
            conversation_context=_conversation_context_text(conv, message),
        )
        result = await composer.compose(brief, grounding_blob, taboo_words, conv.sent_bodies,
                                         business_rationale="Honoring explicit merchant commitment; switching from pitch to action mode.")
        conv.sent_bodies.append(result["body"])
        conv.turns.append({"from_role": "bot", "message": result["body"]})
        return {"action": "send", "body": result["body"], "cta": "binary_yes_no", "rationale": result["rationale"]}

    # "other": on/off-topic question or curveball
    topic_words = set(re.findall(r"[a-zA-Z]{5,}", (ctx.get("anchor").summary if ctx.get("anchor") else "")))
    message_words = set(re.findall(r"[a-zA-Z]{5,}", message.lower()))
    on_topic = bool(topic_words & {w.lower() for w in message_words}) or not ctx.get("anchor")
    instruction = (
        "Answer the merchant's question using ONLY ALLOWED_FACTS, then re-offer the original ask as one CTA."
        if on_topic else
        "The merchant asked something outside what you can help with here. Politely decline in one short clause, "
        "then redirect back to the original topic with one CTA — do not lecture, do not repeat yourself."
    )
    brief = _build_brief(ctx, instruction=instruction, cta_type="open_ended",
                          conversation_context=_conversation_context_text(conv, message))
    result = await composer.compose(brief, grounding_blob, taboo_words, conv.sent_bodies,
                                     business_rationale="Off-topic ask handled without losing the original thread."
                                     if not on_topic else "Answered grounded question; kept the thread open.")
    conv.sent_bodies.append(result["body"])
    conv.turns.append({"from_role": "bot", "message": result["body"]})
    return {"action": "send", "body": result["body"], "cta": "open_ended", "rationale": result["rationale"]}
