import hmac
import logging

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .config import Settings, load_settings
from .digest import build_digest
from .llm import LLMClient, LLMError, build_client
from .logging_setup import setup_logging
from .pipeline import EmailIn, TriageEngine, TriageResponse
from .slack import approval_message, edit_modal, sms_text, urgent_alert_text

log = logging.getLogger("triage")


class ApprovalRequest(BaseModel):
    ticket_id: str = Field(max_length=100)
    sender: str = Field(alias="from", max_length=500)
    subject: str = ""
    triage: dict
    model_config = ConfigDict(populate_by_name=True)


class EditRequest(BaseModel):
    ticket_id: str
    subject: str = ""
    draft_reply: str = ""


class UrgentRequest(BaseModel):
    ticket_id: str
    sender: str = Field(alias="from")
    category: str
    summary: str
    oncall_slack_id: str = ""
    model_config = ConfigDict(populate_by_name=True)


class DigestRequest(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    tickets: list[dict]


def create_app(settings: Settings | None = None, client: LLMClient | None = None) -> FastAPI:
    settings = settings or load_settings()
    setup_logging(settings.log_level)
    client = client or build_client(settings)
    engine = TriageEngine(client, settings)
    app = FastAPI(title="Email triage service", version=__version__)

    def require_key(x_api_key: str | None = Header(default=None)):
        if settings.service_api_key and not hmac.compare_digest(x_api_key or "", settings.service_api_key):
            raise HTTPException(status_code=401, detail="invalid API key")

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__, "model": client.name, "mock": settings.is_mock}

    @app.post("/triage", response_model=TriageResponse, dependencies=[Depends(require_key)])
    def triage(email: EmailIn):
        try:
            return engine.triage(email)
        except LLMError as exc:
            log.error("model call failed: %s", exc)
            raise HTTPException(status_code=502, detail="model call failed") from None

    @app.post("/slack/approval-message", dependencies=[Depends(require_key)])
    def slack_approval(req: ApprovalRequest):
        return approval_message(req.ticket_id, req.sender, req.subject, req.triage)

    @app.post("/slack/edit-modal", dependencies=[Depends(require_key)])
    def slack_edit(req: EditRequest):
        return {"view": edit_modal(req.ticket_id, req.subject, req.draft_reply)}

    @app.post("/slack/urgent-alert", dependencies=[Depends(require_key)])
    def slack_urgent(req: UrgentRequest):
        return {
            "slack_text": urgent_alert_text(req.ticket_id, req.sender, req.summary, req.oncall_slack_id),
            "sms_text": sms_text(req.ticket_id, req.category, req.summary),
        }

    @app.post("/digest", dependencies=[Depends(require_key)])
    def digest(req: DigestRequest):
        return build_digest(req.tickets, req.date)

    return app


def default_app() -> FastAPI:
    return create_app()
