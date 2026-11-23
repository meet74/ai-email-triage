import os
from dataclasses import dataclass

DEFAULT_MODELS = {
    "anthropic": "claude-haiku-4-5",
    "openai": "gpt-4o-mini",
}


@dataclass(frozen=True)
class Settings:
    provider: str
    model: str
    base_url: str
    api_key: str
    timeout: float
    max_body_chars: int
    service_api_key: str
    log_level: str

    @property
    def is_mock(self) -> bool:
        return self.provider == "mock"


def load_settings(env: dict | None = None) -> Settings:
    e = os.environ if env is None else env
    provider = (e.get("LLM_PROVIDER") or "").strip().lower()
    if not provider:
        if e.get("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        elif e.get("OPENAI_API_KEY"):
            provider = "openai"
        else:
            provider = "mock"
    if provider not in ("anthropic", "openai", "mock"):
        raise ValueError(f"LLM_PROVIDER must be anthropic, openai or mock, got {provider!r}")

    key = ""
    if provider == "anthropic":
        key = e.get("ANTHROPIC_API_KEY", "")
    elif provider == "openai":
        key = e.get("OPENAI_API_KEY", "")
    if provider != "mock" and not key:
        raise ValueError(f"LLM_PROVIDER={provider} needs its API key in the environment")

    default_base = {
        "anthropic": "https://api.anthropic.com",
        "openai": "https://api.openai.com/v1",
        "mock": "",
    }[provider]
    return Settings(
        provider=provider,
        model=e.get("LLM_MODEL") or DEFAULT_MODELS.get(provider, "mock-heuristic-v1"),
        base_url=(e.get("LLM_BASE_URL") or default_base).rstrip("/"),
        api_key=key,
        timeout=float(e.get("LLM_TIMEOUT_SECONDS") or 30),
        max_body_chars=int(e.get("MAX_BODY_CHARS") or 6000),
        service_api_key=e.get("TRIAGE_API_KEY", ""),
        log_level=(e.get("LOG_LEVEL") or "INFO").upper(),
    )
