import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import ScriptedClient, good_output
from triage.app import create_app
from triage.config import Settings
from triage.llm import LLMError


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))  # mock model


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["mock"] is True


def test_triage_returns_strict_schema(client):
    r = client.post("/triage", json={"from": "Dana <dana@example.com>", "subject": "Where is my order NB-10482?",
                                     "body": "It has not arrived.\n\nThanks,\nDana Ortiz", "thread": []})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"category", "priority", "sentiment", "language", "summary", "extracted",
                         "draft_reply", "confidence", "reasons", "meta"}
    assert set(body["extracted"]) == {"name", "company", "order_id", "invoice_number", "product",
                                      "requested_action", "deadline"}
    assert body["category"] == "support" and body["extracted"]["order_id"] == "NB-10482"


def test_missing_field_is_422(client):
    assert client.post("/triage", json={"subject": "x"}).status_code == 422


def test_model_outage_is_502(settings):
    class Down(ScriptedClient):
        def complete(self, system, messages):
            raise LLMError("down")

    app = create_app(settings, Down())
    r = TestClient(app).post("/triage", json={"from": "a@example.com", "subject": "s", "body": "Where is my order?"})
    assert r.status_code == 502


def test_api_key_is_enforced_when_configured():
    s = Settings("mock", "m", "", "", 5, 6000, "s3cret", "WARNING")
    c = TestClient(create_app(s))
    payload = {"from": "a@example.com", "subject": "s", "body": "hello"}
    assert c.post("/triage", json=payload).status_code == 401
    assert c.post("/triage", json=payload, headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.post("/triage", json=payload, headers={"X-API-Key": "s3cret"}).status_code == 200
    assert c.get("/health").status_code == 200


def test_approval_message_endpoint(client):
    t = client.post("/triage", json={"from": "a@example.com", "subject": "s", "body": "Where is my order NB-10482?"}).json()
    r = client.post("/slack/approval-message", json={"ticket_id": "T-1", "from": "a@example.com", "subject": "s", "triage": t})
    assert r.status_code == 200 and r.json()["blocks"][-2]["type"] == "actions"


def test_edit_modal_and_urgent_alert_endpoints(client):
    v = client.post("/slack/edit-modal", json={"ticket_id": "T-1", "subject": "s", "draft_reply": "hi"}).json()["view"]
    assert v["callback_id"] == "edit_reply_submit"
    a = client.post("/slack/urgent-alert", json={"ticket_id": "T-1", "from": "a@example.com", "category": "billing", "summary": "Chargeback threat"}).json()
    assert "<!here>" in a["slack_text"] and len(a["sms_text"]) <= 160


def test_digest_endpoint(client):
    tickets = [
        {"ticket_id": "T-1", "created_at": "2026-11-21T09:00:00", "category": "billing", "priority": "urgent", "status": "pending_approval", "from": "a@example.com", "subject": "s"},
        {"ticket_id": "T-2", "created_at": "2026-11-21T10:00:00", "category": "support", "priority": "normal", "status": "sent"},
        {"ticket_id": "T-3", "created_at": "2026-11-20T10:00:00", "category": "support", "priority": "urgent", "status": "pending_approval"},
    ]
    d = client.post("/digest", json={"date": "2026-11-21", "tickets": tickets}).json()
    assert d["stats"]["total"] == 2
    assert d["stats"]["by_category"]["billing"] == 1
    assert [u["ticket_id"] for u in d["stats"]["unanswered_urgent"]] == ["T-3", "T-1"]
    assert client.post("/digest", json={"date": "yesterday", "tickets": []}).status_code == 422
