"""Generates the n8n workflow JSON files in workflows/ and the local test variants
in workflows/test/.

The production workflows use Gmail, Google Sheets and Slack nodes. The test
variants are produced from the same definitions with those nodes swapped for
HTTP Request nodes that talk to scripts/fake_services.py, and with a webhook in
place of the Gmail trigger. Everything else (Code nodes, Switch, IF, calls to the
triage service, signature check) is identical, so a test run exercises the real
routing logic.

    python scripts/build_workflows.py
"""

import json
import pathlib
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "workflows" / "src"

IDS = {"triage": "NbTriage0000001", "approval": "NbApprove000001", "errors": "NbErrors0000001", "digest": "NbDigest0000001"}
NS = uuid.UUID("6f1d0d5e-3a39-4c52-9a6d-0b5c7d1e2f10")

CRED = {
    "gmail": ("gmailOAuth2", "Gmail account"),
    "sheets": ("googleSheetsOAuth2Api", "Google Sheets account"),
    "slack": ("slackApi", "Slack bot token"),
    "service": ("httpHeaderAuth", "Triage service API key"),
}

FAKE = "http://127.0.0.1:8770"
SERVICE_TEST = "http://127.0.0.1:8765"


def code(name):
    return (SRC / name).read_text()


class Flow:
    def __init__(self, key, name, test=False):
        self.key, self.name, self.test = key, name, test
        self.nodes, self.conns = [], {}

    def add(self, name, type_, version, params, pos, cred=None, notes=None, **extra):
        node = {
            "parameters": params, "id": str(uuid.uuid5(NS, f"{self.key}/{name}")),
            "name": name, "type": type_, "typeVersion": version, "position": list(pos),
        }
        if cred and not self.test:
            ctype, cname = CRED[cred]
            node["credentials"] = {ctype: {"id": None, "name": cname}}
        if notes:
            node["notes"] = notes
        node.update(extra)
        self.nodes.append(node)
        return name

    def link(self, src, dst, out=0, dst_index=0):
        outs = self.conns.setdefault(src, {"main": []})["main"]
        while len(outs) <= out:
            outs.append([])
        outs[out].append({"node": dst, "type": "main", "index": dst_index})

    def chain(self, *names):
        for a, b in zip(names, names[1:]):
            self.link(a, b)

    def dump(self, settings=None):
        return {
            "name": self.name + (" (test)" if self.test else ""),
            "id": IDS[self.key] + ("t" if self.test else ""),
            "nodes": self.nodes, "connections": self.conns, "active": False,
            "settings": {"executionOrder": "v1", **(settings or {})},
            "pinData": {}, "tags": [],
        }


# ---------- node helpers that switch between production and test variants ----------

def settings_node(f, pos, values):
    assignments = [{"id": str(uuid.uuid5(NS, f"{f.key}/set/{k}")), "name": k, "value": v, "type": "string"} for k, v in values.items()]
    return f.add("Settings", "n8n-nodes-base.set", 3.4,
                 {"assignments": {"assignments": assignments}, "includeOtherFields": True, "options": {}}, pos,
                 notes="Edit these values for your workspace. Nothing secret belongs here.")


def http(f, name, pos, url, body, service=False, retry=False, notes=None, method="POST", cred_slack=False):
    p = {"method": method, "url": url, "sendBody": True, "specifyBody": "json", "jsonBody": body, "options": {"timeout": 60000}}
    extra = {}
    if retry:
        extra.update(retryOnFail=True, maxTries=3, waitBetweenTries=2000)
    if f.test:
        return f.add(name, "n8n-nodes-base.httpRequest", 4.2, p, pos, notes=notes, **extra)
    if service:
        p.update(authentication="genericCredentialType", genericAuthType="httpHeaderAuth")
        return f.add(name, "n8n-nodes-base.httpRequest", 4.2, p, pos, cred="service", notes=notes, **extra)
    if cred_slack:
        p.update(authentication="predefinedCredentialType", nodeCredentialType="slackApi")
        return f.add(name, "n8n-nodes-base.httpRequest", 4.2, p, pos, cred="slack", notes=notes, **extra)
    return f.add(name, "n8n-nodes-base.httpRequest", 4.2, p, pos, notes=notes, **extra)


