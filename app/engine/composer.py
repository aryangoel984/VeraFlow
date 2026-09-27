"""Turns a decision brief into final message text.

The deterministic engine (signal_selector + strategy / conversation) has
already decided WHAT to say and WHY. This module's only job is phrasing:
ask the LLM to turn a curated set of allowed facts into a natural WhatsApp
message, then validate the result and fall back to a deterministic template
if the LLM is unavailable or produces anything ungrounded or malformed.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from app.engine import validator
from app.llm import client as llm_client

SYSTEM_PROMPT = """You are composing ONE WhatsApp message for Vera, magicpin's AI assistant for merchants.

Hard rules:
- Use ONLY the facts given in ALLOWED_FACTS. Never invent numbers, dates, names, offers, competitors, or citations.
- Anchor the message on the single PRIMARY_SIGNAL given — do not list every fact you have.
- Exactly ONE call-to-action, matching the required cta_type. Never ask more than one thing.
- No preamble ("I hope you're doing well..."), no re-introducing yourself, concise and specific.
- Match VOICE.tone and use VOICE.vocab_allowed where natural; NEVER use any word in VOICE.vocab_taboo.
- If languages include "hi" or the customer's language_pref mentions Hindi, natural Hindi-English code-mix is preferred.
- Never include a URL.
- If CUSTOMER is present, this message is sent on the merchant's behalf to their customer — respect the customer's stated preferences and be warm; do not use internal jargon.
- If a citation/source is present in the primary signal, include it briefly (adds credibility, required for research/compliance claims).
- Specificity wins: prefer the concrete number/date/citation over vague language.

Respond with ONLY this JSON object, nothing else:
{"body": "<the message text>", "rationale": "<one sentence: why this message, why now>"}"""


def _cta_instruction(cta_type: str, facts: dict) -> str:
    if cta_type == "binary_yes_no":
        return "cta_type=binary_yes_no: end with a single yes/no ask (e.g. 'Reply YES / STOP')."
    if cta_type == "multi_choice_slot":
        slots = facts.get("available_slots") or []
        labels = [s.get("label", s.get("iso", "")) for s in slots if isinstance(s, dict)]
        return f"cta_type=multi_choice_slot: offer the available slots {labels} as a simple numbered choice, or let them propose another time."
    if cta_type == "none":
        return "cta_type=none: this is pure information, no ask at all."
    return "cta_type=open_ended: end with one open, low-friction question inviting a reply."


def _build_prompt(brief: dict[str, Any]) -> str:
    allowed_facts = {
        "primary_signal": brief.get("anchor_summary"),
        "primary_signal_facts": brief.get("anchor_facts"),
        "merchant_name": brief.get("merchant_name"),
        "owner_first_name": brief.get("owner_first_name"),
        "locality": brief.get("locality"),
        "languages": brief.get("languages"),
        "active_offers": brief.get("active_offers"),
        "customer": brief.get("customer"),
    }
    payload = {
        "ALLOWED_FACTS": allowed_facts,
        "VOICE": brief.get("voice", {}),
        "category_register_notes": brief.get("register_notes"),
        "customer_facing_notes": brief.get("customer_facing_notes") if brief.get("customer") else None,
        "send_as": brief.get("send_as"),
        "cta_type": brief.get("cta_type"),
        "cta_instruction": _cta_instruction(brief.get("cta_type", "open_ended"), brief.get("anchor_facts") or {}),
        "conversation_context": brief.get("conversation_context"),
        "composition_instruction": brief.get("instruction", "Compose a fresh outbound message from PRIMARY_SIGNAL."),
    }
    return json.dumps(payload, default=str, ensure_ascii=False)


def cta_phrase(cta_type: str, facts: dict) -> str:
    if cta_type == "binary_yes_no":
        return "Reply YES to go ahead, or STOP to skip."
    if cta_type == "multi_choice_slot":
        slots = facts.get("available_slots") or []
        labels = [s.get("label") for s in slots if isinstance(s, dict) and s.get("label")]
        if len(labels) >= 2:
            return f"Reply 1 for {labels[0]}, 2 for {labels[1]}, or tell us a time that works."
        if labels:
            return f"Reply 1 to book {labels[0]}, or tell us a time that works."
        return "Reply with a time that works for you."
    if cta_type == "none":
        return ""
    return "Want me to take this further?"


def build_fallback_body(brief: dict[str, Any]) -> str:
    anchor = (brief.get("anchor_summary") or "").strip()
    facts = brief.get("anchor_facts") or {}
    cta_type = brief.get("cta_type", "open_ended")
    phrase = cta_phrase(cta_type, facts)
    customer = brief.get("customer")
    if customer:
        name = customer.get("identity", {}).get("name") or "there"
        merchant_name = brief.get("merchant_name") or "the clinic"
        greeting = f"Hi {name}, {merchant_name} here."
    else:
        who = brief.get("owner_first_name") or brief.get("merchant_name") or "there"
        greeting = f"{who},"
    pieces = [greeting, anchor, phrase]
    return " ".join(p for p in pieces if p)


async def generate_body(brief: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Returns (body, rationale) from the LLM, or (None, None) if unavailable/failed."""
    if not llm_client.is_available():
        return None, None
    prompt = _build_prompt(brief)
    result = await llm_client.complete_json(SYSTEM_PROMPT, prompt)
    if not result or not result.get("body"):
        return None, None
    return str(result["body"]).strip(), str(result.get("rationale", "")).strip()


async def compose(brief: dict[str, Any], grounding_blob: str, taboo_words: list[str],
                   previous_bodies: list[str], business_rationale: str) -> dict[str, Any]:
    """Full compose pipeline: LLM phrasing -> validation -> fallback if needed."""
    llm_body, llm_rationale = await generate_body(brief)
    used_llm = False
    body = llm_body
    rationale = llm_rationale

    if body:
        result = validator.validate_body(body, grounding_blob, taboo_words, previous_bodies)
        if result.ok:
            used_llm = True
        else:
            body = None

    if not body:
        body = build_fallback_body(brief)
        # Fallback bodies are template-built directly from the same facts, but
        # still re-validated (e.g. anti-repetition) and re-varied if needed.
        result = validator.validate_body(body, grounding_blob, taboo_words, previous_bodies)
        if not result.ok and "identical to a previously sent message" in " ".join(result.notes):
            body = body.rstrip(".") + " (following up)."
        rationale = rationale or business_rationale

    if not rationale:
        rationale = business_rationale

    return {"body": body, "rationale": rationale, "used_llm": used_llm}
