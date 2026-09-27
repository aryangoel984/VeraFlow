"""Registry of per-category behavioral hints (non-factual composition bias only)."""
from . import dentists, gyms, pharmacies, restaurants, salons

CATEGORY_RULES: dict[str, dict] = {
    "dentists": dentists.RULES,
    "salons": salons.RULES,
    "restaurants": restaurants.RULES,
    "gyms": gyms.RULES,
    "pharmacies": pharmacies.RULES,
}

DEFAULT_RULES = {
    "salutation_style": "Use the merchant's owner first name plainly.",
    "register_notes": "Peer, non-promotional tone. Follow the pushed CategoryContext.voice fields.",
    "cta_bias": {},
    "customer_facing_notes": "Respect stated language preference and consent scope.",
    "compliance_urgency_multiplier": 1.0,
}


def get_category_rules(slug: str) -> dict:
    return CATEGORY_RULES.get(slug, DEFAULT_RULES)
