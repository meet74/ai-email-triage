"""Cheap rules that settle the obvious cases before any model call.

The rules are conservative: a miss costs one model call, a false hit hides a
real customer. Matched mail is still ticketed and labelled, never deleted.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PrefilterHit:
    kind: str  # auto_reply | newsletter | spam | phishing
    category: str
    priority: str
    reason: str


_AUTO_SUBJECT = re.compile(
    r"^\s*(re:\s*)?(automatic reply|auto[- ]?reply|autoreply|out of office|undeliverable|"
    r"delivery status notification|mail delivery (failed|subsystem)|returned mail|"
    r"réponse automatique|absence du bureau|respuesta automática|fuera de la oficina)",
    re.I,
)
_AUTO_SENDER = re.compile(r"^(mailer-daemon|postmaster)@", re.I)
_AUTO_BODY = re.compile(
    r"(this is an automated (message|reply|response)|i am (currently )?out of (the )?office|"
    r"do not reply to this (message|email)|je suis absent|estaré fuera de la oficina|"
    r"message could not be delivered)",
    re.I,
)

_BULK_SENDER = re.compile(r"(^|[<\s])(no-?reply|newsletter|news|marketing|offers|deals|promo|mailer)[\w.+-]*@", re.I)
_UNSUBSCRIBE = re.compile(r"\bunsubscribe\b|\bse désabonner\b|\bdarse de baja\b|\bmanage (your )?(email )?preferences\b", re.I)
_VIEW_IN_BROWSER = re.compile(r"view (this email )?in (your )?browser|voir (cet e-?mail )?dans (votre )?navigateur", re.I)

_SPAM_STRONG = re.compile(
    r"(guaranteed (first|top|#1) (page|ranking)|rank (you )?(#1|first|on page one)|"
    r"\bseo (services|package|audit)\b|buy (followers|likes)|crypto(currency)? (investment|trading|signals)|"
    r"you('ve| have) (won|been selected)|lottery|inheritance|bulk (email|mailing) list|"
    r"verified (leads|email list)|(erectile|viagra|cialis)|work from home and earn|"
    r"\bloan (approval|offer)\b.{0,30}\bno credit check)",
    re.I,
)
_PHISH_LURE = re.compile(
    r"(verify your (account|identity|payment)|confirm your (password|account|login)|"
    r"(account|payment|card) (has been |will be |is )?(suspended|locked|limited|restricted)|"
    r"unusual (sign-?in|activity)|update your (billing|payment) (details|information))",
    re.I,
)
_URL = re.compile(r"https?://\S+", re.I)


def prefilter(sender: str, subject: str, body: str) -> PrefilterHit | None:
    subject = subject or ""
    body = body or ""
    sender = sender or ""
    head = body[:1500]
    address = sender.strip().split("<")[-1].strip(">").strip()

    if _AUTO_SUBJECT.search(subject) or _AUTO_SENDER.search(address):
        return PrefilterHit("auto_reply", "other", "low", "automatic reply or delivery notice")
    if _AUTO_BODY.search(head) and len(body) < 700 and "?" not in body:
        return PrefilterHit("auto_reply", "other", "low", "automated message text")

    if _UNSUBSCRIBE.search(body) and (_BULK_SENDER.search(sender) or _VIEW_IN_BROWSER.search(body)):
        return PrefilterHit("newsletter", "spam", "low", "bulk mailing with unsubscribe footer")

    if _PHISH_LURE.search(body) and _URL.search(body):
        return PrefilterHit("phishing", "spam", "low", "account-verification lure with a link")

    if _SPAM_STRONG.search(subject + "\n" + body):
        return PrefilterHit("spam", "spam", "low", "unsolicited offer")
    return None
