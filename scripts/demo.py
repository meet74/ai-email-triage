"""Run a few sample emails through the service code and print what n8n would
hand to Slack. Uses the mock model unless an API key is set.

    python scripts/demo.py            # prints a readable summary
    python scripts/demo.py --json     # also prints the full Slack payloads
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from triage.app import create_app  # noqa: E402
from triage.config import load_settings  # noqa: E402

SAMPLES = ["e01", "e07", "e30", "e23", "e77", "e49"]


def main():
    show_json = "--json" in sys.argv
    settings = load_settings()
    client = TestClient(create_app(settings))
    rows = {json.loads(line)["id"]: json.loads(line) for line in (ROOT / "data" / "emails.jsonl").read_text(encoding="utf-8").splitlines()}
    print(f"model: {client.get('/health').json()['model']}\n")
    captured = []
    for eid in SAMPLES:
        r = rows[eid]
        t = client.post("/triage", json={"from": r["from"], "subject": r["subject"], "body": r["body"], "thread": r["thread"]}).json()
        ticket = f"T-DEMO-{eid}"
        print(f"== {eid}: {r['subject']}")
        print(f"   {t['category']} / {t['priority']} / {t['sentiment']} / {t['language']}  confidence={t['confidence']}  source={t['meta']['source']}")
        print(f"   summary: {t['summary']}")
        print("   extracted:", {k: v for k, v in t["extracted"].items() if v})
        if t["meta"]["skip_reason"]:
            print(f"   no Slack message: filtered as {t['meta']['skip_reason']}\n")
            continue
        msg = client.post("/slack/approval-message", json={"ticket_id": ticket, "from": r["from"], "subject": r["subject"], "triage": t}).json()
        captured.append({"id": eid, "from": r["from"], "subject": r["subject"], "triage": t, "slack": msg})
        buttons = [b["text"]["text"] for blk in msg["blocks"] if blk["type"] == "actions" for b in blk["elements"]]
        print(f"   Slack message: {len(msg['blocks'])} blocks, buttons: {', '.join(buttons)}")
        if t["priority"] == "urgent":
            alert = client.post("/slack/urgent-alert", json={"ticket_id": ticket, "from": r["from"], "category": t["category"], "summary": t["summary"]}).json()
            print("   urgent alert:", alert["slack_text"])
            print("   SMS text:   ", alert["sms_text"])
        if show_json:
            print(json.dumps(msg, indent=2, ensure_ascii=False))
        print()
    out = ROOT / "docs" / "demo-output.json"
    out.write_text(json.dumps(captured, indent=2, ensure_ascii=False))
    print(f"payloads saved to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
