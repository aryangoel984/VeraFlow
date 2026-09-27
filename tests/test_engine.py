from datetime import datetime, timezone

import pytest

from app.engine import composer, validator
from app.engine.signal_selector import select_signal

NOW = datetime(2026, 4, 26, 10, 30, tzinfo=timezone.utc)


def test_perf_dip_skips_when_no_material_dip():
    trigger = {"kind": "perf_dip", "scope": "merchant", "payload": {"placeholder": True}}
    merchant = {"performance": {"delta_7d": {"views_pct": 0.02, "calls_pct": -0.03}}}
    result = select_signal(trigger, {}, merchant, None, NOW)
    assert result.ok is False


def test_perf_dip_derives_from_merchant_performance_when_payload_is_placeholder():
    trigger = {"kind": "perf_dip", "scope": "merchant", "payload": {"placeholder": True}}
    merchant = {"performance": {"delta_7d": {"views_pct": 0.02, "calls_pct": -0.45}}}
    result = select_signal(trigger, {}, merchant, None, NOW)
    assert result.ok is True
    assert result.facts["metric"] == "calls"
    assert "45%" in result.summary


def test_research_digest_requires_real_category_digest_item():
    trigger = {"kind": "research_digest", "scope": "merchant", "payload": {"top_item_id": "missing"}}
    category = {"digest": []}
    result = select_signal(trigger, category, {}, None, NOW)
    assert result.ok is False


def test_competitor_opened_never_fabricates_a_competitor():
    trigger = {"kind": "competitor_opened", "scope": "merchant", "payload": {"placeholder": True}}
    result = select_signal(trigger, {}, {}, None, NOW)
    assert result.ok is False
    assert "no verified" in result.skip_reason


def test_recall_due_requires_customer_context():
    trigger = {"kind": "recall_due", "scope": "customer", "payload": {"service_due": "cleaning"}}
    result = select_signal(trigger, {}, {}, None, NOW)
    assert result.ok is False


def test_recall_due_requires_consent():
    trigger = {"kind": "recall_due", "scope": "customer", "payload": {"service_due": "cleaning", "due_date": "2026-05-01"}}
    customer_no_consent = {"consent": {"scope": []}, "preferences": {"reminder_opt_in": False}}
    result = select_signal(trigger, {}, {}, customer_no_consent, NOW)
    assert result.ok is False
    assert "consent" in result.skip_reason


def test_recall_due_ok_with_consent():
    trigger = {"kind": "recall_due", "scope": "customer",
               "payload": {"service_due": "cleaning", "last_service_date": "2025-11-01",
                            "due_date": "2026-05-01", "available_slots": []}}
    customer = {"consent": {"scope": ["recall_reminders"]}}
    result = select_signal(trigger, {}, {}, customer, NOW)
    assert result.ok is True


def test_gbp_unverified_skips_if_already_verified():
    trigger = {"kind": "gbp_unverified", "scope": "merchant", "payload": {}}
    merchant = {"identity": {"verified": True}}
    result = select_signal(trigger, {}, merchant, None, NOW)
    assert result.ok is False


def test_unknown_kind_falls_back_generically_with_real_payload():
    trigger = {"kind": "some_brand_new_kind_the_judge_invented", "scope": "merchant",
               "payload": {"cool_new_fact": 42}}
    result = select_signal(trigger, {}, {}, None, NOW)
    assert result.ok is True
    assert "cool_new_fact" in result.summary


def test_unknown_kind_with_placeholder_payload_skips():
    trigger = {"kind": "some_brand_new_kind", "scope": "merchant", "payload": {"placeholder": True}}
    result = select_signal(trigger, {}, {}, None, NOW)
    assert result.ok is False


# ---------------------------------------------------------------------------
# validator
# ---------------------------------------------------------------------------

def test_validator_catches_hallucinated_number():
    blob = validator.build_grounding_blob({"ctr": 0.021}, {"views": 2410})
    result = validator.validate_body("Your CTR jumped to 99.9% today!", blob, [], [])
    assert result.ok is False
    assert any("unverified number" in n for n in result.notes)


