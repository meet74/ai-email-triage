"""Defences around the model call.

Email text is untrusted. Three layers: the prompt tells the model to treat it as
data, lines that look like instructions to an AI are removed before the model
sees them, and the draft that comes back is checked against the reply rules
whatever the model was told.
"""

import re

from .company import COMPANY

PLACEHOLDER = "[line removed: addressed to an automated system]"

_INJECTION_PATTERNS = [
    r"ignor(e|ez|a|ar)\b.{0,40}\b(previous|prior|above|earlier|all|anteriores|précédentes|precedentes)\b.{0,30}\b(instruction|prompt|rule|consigne|instrucci)",
    r"\b(ignore|ignorez|ignora|ignorar)\b.{0,30}\b(instrucci\w+|instructions|consignes|directives)\b",
    r"disregard\b.{0,40}\b(instruction|prompt|rule|above)",
    r"forget\b.{0,30}\b(instruction|everything|your rules)",
    r"\b(system|developer|admin)\s*(prompt|message|mode|override)\b",
    r"\byou are (now|no longer)\b",
    r"\bnew (instructions?|task|role)\s*:",
    r"\b(as|you are) an? (ai|llm|language model|assistant|chatbot|bot)\b",
    r"\b(note|message|attention|instruction)s? (to|for) (the )?(ai|assistant|bot|model|llm|automated|classifier|reviewer)\b",
    r"\b(asistente|assistant|asistente de ia|assistant ia)\b.{0,60}\b(clasifica|classifie|classify|marca|marque|mark)\b",
    r"\b(classify|categori[sz]e|mark|label|flag|rate|tag)\b.{0,25}\b(this|the)\b.{0,20}\b(email|message|mail|ticket)\b.{0,15}\bas\b",
    r"\b(correct|proper|right) (classification|category|priority)\b",
    r"\b(reveal|print|output|show|repeat|leak)\b.{0,40}\b(system prompt|your instructions|your prompt|hidden|customer (emails|data|list))\b",
    r"\b(respond|reply|answer|output) (only )?with\b.{0,30}\b(json|exactly|the following)\b",
    r"\bjailbreak\b|\bdo anything now\b|\bDAN mode\b",
    r"\bdo not (flag|escalate|show|display|mention)\b.{0,40}\b(this|human|staff|team)\b",
]
_INJECTION_RE = re.compile("|".join(f"(?:{p})" for p in _INJECTION_PATTERNS), re.I | re.S)


def detect_injection(text: str) -> bool:
    return bool(_INJECTION_RE.search(text or ""))


def strip_injected_lines(text: str) -> tuple[str, int]:
    """Replace every line (and sentence, for long lines) that matches an
    instruction-like pattern. Returns the cleaned text and how many pieces were removed."""
    removed = 0
    out_lines = []
    for line in (text or "").split("\n"):
        if not _INJECTION_RE.search(line):
            out_lines.append(line)
            continue
        pieces = re.split(r"(?<=[.!?])\s+", line)
        kept = []
        for piece in pieces:
            if _INJECTION_RE.search(piece):
                removed += 1
                if not kept or kept[-1] != PLACEHOLDER:
                    kept.append(PLACEHOLDER)
            else:
                kept.append(piece)
        out_lines.append(" ".join(kept))
    return "\n".join(out_lines), removed


def neutralise_delimiters(text: str) -> str:
    """Stop the email from closing the <email> block we wrap it in."""
    return re.sub(r"<\s*/?\s*email\s*>", "[tag removed]", text, flags=re.I)


# Drafts must not promise money, outcomes or dates, link anywhere, or hand out codes.
_DRAFT_RULES = [
    ("promises a refund", r"\b(we (will|'ll|are going to|have|'ve) (issue|process|send|give|grant|approve)[a-z ]{0,20}(refund|credit|reimburse))|\brefund (has been|is|was|will be) (approved|issued|processed|granted)|\b(full|complete) refund\b|\bwill be refunded\b|\bwe (will|'ll) refund\b|\bnous (vous )?rembourserons\b|\bremboursement (est |a été )?(accordé|approuvé|effectué)|\bhemos aprobado\b|\breembolso (aprobado|completo)"),
    ("promises a replacement or outcome", r"\bwe (will|'ll) (send|ship|replace|resend) (you )?(a |the )?(new|replacement)\b|\bguarantee\b|\bgarantizamos\b|\bnous garantissons\b"),
    ("promises a date or time frame", r"\b(within|in) (the next )?\d+\s*(business |working )?(hours?|days?|weeks?|heures?|jours?|horas?|días)\b|\b(by|on|before) (monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|tonight|today)\b|\bwill (arrive|be delivered|ship) (by|on|before)\b|\btomorrow\b"),
    ("contains a link", r"https?://|www\."),
    ("contains a code or secret", r"\b(discount|promo|voucher|coupon|access|admin|api)[ -]?(code|key|token|password)\b|\bpassword\b"),
    ("contains a payment instruction", r"\b(wire|transfer)\b.{0,30}\b(iban|account|bitcoin|btc)\b|\bgift ?card\b"),
]
_DRAFT_RULES_RE = [(name, re.compile(p, re.I)) for name, p in _DRAFT_RULES]


def draft_violations(draft: str) -> list[str]:
    hits = [name for name, rx in _DRAFT_RULES_RE if rx.search(draft or "")]
    # An address other than ours means the model was talked into redirecting the customer.
    for addr in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", draft or ""):
        if addr.lower() != COMPANY["support_address"]:
            hits.append("mentions an unknown email address")
            break
    return hits


_SAFE_DRAFTS = {
    "en": "Hello{name},\n\nThank you for writing to us. We have received your message and a member of our team will review it and reply personally. If you have an order number, please include it so we can find your order quickly.\n\nKind regards,\n{sig}",
    "fr": "Bonjour{name},\n\nMerci de nous avoir écrit. Nous avons bien reçu votre message et un membre de notre équipe l'examinera et vous répondra personnellement. Si vous avez un numéro de commande, merci de nous l'indiquer.\n\nCordialement,\n{sig}",
    "es": "Hola{name},\n\nGracias por escribirnos. Hemos recibido su mensaje y un miembro de nuestro equipo lo revisará y le responderá personalmente. Si tiene un número de pedido, indíquelo para que podamos localizar su compra.\n\nSaludos cordiales,\n{sig}",
}


def safe_draft(language: str, name: str | None) -> str:
    template = _SAFE_DRAFTS.get(language, _SAFE_DRAFTS["en"])
    first = ""
    if name:
        first = " " + name.strip().split()[0]
    return template.format(name=first, sig=COMPANY["signature"])
