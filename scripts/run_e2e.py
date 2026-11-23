"""Run the workflows in a real local n8n against local fakes.

What runs for real: n8n (imported test variants of the workflows), the triage
service with the mock model, and the Code, Switch, IF and HTTP nodes of every
workflow. What is faked: Gmail, Google Sheets, Slack and the SMS bridge, which
are replaced by scripts/fake_services.py.

    python scripts/run_e2e.py

Needs an n8n install (see README) and Node 22.16+ or 24. Writes docs/e2e-run.txt.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import fake_services  # noqa: E402
from triage.slack import sign_request  # noqa: E402

N8N_DIR = pathlib.Path(os.environ.get("N8N_DIR", ROOT / ".tools24"))
NODE_BIN = os.environ.get("N8N_NODE_BIN", "/opt/node24/bin")
N8N = N8N_DIR / "node_modules" / ".bin" / "n8n"
FAKE, SERVICE, N8N_PORT = 18770, 18765, 15744
HOOK = f"http://127.0.0.1:{N8N_PORT}/webhook"
SECRET = "e2e-signing-secret"
LOG: list[str] = []
FAILS = 0


def say(line=""):
    print(line, flush=True)
    LOG.append(line)


def check(name, ok, detail=""):
    global FAILS
    FAILS += 0 if ok else 1
    say(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    return ok


def http(method, url, body=None, headers=None, raw=None, timeout=60):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method, headers=headers or ({"content-type": "application/json"} if body is not None else {}))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def calls(kind=None):
    _, t = http("GET", f"http://127.0.0.1:{FAKE}/calls")
    rows = json.loads(t)
    return [c["body"] for c in rows if kind is None or c["kind"] == kind]


def table():
    return json.loads(http("GET", f"http://127.0.0.1:{FAKE}/table")[1])


def reset():
    http("POST", f"http://127.0.0.1:{FAKE}/reset", {})


def wait_for(fn, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.3)
    return None


def n8n_env(folder):
    env = dict(os.environ)
    env.update({
        "PATH": f"{NODE_BIN}:{env['PATH']}", "N8N_USER_FOLDER": folder, "N8N_DIAGNOSTICS_ENABLED": "false",
        "N8N_PORT": str(N8N_PORT), "N8N_HOST": "127.0.0.1", "N8N_LISTEN_ADDRESS": "127.0.0.1", "N8N_PROTOCOL": "http",
        "SLACK_SIGNING_SECRET": SECRET, "N8N_BLOCK_ENV_ACCESS_IN_NODE": "false", "NODE_FUNCTION_ALLOW_BUILTIN": "crypto",
        "N8N_VERSION_NOTIFICATIONS_ENABLED": "false", "N8N_PERSONALIZATION_ENABLED": "false",
        "N8N_RUNNERS_ENABLED": "true", "EXECUTIONS_DATA_SAVE_ON_SUCCESS": "all",
    })
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLM_PROVIDER"):
        env.pop(k, None)
    return env


def gmail_item(row, n):
    m = row["from"]
    name, addr = (m.split("<")[0].strip().strip('"'), m.split("<")[1].strip(">")) if "<" in m else ("", m)
    return {"id": f"e2e{n:04d}abcdef{row['id']}", "threadId": f"thread-{row['id']}",
            "from": {"value": [{"address": addr, "name": name}], "text": m}, "subject": row["subject"], "text": row["body"]}


def interaction(payload, secret=SECRET, ts=None):
    raw = "payload=" + urllib.parse.quote(json.dumps(payload))
    ts = str(int(time.time())) if ts is None else ts
    headers = {"content-type": "application/x-www-form-urlencoded", "x-slack-request-timestamp": ts,
               "x-slack-signature": sign_request(secret, ts, raw.encode())}
    return http("POST", f"{HOOK}/slack-interactivity", raw=raw.encode(), headers=headers)


def button(action_id, ticket, user="sam.lee"):
    return {"type": "block_actions", "user": {"username": user}, "trigger_id": "trig-1", "response_url": f"http://127.0.0.1:{FAKE}/slack/response",
            "actions": [{"action_id": action_id, "value": ticket}]}


def main():
    rows = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "data" / "emails.jsonl").read_text(encoding="utf-8").splitlines()}
    workdir = tempfile.mkdtemp(prefix="n8n-e2e-")
    env = n8n_env(workdir)
    procs = []
    try:
        fake_services.serve(FAKE)
        svc_env = dict(os.environ, PORT=str(SERVICE))
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLM_PROVIDER", "TRIAGE_API_KEY"):
            svc_env.pop(k, None)
        svc = subprocess.Popen([sys.executable, "-m", "triage"], env=svc_env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(svc)
        say(f"n8n {subprocess.run([str(N8N), '--version'], env=env, capture_output=True, text=True).stdout.strip()}, node {NODE_BIN}")

        say("Importing and publishing the test variants")
        for f in sorted((ROOT / "workflows" / "test").glob("*.json")):
            wf = json.loads(f.read_text())
            r = subprocess.run([str(N8N), "import:workflow", f"--input={f}"], env=env, capture_output=True, text=True)
            check(f"import {f.name}", "Successfully imported" in r.stdout + r.stderr, r.stderr[-200:])
            r = subprocess.run([str(N8N), "publish:workflow", f"--id={wf['id']}"], env=env, capture_output=True, text=True)
            check(f"publish {wf['name']}", r.returncode == 0, (r.stdout + r.stderr)[-300:])

        n8n = subprocess.Popen([str(N8N), "start"], env=env, cwd=workdir, stdout=open(f"{workdir}/n8n.log", "w"), stderr=subprocess.STDOUT)
        procs.append(n8n)
        up = wait_for(lambda: n8n.poll() is None and _alive(N8N_PORT) and http("GET", f"http://127.0.0.1:{N8N_PORT}/healthz")[0] == 200, 90)
        check("n8n is up", bool(up))
        if not up:
            say(open(f"{workdir}/n8n.log").read()[-1500:])
        up_svc = wait_for(lambda: _alive(SERVICE) and http("GET", f"http://127.0.0.1:{SERVICE}/health")[0] == 200, 20)
        check("triage service is up (mock model)", bool(up_svc))
        if not (up and up_svc):
            say(open(f"{workdir}/n8n.log").read()[-2000:])
            return

        def hooks_ready():
            # a GET on a POST-only webhook answers "did you mean POST" once it is registered
            return all("POST" in http("GET", f"{HOOK}/{h}")[1] for h in ("triage-test", "slack-interactivity", "digest-test"))

        check("webhooks registered", bool(wait_for(hooks_ready, 60)))

        # ---------------------------------------------------------- inbox triage
        say("\nInbox triage")
        reset()
        n = 0

        def send(eid):
            nonlocal n
            n += 1
            return http("POST", f"{HOOK}/triage-test", gmail_item(rows[eid], n))

        st, _ = send("e01")
        t = table()
        t1 = next((v for v in t.values() if v["subject"] == rows["e01"]["subject"]), None)
        check("normal support email: webhook returns 200", st == 200, str(st))
        check("ticket row saved with status pending_approval", bool(t1) and t1["status"] == "pending_approval" and t1["category"] == "support", str(t1)[:200])
        posts = calls("slack/chat.postMessage")
        msg = posts[-1] if posts else {}
        check("one Slack approval message, with the support channel", len(posts) == 1 and msg.get("channel") == "C0SUPPORT00", str(posts)[:200])
        btns = [b["action_id"] for blk in msg.get("blocks", []) if blk["type"] == "actions" for b in blk["elements"]]
        check("message has Approve, Edit and Reject buttons", btns == ["approve_reply", "edit_reply", "reject_reply"], str(btns))
        check("Gmail label applied", len(calls("gmail/labels")) == 1)
        check("nothing was sent to the customer", calls("gmail/reply") == [])
        check("no SMS for a normal email", calls("sms") == [])
        ticket1 = t1["ticket_id"] if t1 else ""

        reset()
        send("e30")
        posts = calls("slack/chat.postMessage")
        urgent_channel = [p for p in posts if p.get("channel") == "C0URGENT000"]
        check("urgent chargeback threat: @here alert posted", any("<!here>" in p.get("text", "") for p in posts), str(posts)[:300])
        check("urgent: approval message also goes to the urgent channel", any("blocks" in p for p in urgent_channel))
        sms = calls("sms")
        check("urgent: SMS-ready webhook called with <=160 chars", len(sms) == 1 and len(sms[0]["message"]) <= 160 and sms[0]["to"].startswith("+1555"), str(sms)[:200])
        urgent_ticket = next((v["ticket_id"] for v in table().values()), "")

        reset()
        send("e49")
        check("newsletter: ticketed as filtered", any(v["status"] == "filtered_newsletter" for v in table().values()), str(table())[:200])
        check("newsletter: no Slack message, label still applied", calls("slack/chat.postMessage") == [] and len(calls("gmail/labels")) == 1)

        reset()
        send("e64")
        check("auto-reply: filtered, no Slack message", any(v["status"] == "filtered_auto_reply" for v in table().values()) and calls("slack/chat.postMessage") == [])

        reset()
        send("e77")
        posts = calls("slack/chat.postMessage")
        text = json.dumps(posts)
        check("prompt injection email: draft replaced, warning shown, no refund promise",
              "aimed at the AI" in text and "refund of $500" not in text and "has been approved" not in text, text[:300])

        # ------------------------------------------------------ approval handler
        say("\nSlack approval handler")
        reset()
        send("e01")
        tk = next(v for v in table().values())["ticket_id"]
        draft = table()[tk]["draft_reply"]
        send("e30")
        tk_reject = next(v["ticket_id"] for v in table().values() if v["ticket_id"] != tk)

        bad = interaction(button("approve_reply", tk), secret="wrong-secret")
        check("wrong signature gets 401", bad[0] == 401, str(bad))
        st_old = interaction(button("approve_reply", tk), ts=str(int(time.time()) - 4000))
        check("stale timestamp gets 401", st_old[0] == 401, str(st_old))
        time.sleep(1)
        check("rejected requests sent nothing", calls("gmail/reply") == [] and table()[tk]["status"] == "pending_approval")

        st, _ = interaction(button("approve_reply", tk))
        check("valid Approve is acknowledged with 200", st == 200, str(st))
        replies = wait_for(lambda: calls("gmail/reply"))
        check("Approve sends exactly the stored draft as a reply in the thread",
              bool(replies) and len(replies) == 1 and replies[0]["message"] == draft and replies[0]["thread_id"].startswith("thread-"), str(replies)[:300])
        check("ticket marked sent with approver", wait_for(lambda: table()[tk]["status"] == "sent") and table()[tk]["approved_by"] == "sam.lee")
        check("original Slack message updated", bool(wait_for(lambda: [c for c in calls("slack/response") if "Reply sent" in c.get("text", "")])))

        interaction(button("approve_reply", tk))
        time.sleep(2.5)
        check("second click does not send again", len(calls("gmail/reply")) == 1, str(len(calls("gmail/reply"))))
        check("second click is answered with 'already handled'", any("already handled" in c.get("text", "") for c in calls("slack/response")))

        interaction(button("reject_reply", tk_reject))
        check("Reject marks the ticket rejected", bool(wait_for(lambda: table()[tk_reject]["status"] == "rejected")))
        check("Reject sends nothing", len(calls("gmail/reply")) == 1)

        reset()
        send("e12")
        tk_edit = next(v for v in table().values())["ticket_id"]
        interaction(button("edit_reply", tk_edit))
        views = wait_for(lambda: calls("slack/views.open"))
        check("Edit opens a modal prefilled with the draft",
              bool(views) and views[0]["trigger_id"] == "trig-1" and views[0]["view"]["blocks"][1]["element"]["initial_value"] == table()[tk_edit]["draft_reply"], str(views)[:300])
        check("Edit alone sends nothing", calls("gmail/reply") == [])
        edited = "Hello,\n\nYour return window is still open. Please reply with your order number.\n\nNorthbeam Outdoor Gear Support"
        submit = {"type": "view_submission", "user": {"username": "sam.lee"}, "view": {"callback_id": "edit_reply_submit", "private_metadata": tk_edit,
                  "state": {"values": {"draft_block": {"draft_input": {"type": "plain_text_input", "value": edited}}}}}}
        st, _ = interaction(submit)
        check("modal submit acknowledged with 200", st == 200, str(st))
        replies = wait_for(lambda: calls("gmail/reply"))
        check("modal submit sends the edited text", bool(replies) and replies[0]["message"] == edited, str(replies)[:200])
        check("ticket marked sent_edited", bool(wait_for(lambda: table()[tk_edit]["status"] == "sent_edited")) and table()[tk_edit]["draft_reply"] == edited)

        # ----------------------------------------------------------- daily digest
        say("\nDaily digest")
        reset()
        seed = [
            {"ticket_id": "T-1", "created_at": "2026-11-21T09:00:00", "category": "billing", "priority": "urgent", "status": "pending_approval", "from": "julia@example.com", "subject": "Chargeback"},
            {"ticket_id": "T-2", "created_at": "2026-11-21T10:00:00", "category": "support", "priority": "normal", "status": "sent", "from": "a@example.com", "subject": "Order"},
            {"ticket_id": "T-3", "created_at": "2026-11-21T11:00:00", "category": "spam", "priority": "low", "status": "filtered_spam", "from": "b@example.com", "subject": "SEO"},
            {"ticket_id": "T-4", "created_at": "2026-11-19T11:00:00", "category": "support", "priority": "urgent", "status": "pending_approval", "from": "c@example.com", "subject": "Stove"},
        ]
        http("POST", f"http://127.0.0.1:{FAKE}/sheets/seed", {"rows": seed})
        st, _ = http("POST", f"{HOOK}/digest-test", {})
        posts = wait_for(lambda: calls("slack/chat.postMessage"))
        body = json.dumps(posts)
        check("digest posted to Slack", st == 200 and bool(posts), str(st))
        check("digest counts 3 tickets for the day", "Tickets for 2026-11-21: 3" in body, body[:300])
        check("digest lists both unanswered urgent tickets (T-1 and the older T-4)", "T-1" in body and "T-4" in body and "Urgent and still unanswered: 2" in body)

        # ----------------------------------------------------------- error alerts
        say("\nError alerts")
        reset()
        svc.terminate()
        svc.wait()
        send("e01")  # the service is down, so 'Classify and draft reply' fails after its retries
        alerts = wait_for(lambda: [c for c in calls("slack/chat.postMessage") if "Workflow failed" in c.get("text", "")], 40)
        check("failure in the triage flow raises an alert", bool(alerts), str(calls())[:300])
        if alerts:
            check("alert names the workflow and the failed node", "Inbox triage" in alerts[0]["text"] and "Classify and draft reply" in alerts[0]["text"], alerts[0]["text"])
            check("alert carries an execution link", "/executions/" in alerts[0]["text"], alerts[0]["text"])
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        if FAILS:
            say(f"n8n data kept for inspection: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)
        say(f"\n{'ALL CHECKS PASSED' if FAILS == 0 else str(FAILS) + ' CHECK(S) FAILED'}")
        (ROOT / "docs" / "e2e-run.txt").write_text("\n".join(LOG) + "\n")
    sys.exit(1 if FAILS else 0)


def _alive(port):
    import socket
    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


if __name__ == "__main__":
    main()