def test_validator_allows_numbers_present_in_context():
    blob = validator.build_grounding_blob({"trial_n": 2100}, {"views": 2410})
    result = validator.validate_body("The trial had 2100 participants.", blob, [], [])
    assert result.ok is True


def test_validator_rejects_taboo_words():
    blob = validator.build_grounding_blob({})
    result = validator.validate_body("This treatment is 100% safe and guaranteed!", blob,
                                       ["guaranteed", "100% safe"], [])
    assert result.ok is False


def test_validator_rejects_urls():
    blob = validator.build_grounding_blob({})
    result = validator.validate_body("Read more: https://example.com", blob, [], [])
    assert result.ok is False


def test_validator_rejects_multiple_ctas():
    blob = validator.build_grounding_blob({})
    result = validator.validate_body("Want me to draft this? Should I also schedule it?", blob, [], [])
    assert result.ok is False


def test_validator_rejects_repeated_body():
    blob = validator.build_grounding_blob({})
    result = validator.validate_body("Hello there.", blob, [], ["Hello there."])
    assert result.ok is False


# ---------------------------------------------------------------------------
# composer (mocking the LLM boundary)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_composer_falls_back_when_llm_hallucinates(monkeypatch):
    async def fake_complete_json(system, prompt, max_tokens=500):
        return {"body": "Amazing! 99999 customers love this!", "rationale": "fabricated"}

    monkeypatch.setattr("app.llm.client.is_available", lambda: True)
    monkeypatch.setattr("app.llm.client.complete_json", fake_complete_json)

    brief = {
        "merchant_name": "Test Clinic", "owner_first_name": "Meera", "cta_type": "open_ended",
        "anchor_summary": "CTR is 2.1% vs peer 3.0%.", "anchor_facts": {"ctr": 0.021, "peer_ctr": 0.030},
        "voice": {}, "send_as": "vera", "customer": None,
    }
    grounding_blob = validator.build_grounding_blob(brief["anchor_facts"])
    result = await composer.compose(brief, grounding_blob, [], [], business_rationale="fallback rationale")

    assert "99999" not in result["body"]
    assert result["used_llm"] is False
    assert "2.1" in result["body"] or "CTR" in result["body"]


@pytest.mark.asyncio
async def test_composer_uses_llm_output_when_grounded(monkeypatch):
    async def fake_complete_json(system, prompt, max_tokens=500):
        return {"body": "Meera, your CTR is 2.1% vs peer 3.0%. Want a fix?", "rationale": "grounded"}

    monkeypatch.setattr("app.llm.client.is_available", lambda: True)
    monkeypatch.setattr("app.llm.client.complete_json", fake_complete_json)

    brief = {
        "merchant_name": "Test Clinic", "owner_first_name": "Meera", "cta_type": "open_ended",
        "anchor_summary": "CTR is 2.1% vs peer 3.0%.", "anchor_facts": {"ctr": 0.021, "peer_ctr": 0.030},
        "voice": {}, "send_as": "vera", "customer": None,
    }
    grounding_blob = validator.build_grounding_blob(brief["anchor_facts"])
    result = await composer.compose(brief, grounding_blob, [], [], business_rationale="fallback rationale")

    assert result["used_llm"] is True
    assert "2.1" in result["body"]


@pytest.mark.asyncio
async def test_composer_falls_back_without_llm_configured(monkeypatch):
    monkeypatch.setattr("app.llm.client.is_available", lambda: False)
    brief = {
        "merchant_name": "Test Clinic", "owner_first_name": "Meera", "cta_type": "binary_yes_no",
        "anchor_summary": "Subscription renews in 5 days.", "anchor_facts": {"days_remaining": 5},
        "voice": {}, "send_as": "vera", "customer": None,
    }
    grounding_blob = validator.build_grounding_blob(brief["anchor_facts"])
    result = await composer.compose(brief, grounding_blob, [], [], business_rationale="renewal reminder")
    assert result["used_llm"] is False
    assert result["body"]
