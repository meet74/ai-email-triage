"""Render a Block Kit payload from the demo as a plain HTML page for the README.

This is a rendering of the JSON the workflow posts, in neutral styling. It is
not a capture of Slack. Run `make demo` first so docs/demo-output.json exists.
"""

import html
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
PICK = "e30"


def mrkdwn(text: str) -> str:
    out = html.escape(html.unescape(text))
    out = re.sub(r"\*(.+?)\*", r"<b>\1</b>", out)
    out = re.sub(r"_(.+?)_", r"<i>\1</i>", out)
    lines, quoted = [], []
    for ln in out.split("\n"):
        if ln.startswith("&gt; "):
            quoted.append(ln[5:])
            continue
        if quoted:
            lines.append("<blockquote>" + "<br>".join(quoted) + "</blockquote>")
            quoted = []
        lines.append(ln + "<br>" if not ln.startswith("- ") else "&bull; " + ln[2:] + "<br>")
    if quoted:
        lines.append("<blockquote>" + "<br>".join(quoted) + "</blockquote>")
    return "".join(lines)


def render(blocks) -> str:
    parts = []
    for b in blocks:
        t = b["type"]
        if t == "header":
            parts.append(f'<h2>{html.escape(b["text"]["text"])}</h2>')
        elif t == "section" and "fields" in b:
            cells = "".join(f'<div>{mrkdwn(f["text"])}</div>' for f in b["fields"])
            parts.append(f'<div class="fields">{cells}</div>')
        elif t == "section":
            parts.append(f'<div class="sec">{mrkdwn(b["text"]["text"])}</div>')
        elif t == "actions":
            btns = "".join(
                f'<span class="btn {e.get("style", "")}">{html.escape(e["text"]["text"])}</span>' for e in b["elements"])
            parts.append(f'<div class="actions">{btns}</div>')
        elif t == "context":
            parts.append(f'<div class="ctx">{mrkdwn(b["elements"][0]["text"])}</div>')
    return "\n".join(parts)


PAGE = """<!doctype html><meta charset="utf-8"><title>Approval message (rendering)</title>
<style>
body{{margin:0;background:#eef1f5;font:15px/1.45 Helvetica,Arial,sans-serif;color:#1d2530;padding:28px}}
.note{{font-size:12px;color:#5b6675;margin-bottom:10px}}
.card{{background:#fff;border:1px solid #d5dbe3;border-left:4px solid #2ec4b6;border-radius:6px;padding:16px 20px}}
.meta{{font-size:13px;color:#5b6675;margin-bottom:8px}}
h2{{margin:0 0 10px;font-size:18px}}
.fields{{display:grid;grid-template-columns:1fr 1fr;gap:8px 20px;margin-bottom:10px}}
.sec{{margin:10px 0}}
blockquote{{margin:6px 0;padding-left:12px;border-left:3px solid #c8d0da;color:#33404f}}
.actions{{margin-top:14px;display:flex;gap:8px}}
.btn{{border:1px solid #b9c2cd;border-radius:5px;padding:6px 14px;font-weight:600;background:#fff}}
.btn.primary{{background:#0d7a70;color:#fff;border-color:#0d7a70}}
.btn.danger{{color:#b3261e;border-color:#b3261e}}
.ctx{{margin-top:12px;font-size:12px;color:#5b6675}}
</style>
<div class="note">Rendering of the Block Kit payload produced by <code>make demo</code> (email {eid}). Not a screenshot of Slack.</div>
<div class="card"><div class="meta">#urgent &middot; posted by the triage workflow</div>
{body}
</div>"""


if __name__ == "__main__":
    data = json.loads((ROOT / "docs" / "demo-output.json").read_text())
    item = next(d for d in data if d["id"] == PICK)
    out = ROOT / "assets" / "approval-message.html"
    out.write_text(PAGE.format(eid=PICK, body=render(item["slack"]["blocks"])), encoding="utf-8")
    print("wrote", out.relative_to(ROOT))
