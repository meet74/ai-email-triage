"""Slack helpers: request signature check and Block Kit builders.

The signature scheme is Slack's v0: HMAC-SHA256 over "v0:{timestamp}:{raw body}".
The n8n approval workflow does the same check in a Code node; this version is
the reference the tests and the e2e script sign with.
"""

import hashlib
import hmac
import time

MAX_AGE_SECONDS = 300
_TEXT_LIMIT = 2800  # Slack rejects section text above 3000 characters


def sign_request(signing_secret: str, timestamp: str, body: bytes) -> str:
    base = b"v0:" + timestamp.encode() + b":" + body
    return "v0=" + hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()


def verify_signature(
    signing_secret: str,
    timestamp: str,
    body: bytes,
    signature: str,
    now: float | None = None,
    max_age: int = MAX_AGE_SECONDS,
) -> bool:
    if not signing_secret or not timestamp or not signature:
        return False
    try:
        age = abs((now if now is not None else time.time()) - int(timestamp))
    except ValueError:
        return False
    if age > max_age:  # stops replay of a captured request
        return False
    return hmac.compare_digest(sign_request(signing_secret, timestamp, body), signature)


def _clip(text: str, limit: int = _TEXT_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _escape(text: str) -> str:
    # Slack treats <, > and & as control characters in mrkdwn
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def approval_message(ticket_id: str, sender: str, subject: str, triage: dict) -> dict:
    meta = triage.get("meta", {})
    urgent = triage["priority"] == "urgent"
    ex = triage["extracted"]
    fields = [
        ("Name", ex.get("name")), ("Company", ex.get("company")), ("Order", ex.get("order_id")),
        ("Invoice", ex.get("invoice_number")), ("Product", ex.get("product")),
        ("Wants", (ex.get("requested_action") or "").replace("_", " ") or None), ("Deadline", ex.get("deadline")),
    ]
    extracted_text = "\n".join(f"*{k}:* {_escape(str(v))}" for k, v in fields if v) or "_nothing extracted_"
    draft = triage.get("draft_reply") or ""

    blocks = [
        {"type": "header", "text": {"type": "plain_text",
         "text": _clip(("URGENT: " if urgent else "") + f"{triage['category'].replace('_', ' ')} email", 150)}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*From*\n{_escape(sender)}"},
            {"type": "mrkdwn", "text": f"*Subject*\n{_escape(subject) or '_(none)_'}"},
            {"type": "mrkdwn", "text": f"*Priority*\n{triage['priority']}"},
            {"type": "mrkdwn", "text": f"*Sentiment / language*\n{triage['sentiment']} / {triage['language']}"},
        ]},
        {"type": "section", "text": {"type": "mrkdwn", "text": _clip(f"*Summary*\n{_escape(triage['summary'])}")}},
        {"type": "section", "text": {"type": "mrkdwn", "text": _clip(f"*Extracted*\n{extracted_text}")}},
    ]
    warnings = []
    if meta.get("injection_suspected"):
        warnings.append("The email contained text aimed at the AI. It was ignored and the draft was replaced with a neutral one. Read the original before approving.")
    if meta.get("degraded"):
        warnings.append("Automatic triage failed for this email. Read it and write the reply with Edit.")
    if meta.get("draft_replaced") and not meta.get("injection_suspected"):
        warnings.append("The first draft broke a reply rule (promise, link or date) and was replaced.")
    if triage["confidence"] < 0.5 and not meta.get("degraded"):
        warnings.append(f"Low confidence ({triage['confidence']:.2f}). Check the category.")
    if warnings:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": _clip("*Check before approving*\n" + "\n".join(f"- {w}" for w in warnings))}})

    if draft:
        quoted = "\n".join("> " + ln for ln in _escape(draft).split("\n"))
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": _clip(f"*Draft reply*\n{quoted}")}})
    else:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Draft reply*\n_No draft. Use Edit to write one._"}})

    actions = []
    if draft:
        actions.append({"type": "button", "text": {"type": "plain_text", "text": "Approve and send"},
                        "style": "primary", "action_id": "approve_reply", "value": ticket_id,
                        "confirm": {"title": {"type": "plain_text", "text": "Send this reply?"},
                                    "text": {"type": "plain_text", "text": "The draft is emailed to the customer as it is."},
                                    "confirm": {"type": "plain_text", "text": "Send"},
                                    "deny": {"type": "plain_text", "text": "Cancel"}}})
    actions.append({"type": "button", "text": {"type": "plain_text", "text": "Edit"},
                    "action_id": "edit_reply", "value": ticket_id})
    actions.append({"type": "button", "text": {"type": "plain_text", "text": "Reject"},
                    "style": "danger", "action_id": "reject_reply", "value": ticket_id})
    blocks.append({"type": "actions", "block_id": f"ticket_{ticket_id}", "elements": actions})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
                   "text": f"Ticket {ticket_id}. Nothing is sent until someone presses Approve or sends from Edit."}]})

    prefix = "URGENT " if urgent else ""
    return {"text": f"{prefix}{triage['category']} email from {_escape(sender)}: {_escape(triage['summary'])}"[:300], "blocks": blocks}


def edit_modal(ticket_id: str, subject: str, draft: str) -> dict:
    return {
        "type": "modal",
        "callback_id": "edit_reply_submit",
        "private_metadata": ticket_id,
        "title": {"type": "plain_text", "text": "Edit reply"},
        "submit": {"type": "plain_text", "text": "Send reply"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": _clip(f"Replying to: *{_escape(subject) or '(no subject)'}*\nPressing *Send reply* emails exactly this text to the customer.", 500)}},
            {"type": "input", "block_id": "draft_block", "label": {"type": "plain_text", "text": "Reply"},
             "element": {"type": "plain_text_input", "action_id": "draft_input", "multiline": True,
                         "initial_value": draft[:2900]}},
        ],
    }


def urgent_alert_text(ticket_id: str, sender: str, summary: str, oncall: str = "") -> str:
    mention = f"<@{oncall}> " if oncall else "<!here> "
    return f"{mention}URGENT email from {_escape(sender)}: {_escape(summary)} (ticket {ticket_id})"


def sms_text(ticket_id: str, category: str, summary: str) -> str:
    return f"Northbeam URGENT {category}: {summary}"[:140] + f" #{ticket_id}"