def fake_http(f, name, pos, path, body):
    return f.add(name, "n8n-nodes-base.httpRequest", 4.2,
                 {"method": "POST", "url": f"={FAKE}{path}", "sendBody": True, "specifyBody": "json", "jsonBody": body, "options": {}}, pos)


SHEET_COLS = ["ticket_id", "created_at", "message_id", "thread_id", "from", "subject", "category", "priority", "sentiment",
              "language", "summary", "extracted", "draft_reply", "confidence", "status", "approved_by", "updated_at"]


def sheet_doc(cfg="Settings"):
    return {"__rl": True, "value": f"={{{{ $('{cfg}').first().json.sheet_id }}}}", "mode": "id"}


def sheet_tab(cfg="Settings"):
    return {"__rl": True, "value": f"={{{{ $('{cfg}').first().json.sheet_name }}}}", "mode": "name"}


def sheet_schema(cols):
    return [{"id": c, "displayName": c, "required": False, "defaultMatch": c == "ticket_id", "display": True, "type": "string", "canBeUsedToMatch": True} for c in cols]


def sheets_append(f, name, pos, ref):
    if f.test:
        return fake_http(f, name, pos, "/sheets/append", "={{ JSON.stringify(" + ref + ") }}")
    vals = {c: f"={{{{ {ref}.{c} }}}}" for c in SHEET_COLS}
    return f.add(name, "n8n-nodes-base.googleSheets", 4.5, {
        "operation": "append", "documentId": sheet_doc(), "sheetName": sheet_tab(),
        "columns": {"mappingMode": "defineBelow", "value": vals, "matchingColumns": [], "schema": sheet_schema(SHEET_COLS)},
        "options": {}}, pos, cred="sheets", notes="Appends one row per email. The first row of the sheet must hold the column names from the README.")


def sheets_lookup(f, name, pos, ticket_expr):
    if f.test:
        return fake_http(f, name, pos, "/sheets/lookup", "={{ JSON.stringify({ticket_id: " + ticket_expr + "}) }}")
    return f.add(name, "n8n-nodes-base.googleSheets", 4.5, {
        "operation": "read", "documentId": sheet_doc(), "sheetName": sheet_tab(),
        "filtersUI": {"values": [{"lookupColumn": "ticket_id", "lookupValue": "=" + "{{ " + ticket_expr + " }}"}]},
        "options": {}}, pos, cred="sheets", alwaysOutputData=True)


def sheets_update(f, name, pos, fields):
    """fields: dict column -> expression (without '=' prefix handling)."""
    if f.test:
        return fake_http(f, name, pos, "/sheets/update", "={{ JSON.stringify({" + ", ".join(f"{k}: {v}" for k, v in fields.items()) + "}) }}")
    cols = list(fields)
    return f.add(name, "n8n-nodes-base.googleSheets", 4.5, {
        "operation": "update", "documentId": sheet_doc(), "sheetName": sheet_tab(),
        "columns": {"mappingMode": "defineBelow", "value": {k: "={{ " + v + " }}" for k, v in fields.items()},
                    "matchingColumns": ["ticket_id"], "schema": sheet_schema(cols)},
        "options": {}}, pos, cred="sheets")


def sheets_read_all(f, name, pos):
    if f.test:
        return f.add(name, "n8n-nodes-base.httpRequest", 4.2, {"method": "GET", "url": f"={FAKE}/sheets/all", "options": {}}, pos)
    return f.add(name, "n8n-nodes-base.googleSheets", 4.5, {
        "operation": "read", "documentId": sheet_doc(), "sheetName": sheet_tab(), "options": {}}, pos, cred="sheets", alwaysOutputData=True)


def slack_blocks(f, name, pos, notes=None):
    """Posts {channel, text, blocks} as produced by the service's /slack/approval-message."""
    if f.test:
        return fake_http(f, name, pos, "/slack/chat.postMessage", "={{ JSON.stringify($json) }}")
    return f.add(name, "n8n-nodes-base.slack", 2.3, {
        "select": "channel", "channelId": {"__rl": True, "value": "={{ $json.channel }}", "mode": "id"},
        "messageType": "block", "blocksUi": "={{ JSON.stringify({ blocks: $json.blocks }) }}", "text": "={{ $json.text }}",
        "otherOptions": {"includeLinkToWorkflow": False}}, pos, cred="slack", notes=notes)


