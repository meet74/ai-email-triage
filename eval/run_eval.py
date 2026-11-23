"""Score the triage pipeline against data/emails.jsonl.

    python -m eval.run_eval                 # mock model, plus a real model if a key is set
    python -m eval.run_eval --only mock

Writes eval/results/<name>.json and <name>.md and prints the markdown.
"""

import argparse
import json
import pathlib
import sys
import time
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from triage.config import Settings, load_settings  # noqa: E402
from triage.llm import build_client  # noqa: E402
from triage.mock_llm import MockLLM  # noqa: E402
from triage.pipeline import EmailIn, TriageEngine  # noqa: E402
from triage.schema import CATEGORIES  # noqa: E402

FIELDS = ["name", "company", "order_id", "invoice_number", "product", "requested_action", "deadline"]


class Counting:
    def __init__(self, inner):
        self.inner, self.name, self.calls = inner, inner.name, 0

    def complete(self, system, messages):
        self.calls += 1
        return self.inner.complete(system, messages)


def norm(v):
    return " ".join(str(v).lower().replace(".", "").replace(",", "").split()) if v else ""


def field_match(field, exp, got):
    e, g = norm(exp), norm(got)
    if not e or not g:
        return False
    if field in ("order_id", "invoice_number", "requested_action"):
        return e == g
    return e in g or g in e


def injection_ok(inj, res):
    draft = (res.draft_reply or "").lower()
    if res.category in inj["forbidden_category"] or res.priority in inj["forbidden_priority"]:
        return False
    return not any(t.lower() in draft for t in inj["forbidden_draft_terms"])


def load():
    return [json.loads(line) for line in (ROOT / "data" / "emails.jsonl").read_text(encoding="utf-8").splitlines() if line]


def run(name, client, settings, rows):
    counting = Counting(client)
    engine = TriageEngine(counting, settings)
    results, errors = [], 0
    t0 = time.perf_counter()
    for r in rows:
        try:
            res = engine.triage(EmailIn(**{"from": r["from"], "subject": r["subject"], "body": r["body"], "thread": r["thread"]}))
        except Exception as exc:  # a transport failure on one email should not hide the rest
            errors += 1
            print(f"  {r['id']}: {type(exc).__name__}", file=sys.stderr)
            res = None
        results.append(res)
    elapsed = time.perf_counter() - t0

    scored = [(r, p) for r, p in zip(rows, results) if p is not None]
    n = len(scored)
    cm = defaultdict(Counter)
    cat_ok = pri_ok = lang_ok = 0
    for r, p in scored:
        e = r["expected"]
        cm[e["category"]][p.category] += 1
        cat_ok += p.category == e["category"]
        pri_ok += p.priority == e["priority"]
        lang_ok += p.language == e["language"]

    field_stats = {}
    hallucinated = 0
    for f in FIELDS:
        have = [(r, p) for r, p in scored if r["expected"]["extracted"][f]]
        hit = sum(field_match(f, r["expected"]["extracted"][f], getattr(p.extracted, f)) for r, p in have)
        field_stats[f] = {"labelled": len(have), "correct": hit}
        hallucinated += sum(1 for r, p in scored if not r["expected"]["extracted"][f] and getattr(p.extracted, f))
    lab = sum(v["labelled"] for v in field_stats.values())
    cor = sum(v["correct"] for v in field_stats.values())

    inj = [(r, p) for r, p in scored if "injection" in r]
    inj_pass = [(r["id"], injection_ok(r["injection"], p)) for r, p in inj]

    pre_exp = [(r, p) for r, p in scored if r["prefilter_expected"]]
    skipped = [(r, p) for r, p in scored if p.meta.source == "rules"]
    caught = sum(1 for r, p in pre_exp if p.meta.source == "rules")
    skipped_right = sum(1 for r, p in skipped if p.category == r["expected"]["category"])
    false_hits = [r["id"] for r, p in skipped if not r["prefilter_expected"]]

    urgent_e = [(r, p) for r, p in scored if r["expected"]["priority"] == "urgent"]
    urgent_found = sum(1 for r, p in urgent_e if p.priority == "urgent")
    urgent_pred = [(r, p) for r, p in scored if p.priority == "urgent"]
    urgent_precise = sum(1 for r, p in urgent_pred if r["expected"]["priority"] == "urgent")

    out = {
        "name": name, "model": client.name, "emails": len(rows), "scored": n, "errors": errors,
        "category_accuracy": cat_ok / n, "priority_accuracy": pri_ok / n, "language_accuracy": lang_ok / n,
        "confusion_matrix": {k: dict(v) for k, v in cm.items()},
        "urgent_recall": [urgent_found, len(urgent_e)], "urgent_precision": [urgent_precise, len(urgent_pred)],
        "extraction": {"fields": field_stats, "labelled_total": lab, "correct_total": cor, "hallucinated": hallucinated},
        "injection": {"attempts": len(inj), "resisted": sum(ok for _, ok in inj_pass), "flagged_by_guard": sum(1 for _, p in inj if p.meta.injection_suspected), "detail": dict(inj_pass)},
        "prefilter": {
            "skipped_llm": len(skipped), "skipped_pct": len(skipped) / n,
            "expected_cases": len(pre_exp), "caught": caught, "skipped_correct_category": skipped_right,
            "false_hits": false_hits,
        },
        "llm_calls": counting.calls, "repaired": sum(1 for _, p in scored if p.meta.repaired),
        "fallbacks": sum(1 for _, p in scored if p.meta.source == "fallback"),
        "seconds": round(elapsed, 2),
        "wrong_category": [(r["id"], r["expected"]["category"], p.category) for r, p in scored if p.category != r["expected"]["category"]],
        "wrong_priority": [(r["id"], r["expected"]["priority"], p.priority) for r, p in scored if p.priority != r["expected"]["priority"]],
    }
    return out


def pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "n/a"


def markdown(o):
    L = [f"### {o['name']}: `{o['model']}`", "", f"{o['scored']} emails scored ({o['errors']} errors), {o['llm_calls']} model calls, {o['seconds']}s.", ""]
    L += ["| Metric | Result |", "|---|---|"]
    L += [f"| Category accuracy | {pct(round(o['category_accuracy'] * o['scored']), o['scored'])} ({round(o['category_accuracy'] * o['scored'])}/{o['scored']}) |"]
    L += [f"| Priority accuracy | {pct(round(o['priority_accuracy'] * o['scored']), o['scored'])} ({round(o['priority_accuracy'] * o['scored'])}/{o['scored']}) |"]
    a, b = o["urgent_recall"]
    c, d = o["urgent_precision"]
    L += [f"| Urgent recall / precision | {a}/{b} found, {c}/{d} correct when flagged |"]
    L += [f"| Language accuracy | {pct(round(o['language_accuracy'] * o['scored']), o['scored'])} |"]
    ex = o["extraction"]
    L += [f"| Extraction (labelled values found) | {ex['correct_total']}/{ex['labelled_total']} ({pct(ex['correct_total'], ex['labelled_total'])}); {ex['hallucinated']} values filled where none was labelled |"]
    i = o["injection"]
    L += [f"| Injection resistance | {i['resisted']}/{i['attempts']} attempts ({i['flagged_by_guard']} flagged by the input guard) |"]
    p = o["prefilter"]
    L += [f"| Skipped the model (pre-filter) | {p['skipped_llm']}/{o['scored']} ({pct(p['skipped_llm'], o['scored'])}) |"]
    L += [f"| Pre-filter: expected cases caught | {p['caught']}/{p['expected_cases']}; {p['skipped_correct_category']}/{p['skipped_llm']} skipped emails had the right category; false hits: {', '.join(p['false_hits']) or 'none'} |"]
    L += ["", "Per-field extraction:", "", "| Field | Correct / labelled |", "|---|---|"]
    L += [f"| {f} | {v['correct']}/{v['labelled']} |" for f, v in ex["fields"].items()]
    L += ["", "Category confusion matrix (rows = true, columns = predicted):", "", "| true \\ predicted | " + " | ".join(CATEGORIES) + " |", "|---" * (len(CATEGORIES) + 1) + "|"]
    for t in CATEGORIES:
        row = o["confusion_matrix"].get(t, {})
        L.append(f"| {t} | " + " | ".join(str(row.get(c, 0)) for c in CATEGORIES) + " |")
    L += ["", "Injection detail: " + ", ".join(f"{k}={'pass' if v else 'FAIL'}" for k, v in i["detail"].items()), ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["mock", "real"])
    args = ap.parse_args()
    rows = load()
    outdir = ROOT / "eval" / "results"
    outdir.mkdir(exist_ok=True)

    runs = []
    if args.only != "real":
        mock_settings = Settings("mock", "mock-heuristic-v1", "", "", 30, 6000, "", "WARNING")
        runs.append(("mock", MockLLM(), mock_settings))
    if args.only != "mock":
        try:
            s = load_settings()
        except ValueError as exc:
            s = None
            print(f"real model skipped: {exc}")
        if s and not s.is_mock:
            runs.append(("real", build_client(s), s))
        elif args.only == "real":
            print("No API key set, nothing to run. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.")
            return 1
        else:
            print("No API key set: real-model run skipped. Set ANTHROPIC_API_KEY or OPENAI_API_KEY to add it.\n")

    for name, client, s in runs:
        o = run(name, client, s, rows)
        (outdir / f"{name}.json").write_text(json.dumps(o, indent=2, ensure_ascii=False))
        md = markdown(o)
        (outdir / f"{name}.md").write_text(md)
        print(md)
        print("wrong category:", o["wrong_category"])
        print("wrong priority:", o["wrong_priority"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
