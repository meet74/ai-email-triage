"""Body clean-up and language detection. Both are deliberately simple and
dependency-free; the n8n workflow runs the same kind of clean-up before it
calls the service, and running it twice is harmless."""

import re

_REPLY_MARKERS = [
    re.compile(r"^\s*On .{5,120}wrote:\s*$", re.I),
    re.compile(r"^\s*Le .{5,120}a écrit\s*:\s*$", re.I),
    re.compile(r"^\s*El .{5,120}escribió:\s*$", re.I),
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$", re.I),
    re.compile(r"^\s*_{5,}\s*$"),
    re.compile(r"^\s*From:\s.+$", re.I),  # only honoured when Sent:/Date: follows
]
_SIGNATURE_MARKERS = [
    re.compile(r"^--\s?$"),
    re.compile(r"^\s*Sent from my (iPhone|iPad|Android|phone|Galaxy)", re.I),
    re.compile(r"^\s*Get Outlook for (iOS|Android)", re.I),
    re.compile(r"^\s*(This|The) (e-?mail|message) (and any attachments )?(is|are) confidential", re.I),
    re.compile(r"^\s*Envoyé de mon (iPhone|iPad)", re.I),
    re.compile(r"^\s*Enviado desde mi (iPhone|iPad|móvil)", re.I),
]
_FORWARD = re.compile(r"-{3,}\s*(Forwarded message|Message transféré|Mensaje reenviado)\s*-{3,}", re.I)


def split_quoted(body: str) -> tuple[str, str]:
    """Return (new_text, quoted_history). Forwarded content stays in new_text
    because the forwarder usually wants it acted on."""
    lines = body.replace("\r\n", "\n").split("\n")
    cut = None
    for i, line in enumerate(lines):
        if _FORWARD.search(line):
            # everything from here is forwarded content, not reply history
            break
        if line.lstrip().startswith(">"):
            cut = i
            break
        for pat in _REPLY_MARKERS[:5]:
            if pat.match(line):
                cut = i
                break
        if cut is not None:
            break
        if _REPLY_MARKERS[5].match(line) and any(
            re.match(r"^\s*(Sent|Date|Envoyé|Enviado):", nxt, re.I) for nxt in lines[i + 1 : i + 4]
        ):
            cut = i
            break
    if cut is None:
        return body.strip(), ""
    return "\n".join(lines[:cut]).strip(), "\n".join(lines[cut:]).strip()


def strip_signature(text: str) -> str:
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if _FORWARD.search(line):
            return text.strip()
        if any(p.match(line) for p in _SIGNATURE_MARKERS):
            return "\n".join(lines[:i]).strip()
    return text.strip()


def clean_body(body: str) -> tuple[str, str]:
    new_text, quoted = split_quoted(body or "")
    return strip_signature(new_text), quoted


_STOPWORDS = {
    "en": "the and is are to of in for with my your you i we this that have has not was it on be can please thanks order".split(),
    "fr": "le la les de des et est un une pour avec mon ma vous je nous ce que pas sur bonjour merci commande êtes suis".split(),
    "es": "el la los las de y es un una para con mi su usted yo nosotros que no en hola gracias pedido por está".split(),
    "de": "der die das und ist ein eine für mit mein ihr sie ich wir nicht auf bitte danke bestellung".split(),
}
_WORD = re.compile(r"[a-zA-ZÀ-ÿ']+")


def detect_language(text: str) -> str:
    words = [w.lower() for w in _WORD.findall(text)[:400]]
    if not words:
        return "en"
    scores = {}
    for lang, stops in _STOPWORDS.items():
        s = set(stops)
        scores[lang] = sum(1 for w in words if w in s)
    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0 or (best != "en" and scores[best] <= scores["en"]):
        return "en"
    return best