def slack_text(f, name, pos, channel_expr, text_expr, notes=None):
    if f.test:
        return fake_http(f, name, pos, "/slack/chat.postMessage", "={{ JSON.stringify({channel: " + channel_expr + ", text: " + text_expr + "}) }}")
    return f.add(name, "n8n-nodes-base.slack", 2.3, {
        "select": "channel", "channelId": {"__rl": True, "value": "={{ " + channel_expr + " }}", "mode": "id"},
        "text": "={{ " + text_expr + " }}", "otherOptions": {"includeLinkToWorkflow": False}}, pos, cred="slack", notes=notes)


def gmail_label(f, name, pos):
    if f.test:
        return fake_http(f, name, pos, "/gmail/labels", "={{ JSON.stringify({message_id: $('Build ticket').item.json.message_id, label_id: $('Build ticket').item.json.label_id, category: $('Build ticket').item.json.category}) }}")
    return f.add(name, "n8n-nodes-base.gmail", 2.1, {
        "resource": "message", "operation": "addLabels",
        "messageId": "={{ $('Build ticket').item.json.message_id }}",
        "labelIds": "={{ [$('Build ticket').item.json.label_id] }}"}, pos, cred="gmail",
        notes="Label IDs are set in the Settings node (gmail_labels_json).")


def gmail_reply(f, name, pos, message_expr):
    if f.test:
        return fake_http(f, name, pos, "/gmail/reply", "={{ JSON.stringify({message_id: $('Look up ticket').item.json.message_id, thread_id: $('Look up ticket').item.json.thread_id, to: $('Look up ticket').item.json.from, message: " + message_expr + "}) }}")
    return f.add(name, "n8n-nodes-base.gmail", 2.1, {
        "resource": "message", "operation": "reply",
        "messageId": "={{ $('Look up ticket').item.json.message_id }}",
        "emailType": "text", "message": "={{ " + message_expr + " }}",
        "options": {"appendAttribution": False}}, pos, cred="gmail",
        notes="Replies inside the original thread. This is the only node in the project that sends mail to a customer.")


def code_node(f, name, pos, src, mode="runOnceForEachItem", notes=None):
    return f.add(name, "n8n-nodes-base.code", 2, {"mode": mode, "jsCode": code(src)}, pos, notes=notes)


def cond(left, op, right=None, typ="string"):
    c = {"id": str(uuid.uuid5(NS, f"{left}{op}{right}")), "leftValue": left,
         "operator": {"type": typ, "operation": op, **({"singleValue": True} if right is None else {})}}
    if right is not None:
        c["rightValue"] = right
    return c


def cond_block(*conds, combinator="and"):
    return {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
            "conditions": list(conds), "combinator": combinator}


def if_node(f, name, pos, *conds, notes=None):
    return f.add(name, "n8n-nodes-base.if", 2.2, {"conditions": cond_block(*conds), "options": {}}, pos, notes=notes)


def switch_node(f, name, pos, rules, fallback=None, notes=None):
    values = [{"conditions": cond_block(*cs), "renameOutput": True, "outputKey": key} for key, cs in rules]
    opts = {}
    if fallback:
        opts = {"fallbackOutput": "extra", "renameFallbackOutput": fallback}
    return f.add(name, "n8n-nodes-base.switch", 3.2, {"rules": {"values": values}, "options": opts}, pos, notes=notes)


def test_webhook(f, name, pos, path):
    return f.add(name, "n8n-nodes-base.webhook", 2.1, {"httpMethod": "POST", "path": path, "responseMode": "lastNode", "options": {}}, pos,
                 webhookId=str(uuid.uuid5(NS, f"{f.key}/hook/{path}")))


