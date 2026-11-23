from collections import Counter

from .schema import CATEGORIES, PRIORITIES

OPEN_STATUSES = {"pending_approval", "new"}


def build_digest(tickets: list[dict], date: str) -> dict:
    """Summarise tickets created on `date` (YYYY-MM-DD) and list urgent tickets
    that are still waiting, whatever day they arrived."""
    day = [t for t in tickets if str(t.get("created_at", "")).startswith(date)]
    by_cat = Counter(t.get("category", "other") for t in day)
    by_pri = Counter(t.get("priority", "normal") for t in day)
    by_status = Counter(t.get("status", "") for t in day)
    waiting = [
        t for t in tickets
        if t.get("priority") == "urgent" and t.get("status") in OPEN_STATUSES
    ]
    waiting.sort(key=lambda t: str(t.get("created_at", "")))

    stats = {
        "date": date,
        "total": len(day),
        "by_category": {c: by_cat.get(c, 0) for c in CATEGORIES},
        "by_priority": {p: by_pri.get(p, 0) for p in PRIORITIES},
        "by_status": dict(by_status),
        "unanswered_urgent": [
            {"ticket_id": t.get("ticket_id"), "from": t.get("from"), "subject": t.get("subject"),
             "created_at": t.get("created_at")}
            for t in waiting
        ],
    }

    lines = [f"*Tickets for {date}: {stats['total']}*"]
    if stats["total"]:
        lines.append("By category: " + ", ".join(f"{c} {n}" for c, n in stats["by_category"].items() if n))
        lines.append("By priority: " + ", ".join(f"{p} {n}" for p, n in stats["by_priority"].items() if n))
        lines.append("By status: " + ", ".join(f"{s or 'unknown'} {n}" for s, n in sorted(by_status.items())))
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"Inbox digest for {date}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
    ]
    if waiting:
        items = "\n".join(
            f"- {t.get('ticket_id')} from {t.get('from')}: {t.get('subject')} (since {str(t.get('created_at'))[:16]})"
            for t in waiting[:15]
        )
        more = f"\n...and {len(waiting) - 15} more" if len(waiting) > 15 else ""
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
                       "text": f"*Urgent and still unanswered: {len(waiting)}*\n{items}{more}"}})
    else:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "No urgent tickets waiting."}})
    return {"text": f"Inbox digest {date}: {stats['total']} tickets, {len(waiting)} urgent unanswered",
            "blocks": blocks, "stats": stats}
