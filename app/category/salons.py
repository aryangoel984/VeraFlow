"""Behavioral hints for the salons vertical. See dentists.py for the pattern."""

RULES = {
    "salutation_style": "Use the owner's first name plainly (e.g. 'Hi Lakshmi').",
    "register_notes": "Warm, friendly, practical. Occasion/visual-driven framing (bridal, event prep) is high-value. Emojis in moderation are fine.",
    "cta_bias": {
        "research_digest": "open_ended",
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
        "bridal_followup": "binary_yes_no",
        "customer_lapsed_soft": "binary_yes_no",
        "customer_lapsed_hard": "binary_yes_no",
        "appointment_tomorrow": "binary_yes_no",
        "trial_followup": "open_ended",
    },
    "customer_facing_notes": "Personalize on occasion (wedding date, event) when present. Keep language warm, never pushy about repeat spend.",
    "compliance_urgency_multiplier": 1.0,
}
