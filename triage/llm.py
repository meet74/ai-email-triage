"""One small client for Anthropic and OpenAI-compatible chat APIs.

`complete()` takes a list of {role, content} messages (user/assistant only) plus
a system string and returns the reply text. The pipeline adds the repair turn by
appending to the list, so a client never has to know about retries.
"""

from typing import Protocol

import httpx

from .config import Settings


class LLMError(RuntimeError):
    """Transport or API failure (not a bad answer)."""


class LLMClient(Protocol):
    name: str

    def complete(self, system: str, messages: list[dict]) -> str: ...


class AnthropicClient:
    def __init__(self, s: Settings, http: httpx.Client | None = None):
        self.name = f"anthropic:{s.model}"
        self._s = s
        self._http = http or httpx.Client(timeout=s.timeout)

    def complete(self, system: str, messages: list[dict]) -> str:
        try:
            r = self._http.post(
                f"{self._s.base_url}/v1/messages",
                headers={
                    "x-api-key": self._s.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={"model": self._s.model, "max_tokens": 1200, "temperature": 0,
                      "system": system, "messages": messages},
            )
            r.raise_for_status()
            blocks = r.json()["content"]
            return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LLMError(f"anthropic request failed: {type(exc).__name__}") from None


class OpenAIClient:
    def __init__(self, s: Settings, http: httpx.Client | None = None):
        self.name = f"openai:{s.model}"
        self._s = s
        self._http = http or httpx.Client(timeout=s.timeout)

    def complete(self, system: str, messages: list[dict]) -> str:
        try:
            r = self._http.post(
                f"{self._s.base_url}/chat/completions",
                headers={"authorization": f"Bearer {self._s.api_key}"},
                json={
                    "model": self._s.model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "system", "content": system}, *messages],
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"] or ""
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"openai-compatible request failed: {type(exc).__name__}") from None


def build_client(s: Settings) -> LLMClient:
    if s.provider == "anthropic":
        return AnthropicClient(s)
    if s.provider == "openai":
        return OpenAIClient(s)
    from .mock_llm import MockLLM

    return MockLLM()