# ------------------------------------------------------------------ workflow a
def inbox_triage(test=False):
    f = Flow("triage", "Inbox triage", test)
    triage_url = SERVICE_TEST if test else "http://localhost:8000"
    cfg = {
        "triage_url": triage_url, "sheet_id": "REPLACE_WITH_SPREADSHEET_ID", "sheet_name": "Tickets",
        "channel_support": "C0SUPPORT00", "channel_sales": "C0SALES0000", "channel_billing": "C0BILLING00", "channel_urgent": "C0URGENT000",
        "oncall_slack_id": "", "sms_webhook_url": "https://example.com/sms-bridge", "sms_to": "+15555550100",
        "gmail_labels_json": json.dumps({"support": "Label_1", "sales_lead": "Label_2", "billing": "Label_3", "complaint": "Label_4", "spam": "Label_5", "other": "Label_6"}),
    }
    if test:
        cfg.update(sms_webhook_url=f"{FAKE}/sms")
    if test:
        trig = test_webhook(f, "Test trigger: POST a Gmail-style email", (0, 300), "triage-test")
        unwrap = f.add("Unwrap test body", "n8n-nodes-base.code", 2, {"mode": "runOnceForEachItem", "jsCode": "return { json: $input.item.json.body };"}, (200, 300))
        f.link(trig, unwrap)
        first = unwrap
    else:
        first = f.add("Gmail Trigger: new inbox mail", "n8n-nodes-base.gmailTrigger", 1.3, {
            "pollTimes": {"item": [{"mode": "everyMinute"}]}, "simple": False,
            "filters": {"labelIds": ["INBOX"], "readStatus": "unread"}, "options": {}}, (0, 300), cred="gmail",
            notes="Polls the inbox every minute. Simplify must stay off: the flow needs the message body.")
    st = settings_node(f, (400, 300), cfg)
    norm = code_node(f, "Normalise email", (600, 300), "normalise.js", notes="Strips quoted history and signatures, detects language, builds the ticket id.")
    triage = http(f, "Classify and draft reply", (800, 300), "={{ $('Settings').first().json.triage_url }}/triage",
                  "={{ JSON.stringify({ from: $json.from, subject: $json.subject, body: $json.body, thread: $json.thread }) }}",
                  service=True, retry=True, notes="Calls the triage service. Retries 3 times; a persistent failure triggers the Error alerts workflow.")
    ticket = code_node(f, "Build ticket", (1000, 300), "ticket.js")
    save = sheets_append(f, "Save ticket to sheet", (1200, 300), "$json")
    route = switch_node(f, "Route by category and priority", (1400, 300), [
        ("Filtered (spam or auto-reply)", [cond("={{ $('Build ticket').item.json.skip_reason }}", "notEmpty")]),
        ("Urgent", [cond("={{ $('Build ticket').item.json.priority }}", "equals", "urgent")]),
        ("Sales lead", [cond("={{ $('Build ticket').item.json.category }}", "equals", "sales_lead")]),
        ("Billing", [cond("={{ $('Build ticket').item.json.category }}", "equals", "billing")]),
    ], fallback="Support, complaint, other",
        notes="First match wins: filtered mail never reaches Slack, urgent mail is escalated before category routing.")
    f.link(first, st)
    f.chain(st, norm, triage, ticket, save, route)

    label = gmail_label(f, "Apply Gmail label", (2400, 120))
    f.link(route, label, out=0)

    chans = {
        "urgent": ("Channel: urgent", 1, "channel_urgent", 300),
        "sales": ("Channel: sales", 2, "channel_sales", 500),
        "billing": ("Channel: billing", 3, "channel_billing", 700),
        "support": ("Channel: support", 4, "channel_support", 900),
    }
    render = http(f, "Render approval message", (1950, 600), "={{ $('Settings').first().json.triage_url }}/slack/approval-message",
                  "={{ JSON.stringify({ ticket_id: $('Build ticket').item.json.ticket_id, from: $('Build ticket').item.json.from, subject: $('Build ticket').item.json.subject, triage: $('Build ticket').item.json.triage, channel: $json.slack_channel }) }}",
                  service=True, notes="The service builds the Slack Block Kit JSON so the message layout is tested in Python.")
    post = slack_blocks(f, "Post approval message to Slack", (2200, 600), notes="Buttons: Approve and send, Edit, Reject. Their clicks go to the Slack approval handler workflow.")
    for _, (name, out, key, y) in chans.items():
        n = f.add(name, "n8n-nodes-base.set", 3.4, {"assignments": {"assignments": [
            {"id": str(uuid.uuid5(NS, f"ch/{key}")), "name": "slack_channel", "value": f"={{{{ $('Settings').first().json.{key} }}}}", "type": "string"}]},
            "includeOtherFields": True, "options": {}}, (1700, y))
        f.link(route, n, out=out)
        f.link(n, render)
    f.link(render, post)
    f.link(post, label)

    alert = http(f, "Build urgent alert", (1950, 100), "={{ $('Settings').first().json.triage_url }}/slack/urgent-alert",
                 "={{ JSON.stringify({ ticket_id: $('Build ticket').item.json.ticket_id, from: $('Build ticket').item.json.from, category: $('Build ticket').item.json.category, summary: $('Build ticket').item.json.summary, oncall_slack_id: $('Settings').first().json.oncall_slack_id }) }}",
                 service=True)
    f.link("Channel: urgent", alert)
    mention = slack_text(f, "Slack: urgent mention", (2200, 20), "$('Settings').first().json.channel_urgent", "$json.slack_text",
                         notes="Posts immediately with an @here (or the on-call user if oncall_slack_id is set).")
    sms_params = {"method": "POST", "url": "={{ $('Settings').first().json.sms_webhook_url }}", "sendBody": True, "specifyBody": "json",
                  "jsonBody": "={{ JSON.stringify({ to: $('Settings').first().json.sms_to, message: $json.sms_text, ticket_id: $('Build ticket').item.json.ticket_id }) }}",
                  "options": {"timeout": 15000}}
    sms = f.add("SMS-ready webhook", "n8n-nodes-base.httpRequest", 4.2, sms_params, (2200, 200),
                notes="Posts {to, message, ticket_id}; message is at most 160 characters. Point it at Twilio, an SMS gateway or any automation hook.")
    f.link(alert, mention)
    f.link(alert, sms)
    return f.dump({"errorWorkflow": IDS["errors"] + ("t" if test else "")})


