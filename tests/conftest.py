import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from triage.config import Settings  # noqa: E402
from triage.pipeline import EmailIn, TriageEngine  # noqa: E402


@pytest.fixture
def settings():
    return Settings("mock", "mock-heuristic-v1", "", "", 5, 6000, "", "WARNING")


def good_output(**over):
    data = {
        "category": "support", "priority": "normal", "sentiment": "neutral", "language": "en",
        "summary": "Customer asks about a delivery.",
        "extracted": {"name": "Dana", "company": None, "order_id": "NB-10482", "invoice_number": None,
                      "product": None, "requested_action": "order_status", "deadline": None},
        "draft_reply": "Hello Dana,\n\nThanks for writing. A team member will look into your order and reply personally.\n\nKind regards,\nNorthbeam Outdoor Gear Support",
        "confidence": 0.8, "reasons": ["asks about delivery"],
    }
    data.update(over)
    return json.dumps(data)


class ScriptedClient:
    """Returns queued replies in order and records what it was sent."""

    name = "scripted"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, system, messages):
        self.calls.append((system, [dict(m) for m in messages]))
        return self.replies.pop(0)


@pytest.fixture
def make_engine(settings):
    def _make(*replies):
        client = ScriptedClient(*replies)
        return TriageEngine(client, settings), client
    return _make


def email(**kw):
    base = {"from": "Dana <dana@example.com>", "subject": "Where is my order", "body": "Hi, order NB-10482 has not arrived.\n\nDana"}
    base.update(kw)
    return EmailIn(**base)
