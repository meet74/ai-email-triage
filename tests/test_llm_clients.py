import json

import httpx
import pytest

from triage.config import Settings, load_settings
from triage.llm import AnthropicClient, LLMError, OpenAIClient


def settings(provider, base="https://llm.test"):
    return Settings(provider, "m-1", base, "key-1", 5, 6000, "", "WARNING")


def test_anthropic_request_and_response():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["headers"], seen["json"] = str(req.url), req.headers, json.loads(req.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "{\"a\": 1}"}]})

    c = AnthropicClient(settings("anthropic"), httpx.Client(transport=httpx.MockTransport(handler)))
    assert c.complete("sys", [{"role": "user", "content": "hi"}]) == '{"a": 1}'
    assert seen["url"] == "https://llm.test/v1/messages"
    assert seen["headers"]["x-api-key"] == "key-1"
    assert seen["json"]["system"] == "sys" and seen["json"]["temperature"] == 0


def test_openai_compatible_request_and_response():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["json"] = str(req.url), json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    c = OpenAIClient(settings("openai", "http://localhost:9/v1"), httpx.Client(transport=httpx.MockTransport(handler)))
    assert c.complete("sys", [{"role": "user", "content": "hi"}]) == "ok"
    assert seen["url"] == "http://localhost:9/v1/chat/completions"
    assert seen["json"]["messages"][0] == {"role": "system", "content": "sys"}


def test_http_errors_become_llm_error():
    c = AnthropicClient(settings("anthropic"), httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    with pytest.raises(LLMError):
        c.complete("s", [{"role": "user", "content": "x"}])


def test_provider_selection_from_env():
    assert load_settings({}).provider == "mock"
    assert load_settings({"ANTHROPIC_API_KEY": "k"}).provider == "anthropic"
    assert load_settings({"OPENAI_API_KEY": "k"}).provider == "openai"
    assert load_settings({"LLM_PROVIDER": "mock", "ANTHROPIC_API_KEY": "k"}).provider == "mock"
    with pytest.raises(ValueError):
        load_settings({"LLM_PROVIDER": "anthropic"})