# ------------------------------------------------------------------ workflow b
def approval_handler(test=False):
    f = Flow("approval", "Slack approval handler", test)
    cfg = {"triage_url": SERVICE_TEST if test else "http://localhost:8000", "sheet_id": "REPLACE_WITH_SPREADSHEET_ID", "sheet_name": "Tickets"}
    hook = f.add("Slack interactivity webhook", "n8n-nodes-base.webhook", 2.1, {
        "httpMethod": "POST", "path": "slack-interactivity", "responseMode": "responseNode", "options": {"rawBody": True}}, (0, 300),
        webhookId=str(uuid.uuid5(NS, "approval/hook")),
        notes="Set this URL as the Interactivity Request URL in the Slack app. Raw body is kept for the signature check.")
    verify = code_node(f, "Verify Slack signature", (200, 300), "verify_signature.js", mode="runOnceForAllItems",
                       notes="Needs SLACK_SIGNING_SECRET, N8N_BLOCK_ENV_ACCESS_IN_NODE=false and NODE_FUNCTION_ALLOW_BUILTIN=crypto.")
    valid = if_node(f, "Signature valid?", (400, 300), cond("={{ $json.valid }}", "true", typ="boolean"))
    deny = f.add("Reject request (401)", "n8n-nodes-base.respondToWebhook", 1.1, {"respondWith": "text", "responseBody": "invalid signature", "options": {"responseCode": 401}}, (600, 480))
    ack = f.add("Acknowledge Slack (200)", "n8n-nodes-base.respondToWebhook", 1.1, {"respondWith": "noData", "options": {"responseCode": 200}}, (600, 200),
                notes="Slack gives 3 seconds to answer. The rest of the flow keeps running after this reply.")
    parse = code_node(f, "Parse interaction", (800, 200), "parse_interaction.js")
    st = settings_node(f, (1000, 200), cfg)
    look = sheets_lookup(f, "Look up ticket", (1200, 200), "$('Parse interaction').item.json.ticket_id")
    pending = if_node(f, "Ticket still pending?", (1400, 200),
                      cond("={{ $json.status }}", "equals", "pending_approval"), notes="Stops a second click, or a click after Reject, from sending anything.")
    f.link(hook, verify)
    f.chain(verify, valid)
    f.link(valid, ack, out=0)
    f.link(valid, deny, out=1)
    f.chain(ack, parse, st, look, pending)

    route = switch_node(f, "Route interaction", (1650, 120), [
        ("Approve", [cond("={{ $('Parse interaction').item.json.kind }}", "equals", "approve")]),
        ("Reject", [cond("={{ $('Parse interaction').item.json.kind }}", "equals", "reject")]),
        ("Edit", [cond("={{ $('Parse interaction').item.json.kind }}", "equals", "edit")]),
        ("Edited reply submitted", [cond("={{ $('Parse interaction').item.json.kind }}", "equals", "submit_edit")]),
    ])
    f.link(pending, route, out=0)

    # already handled
    can = if_node(f, "Can answer in Slack?", (1650, 520), cond("={{ $('Parse interaction').item.json.response_url }}", "notEmpty"))
    f.link(pending, can, out=1)
    note = http(f, "Tell Slack: already handled", (1900, 520), "={{ $('Parse interaction').item.json.response_url }}",
                "={{ JSON.stringify({ response_type: 'ephemeral', replace_original: false, text: 'This ticket was already handled (status: ' + ($('Look up ticket').item.json.status || 'unknown') + '). Nothing was sent.' }) }}")
    f.link(can, note, out=0)

    # approve
    send = gmail_reply(f, "Send approved reply", (1950, 0), "$('Look up ticket').item.json.draft_reply")
    sent = sheets_update(f, "Mark ticket as sent", (2200, 0), {
        "ticket_id": "$('Parse interaction').item.json.ticket_id", "status": "'sent'",
        "approved_by": "$('Parse interaction').item.json.user", "updated_at": "$now.toISO()"})
    upd_sent = http(f, "Update Slack message: sent", (2450, 0), "={{ $('Parse interaction').item.json.response_url }}",
                    "={{ JSON.stringify({ replace_original: true, text: 'Reply sent to ' + $('Look up ticket').item.json.from + ' (approved by ' + $('Parse interaction').item.json.user + '). Ticket ' + $('Parse interaction').item.json.ticket_id + '.' }) }}")
    f.link(route, send, out=0)
    f.chain(send, sent, upd_sent)

    # reject
    rej = sheets_update(f, "Mark ticket as rejected", (1950, 160), {
        "ticket_id": "$('Parse interaction').item.json.ticket_id", "status": "'rejected'",
        "approved_by": "$('Parse interaction').item.json.user", "updated_at": "$now.toISO()"})
    upd_rej = http(f, "Update Slack message: rejected", (2200, 160), "={{ $('Parse interaction').item.json.response_url }}",
                   "={{ JSON.stringify({ replace_original: true, text: 'Draft rejected by ' + $('Parse interaction').item.json.user + '. Nothing was sent. Ticket ' + $('Parse interaction').item.json.ticket_id + '.' }) }}")
    f.link(route, rej, out=1)
    f.chain(rej, upd_rej)

    # edit: open modal
    modal = http(f, "Build edit modal", (1950, 320), "={{ $('Settings').first().json.triage_url }}/slack/edit-modal",
                 "={{ JSON.stringify({ ticket_id: $('Parse interaction').item.json.ticket_id, subject: $('Look up ticket').item.json.subject, draft_reply: $('Look up ticket').item.json.draft_reply }) }}",
                 service=True)
    if test:
        opener = fake_http(f, "Open edit modal in Slack", (2200, 320), "/slack/views.open",
                           "={{ JSON.stringify({ trigger_id: $('Parse interaction').item.json.trigger_id, view: $json.view }) }}")
    else:
        opener = http(f, "Open edit modal in Slack", (2200, 320), "https://slack.com/api/views.open",
                      "={{ JSON.stringify({ trigger_id: $('Parse interaction').item.json.trigger_id, view: $json.view }) }}", cred_slack=True,
                      notes="Slack requires the trigger_id within 3 seconds of the click, so keep the path from the button to this node short.")
    f.link(route, modal, out=2)
    f.chain(modal, opener)

    # edited reply submitted
    send2 = gmail_reply(f, "Send edited reply", (1950, 480), "$('Parse interaction').item.json.edited_text")
    sent2 = sheets_update(f, "Mark ticket as sent (edited)", (2200, 480), {
        "ticket_id": "$('Parse interaction').item.json.ticket_id", "status": "'sent_edited'",
        "draft_reply": "$('Parse interaction').item.json.edited_text",
        "approved_by": "$('Parse interaction').item.json.user", "updated_at": "$now.toISO()"})
    f.link(route, send2, out=3)
    f.chain(send2, sent2)
    return f.dump({"errorWorkflow": IDS["errors"]} if not test else {})


