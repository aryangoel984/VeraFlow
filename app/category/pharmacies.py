"""Behavioral hints for the pharmacies vertical. See dentists.py for the pattern."""

RULES = {
    "salutation_style": "Use the owner's first name plainly for merchant-facing (e.g. 'Ramesh'); use 'Namaste' + respectful register for senior customers.",
    "register_notes": "Trustworthy, precise, compliance-sensitive. Use exact batch numbers / molecule names when citing recalls or refills — never round or approximate them.",
    "cta_bias": {
        "research_digest": "open_ended",
        "regulation_change": "binary_yes_no",
        "supply_alert": "open_ended",
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
        "chronic_refill_due": "binary_yes_no",
        "customer_lapsed_soft": "binary_yes_no",
    },
    "customer_facing_notes": "Respectful of senior citizens; precise on dosage/medicine names; never imply a change in prescription. Always give a phone-call fallback alongside a reply CTA for anything dosage-related.",
    "compliance_urgency_multiplier": 2.5,  # supply/compliance alerts are highest urgency in this vertical
}
