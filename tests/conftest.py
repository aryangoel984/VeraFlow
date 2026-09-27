import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.storage.state import state

DATASET_DIR = Path(__file__).parent.parent / "dataset"


@pytest.fixture(autouse=True)
def reset_state():
    state.reset()
    yield
    state.reset()


@pytest.fixture(autouse=True)
def no_ambient_llm_key(monkeypatch):
    """The test suite must never depend on (or spend) a real LLM key that
    happens to be sitting in a developer's .env — strip it for every test.
    Tests that specifically want to exercise the LLM code path mock
    app.llm.client.is_available/complete_json directly instead."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def dentists_category():
    return json.load(open(DATASET_DIR / "categories" / "dentists.json"))


@pytest.fixture
def seed_merchants():
    return json.load(open(DATASET_DIR / "merchants_seed.json"))["merchants"]


@pytest.fixture
def seed_customers():
    return json.load(open(DATASET_DIR / "customers_seed.json"))["customers"]


@pytest.fixture
def seed_triggers():
    return json.load(open(DATASET_DIR / "triggers_seed.json"))["triggers"]


@pytest.fixture
def dr_meera(seed_merchants):
    return next(m for m in seed_merchants if m["merchant_id"] == "m_001_drmeera_dentist_delhi")


@pytest.fixture
def priya(seed_customers):
    return next(c for c in seed_customers if c["customer_id"] == "c_001_priya_for_m001")


def push(client, scope, cid, version, payload):
    return client.post("/v1/context", json={
        "scope": scope, "context_id": cid, "version": version,
        "payload": payload, "delivered_at": "2026-04-26T09:45:00Z",
    })