# ------------------------------------------------------------------ workflow c
def error_alerts(test=False):
    f = Flow("errors", "Error alerts", test)
    trig = f.add("Error Trigger", "n8n-nodes-base.errorTrigger", 1, {}, (0, 0))
    st = settings_node(f, (220, 0), {"alert_channel": "C0ALERTS000"})
    text = ("'Workflow failed: ' + $('Error Trigger').item.json.workflow.name + '. Node: ' + ($('Error Trigger').item.json.execution.lastNodeExecuted || 'unknown') "
            "+ '. Error: ' + ($('Error Trigger').item.json.execution.error.message || 'no message') + '. Execution: ' + ($('Error Trigger').item.json.execution.url || 'n/a')")
    msg = slack_text(f, "Alert in Slack", (440, 0), "$('Settings').first().json.alert_channel", text)
    f.chain(trig, st, msg)
    return f.dump({})


# ------------------------------------------------------------------ workflow d
def daily_digest(test=False):
    f = Flow("digest", "Daily digest", test)
    cfg = {"triage_url": SERVICE_TEST if test else "http://localhost:8000", "sheet_id": "REPLACE_WITH_SPREADSHEET_ID",
           "sheet_name": "Tickets", "digest_channel": "C0DIGEST000"}
    if test:
        trig = test_webhook(f, "Test trigger: run the digest now", (0, 0), "digest-test")
    else:
        trig = f.add("Every morning at 08:00", "n8n-nodes-base.scheduleTrigger", 1.2,
                     {"rule": {"interval": [{"field": "days", "triggerAtHour": 8}]}}, (0, 0),
                     notes="Uses the workflow time zone (Settings > Timezone).")
    st = settings_node(f, (220, 0), cfg)
    day_expr = "='2026-11-21'" if test else "={{ $now.minus({ days: 1 }).toFormat('yyyy-LL-dd') }}"
    day = f.add("Pick yesterday", "n8n-nodes-base.set", 3.4, {"assignments": {"assignments": [
        {"id": str(uuid.uuid5(NS, "digest/date")), "name": "date", "value": day_expr, "type": "string"}]}, "options": {}}, (440, 0))
    rows = sheets_read_all(f, "Read all tickets", (660, 0))
    agg = f.add("Collect tickets", "n8n-nodes-base.aggregate", 1, {"aggregate": "aggregateAllItemData", "destinationFieldName": "tickets", "options": {}}, (880, 0))
    dig = http(f, "Build digest", (1100, 0), "={{ $('Settings').first().json.triage_url }}/digest",
               "={{ JSON.stringify({ date: $('Pick yesterday').first().json.date, tickets: $json.tickets }) }}", service=True,
               notes="Counts by category and priority for the day, plus every urgent ticket still waiting.")
    if test:
        post = fake_http(f, "Post digest to Slack", (1320, 0), "/slack/chat.postMessage", "={{ JSON.stringify({channel: 'digest', text: $json.text, blocks: $json.blocks}) }}")
    else:
        post = f.add("Post digest to Slack", "n8n-nodes-base.slack", 2.3, {
            "select": "channel", "channelId": {"__rl": True, "value": "={{ $('Settings').first().json.digest_channel }}", "mode": "id"},
            "messageType": "block", "blocksUi": "={{ JSON.stringify({ blocks: $json.blocks }) }}", "text": "={{ $json.text }}",
            "otherOptions": {"includeLinkToWorkflow": False}}, (1320, 0), cred="slack")
    f.chain(trig, st, day, rows, agg, dig, post)
    return f.dump({"errorWorkflow": IDS["errors"]} if not test else {})


def write(path, wf):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(wf, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", path.relative_to(ROOT))


if __name__ == "__main__":
    W = ROOT / "workflows"
    write(W / "inbox-triage.json", inbox_triage())
    write(W / "slack-approval-handler.json", approval_handler())
    write(W / "error-alerts.json", error_alerts())
    write(W / "daily-digest.json", daily_digest())
    write(W / "test" / "error-alerts.test.json", error_alerts(test=True))
    write(W / "test" / "inbox-triage.test.json", inbox_triage(test=True))
    write(W / "test" / "slack-approval-handler.test.json", approval_handler(test=True))
    write(W / "test" / "daily-digest.test.json", daily_digest(test=True))
