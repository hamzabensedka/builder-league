"""D7: /api/decision router over TestClient — decide round trip, validation,
decisions list, one-click demo seed."""

import pytest
from fastapi.testclient import TestClient

from api.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def _seed(client):
    r = client.post("/api/decision/demo")
    assert r.status_code == 200
    return r.json()


# --- demo seed ---------------------------------------------------------------

def test_demo_seeds_three_domains(client):
    data = _seed(client)
    assert data["triage_key"] and data["deploy_key"] and data["mod_key"]
    assert len(data["beats"]) >= 4


# --- decide round trip: EXECUTE on a clean refund ----------------------------

def test_decide_execute_clean_refund(client):
    keys = _seed(client)
    r = client.post("/api/decision/decide", json={
        "domain": "refund", "action": "issue_refund",
        "actor_key": keys["triage_key"], "amount": 120,
        "context": {"invoice_id": "INV-1", "reason": "defective"},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "execute"
    assert 0.0 <= body["confidence"] <= 1.0
    assert 0.0 <= body["risk"] <= 1.0
    assert len(body["signals"]) >= 5
    assert body["llm_called"] is False
    assert body["receipt_id"]


# --- decide: ASK names the missing field --------------------------------------

def test_decide_ask_names_missing(client):
    keys = _seed(client)
    r = client.post("/api/decision/decide", json={
        "domain": "refund", "action": "issue_refund",
        "actor_key": keys["triage_key"], "amount": 2400,
        "context": {"reason": "defective"},  # invoice_id missing
    })
    body = r.json()
    assert body["outcome"] != "execute"
    assert "invoice_id" in body["missing_information"]


# --- decide: ESCALATE irreversible over-threshold deploy -----------------------

def test_decide_escalate_deploy(client):
    keys = _seed(client)
    r = client.post("/api/decision/decide", json={
        "domain": "deploy", "action": "deploy_production",
        "actor_key": keys["deploy_key"], "amount": 8000,
        "context": {"tests_passing": True, "approvals": 2, "change_ticket": "CHG-1"},
    })
    body = r.json()
    assert body["outcome"] == "escalate"
    assert body["reversibility"]["partial"] is True


# --- validation ---------------------------------------------------------------

def test_unknown_domain_422(client):
    _seed(client)
    r = client.post("/api/decision/decide", json={
        "domain": "nope", "action": "x", "actor_key": "k", "amount": 1,
    })
    assert r.status_code == 422


def test_unknown_action_422(client):
    keys = _seed(client)
    r = client.post("/api/decision/decide", json={
        "domain": "refund", "action": "not_an_action",
        "actor_key": keys["triage_key"], "amount": 1,
    })
    assert r.status_code == 422


def test_negative_amount_422(client):
    keys = _seed(client)
    r = client.post("/api/decision/decide", json={
        "domain": "refund", "action": "issue_refund",
        "actor_key": keys["triage_key"], "amount": -5,
        "context": {"invoice_id": "I", "reason": "r"},
    })
    assert r.status_code == 422


# --- decisions list + domains catalog ------------------------------------------

def test_list_decisions_and_domains(client):
    keys = _seed(client)
    client.post("/api/decision/decide", json={
        "domain": "refund", "action": "issue_refund",
        "actor_key": keys["triage_key"], "amount": 50,
        "context": {"invoice_id": "I", "reason": "r"},
    })
    lst = client.get("/api/decision/decisions").json()
    assert lst["decisions"] and lst["decisions"][0]["outcome"]
    doms = client.get("/api/decision/domains").json()
    names = {d["domain"] for d in doms["domains"]}
    assert names == {"refund", "deploy", "moderation"}
