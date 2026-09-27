"""Behavioral hints for the dentists vertical.

These are NOT facts — the CategoryContext pushed via /v1/context carries all
factual voice/offer/digest data. This module only encodes non-factual
composition bias: how to talk, what CTA shapes fit, what to avoid. Never add
category-specific claims here that aren't already in the pushed context.
"""

RULES = {
    "salutation_style": "Use the owner's title + first name if available (e.g. 'Dr. {first_name}'), never just 'Hi'.",
    "register_notes": "Peer-to-peer clinical register. Technical vocabulary from voice.vocab_allowed is welcome. Never use words in voice.vocab_taboo.",
    "cta_bias": {
        "research_digest": "open_ended",
        "regulation_change": "binary_yes_no",
        "category_trend_movement": "open_ended",
        "perf_spike": "open_ended",
        "perf_dip": "open_ended",
        "milestone_reached": "open_ended",
        "dormant_with_vera": "open_ended",
        "review_theme_emerged": "open_ended",
        "competitor_opened": "open_ended",
        "festival_upcoming": "binary_yes_no",
        "renewal_due": "binary_yes_no",
        "curious_ask_due": "open_ended",
        "scheduled_recurring": "open_ended",
        "recall_due": "multi_choice_slot",
        "customer_lapsed_soft": "binary_yes_no",
        "customer_lapsed_hard": "binary_yes_no",
        "appointment_tomorrow": "binary_yes_no",
        "trial_followup": "open_ended",
    },
    "customer_facing_notes": "No medical claims, no 'guaranteed'/'cure'. Warm-clinical, not promotional. Cite exact price + slot when offering a booking.",
    "compliance_urgency_multiplier": 2.0,  # regulation_change triggers should escalate urgency
}
