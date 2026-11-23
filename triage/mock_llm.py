"""Deterministic stand-in for a real model.

Keyword and regex heuristics over the email text it is handed, in English,
French and Spanish. It has no access to labels and makes no network calls. It is
meant for tests, demos and free local runs; it is much weaker than a real model
and the eval report labels its numbers accordingly.
"""

import json
import re

from .company import COMPANY
from .prompts import EMAIL_CLOSE, EMAIL_OPEN
from .text import detect_language

_CATEGORY_TERMS = {
    "billing": [
        ("invoice", 2), ("facture", 2), ("factura", 2), ("charged", 2), ("double charge", 3),
        ("billing", 2), ("receipt", 1.5), ("payment", 1.5), ("paiement", 1.5), ("pago", 1.5),
        ("cobro", 2), ("cobrado", 2), ("débité", 2), ("prélevé", 2), ("vat", 1.5), ("tax id", 2),
        ("credit card", 1), ("card was", 1), ("refund", 0.5), ("remboursement", 0.5), ("reembolso", 0.5),
        ("purchase order", 1),
    ],
    "sales_lead": [
        ("wholesale", 3), ("bulk", 2), ("quote", 2.5), ("quotation", 2.5), ("devis", 2.5), ("presupuesto", 2.5),
        ("mayorista", 3), ("reseller", 3), ("distributor", 3), ("partnership", 2), ("corporate", 1.5),
        ("our team of", 1.5), ("for our staff", 1.5), ("volume discount", 3), ("pricing for", 2),
        ("pricing", 1), ("interested in ordering", 3), ("retail", 1), ("stock", 0.5), ("sponsor", 1.5),
        ("custom logo", 2),
    ],
    "complaint": [
        ("unacceptable", 3), ("inacceptable", 3), ("inadmisible", 3), ("disappointed", 2), ("déçu", 2), ("decepcion", 2),
        ("terrible", 2), ("worst", 2.5), ("furious", 3), ("angry", 2), ("never again", 3), ("jamás volveré", 3),
        ("complaint", 2.5), ("queja", 2.5), ("réclamation", 2.5), ("fed up", 2.5), ("ridiculous", 2), ("scandal", 2),
        ("lawyer", 2), ("chargeback", 3), ("dispute", 1.5), ("negative review", 2.5), ("worthless", 2), ("rip-off", 3), ("rip off", 3),
        ("no one has replied", 2), ("still no reply", 2), ("third time", 2), ("poor quality", 1.5),
    ],
    "support": [
        ("where is my order", 3), ("tracking", 2), ("not arrived", 2), ("hasn't arrived", 2), ("has not arrived", 2),
        ("broken", 2), ("defective", 2), ("damaged", 2), ("not working", 2), ("stopped working", 2),
        ("return", 1.5), ("exchange", 1.5), ("warranty", 2), ("size", 1), ("zipper", 2), ("leak", 1.5),
        ("how do i", 2), ("how can i", 1.5), ("cancel my order", 3), ("missing", 1.5), ("wrong item", 3),
        ("replacement", 1.5), ("order status", 2.5), ("suivi", 2), ("colis", 2), ("n'est pas arrivé", 2.5),
        ("pedido", 1.5), ("no ha llegado", 3), ("seguimiento", 2), ("roto", 2), ("cassé", 2), ("est cassée", 2),
        ("change the shipping address", 2.5), ("compatible", 1.5), ("instructions", 1), ("does it", 1), ("is it possible", 1),
        ("fit", 1), ("replace", 1.5), ("order", 0.5),
    ],
    "other": [
        ("journalist", 3), ("press", 2), ("interview", 2), ("job application", 3), ("resume", 2.5), ("cv attached", 3),
        ("careers", 2), ("hiring", 1.5), ("supplier", 2), ("wrong address", 2), ("meant for", 2),
        ("podcast", 2.5), ("guest post", 2), ("sponsorship request", 2), ("donation", 2), ("volunteer", 1.5),
        ("not sure this is the right", 2.5), ("blog", 1), ("photographer", 1.5),
    ],
}

