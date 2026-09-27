"""Behavioral hints for the restaurants vertical. See dentists.py for the pattern."""

RULES = {
    "salutation_style": "Use the owner's first name plainly (e.g. 'Suresh').",
    "register_notes": "Operator-to-operator voice ('covers', 'AOV', 'delivery radius'). Data-informed judgment (e.g. contrarian calls on demand spikes) scores highest.",
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
        "ipl_match_today": "binary_yes_no",
        "active_planning_intent": "open_ended",
    },
    "customer_facing_notes": "Restaurants rarely message end customers directly through this bot; treat as merchant-facing by default.",
    "compliance_urgency_multiplier": 1.0,
}
