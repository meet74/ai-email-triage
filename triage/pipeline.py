import hashlib
import logging
import time
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from . import guard
from .config import Settings
from .llm import LLMClient, LLMError
from .prefilter import prefilter
from .prompts import repair_prompt, system_prompt, user_prompt
from .schema import Extracted, SchemaError, TriageResult, parse_model_output
from .text import clean_body, detect_language

log = logging.getLogger("triage")


class EmailIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sender: str = Field(alias="from", max_length=500)
    subject: str = Field(default="", max_length=1000)
    body: str = Field(default="", max_length=200_000)
    thread: list[str] = Field(default_factory=list, max_length=30)


class Meta(BaseModel):
    source: str  # rules | llm | fallback
    model: str
    skip_reason: Optional[str] = None  # spam | newsletter | auto_reply: no reply needed
    injection_suspected: bool = False
    draft_replaced: bool = False
    repaired: bool = False
    degraded: bool = False
    latency_ms: int = 0


class TriageResponse(TriageResult):
    meta: Meta


def _email_id(e: EmailIn) -> str:
    return hashlib.sha256(f"{e.sender}|{e.subject}".encode()).hexdigest()[:10]


class TriageEngine:
    def __init__(self, client: LLMClient, settings: Settings):
        self.client = client
        self.settings = settings
        self._system = system_prompt()

    def triage(self, email: EmailIn) -> TriageResponse:
        t0 = time.perf_counter()
        body, quoted = clean_body(email.body)
        thread = [t for t in email.thread if t.strip()]
        if quoted:
            thread.append(quoted)
        body = body[: self.settings.max_body_chars]
        lang = detect_language(f"{email.subject}\n{body}")

        hit = prefilter(email.sender, email.subject, body)
        if hit:
            res = TriageResponse(
                category=hit.category,
                priority=hit.priority,
                sentiment="neutral",
                language=lang,
                summary=(f"{hit.reason}: {email.subject}"[:300] or hit.reason),
                extracted=Extracted(),
                draft_reply="",
                confidence=0.9,
                reasons=[f"rule: {hit.reason}"],
                meta=Meta(source="rules", model="rules", skip_reason=hit.kind),
            )
            return self._done(email, res, t0)

        clean_subject, subj_removed = guard.strip_injected_lines(email.subject)
        clean_text, body_removed = guard.strip_injected_lines(body)
        clean_thread = []
        thread_removed = 0
        for item in thread:
            c, n = guard.strip_injected_lines(item)
            clean_thread.append(guard.neutralise_delimiters(c[: self.settings.max_body_chars]))
            thread_removed += n
        injected = (subj_removed + body_removed + thread_removed) > 0

        user = user_prompt(
            guard.neutralise_delimiters(email.sender),
            guard.neutralise_delimiters(clean_subject),
            guard.neutralise_delimiters(clean_text),
            clean_thread,
        )
        messages = [{"role": "user", "content": user}]
        repaired = False
        result: TriageResult | None = None
        try:
            raw = self.client.complete(self._system, messages)
            try:
                result = parse_model_output(raw)
            except SchemaError as first:
                repaired = True
                log.warning("model output invalid, retrying once: %s", first)
                messages += [
                    {"role": "assistant", "content": raw[:4000]},
                    {"role": "user", "content": repair_prompt(str(first))},
                ]
                result = parse_model_output(self.client.complete(self._system, messages))
        except SchemaError as second:
            log.error("model output invalid after retry: %s", second)
            result = None
        # LLMError is deliberately not caught: the API answers 502 and n8n retries.

        if result is None:
            fallback = TriageResponse(
                category="other",
                priority="normal",
                sentiment="neutral",
                language=lang,
                summary=f"Automatic triage failed; read the email: {email.subject}"[:300],
                extracted=Extracted(),
                draft_reply="",
                confidence=0.0,
                reasons=["model output was not valid after one repair attempt"],
                meta=Meta(source="fallback", model=self.client.name, repaired=True,
                          degraded=True, injection_suspected=injected),
            )
            return self._done(email, fallback, t0)

        data = result.model_dump()
        meta = Meta(source="llm", model=self.client.name, repaired=repaired, injection_suspected=injected)

        if result.category == "spam":
            meta.skip_reason = "spam"
            data["draft_reply"] = ""
        elif injected:
            data["draft_reply"] = guard.safe_draft(result.language, result.extracted.name)
            meta.draft_replaced = True
            data["reasons"] = (data["reasons"] + ["email contained instructions aimed at the assistant; they were removed and the draft was replaced"])[:6]
        else:
            problems = guard.draft_violations(result.draft_reply)
            if problems:
                data["draft_reply"] = guard.safe_draft(result.language, result.extracted.name)
                meta.draft_replaced = True
                data["reasons"] = (data["reasons"] + ["draft replaced: " + ", ".join(problems)])[:6]

        res = TriageResponse(**data, meta=meta)
        return self._done(email, res, t0)

    def _done(self, email: EmailIn, res: TriageResponse, t0: float) -> TriageResponse:
        res.meta.latency_ms = int((time.perf_counter() - t0) * 1000)
        # ids and labels only: no addresses, subjects, names or body text
        log.info(
            "triaged id=%s source=%s category=%s priority=%s injection=%s repaired=%s ms=%d",
            _email_id(email), res.meta.source, res.category, res.priority,
            res.meta.injection_suspected, res.meta.repaired, res.meta.latency_ms,
        )
        return res