_URGENT_TERMS = [
    "chargeback", "dispute with my bank", "contacting my bank", "lawyer", "legal action", "sue ", "small claims",
    "caught fire", "on fire", "fire ", "burn", "smoke", "overheat", "got hot", "too hot to", "leaking fuel", "fuel leak",
    "gas leak", "smell of gas", "smell gas", "injur", "hospital", "unsafe", "dangerous", "poison", "explod", "emergency",
    "feu ", "brûl", "fuite de gaz", "danger", "peligro", "fuga de gas", "incendio", "urgence", "urgente", "refund immediately",
    "asap", "right now", "within 24 hours", "recall",
]
_DEADLINE_PRESSURE = ["tomorrow", "this weekend", "leaving on", "leave on", "depart", "trip starts", "demain", "mañana", "ce week-end", "este fin de semana"]
_LOW_TERMS = [
    "no rush", "no hurry", "when you get a chance", "just wanted to say", "thank you so much", "thanks again", "love my",
    "great product", "just a thought", "fyi", "for your information", "just wondering", "whenever you can", "keep up the good work",
    "feedback", "suggestion",
]
_NEG = ["unacceptable", "disappointed", "terrible", "worst", "furious", "angry", "never again", "fed up", "ridiculous",
        "broken", "defective", "damaged", "unhappy", "frustrated", "scandal", "rip-off", "not happy", "déçu", "inacceptable", "inadmisible",
        "decepcion", "enfadado", "molesto", "cassé", "roto", "poor", "worthless", "no reply", "third time", "dangerous", "stopped working"]
_POS = ["thank you", "thanks", "love", "great", "happy", "perfect", "excellent", "appreciate", "merci", "gracias", "awesome", "wonderful"]

_ORDER = re.compile(r"\bNB-\d{4,6}\b")
_INVOICE = re.compile(r"\bINV-\d{4}-\d{3,5}\b")
_DAYS = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|lunes|martes|miércoles|jueves|viernes|sábado|domingo)"
_MONTHS = r"(?:january|february|march|april|may|june|july|august|september|october|november|december|janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre|enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)"
_DEADLINE = re.compile(
    rf"\b(?:by|before|no later than|until|avant le|antes del|avant|antes de|pour le|para el|for)\s+((?:the\s+)?(?:end of (?:the )?(?:day|week|month)|{_DAYS}(?:\s+(?:morning|evening))?|{_MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?|\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+|de\s+)?{_MONTHS}|tomorrow|tonight|demain|mañana))",
    re.I,
)
_DEADLINE_ONON = re.compile(rf"\b(?:on|le|el)\s+({_DAYS}|\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+|de\s+)?{_MONTHS}|{_MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?)\b.*(?:need|trip|event|leav|depart|besoin|necesito|salgo|part)", re.I)

_SIGNOFF = re.compile(
    r"^\s*(thanks|thank you|many thanks|regards|best regards|best|kind regards|warm regards|cheers|sincerely|"
    r"yours sincerely|merci|cordialement|bien cordialement|salutations|gracias|saludos|atentamente|un saludo|saludos cordiales|thx)[,.!]?\s*$",
    re.I,
)
_COMPANY_WORDS = re.compile(r"\b(inc|llc|ltd|co\.|corp|gmbh|sarl|sa|s\.l\.|outfitters|supply|store|shop|club|school|rentals|guides|expeditions|adventures|collective|retail|sports|group|outdoors)\b\.?", re.I)

_ACTIONS = [
    ("payment_issue", r"charged (me )?(twice|two times|double)|double charge|doublement|cobrado dos veces|payment (failed|was declined|didn't go)|débité deux fois"),
    ("invoice_copy", r"(copy of|send( me)?|need|resend|get) (the |my |an? )?(invoice|receipt|facture|factura)|invoice copy|vat invoice|facture (au nom|avec)|factura (a nombre|con)"),
    ("cancel_order", r"cancel (my|the) order|annuler (ma|la) commande|cancelar (mi|el) pedido"),
    ("address_change", r"change (the |my )?(shipping |delivery )?address|wrong address|changer l'adresse|cambiar la dirección"),
    ("warranty_claim", r"warranty|garantie|garantía"),
    ("replacement", r"replacement|replace (it|the|my)|send (me )?a new|remplacement|remplacer|reemplazo|reemplazar|sustituir"),
    ("exchange", r"exchange|swap (it|for)|échanger|changer (de )?taille|cambiar (por|de talla)"),
    ("refund", r"refund|money back|reimburse|rembours|reembolso|devolución del dinero"),
    ("order_status", r"where is my (order|package|parcel)|tracking|order status|hasn't arrived|has not arrived|not arrived|n'est pas arrivé|pas reçu|no ha llegado|no he recibido|seguimiento|suivi"),
    ("quote", r"\bquote\b|quotation|pricing|price list|devis|presupuesto|volume discount|wholesale|mayorista"),
    ("product_info", r"how (do|can) i|is it (possible|compatible)|does (it|the)|will (it|the) .{0,30}(fit|work)|compatible|what size|which size|instructions|quelle taille|cuál talla|qué talla"),
]

