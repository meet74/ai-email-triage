import json
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

Category = Literal["support", "sales_lead", "billing", "complaint", "spam", "other"]
Priority = Literal["urgent", "normal", "low"]
Sentiment = Literal["positive", "neutral", "negative"]

CATEGORIES = ["support", "sales_lead", "billing", "complaint", "spam", "other"]
PRIORITIES = ["urgent", "normal", "low"]
ACTIONS = [
    "refund", "replacement", "exchange", "cancel_order", "order_status",
    "invoice_copy", "payment_issue", "quote", "product_info", "warranty_claim",
    "address_change", "other",
]


class Extracted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    company: Optional[str] = None
    order_id: Optional[str] = None
    invoice_number: Optional[str] = None
    product: Optional[str] = None
    requested_action: Optional[str] = None
    deadline: Optional[str] = None

    @field_validator("*", mode="before")
    @classmethod
    def blank_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        if isinstance(v, str) and v.strip().lower() in ("null", "none", "n/a", "unknown"):
            return None
        return v

    @field_validator("requested_action")
    @classmethod
    def known_action(cls, v):
        if v is not None and v not in ACTIONS:
            raise ValueError(f"requested_action must be one of {ACTIONS}")
        return v


class TriageResult(BaseModel):
    """What the model must return. All keys are required; extra keys are rejected."""

    model_config = ConfigDict(extra="forbid")

    category: Category
    priority: Priority
    sentiment: Sentiment
    language: str = Field(min_length=2, max_length=5)
    summary: str = Field(min_length=1, max_length=400)
    extracted: Extracted
    draft_reply: str = Field(max_length=3000)
    confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(min_length=1, max_length=6)

    @field_validator("language")
    @classmethod
    def lower_language(cls, v):
        return v.strip().lower()


class SchemaError(ValueError):
    """Model output could not be parsed or validated."""


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def parse_model_output(raw: str) -> TriageResult:
    text = _FENCE.sub("", (raw or "").strip()).strip()
    if not text.startswith("{"):
        # tolerate a sentence before the object, but only take one top-level object
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise SchemaError("no JSON object found in model output")
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SchemaError(f"invalid JSON: {exc.msg} at position {exc.pos}") from None
    if not isinstance(data, dict):
        raise SchemaError("top-level JSON value must be an object")
    try:
        return TriageResult.model_validate(data)
    except ValidationError as exc:
        raise SchemaError(describe_validation_error(exc)) from None


def describe_validation_error(exc: ValidationError) -> str:
    """Field paths and reasons only. Pydantic's default text echoes the offending
    values, which can contain customer text, so it never goes into logs or prompts."""
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        parts.append(f"{loc}: {err['type']}")
    return "; ".join(parts)
