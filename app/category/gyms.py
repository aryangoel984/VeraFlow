"""Behavioral hints for the gyms vertical. See dentists.py for the pattern."""

RULES = {
    "salutation_style": "Use the owner's first name plainly (e.g. 'Karthik').",
    "register_notes": "Coach-to-operator / coach-to-member. Energetic but not hype. Never guilt-trip lapsed members.",
    "cta_bias": {
        "research_digest": "open_ended",
        "category_trend_movement": "open_ended",
        "perf_spike": "open_ended",
        "perf_dip": "open_ended",
        "seasonal_perf_dip": "open_ended",
        "milestone_reached": "open_ended",
        "dormant_with_vera": "open_ended",
        "review_theme_emerged": "open_ended",
        "competitor_opened": "open_ended",
        "festival_upcoming": "binary_yes_no",
        "renewal_due": "binary_yes_no",
        "curious_ask_due": "open_ended",
        "scheduled_recurring": "open_ended",
        "customer_lapsed_soft": "binary_yes_no",
        "customer_lapsed_hard": "binary_yes_no",
        "appointment_tomorrow": "binary_yes_no",
    },
    "customer_facing_notes": "Warm, no-shame, no guilt-trip for lapsed members. Offer a concrete no-commitment next step (trial class, not a hard sell).",
    "compliance_urgency_multiplier": 1.0,
}
