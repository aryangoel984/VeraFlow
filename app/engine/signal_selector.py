"""Picks the ONE grounded signal that should drive the next message.

This is the "decision quality" core: given a trigger + the pushed contexts,
decide what real, verifiable fact anchors this message — or decide that
there isn't one, in which case the tick should skip sending entirely.

Every selector either derives its anchor from the trigger's own payload
(when the judge supplied specifics) or, for internally-derivable trigger
families (performance, subscription, review, customer relationship), falls
back to the merchant/customer context directly. External-event kinds
(research digests, regulation changes, competitors, festivals, supply
alerts) are NEVER invented — if the payload lacks concrete specifics and
there's no matching category digest item, the trigger is skipped.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional


@dataclass
class AnchorResult:
    ok: bool
    summary: str = ""
    facts: dict[str, Any] = field(default_factory=dict)
    citation: Optional[str] = None
    merchant_fit_note: Optional[str] = None
    skip_reason: str = ""


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _get_digest_item(category: dict, item_id: Optional[str]) -> Optional[dict]:
    if not item_id:
        return None
    for item in category.get("digest", []):
        if item.get("id") == item_id:
            return item
    return None


def _pick_digest_by_kind(category: dict, kind: str) -> Optional[dict]:
    for item in category.get("digest", []):
        if item.get("kind") == kind:
            return item
    return None


def _match_merchant_signal(merchant: dict, segment: Optional[str]) -> Optional[str]:
    if not segment:
        return None
    needle = segment.replace("_", " ").lower()
    for sig in merchant.get("signals", []):
        if needle in sig.replace("_", " ").lower():
            return f"merchant signals include a matching cohort ({segment})"
    return None


def _active_offer_titles(merchant: dict) -> list[str]:
    return [o.get("title") for o in merchant.get("offers", []) if o.get("status") == "active" and o.get("title")]


# ---------------------------------------------------------------------------
# Merchant-scope, external-event selectors (never fabricate — payload or
# category digest must carry the real specifics)
# ---------------------------------------------------------------------------

def sel_research_digest(t, category, merchant, customer, now):
    p = t.get("payload", {})
    item = _get_digest_item(category, p.get("top_item_id")) or _pick_digest_by_kind(category, "research")
    if not item:
        return AnchorResult(ok=False, skip_reason="no research digest item available in category context")
    segment = item.get("patient_segment") or item.get("segment")
    facts = {k: item[k] for k in ("title", "source", "trial_n", "patient_segment", "summary", "actionable") if k in item}
    summary = f'Research digest: "{item.get("title")}" ({item.get("source")}).'
    if item.get("summary"):
        summary += f" {item['summary']}"
    return AnchorResult(ok=True, summary=summary, facts=facts, citation=item.get("source"),
                         merchant_fit_note=_match_merchant_signal(merchant, segment))


def sel_regulation_change(t, category, merchant, customer, now):
    p = t.get("payload", {})
    item = _get_digest_item(category, p.get("top_item_id")) or _pick_digest_by_kind(category, "compliance")
    if not item:
        return AnchorResult(ok=False, skip_reason="no compliance digest item available in category context")
    facts = {k: item[k] for k in ("title", "source", "summary", "actionable") if k in item}
    if p.get("deadline_iso"):
        facts["deadline_iso"] = p["deadline_iso"]
    summary = f'Compliance change: "{item.get("title")}" ({item.get("source")}).'
    if item.get("summary"):
        summary += f" {item['summary']}"
    if p.get("deadline_iso"):
        summary += f" Deadline: {p['deadline_iso']}."
    return AnchorResult(ok=True, summary=summary, facts=facts, citation=item.get("source"))


def sel_category_trend(t, category, merchant, customer, now):
    p = t.get("payload", {})
    query = p.get("query")
    trend = next((tr for tr in category.get("trend_signals", []) if tr.get("query") == query), None)
    if trend is None:
        trends = category.get("trend_signals", [])
        trend = trends[0] if trends else None
    if trend is None:
        return AnchorResult(ok=False, skip_reason="no trend signal available in category context")
    facts = dict(trend)
    delta = trend.get("delta_yoy", 0) or 0
    summary = f'Trend: "{trend.get("query")}" searches {delta * 100:.0f}% YoY (segment {trend.get("segment_age", "n/a")}).'
    return AnchorResult(ok=True, summary=summary, facts=facts)


def sel_category_seasonal(t, category, merchant, customer, now):
    p = t.get("payload", {})
    real = {k: v for k, v in p.items() if k not in ("placeholder", "metric_or_topic") and v is not None}
    if real:
        summary = f"Seasonal category shift: {json.dumps(real)}"
        return AnchorResult(ok=True, summary=summary, facts=real)
    beats = category.get("seasonal_beats", [])
    if not beats:
        return AnchorResult(ok=False, skip_reason="no seasonal beat data available in category context")
    beat = beats[0]
    summary = f'Seasonal pattern: {beat.get("month_range")} — {beat.get("note")}'
    return AnchorResult(ok=True, summary=summary, facts=dict(beat))


def sel_festival(t, category, merchant, customer, now):
    p = t.get("payload", {})
    if not p.get("festival"):
        return AnchorResult(ok=False, skip_reason="no festival specifics in trigger payload")
    facts = {k: p[k] for k in ("festival", "date", "days_until", "category_relevance") if k in p}
    summary = f'{p["festival"]} is {p.get("days_until", "?")} day(s) away ({p.get("date", "")}).'
    if p.get("category_relevance"):
        summary += f" Relevance: {p['category_relevance']}."
    return AnchorResult(ok=True, summary=summary, facts=facts)


def sel_competitor_opened(t, category, merchant, customer, now):
    p = t.get("payload", {})
    if not p.get("competitor_name"):
        return AnchorResult(ok=False, skip_reason="no verified competitor data in trigger payload")
    facts = {k: p[k] for k in ("competitor_name", "distance_km", "their_offer", "opened_date") if k in p}
    summary = f'New competitor "{p["competitor_name"]}" opened {p.get("distance_km", "?")}km away on {p.get("opened_date", "")}.'
    if p.get("their_offer"):
        summary += f" Their offer: {p['their_offer']}."
    return AnchorResult(ok=True, summary=summary, facts=facts)


def sel_supply_alert(t, category, merchant, customer, now):
    p = t.get("payload", {})
    if not p.get("molecule") and not p.get("affected_batches"):
        return AnchorResult(ok=False, skip_reason="no verified recall/supply specifics in trigger payload")
    facts = {k: p[k] for k in ("alert_id", "molecule", "affected_batches", "manufacturer") if k in p}
    batches = ", ".join(p.get("affected_batches", []) or [])
    summary = f'Voluntary recall: {p.get("molecule", "")} batches {batches} by {p.get("manufacturer", "")}.'
    return AnchorResult(ok=True, summary=summary, facts=facts)


def sel_cde_opportunity(t, category, merchant, customer, now):
    p = t.get("payload", {})
    item = _get_digest_item(category, p.get("digest_item_id")) or _pick_digest_by_kind(category, "cde")
    if not item:
        return AnchorResult(ok=False, skip_reason="no CDE/webinar digest item available in category context")
    facts = {k: item[k] for k in ("title", "source", "date", "credits", "summary", "actionable") if k in item}
    if p.get("fee") is not None:
        facts["fee"] = p["fee"]
    summary = f'CDE opportunity: "{item.get("title")}" ({item.get("source")}, {item.get("date", "")}).'
    return AnchorResult(ok=True, summary=summary, facts=facts, citation=item.get("source"))


def sel_gbp_unverified(t, category, merchant, customer, now):
    p = t.get("payload", {})
    verified = merchant.get("identity", {}).get("verified")
    if verified:
        return AnchorResult(ok=False, skip_reason="merchant is already verified; trigger not applicable")
    facts = {"verified": verified}
    if p.get("verification_path"):
        facts["verification_path"] = p["verification_path"]
    if p.get("estimated_uplift_pct") is not None:
        facts["estimated_uplift_pct"] = p["estimated_uplift_pct"]
    summary = "Google Business Profile is not yet verified."
    if p.get("estimated_uplift_pct") is not None:
        summary += f" Verification is associated with an estimated {p['estimated_uplift_pct'] * 100:.0f}% visibility uplift."
    return AnchorResult(ok=True, summary=summary, facts=facts)


# ---------------------------------------------------------------------------
# Merchant-scope, internally-derivable selectors (payload OR live merchant
# state, since both are real data we were actually given)
# ---------------------------------------------------------------------------

def sel_perf_dip(t, category, merchant, customer, now):
    p = t.get("payload", {})
    metric, delta = p.get("metric"), p.get("delta_pct")
    if metric is None or delta is None:
        d7 = merchant.get("performance", {}).get("delta_7d", {}) or {}
        candidates = [(k, v) for k, v in d7.items() if v is not None and v < -0.10]
        if not candidates:
            return AnchorResult(ok=False, skip_reason="no material dip in merchant performance data")
        metric, delta = min(candidates, key=lambda kv: kv[1])
        metric = metric.replace("_pct", "")
    facts = {"metric": metric, "delta_pct": delta, "window": p.get("window", "7d"), "vs_baseline": p.get("vs_baseline")}
    summary = f"{metric} down {abs(delta) * 100:.0f}% over {p.get('window', '7d')}"
    if p.get("vs_baseline") is not None:
        summary += f" (baseline {p['vs_baseline']})"
    summary += "."
    return AnchorResult(ok=True, summary=summary, facts=facts)


def sel_seasonal_perf_dip(t, category, merchant, customer, now):
    p = t.get("payload", {})
    if p.get("delta_pct") is None:
        return sel_perf_dip(t, category, merchant, customer, now)
    facts = {k: p[k] for k in ("metric", "delta_pct", "window", "is_expected_seasonal", "season_note") if k in p}
    summary = f"{p.get('metric', 'views')} down {abs(p.get('delta_pct', 0)) * 100:.0f}% over {p.get('window', '7d')}"
    if p.get("is_expected_seasonal"):
        summary += " — flagged as a normal seasonal pattern"
        if p.get("season_note"):
            summary += f" ({p['season_note']})"
    summary += "."
    return AnchorResult(ok=True, summary=summary, facts=facts)


def sel_perf_spike(t, category, merchant, customer, now):
    p = t.get("payload", {})
    metric, delta = p.get("metric"), p.get("delta_pct")
    if metric is None or delta is None:
        d7 = merchant.get("performance", {}).get("delta_7d", {}) or {}
        candidates = [(k, v) for k, v in d7.items() if v is not None and v > 0.10]
        if not candidates:
            return AnchorResult(ok=False, skip_reason="no material spike in merchant performance data")
        metric, delta = max(candidates, key=lambda kv: kv[1])
        metric = metric.replace("_pct", "")
    facts = {"metric": metric, "delta_pct": delta, "window": p.get("window", "7d"),
             "vs_baseline": p.get("vs_baseline"), "likely_driver": p.get("likely_driver")}
    summary = f"{metric} up {abs(delta) * 100:.0f}% over {p.get('window', '7d')}"
    if p.get("likely_driver"):
        summary += f", likely driver: {p['likely_driver']}"
    summary += "."
    return AnchorResult(ok=True, summary=summary, facts=facts)


def sel_milestone(t, category, merchant, customer, now):
    p = t.get("payload", {})
    metric, value_now, milestone_value = p.get("metric"), p.get("value_now"), p.get("milestone_value")
    if metric and value_now is not None and milestone_value is not None:
        facts = {"metric": metric, "value_now": value_now, "milestone_value": milestone_value, "is_imminent": p.get("is_imminent")}
        verb = "about to cross" if p.get("is_imminent") else "near"
        summary = f"{metric} at {value_now}, {verb} the {milestone_value} milestone."
        return AnchorResult(ok=True, summary=summary, facts=facts)
    total = merchant.get("customer_aggregate", {}).get("total_unique_ytd")
    if total and total >= 100:
        milestone_value = (total // 100) * 100
        facts = {"metric": "total_unique_ytd", "value_now": total, "milestone_value": milestone_value}
        summary = f"Customer roster at {total} unique patrons YTD, past the {milestone_value} mark."
        return AnchorResult(ok=True, summary=summary, facts=facts)
    return AnchorResult(ok=False, skip_reason="no milestone crossed")


def sel_dormant(t, category, merchant, customer, now):
    p = t.get("payload", {})
    days = p.get("days_since_last_merchant_message")
    last_topic = p.get("last_topic")
    if days is None:
        history = merchant.get("conversation_history", [])
        if not history:
            days = 999
        else:
            timestamps = [_parse_iso(h.get("ts")) for h in history if h.get("ts")]
            timestamps = [d for d in timestamps if d]
            if not timestamps:
                days = 999
            else:
                days = (now - max(timestamps)).days
                last_topic = history[-1].get("body", "")[:80]
    if days < 10:
        return AnchorResult(ok=False, skip_reason="merchant recently engaged; dormancy trigger not applicable")
    facts = {"days_since_last_merchant_message": days, "last_topic": last_topic}
    summary = f"No merchant message in {days} day(s)."
    if last_topic:
        summary += f' Last topic: "{last_topic}".'
    return AnchorResult(ok=True, summary=summary, facts=facts)


def sel_review_theme(t, category, merchant, customer, now):
    p = t.get("payload", {})
    theme, occ = p.get("theme"), p.get("occurrences_30d")
    quote, sentiment = p.get("common_quote"), p.get("trend")
    if theme is None:
        themes = merchant.get("review_themes", [])
        if not themes:
            return AnchorResult(ok=False, skip_reason="no review theme data available")
        top = max(themes, key=lambda x: x.get("occurrences_30d", 0))
        theme, occ = top.get("theme"), top.get("occurrences_30d")
        quote, sentiment = top.get("common_quote"), top.get("sentiment")
    facts = {"theme": theme, "occurrences_30d": occ, "quote": quote, "sentiment": sentiment}
    summary = f'Review theme "{theme}" appeared {occ} time(s) in the last 30 days'
    if quote:
        summary += f' (e.g. "{quote}")'
    summary += "."
    return AnchorResult(ok=True, summary=summary, facts=facts)


def sel_renewal_due(t, category, merchant, customer, now):
    p = t.get("payload", {})
    days_remaining = p.get("days_remaining", merchant.get("subscription", {}).get("days_remaining"))
    if days_remaining is None or days_remaining > 30:
        return AnchorResult(ok=False, skip_reason="renewal not imminent")
    plan = p.get("plan", merchant.get("subscription", {}).get("plan"))
    facts = {"days_remaining": days_remaining, "plan": plan, "renewal_amount": p.get("renewal_amount")}
    summary = f"Subscription ({plan}) renews in {days_remaining} day(s)."
    if p.get("renewal_amount"):
        summary += f" Renewal amount: {p['renewal_amount']}."
    return AnchorResult(ok=True, summary=summary, facts=facts)


def sel_winback_eligible(t, category, merchant, customer, now):
    p = t.get("payload", {})
    facts = {k: p[k] for k in ("days_since_expiry", "perf_dip_pct", "lapsed_customers_added_since_expiry") if k in p}
    if not facts:
        sub = merchant.get("subscription", {})
        if sub.get("status") != "expired":
            return AnchorResult(ok=False, skip_reason="merchant subscription is not expired")
        facts = {"days_since_expiry": sub.get("days_since_expiry")}
    summary = "Subscription lapsed"
    if facts.get("days_since_expiry") is not None:
        summary += f" {facts['days_since_expiry']} day(s) ago"
    if facts.get("perf_dip_pct") is not None:
        summary += f"; visibility down {abs(facts['perf_dip_pct']) * 100:.0f}% since"
    summary += "."
    return AnchorResult(ok=True, summary=summary, facts=facts)


def sel_curious_ask(t, category, merchant, customer, now):
    p = t.get("payload", {})
    facts = {"ask_template": p.get("ask_template"), "last_ask_at": p.get("last_ask_at"),
             "active_offers": _active_offer_titles(merchant)}
    summary = "Weekly curiosity-ask cadence — no external fact required; ask the merchant one low-stakes question."
    return AnchorResult(ok=True, summary=summary, facts=facts)


def sel_active_planning_intent(t, category, merchant, customer, now):
    p = t.get("payload", {})
    topic, last_msg = p.get("intent_topic"), p.get("merchant_last_message")
    if not topic:
        return AnchorResult(ok=False, skip_reason="no planning-intent topic in trigger payload")
    # intent_topic is an internal snake_case identifier (e.g.
    # "corporate_bulk_thali_package"), never meant to be read as-is -- render
    # it as plain words for the summary/prompt so it doesn't leak into the
    # composed message verbatim. The merchant's own last_message (real,
    # already-natural text) remains the stronger anchor either way.
    topic_readable = str(topic).replace("_", " ")
    facts = {"intent_topic": topic_readable, "merchant_last_message": last_msg}
    summary = f'Merchant is actively planning: {topic_readable}.'
    if last_msg:
        summary += f' Their last message: "{last_msg}".'
    return AnchorResult(ok=True, summary=summary, facts=facts)


# ---------------------------------------------------------------------------
# Customer-scope selectors — always gate on consent
# ---------------------------------------------------------------------------

def _consented(customer: dict, allowed_scopes: tuple[str, ...]) -> bool:
    scope = customer.get("consent", {}).get("scope", [])
    if scope:
        return any(s in scope for s in allowed_scopes)
    # generated customers only carry `preferences.reminder_opt_in`
    return bool(customer.get("preferences", {}).get("reminder_opt_in", False))


def sel_recall_due(t, category, merchant, customer, now):
    if customer is None:
        return AnchorResult(ok=False, skip_reason="no customer context available for a customer-scoped trigger")
    if not _consented(customer, ("recall_reminders", "appointment_reminders")):
        return AnchorResult(ok=False, skip_reason="customer has not consented to recall/appointment reminders")
    p = t.get("payload", {})
    facts = {k: p[k] for k in ("service_due", "last_service_date", "due_date", "available_slots") if k in p}
    offers = _active_offer_titles(merchant)
    facts["active_offer"] = offers[0] if offers else None
    summary = f"Recall due: {p.get('service_due', '')}, last serviced {p.get('last_service_date', '')}, due {p.get('due_date', '')}."
    return AnchorResult(ok=True, summary=summary, facts=facts)


def sel_customer_lapsed(t, category, merchant, customer, now):
    if customer is None:
        return AnchorResult(ok=False, skip_reason="no customer context available for a customer-scoped trigger")
    if not _consented(customer, ("promotional_offers", "recall_reminders", "appointment_reminders")):
        return AnchorResult(ok=False, skip_reason="customer has not consented to outreach")
    p = t.get("payload", {})
    days = p.get("days_since_last_visit")
    if days is None:
        last_visit = _parse_iso(customer.get("relationship", {}).get("last_visit"))
        days = (now.date() - last_visit.date()).days if last_visit else None
    facts = {"days_since_last_visit": days, "previous_focus": p.get("previous_focus"),
             "previous_membership_months": p.get("previous_membership_months")}
    offers = _active_offer_titles(merchant)
    facts["active_offer"] = offers[0] if offers else None
    summary = f"Customer state: {customer.get('state')}"
    if days is not None:
        summary += f", {days} day(s) since last visit"
    summary += "."
    if p.get("previous_focus"):
        summary += f" Previous focus: {p['previous_focus']}."
    return AnchorResult(ok=True, summary=summary, facts=facts)


def sel_appointment_tomorrow(t, category, merchant, customer, now):
    if customer is None:
        return AnchorResult(ok=False, skip_reason="no customer context available")
    if not _consented(customer, ("appointment_reminders",)):
        return AnchorResult(ok=False, skip_reason="customer has not consented to appointment reminders")
    p = t.get("payload", {})
    real = {k: v for k, v in p.items() if k not in ("placeholder", "metric_or_topic") and v is not None}
    if not real:
        return AnchorResult(ok=False, skip_reason="no verified appointment specifics in trigger payload")
    summary = "Appointment confirmed for tomorrow: " + ", ".join(f"{k}={v}" for k, v in real.items())
    return AnchorResult(ok=True, summary=summary, facts=real)


def sel_chronic_refill(t, category, merchant, customer, now):
    if customer is None:
        return AnchorResult(ok=False, skip_reason="no customer context available")
    p = t.get("payload", {})
    if not p.get("molecule_list"):
        return AnchorResult(ok=False, skip_reason="no verified refill specifics in trigger payload")
    facts = {k: p[k] for k in ("molecule_list", "last_refill", "stock_runs_out_iso", "delivery_address_saved") if k in p}
    summary = f"Chronic refill due: {', '.join(p['molecule_list'])}, stock runs out {p.get('stock_runs_out_iso', '')}."
    return AnchorResult(ok=True, summary=summary, facts=facts)


def sel_trial_followup(t, category, merchant, customer, now):
    p = t.get("payload", {})
    if p.get("trial_date") or p.get("next_session_options"):
        facts = {k: p[k] for k in ("trial_date", "next_session_options") if k in p}
        summary = f"Trial completed on {p.get('trial_date', '')}."
        return AnchorResult(ok=True, summary=summary, facts=facts)
    if customer and customer.get("state") == "new":
        facts = {"first_visit": customer.get("relationship", {}).get("first_visit")}
        return AnchorResult(ok=True, summary="Customer's trial/first visit is complete; time for a follow-up.", facts=facts)
    return AnchorResult(ok=False, skip_reason="no trial-followup specifics available")


def sel_wedding_followup(t, category, merchant, customer, now):
    p = t.get("payload", {})
    if not p.get("wedding_date"):
        return AnchorResult(ok=False, skip_reason="no wedding date in trigger payload")
    facts = {k: p[k] for k in ("wedding_date", "trial_completed", "days_to_wedding", "next_step_window_open") if k in p}
    summary = f"Wedding on {p['wedding_date']}, {p.get('days_to_wedding', '?')} day(s) away."
    if p.get("trial_completed"):
        summary += " Bridal trial already completed."
    return AnchorResult(ok=True, summary=summary, facts=facts)


def sel_ipl_match(t, category, merchant, customer, now):
    p = t.get("payload", {})
    if not p.get("match"):
        return AnchorResult(ok=False, skip_reason="no match specifics in trigger payload")
    facts = {k: p[k] for k in ("match", "venue", "city", "match_time_iso", "is_weeknight") if k in p}
    summary = f"{p['match']} at {p.get('venue', '')}, {p.get('match_time_iso', '')}."
    if p.get("is_weeknight") is False:
        summary += " This is a weekend match — historically softer dine-in demand."
    return AnchorResult(ok=True, summary=summary, facts=facts)


def sel_unplanned_slot(t, category, merchant, customer, now):
    p = t.get("payload", {})
    real = {k: v for k, v in p.items() if k not in ("placeholder", "metric_or_topic") and v is not None}
    if not real:
        return AnchorResult(ok=False, skip_reason="no verified open-slot specifics in trigger payload")
    summary = "Unplanned open slot: " + ", ".join(f"{k}={v}" for k, v in real.items())
    return AnchorResult(ok=True, summary=summary, facts=real)


def sel_generic_fallback(t, category, merchant, customer, now):
    p = t.get("payload", {})
    real = {k: v for k, v in p.items() if k not in ("placeholder", "metric_or_topic") and v is not None}
    if real:
        return AnchorResult(ok=True, summary=f"Trigger payload: {json.dumps(real, default=str)}.", facts=real)
    return AnchorResult(ok=False, skip_reason=f"trigger kind '{t.get('kind')}' has no concrete grounded data to act on")


KIND_SELECTORS: dict[str, Callable] = {
    "research_digest": sel_research_digest,
    "regulation_change": sel_regulation_change,
    "category_trend_movement": sel_category_trend,
    "category_seasonal": sel_category_seasonal,
    "festival_upcoming": sel_festival,
    "competitor_opened": sel_competitor_opened,
    "supply_alert": sel_supply_alert,
    "cde_opportunity": sel_cde_opportunity,
    "gbp_unverified": sel_gbp_unverified,
    "perf_dip": sel_perf_dip,
    "seasonal_perf_dip": sel_seasonal_perf_dip,
    "perf_spike": sel_perf_spike,
    "milestone_reached": sel_milestone,
    "dormant_with_vera": sel_dormant,
    "review_theme_emerged": sel_review_theme,
    "renewal_due": sel_renewal_due,
    "winback_eligible": sel_winback_eligible,
    "curious_ask_due": sel_curious_ask,
    "scheduled_recurring": sel_curious_ask,
    "active_planning_intent": sel_active_planning_intent,
    "recall_due": sel_recall_due,
    "customer_lapsed_soft": sel_customer_lapsed,
    "customer_lapsed_hard": sel_customer_lapsed,
    "appointment_tomorrow": sel_appointment_tomorrow,
    "chronic_refill_due": sel_chronic_refill,
    "trial_followup": sel_trial_followup,
    "wedding_package_followup": sel_wedding_followup,
    "bridal_followup": sel_wedding_followup,
    "ipl_match_today": sel_ipl_match,
    "unplanned_slot_open": sel_unplanned_slot,
}


def select_signal(trigger: dict, category: Optional[dict], merchant: dict,
                   customer: Optional[dict], now: datetime) -> AnchorResult:
    kind = trigger.get("kind", "")
    fn = KIND_SELECTORS.get(kind, sel_generic_fallback)
    try:
        result = fn(trigger, category or {}, merchant or {}, customer, now)
    except Exception as exc:  # never let a bad selector crash the tick
        result = AnchorResult(ok=False, skip_reason=f"selector error: {exc}")
    return result if result is not None else AnchorResult(ok=False, skip_reason="selector returned no result")