_SUMMARY = {
    "support": "Customer needs help with an order or product",
    "sales_lead": "Business enquiry about buying or partnering",
    "billing": "Billing or invoice question",
    "complaint": "Unhappy customer raising a complaint",
    "spam": "Unsolicited message",
    "other": "General message that does not fit a customer-service category",
}

_REPLIES = {
    "en": {
        "greet": "Hello{name},",
        "body": {
            "support": "Thank you for getting in touch about{ref}. I have passed your message to our team and someone will look into it and reply to you personally.",
            "sales_lead": "Thank you for your interest in Northbeam Outdoor Gear. I have passed your enquiry to our sales team and they will reply to you personally.",
            "billing": "Thank you for your message about{ref}. I have passed it to our accounts team and someone will review it and reply to you personally.",
            "complaint": "I am sorry things have not gone the way they should. I have passed your message to a senior member of our team, who will review it and reply to you personally.",
            "other": "Thank you for your message. I have passed it to the right person on our team, who will reply to you personally.",
        },
        "ask": {
            "order": " Could you please send your order number (it looks like NB-12345) so we can find your order?",
            "invoice": " Could you please send the invoice or order number the question relates to?",
            "quantity": " To help our team, could you tell us roughly which products and quantities you have in mind, and when you would need them?",
            "photos": " If you can, please attach a photo of the problem.",
        },
        "safety": " Please stop using the item until we have spoken.",
        "close": "Kind regards,",
    },
    "fr": {
        "greet": "Bonjour{name},",
        "body": {
            "support": "Merci de nous avoir contactés{ref}. J'ai transmis votre message à notre équipe, qui l'examinera et vous répondra personnellement.",
            "sales_lead": "Merci de l'intérêt que vous portez à Northbeam Outdoor Gear. J'ai transmis votre demande à notre équipe commerciale, qui vous répondra personnellement.",
            "billing": "Merci pour votre message{ref}. Je l'ai transmis à notre service comptabilité, qui l'examinera et vous répondra personnellement.",
            "complaint": "Je suis désolé que les choses ne se soient pas passées comme elles auraient dû. J'ai transmis votre message à un responsable, qui vous répondra personnellement.",
            "other": "Merci pour votre message. Je l'ai transmis à la bonne personne dans notre équipe, qui vous répondra personnellement.",
        },
        "ask": {
            "order": " Pourriez-vous nous indiquer votre numéro de commande (de la forme NB-12345) ?",
            "invoice": " Pourriez-vous nous indiquer le numéro de facture ou de commande concerné ?",
            "quantity": " Pour aider notre équipe, pourriez-vous nous indiquer les produits et quantités envisagés, ainsi que votre échéance ?",
            "photos": " Si possible, joignez une photo du problème.",
        },
        "safety": " Merci de ne plus utiliser l'article en attendant notre retour.",
        "close": "Cordialement,",
    },
    "es": {
        "greet": "Hola{name},",
        "body": {
            "support": "Gracias por ponerse en contacto con nosotros{ref}. He pasado su mensaje a nuestro equipo y alguien lo revisará y le responderá personalmente.",
            "sales_lead": "Gracias por su interés en Northbeam Outdoor Gear. He pasado su consulta a nuestro equipo comercial, que le responderá personalmente.",
            "billing": "Gracias por su mensaje{ref}. Lo he pasado a nuestro equipo de administración, que lo revisará y le responderá personalmente.",
            "complaint": "Lamento que las cosas no hayan salido como debían. He pasado su mensaje a una persona responsable de nuestro equipo, que le responderá personalmente.",
            "other": "Gracias por su mensaje. Lo he pasado a la persona adecuada de nuestro equipo, que le responderá personalmente.",
        },
        "ask": {
            "order": " ¿Podría indicarnos su número de pedido (con el formato NB-12345)?",
            "invoice": " ¿Podría indicarnos el número de factura o de pedido al que se refiere?",
            "quantity": " Para ayudar a nuestro equipo, ¿podría indicarnos qué productos y cantidades necesita y para cuándo?",
            "photos": " Si puede, adjunte una foto del problema.",
        },
        "safety": " Le pedimos que no utilice el artículo hasta que hablemos.",
        "close": "Saludos cordiales,",
    },
}


