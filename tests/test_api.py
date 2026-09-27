from tests.conftest import push


def test_healthz_starts_empty(client):
    r = client.get("/v1/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["contexts_loaded"] == {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}


def test_metadata_shape(client):
    r = client.get("/v1/metadata")
    assert r.status_code == 200
    body = r.json()
    for key in ("team_name", "team_members", "model", "approach", "contact_email", "version", "submitted_at"):
        assert key in body


def test_context_push_accept_and_counts(client, dentists_category, dr_meera):
    r = push(client, "category", "dentists", 1, dentists_category)
    assert r.status_code == 200 and r.json()["accepted"] is True
    r = push(client, "merchant", dr_meera["merchant_id"], 1, dr_meera)
    assert r.status_code == 200 and r.json()["accepted"] is True

    health = client.get("/v1/healthz").json()
    assert health["contexts_loaded"]["category"] == 1
    assert health["contexts_loaded"]["merchant"] == 1


def test_context_same_version_is_409_stale(client, dr_meera):
    push(client, "merchant", dr_meera["merchant_id"], 1, dr_meera)
    r = push(client, "merchant", dr_meera["merchant_id"], 1, dr_meera)
    assert r.status_code == 409
    body = r.json()
    assert body["accepted"] is False
    assert body["reason"] == "stale_version"
    assert body["current_version"] == 1


def test_context_version_bump_replaces(client, dr_meera):
    push(client, "merchant", dr_meera["merchant_id"], 1, dr_meera)
    updated = dict(dr_meera)
    updated["performance"] = {**dr_meera["performance"], "views": 9999}
    r = push(client, "merchant", dr_meera["merchant_id"], 2, updated)
    assert r.status_code == 200 and r.json()["accepted"] is True

    health = client.get("/v1/healthz").json()
    assert health["contexts_loaded"]["merchant"] == 1  # replaced, not duplicated


def test_context_lower_version_rejected(client, dr_meera):
    push(client, "merchant", dr_meera["merchant_id"], 3, dr_meera)
    r = push(client, "merchant", dr_meera["merchant_id"], 2, dr_meera)
    assert r.status_code == 409
    assert r.json()["current_version"] == 3


def test_context_invalid_scope(client):
    r = client.post("/v1/context", json={
        "scope": "bogus", "context_id": "x", "version": 1, "payload": {}, "delivered_at": "x",
    })
    assert r.status_code == 400
    assert r.json()["accepted"] is False
    assert r.json()["reason"] == "invalid_scope"


def test_context_payload_too_large(client):
    huge = {"blob": "x" * (600 * 1024)}
    r = client.post("/v1/context", json={
        "scope": "merchant", "context_id": "m_x", "version": 1, "payload": huge, "delivered_at": "x",
    })
    assert r.status_code == 400
    assert r.json()["reason"] == "payload_too_large"


def test_tick_with_no_triggers_returns_empty(client):
    r = client.post("/v1/tick", json={"now": "2026-04-26T10:30:00Z", "available_triggers": []})
    assert r.status_code == 200
    assert r.json()["actions"] == []


def test_tick_unknown_trigger_id_is_safely_ignored(client):
    r = client.post("/v1/tick", json={"now": "2026-04-26T10:30:00Z", "available_triggers": ["trg_does_not_exist"]})
    assert r.status_code == 200
    assert r.json()["actions"] == []


def test_tick_produces_grounded_action_and_then_suppresses(client, dentists_category, dr_meera, seed_triggers):
    trg = next(t for t in seed_triggers if t["id"] == "trg_001_research_digest_dentists")
    push(client, "category", "dentists", 1, dentists_category)
    push(client, "merchant", dr_meera["merchant_id"], 1, dr_meera)
    push(client, "trigger", trg["id"], 1, trg)

    r1 = client.post("/v1/tick", json={"now": "2026-04-26T10:35:00Z", "available_triggers": [trg["id"]]})
    actions = r1.json()["actions"]
    assert len(actions) == 1
    action = actions[0]
    for key in ("conversation_id", "merchant_id", "send_as", "trigger_id", "template_name",
                "template_params", "body", "cta", "suppression_key", "rationale"):
        assert key in action
    assert action["send_as"] == "vera"
    assert action["merchant_id"] == dr_meera["merchant_id"]
    assert "38" in action["body"]  # the specific trial stat should be present, not a generic message

    # a second tick with the same trigger must not resend (suppression_key dedup)
    r2 = client.post("/v1/tick", json={"now": "2026-04-26T10:40:00Z", "available_triggers": [trg["id"]]})
    assert r2.json()["actions"] == []


def test_tick_respects_customer_consent_scope(client, dentists_category, dr_meera, seed_triggers, priya):
    trg = next(t for t in seed_triggers if t["id"] == "trg_003_recall_due_priya")
    push(client, "category", "dentists", 1, dentists_category)
    push(client, "merchant", dr_meera["merchant_id"], 1, dr_meera)
    push(client, "trigger", trg["id"], 1, trg)
    # NOTE: customer context deliberately not pushed yet

    r = client.post("/v1/tick", json={"now": "2026-04-26T11:00:00Z", "available_triggers": [trg["id"]]})
    assert r.json()["actions"] == []  # must not fabricate a customer-facing send with no customer context

    push(client, "customer", priya["customer_id"], 1, priya)
    r2 = client.post("/v1/tick", json={"now": "2026-04-26T11:05:00Z", "available_triggers": [trg["id"]]})
    actions = r2.json()["actions"]
    assert len(actions) == 1
    assert actions[0]["send_as"] == "merchant_on_behalf"
    assert actions[0]["customer_id"] == priya["customer_id"]


def test_reply_auto_reply_escalates_to_end(client):
    conv_id = "conv_auto_test"
    auto_msg = "Thank you for contacting us! Our team will respond shortly."
    outcomes = []
    for i in range(1, 5):
        r = client.post("/v1/reply", json={
            "conversation_id": conv_id, "merchant_id": "m_x", "customer_id": None,
            "from_role": "merchant", "message": auto_msg, "received_at": "x", "turn_number": i + 1,
        })
        outcomes.append(r.json()["action"])
        if r.json()["action"] == "end":
            break
    assert outcomes == ["send", "wait", "end"]


def test_reply_hostile_ends_and_opts_out(client):
    r = client.post("/v1/reply", json={
        "conversation_id": "conv_hostile_test", "merchant_id": "m_hostile", "customer_id": None,
        "from_role": "merchant", "message": "Stop messaging me. This is useless spam.",
        "received_at": "x", "turn_number": 2,
    })
    assert r.json()["action"] == "end"

    from app.storage.state import state
    assert state.is_merchant_opted_out("m_hostile")


def test_reply_deferral_returns_wait(client):
    r = client.post("/v1/reply", json={
        "conversation_id": "conv_defer_test", "merchant_id": "m_x", "customer_id": None,
        "from_role": "merchant", "message": "Maybe next week, I'm busy right now.",
        "received_at": "x", "turn_number": 2,
    })
    body = r.json()
    assert body["action"] == "wait"
    assert body["wait_seconds"] and body["wait_seconds"] > 0


def test_reply_acceptance_switches_to_action_not_qualifying(client):
    r = client.post("/v1/reply", json={
        "conversation_id": "conv_intent_test", "merchant_id": "m_x", "customer_id": None,
        "from_role": "merchant", "message": "Ok lets do it. Whats next?",
        "received_at": "x", "turn_number": 2,
    })
    body = r.json()
    assert body["action"] == "send"
    lowered = body["body"].lower()
    for qualifying_phrase in ("would you say", "do you think", "how about"):
        assert qualifying_phrase not in lowered


def test_reply_on_already_ended_conversation_stays_ended(client):
    conv_id = "conv_ended_test"
    client.post("/v1/reply", json={
        "conversation_id": conv_id, "merchant_id": "m_x", "customer_id": None,
        "from_role": "merchant", "message": "Not interested. Stop messaging me.",
        "received_at": "x", "turn_number": 2,
    })
    r2 = client.post("/v1/reply", json={
        "conversation_id": conv_id, "merchant_id": "m_x", "customer_id": None,
        "from_role": "merchant", "message": "Actually wait, tell me more",
        "received_at": "x", "turn_number": 3,
    })
    assert r2.json()["action"] == "end"
