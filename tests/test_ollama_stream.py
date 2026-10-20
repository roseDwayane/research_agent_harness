"""Streaming transport must preserve complete JSON, usage and retry boundaries."""
import json

import httpx
import pytest

from scholar_research.config import LLMConfig
from scholar_research.llm.client import OllamaBackend


def backend(handler, retries=0):
    cfg = LLMConfig(provider="ollama", model="test", base_url="https://ollama.test", max_retries=retries)
    instance = OllamaBackend(cfg)
    instance._client.close()
    instance._client = httpx.Client(base_url=cfg.base_url, transport=httpx.MockTransport(handler))
    return instance


def call(instance):
    try:
        return instance(model="test", system="Return JSON", messages=[{"role": "user", "content": "hello"}],
                        tool={"name": "emit", "description": "result", "input_schema": {"type": "object"}},
                        temperature=0, max_tokens=100)
    finally:
        instance._client.close()


def response(*chunks):
    return httpx.Response(200, text="\n".join(json.dumps(c) for c in chunks) + "\n")


def test_stream_assembles_json_and_uses_final_usage():
    def handler(request):
        payload = json.loads(request.content)
        assert payload["stream"] is True
        assert payload["format"] == {"type": "object"}
        assert payload["think"] is False
        return response({"message": {"content": '{"rating":'}},
                        {"message": {"content": "4}"}},
                        {"done": True, "done_reason": "stop", "model": "test:latest",
                         "prompt_eval_count": 12, "eval_count": 5})
    result = call(backend(handler))
    assert result["input"] == {"rating": 4}
    assert result["usage"] == {"input_tokens": 12, "output_tokens": 5}
    assert result["model"] == "test:latest"


def test_retry_discards_previous_partial_content(monkeypatch):
    monkeypatch.setattr("scholar_research.llm.client.time.sleep", lambda _: None)
    count = 0
    def handler(_):
        nonlocal count
        count += 1
        if count == 1:
            return response({"message": {"content": '{"wrong":'}})
        return response({"message": {"content": '{"ok":true}'}, "done": True})
    assert call(backend(handler, retries=1))["input"] == {"ok": True}
    assert count == 2


def test_missing_done_is_not_accepted():
    with pytest.raises(RuntimeError, match="without a done record"):
        call(backend(lambda _: response({"message": {"content": '{"ok":true}'}})))


def test_stream_error_is_not_a_completion():
    with pytest.raises(RuntimeError, match="generation error: failed"):
        call(backend(lambda _: response({"error": "failed"})))


def test_truncated_json_retains_token_limit_hint():
    with pytest.raises(RuntimeError, match="raise.*max_tokens"):
        call(backend(lambda _: response({"message": {"content": '{"rating":'},
                                        "done": True, "done_reason": "length"})))
