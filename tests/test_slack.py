from triage.slack import approval_message, edit_modal, sign_request, verify_signature

SECRET = "test-signing-secret"
BODY = b"payload=%7B%22type%22%3A%22block_actions%22%7D"
NOW = 1_800_000_000


def sig(ts=NOW, body=BODY, secret=SECRET):
    return sign_request(secret, str(ts), body)


def test_valid_signature():
    assert verify_signature(SECRET, str(NOW), BODY, sig(), now=NOW + 10)


def test_known_vector():
    # computed independently with openssl for this exact string
    expected = "v0=" + __import__("hmac").new(b"8f742231b10e8888abcd99yyyzzz85a5", b"v0:1531420618:token=xyzz0WbapA4vBCDEFasx0q6G", "sha256").hexdigest()
    assert sign_request("8f742231b10e8888abcd99yyyzzz85a5", "1531420618", b"token=xyzz0WbapA4vBCDEFasx0q6G") == expected


def test_wrong_secret_tampered_body_and_stale_timestamp_fail():
    assert not verify_signature("other", str(NOW), BODY, sig(), now=NOW)
    assert not verify_signature(SECRET, str(NOW), BODY + b"x", sig(), now=NOW)
    assert not verify_signature(SECRET, str(NOW), BODY, sig(), now=NOW + 301)
    assert not verify_signature(SECRET, str(NOW), BODY, sig(), now=NOW - 301)


def test_missing_or_garbage_inputs_fail():
    assert not verify_signature(SECRET, "", BODY, sig(), now=NOW)
    assert not verify_signature(SECRET, "abc", BODY, sig(), now=NOW)
    assert not verify_signature(SECRET, str(NOW), BODY, "", now=NOW)
    assert not verify_signature("", str(NOW), BODY, sig(), now=NOW)


TRIAGE = {
    "category": "billing", "priority": "urgent", "sentiment": "negative", "language": "en",
    "summary": "Customer threatens a chargeback <b>now</b>.",
    "extracted": {"name": "Julia", "company": None, "order_id": "NB-10555", "invoice_number": None,
                  "product": None, "requested_action": "refund", "deadline": "tomorrow"},
    "draft_reply": "Hello Julia,\n\nWe will look into it.", "confidence": 0.9, "reasons": ["x"],
    "meta": {},
}


def test_approval_message_has_three_buttons_carrying_the_ticket_id():
    msg = approval_message("T-1", "julia@example.com", "Chargeback", TRIAGE)
    actions = [b for b in msg["blocks"] if b["type"] == "actions"][0]["elements"]
    assert [a["action_id"] for a in actions] == ["approve_reply", "edit_reply", "reject_reply"]
    assert all(a["value"] == "T-1" for a in actions)
    assert msg["blocks"][0]["text"]["text"].startswith("URGENT")


def test_slack_control_characters_are_escaped():
    msg = approval_message("T-1", "julia@example.com", "Hi", TRIAGE)
    text = str(msg)
    assert "<b>" not in text and "&lt;b&gt;" in text


def test_no_draft_means_no_approve_button():
    t = dict(TRIAGE, draft_reply="")
    actions = [b for b in approval_message("T-1", "a@example.com", "s", t)["blocks"] if b["type"] == "actions"][0]["elements"]
    assert [a["action_id"] for a in actions] == ["edit_reply", "reject_reply"]


def test_injection_warning_is_shown():
    t = dict(TRIAGE, meta={"injection_suspected": True})
    assert "aimed at the AI" in str(approval_message("T-1", "a@example.com", "s", t))


def test_long_text_stays_under_slack_limit():
    t = dict(TRIAGE, draft_reply="word " * 1500)
    for b in approval_message("T-1", "a@example.com", "s", t)["blocks"]:
        if b["type"] == "section" and "text" in b:
            assert len(b["text"]["text"]) <= 3000


def test_edit_modal_carries_ticket_and_draft():
    v = edit_modal("T-9", "Subject", "Hello")
    assert v["private_metadata"] == "T-9"
    assert v["blocks"][1]["element"]["initial_value"] == "Hello"