def _count(text: str, terms) -> float:
    total = 0.0
    for term, weight in terms:
        if term in text:
            total += weight
    return total


def _extract_email_block(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m["role"] == "user" and EMAIL_OPEN in m["content"]:
            c = m["content"]
            return c[c.index(EMAIL_OPEN) + len(EMAIL_OPEN) : c.rindex(EMAIL_CLOSE)].strip()
    return ""


def _split_block(block: str) -> tuple[str, str, str]:
    lines = block.split("\n")
    sender = lines[0][len("from:"):].strip() if lines and lines[0].startswith("from:") else ""
    subject = lines[1][len("subject:"):].strip() if len(lines) > 1 and lines[1].startswith("subject:") else ""
    body = "\n".join(lines[3:]) if len(lines) > 3 else ""
    return sender, subject, body


def _find_name(sender: str, body: str) -> str | None:
    lines = [ln.strip() for ln in body.split("\n")]
    for i, ln in enumerate(lines):
        if _SIGNOFF.match(ln):
            for nxt in lines[i + 1 : i + 3]:
                if nxt and len(nxt.split()) <= 4 and re.match(r"^[A-ZÀ-Ý][\w'’.-]+(?:\s+[A-ZÀ-Ý][\w'’.-]+){0,3}$", nxt):
                    return nxt
    m = re.search(r"(?:my name is|this is|i am|i'm|je m'appelle|me llamo|soy)\s+([A-ZÀ-Ý][\w'’-]+(?:\s+[A-ZÀ-Ý][\w'’-]+)?)", body)
    if m and m.group(1).lower() not in ("not", "writing", "contacting"):
        return m.group(1)
    m = re.match(r'^"?([^"<@]+?)"?\s*<', sender)
    if m and m.group(1).strip() and "@" not in m.group(1):
        return m.group(1).strip()
    return None


def _find_company(body: str, name: str | None) -> str | None:
    for ln in body.split("\n"):
        s = ln.strip()
        if not s or len(s) > 60 or s == name or s.endswith((".", "?", "!", ":")) and not _COMPANY_WORDS.search(s):
            continue
        if _COMPANY_WORDS.search(s) and len(s.split()) <= 6 and re.match(r"^[A-ZÀ-Ý0-9]", s):
            return s.rstrip(",")
    m = re.search(r"\b(?:from|at|with|for|of)\s+([A-Z][\w&'-]+(?:\s+[A-Z][\w&'-]+){0,3}\s+(?:Inc|LLC|Ltd|GmbH|Co|Outfitters|Supply|Rentals|Guides|Collective|Club|School|Sports))\b", body)
    return m.group(1) if m else None


def _find_deadline(text: str) -> str | None:
    m = _DEADLINE.search(text)
    if m:
        return re.sub(r"^the\s+", "", m.group(1).strip(), flags=re.I)
    m = _DEADLINE_ONON.search(text)
    if m:
        return m.group(1)
    return None


def _find_product(text_lower: str) -> str | None:
    best = None
    for p in COMPANY["products"]:
        i = text_lower.find(p.lower())
        if i != -1 and (best is None or i < best[0]):
            best = (i, p)
    if best:
        return best[1]
    # partial names such as "the Ridgeline" or "my Summit bag"
    for p in COMPANY["products"]:
        head = p.split()[0].lower()
        if len(head) > 4 and re.search(rf"\b{head}\b", text_lower):
            return p
    return None


def _requested_action(text_lower: str) -> str | None:
    for action, pattern in _ACTIONS:
        if re.search(pattern, text_lower):
            return action
    return None


class MockLLM:
    name = "mock:heuristic-v1"

    def complete(self, system: str, messages: list[dict]) -> str:
        sender, subject, body = _split_block(_extract_email_block(messages))
        return json.dumps(self._triage(sender, subject, body), ensure_ascii=False)

    def _triage(self, sender: str, subject: str, body: str) -> dict:
        full = f"{subject}\n{body}"
        low = full.lower()
        lang = detect_language(full)

        scores = {c: _count(low, terms) for c, terms in _CATEGORY_TERMS.items()}
        # A complaint is mostly about tone; a plain problem report stays support.
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        top, top_score = ranked[0]
        second_score = ranked[1][1]
        if top_score < 1:
            category = "other"
        else:
            category = top
        if category == "support" and scores["complaint"] >= 2.5 and scores["complaint"] >= scores["support"] - 1:
            category = "complaint"
        if category == "billing" and scores["complaint"] >= 3 and scores["billing"] < 4:
            category = "complaint"

        urgent_hits = [t.strip() for t in _URGENT_TERMS if t in low]
        pressure = [t for t in _DEADLINE_PRESSURE if t in low]
        negative = sum(1 for t in _NEG if t in low)
        positive = sum(1 for t in _POS if t in low)
        sentiment = "neutral"
        if negative >= 2 or (negative and not positive):
            sentiment = "negative"
        elif positive and not negative:
            sentiment = "positive"

        if urgent_hits or (pressure and category in ("support", "complaint") and negative):
            priority = "urgent"
        elif any(t in low for t in _LOW_TERMS) and category in ("other", "support", "sales_lead") and negative == 0:
            priority = "low"
        elif category == "other" and top_score < 1:
            priority = "low"
        else:
            priority = "normal"

        order = _ORDER.search(full)
        invoice = _INVOICE.search(full)
        name = _find_name(sender, body)
        action = _requested_action(low)
        extracted = {
            "name": name,
            "company": _find_company(body, name),
            "order_id": order.group(0) if order else None,
            "invoice_number": invoice.group(0) if invoice else None,
            "product": _find_product(low),
            "requested_action": action,
            "deadline": _find_deadline(full),
        }

        margin = top_score - second_score
        confidence = 0.35 if top_score < 1 else min(0.92, 0.5 + 0.06 * margin + 0.02 * top_score)
        reasons = []
        if top_score >= 1:
            matched = [t for t, _ in _CATEGORY_TERMS[top] if t in low][:3]
            reasons.append(f"{category} wording: " + ", ".join(matched) if matched else f"looks like {category}")
        else:
            reasons.append("no strong category wording; defaulting to other")
        if urgent_hits:
            reasons.append("urgent wording: " + ", ".join(urgent_hits[:3]))
        elif pressure:
            reasons.append("time pressure mentioned")

        return {
            "category": category,
            "priority": priority,
            "sentiment": sentiment,
            "language": lang,
            "summary": self._summary(category, extracted),
            "extracted": extracted,
            "draft_reply": self._draft(category, lang, extracted, priority, urgent_hits, low),
            "confidence": round(confidence, 2),
            "reasons": reasons,
        }

    @staticmethod
    def _summary(category: str, ex: dict) -> str:
        parts = [_SUMMARY[category]]
        bits = [b for b in (ex["order_id"], ex["invoice_number"], ex["product"]) if b]
        if bits:
            parts.append("(" + ", ".join(bits) + ")")
        if ex["requested_action"]:
            parts.append("- asks for: " + ex["requested_action"].replace("_", " "))
        return " ".join(parts)[:300]

    @staticmethod
    def _draft(category: str, lang: str, ex: dict, priority: str, urgent_hits: list, low: str) -> str:
        if category == "spam":
            return ""
        t = _REPLIES.get(lang, _REPLIES["en"])
        first = (" " + ex["name"].split()[0]) if ex["name"] else ""
        ref = ""
        if ex["order_id"]:
            ref = " order " + ex["order_id"] if lang == "en" else " (" + ex["order_id"] + ")"
        elif ex["invoice_number"]:
            ref = " invoice " + ex["invoice_number"] if lang == "en" else " (" + ex["invoice_number"] + ")"
        text = t["body"][category].format(ref=ref)
        if category in ("support", "complaint") and not ex["order_id"]:
            text += t["ask"]["order"]
        if category == "billing" and not ex["invoice_number"] and not ex["order_id"]:
            text += t["ask"]["invoice"]
        if category == "sales_lead":
            text += t["ask"]["quantity"]
        if category == "support" and any(w in low for w in ("broken", "damaged", "defective", "roto", "cassé", "zipper")):
            text += t["ask"]["photos"]
        if priority == "urgent" and any(w in low for w in ("fire", "burn", "smoke", "overheat", "leak", "fuel", "gas", "injur", "hot", "feu", "brûl", "fuga", "fuite", "incendio")):
            text += t["safety"]
        return f"{t['greet'].format(name=first)}\n\n{text}\n\n{t['close']}\n{COMPANY['signature']}"
