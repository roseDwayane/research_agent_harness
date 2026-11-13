"""The GPT and Gemini providers (harness/providers/gpt.py, gemini.py) against fake APIs: each SDK's own streaming
client, no network, no key."""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.config import MODULE_ROOT, HarnessConfig
from harness.context import RunContext
from harness.executors import RecipeExecutor
from harness.providers import FileScope, GeminiProvider, GPTProvider, WorkerRequest, WorkerResult, gemini, gpt
from harness.providers.chat import CHAT_RULES, RESPONSE_SCHEMA, rate_of
from harness.recipes import parse
from harness.skill import CommandResult, Skill
from ideate_v2.registry import Registry

needs_openai = pytest.mark.skipif(importlib.util.find_spec("openai") is None, reason="openai is not installed")
needs_genai = pytest.mark.skipif(importlib.util.find_spec("google.genai") is None, reason="google-genai is not installed")
PROVIDER = {"gpt": GPTProvider, "gemini": GeminiProvider}


class FakeSSE:
    """Records every request; answers with responder(body, n) -> (200, [(event or None, data)], delay) or
    (status, error body, 0)."""

    def __init__(self, responder):
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        self.paths: list[str] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):                              # noqa: N802 - http.server's name
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                outer.headers.append({k.lower(): v for k, v in self.headers.items()})
                outer.paths.append(self.path)
                status, out, delay = responder(body, len(outer.requests))
                if status == 200:
                    parts = [((f"event: {e}\n" if e else "") + f"data: {json.dumps(d)}\n\n").encode() for e, d in out]
                    ctype = "text/event-stream"
                else:
                    parts, ctype = [json.dumps(out).encode()], "application/json"
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(sum(len(p) for p in parts)))
                self.end_headers()
                try:
                    for p in parts:
                        self.wfile.write(p)
                        self.wfile.flush()
                        time.sleep(delay)
                except (BrokenPipeError, ConnectionResetError):  # the client closed a stream past its deadline
                    pass

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    for v in ("OPENAI_BASE_URL", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI",
              "GOOGLE_GENAI_USE_ENTERPRISE", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"):
        monkeypatch.delenv(v, raising=False)
    servers = []

    def make(responder):
        s = FakeSSE(responder)
        servers.append(s)
        return s
    yield make
    for s in servers:
        s.close()


def files(*pairs: tuple[str, str], note: str = "done") -> str:
    return json.dumps({"files": [{"path": p, "content": c} for p, c in pairs], "note": note})


def cfg_for(worker: str, s: FakeSSE, model: str | None = None, **opts) -> HarnessConfig:
    base = s.url + "/v1" if worker == "gpt" else s.url
    return HarnessConfig(worker=worker, model=model,
                         provider_options={worker: {"base_url": base, "max_retries": 0, **opts}})


def run_one(worker: str, s: FakeSSE, tmp_path: Path, scope: FileScope | None = None, cfg: dict | None = None,
            **kw) -> WorkerResult:
    req = dict(task="Write x.md", system="the rules", cwd=tmp_path, scope=scope or FileScope(base=tmp_path))
    return PROVIDER[worker](cfg_for(worker, s, **(cfg or {}))).run(WorkerRequest(**{**req, **kw}))


# ------------------------------------------------------------------------------------------------- fake answers
def gpt_answer(text: str, status: str = "completed", reason: str | None = None, tin: int = 100, tout: int = 20,
               cached: int = 0, wrote: int = 0, model: str = "gpt-6-astra", refusal: str | None = None,
               error: dict | None = None):
    content = [{"type": "refusal", "refusal": refusal}] if refusal else \
        [{"type": "output_text", "text": text, "annotations": []}]
    resp = {"id": "resp_1", "object": "response", "created_at": 1, "model": model, "status": status,
            "output": [{"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                        "content": content}],
            "usage": {"input_tokens": tin, "output_tokens": tout, "total_tokens": tin + tout,
                      "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": wrote,
                                               "cache_write_tokens_details": {"ttl_30m_tokens": wrote,
                                                                              "ttl_12h_tokens": 0}},
                      "output_tokens_details": {"reasoning_tokens": 0}},
            "incomplete_details": {"reason": reason} if reason else None, "error": error,
            "parallel_tool_calls": True, "tool_choice": "auto", "tools": []}
    final = {"completed": "response.completed", "incomplete": "response.incomplete", "failed": "response.failed"}[status]
    events = [("response.created", {"type": "response.created", "sequence_number": 0,
                                    "response": {**resp, "status": "in_progress", "output": [], "usage": None}}),
              ("response.output_text.delta", {"type": "response.output_text.delta", "sequence_number": 1,
                                              "item_id": "msg_1", "output_index": 0, "content_index": 0,
                                              "delta": text, "logprobs": []}),
              (final, {"type": final, "sequence_number": 2, "response": resp})]
    return 200, events, 0.0


def gemini_answer(text: str, finish: str | None = "STOP", tin: int = 100, tout: int = 20, thoughts: int = 5,
                  cached: int = 0, model: str = "gemini-4-argon", blocked: str | None = None, delay: float = 0.0):
    usage = {"promptTokenCount": tin, "candidatesTokenCount": tout, "thoughtsTokenCount": thoughts,
             "cachedContentTokenCount": cached, "totalTokenCount": tin + tout + thoughts}
    if blocked:
        return 200, [(None, {"promptFeedback": {"blockReason": blocked}, "usageMetadata": usage})], delay
    half = len(text) // 2
    first = {"candidates": [{"index": 0, "content": {"role": "model", "parts": [
        {"text": "weighing the rules first", "thought": True}, {"text": text[:half]}]}}], "modelVersion": model}
    last = {"candidates": [{"index": 0, "content": {"role": "model", "parts": [{"text": text[half:]}]},
                            **({"finishReason": finish} if finish else {})}], "usageMetadata": usage,
            "modelVersion": model}
    return 200, [(None, first), (None, last)], delay


# ------------------------------------------------------------------------------------------------- GPT
@needs_openai
def test_gpt_request_shape_structured_output_cost_and_write(tmp_path, fake):
    s = fake(lambda body, n: gpt_answer(files(("out/x.md", "# hello")), tin=1000, cached=200, wrote=300, tout=50))
    cfg = cfg_for("gpt", s)
    assert cfg.model == "gpt-6-astra"                                       # the provider's default model
    prov = GPTProvider(cfg)
    system = prov.system_prompt(MODULE_ROOT, {"id": "X", "name": "x"}, None, [], ["ideate_tools.py list-papers"])
    r = prov.run(WorkerRequest(task="Write x.md", system=system, cwd=tmp_path,
                               scope=FileScope(base=tmp_path, writes=[tmp_path / "out" / "x.md"])))
    assert r.ok, r.error
    assert (tmp_path / "out" / "x.md").read_text() == "# hello\n"
    assert r.tokens_in == 1000 and r.tokens_out == 50
    assert r.cost_usd == pytest.approx((500 * 10 + 200 * 1.00 + 300 * 12.50 + 50 * 50) / 1e6)   # reads, writes
    body, head = s.requests[0], s.headers[0]
    assert s.paths[0] == "/v1/responses" and body["stream"] is True and body["store"] is False
    assert body["model"] == "gpt-6-astra" and body["max_output_tokens"] == 64000
    assert body["instructions"].startswith(CHAT_RULES) and "Commands you may run" not in body["instructions"]
    assert [m["role"] for m in body["input"]] == ["user"] and body["input"][0]["content"].startswith("Write x.md")
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["name"] == "answer"
    assert fmt["schema"]["additionalProperties"] is False
    assert fmt["schema"]["properties"]["files"]["items"]["additionalProperties"] is False
    assert "reasoning" not in body and "temperature" not in body             # the model's own reasoning effort
    assert head.get("authorization") == "Bearer sk-test"


@needs_openai
def test_gpt_effort_and_a_schema_strict_mode_cannot_take(tmp_path, fake):
    schema = {"type": "object", "properties": {"terms": {"type": "array", "items": {"type": "string"}},
                                               "why": {"type": "string"}}, "required": ["terms"]}   # `why` optional
    s = fake(lambda body, n: gpt_answer('```json\n{"answer": {"terms": ["a"]}, "note": "ok"}\n```'))
    target = tmp_path / "terms.json"
    r = run_one("gpt", s, tmp_path, scope=FileScope(base=tmp_path, writes=[target], schema=schema),
                cfg={"effort": "high"})
    assert r.ok, r.error
    assert json.loads(target.read_text()) == {"terms": ["a"]}
    body = s.requests[0]
    assert body["reasoning"] == {"effort": "high"} and body["text"]["format"] == {"type": "json_object"}


@needs_openai
@pytest.mark.parametrize("kw, category, words", [
    (dict(status="incomplete", reason="max_output_tokens"), "budget", "max_output_tokens"),
    (dict(refusal="I can't help with that."), "model_output", "declined the request (refusal"),
    (dict(status="failed", error={"code": "server_error", "message": "boom"}), "external_service", "server_error"),
    (dict(status="failed", error={"code": "bio_policy", "message": "no"}), "model_output", "bio_policy")])
def test_gpt_a_cut_declined_or_failed_answer_is_not_used(tmp_path, fake, kw, category, words):
    s = fake(lambda body, n: gpt_answer('{"files": [{"path": "x.md", "content": "par', **kw))
    target = tmp_path / "x.md"
    r = run_one("gpt", s, tmp_path, scope=FileScope(base=tmp_path, writes=[target]))
    assert not r.ok and r.error_category == category and words in r.error, r.error
    assert not target.exists() and len(s.requests) == 1


@needs_openai
@pytest.mark.parametrize("status, code, category, sent", [
    (401, "invalid_api_key", "environment", 1), (404, "model_not_found", "environment", 1),
    (429, "rate_limit_exceeded", "external_service", 1), (429, "insufficient_quota", "budget", 1),
    (400, "context_length_exceeded", "budget", 1), (400, "invalid_value", "tool_invocation", 2),
    (500, "server_error", "external_service", 1)])
def test_gpt_http_failures_are_classified(tmp_path, fake, status, code, category, sent):
    s = fake(lambda body, n: (status, {"error": {"message": "nope", "type": "x", "param": None, "code": code}}, 0.0))
    r = run_one("gpt", s, tmp_path)
    assert not r.ok and r.error_category == category and f"HTTP {status}" in r.error, r.error
    assert len(s.requests) == sent                     # a 400 of another kind: once more without text.format


@needs_openai
def test_gpt_a_request_refused_for_its_format_is_sent_once_more_without_it(tmp_path, fake):
    def responder(body, n):
        if n == 1:
            return 400, {"error": {"message": "Invalid schema", "type": "invalid_request_error", "param": "text",
                                   "code": "invalid_json_schema"}}, 0.0
        return gpt_answer(files(("x.md", "ok")))
    s = fake(responder)
    r = run_one("gpt", s, tmp_path, scope=FileScope(base=tmp_path, writes=[tmp_path / "x.md"]))
    assert r.ok, r.error
    assert "text" in s.requests[0] and "text" not in s.requests[1]


@needs_openai
def test_gpt_a_revision_continues_the_conversation(tmp_path, fake):
    s = fake(lambda body, n: gpt_answer(files(("x.md", f"# version {n}"))))
    scope = FileScope(base=tmp_path, writes=[tmp_path / "x.md"])
    prov = GPTProvider(cfg_for("gpt", s))
    r = prov.run(WorkerRequest(task="Write x.md", system="the rules", cwd=tmp_path, scope=scope))
    prov.run(WorkerRequest(task="fix it", system="the rules", cwd=tmp_path, scope=scope, resume=r.session_id))
    second = s.requests[1]
    assert [m["role"] for m in second["input"]] == ["user", "assistant", "user"]
    assert second["input"][1]["content"] == files(("x.md", "# version 1")) and second["instructions"] == "the rules"
    assert (tmp_path / "x.md").read_text() == "# version 2\n"


@needs_openai
def test_gpt_without_a_key_or_the_sdk_the_worker_says_so(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = GPTProvider(HarnessConfig(worker="gpt")).run(WorkerRequest(task="t", system="s", cwd=tmp_path))
    assert not r.ok and r.error_category == "environment" and "OPENAI_API_KEY" in r.error, r.error
    monkeypatch.setitem(sys.modules, "openai", None)
    r = GPTProvider(HarnessConfig(worker="gpt")).run(WorkerRequest(task="t", system="s", cwd=tmp_path))
    assert not r.ok and r.error_category == "environment" and "pip install" in r.error


def test_gpt_prices_long_context_and_dated_snapshots():
    u = lambda total=0, read=0, wrote=0, out=0: SimpleNamespace(       # noqa: E731
        input_tokens=total, output_tokens=out,
        input_tokens_details=SimpleNamespace(cached_tokens=read, cache_write_tokens=wrote))
    m = 1_000_000
    assert gpt.price("gpt-6.1-sol", u(total=100_000, out=m)) == pytest.approx(0.1 * 2 + 10)
    assert gpt.price("gpt-6.1-sol", u(total=300_000)) == pytest.approx(0.3 * 4)            # over 272k tokens
    assert gpt.price("gpt-6-luna-2026-09-01", u(total=m, read=m)) == pytest.approx(0.02)   # a snapshot, long, cached
    assert gpt.price("gpt-unknown", u(total=m)) == 0


# ------------------------------------------------------------------------------------------------- Gemini
@needs_genai
def test_gemini_request_shape_schema_cost_and_write(tmp_path, fake):
    s = fake(lambda body, n: gemini_answer(files(("out/x.md", "# hello")), tin=1000, cached=400, tout=50,
                                           thoughts=30))
    cfg = cfg_for("gemini", s)
    assert cfg.model == "gemini-4-argon"                                    # the provider's default model
    prov = GeminiProvider(cfg)
    system = prov.system_prompt(MODULE_ROOT, {"id": "X", "name": "x"}, None, [], ["ideate_tools.py list-papers"])
    r = prov.run(WorkerRequest(task="Write x.md", system=system, cwd=tmp_path,
                               scope=FileScope(base=tmp_path, writes=[tmp_path / "out" / "x.md"])))
    assert r.ok, r.error
    assert (tmp_path / "out" / "x.md").read_text() == "# hello\n"           # the thought part is not the answer
    assert r.tokens_in == 1000 and r.tokens_out == 80                        # thinking counts as output
    assert r.cost_usd == pytest.approx(rate_of(gemini.PRICES, "gemini-4-argon", 1000).cost(600, 400, 0, 80))
    body, head = s.requests[0], s.headers[0]
    assert s.paths[0] == "/v1/models/gemini-4-argon:streamGenerateContent?alt=sse"     # the SDK's API version
    assert head.get("x-goog-api-key") == "g-test"
    assert body["systemInstruction"]["parts"][0]["text"].startswith(CHAT_RULES)
    assert [c["role"] for c in body["contents"]] == ["user"]
    assert body["contents"][0]["parts"][0]["text"].startswith("Write x.md")
    gen = body["generationConfig"]
    assert gen["maxOutputTokens"] == 65536 and gen["responseMimeType"] == "application/json"
    assert gen["responseJsonSchema"] == RESPONSE_SCHEMA                      # as it is: Gemini closes nothing
    assert "thinkingConfig" not in gen and "temperature" not in gen


@needs_genai
def test_gemini_effort_and_an_open_map_decoded_under_its_schema(tmp_path, fake):
    schema = {"type": "object", "properties": {"flat": {"type": "object",
                                                        "additionalProperties": {"type": "array"}}}}
    s = fake(lambda body, n: gemini_answer(json.dumps({"answer": {"flat": {"Q1": ["a", "b"]}}, "note": "x"})))
    target = tmp_path / "strategy_fill.json"
    r = run_one("gemini", s, tmp_path, scope=FileScope(base=tmp_path, writes=[target], schema=schema),
                cfg={"effort": "high"})
    assert r.ok, r.error
    assert json.loads(target.read_text()) == {"flat": {"Q1": ["a", "b"]}}
    gen = s.requests[0]["generationConfig"]
    thinking = gen["thinkingConfig"]                     # the SDK sends its inner field under the proto name, which
    assert (thinking.get("thinkingLevel") or thinking.get("thinking_level")) == "HIGH"   # the API reads like camelCase
    assert gen["responseJsonSchema"]["properties"]["answer"] == schema       # the map, under the schema


@needs_genai
@pytest.mark.parametrize("kw, category, words", [
    (dict(finish="MAX_TOKENS"), "budget", "max_output_tokens"),
    (dict(finish="SAFETY"), "model_output", "stopped the answer (SAFETY)"),
    (dict(blocked="PROHIBITED_CONTENT"), "model_output", "blocked the prompt (PROHIBITED_CONTENT)"),
    (dict(finish=None), "external_service", "ended before the answer was finished")])
def test_gemini_a_cut_blocked_or_stopped_answer_is_not_used(tmp_path, fake, kw, category, words):
    s = fake(lambda body, n: gemini_answer('{"files": [{"path": "x.md", "content": "par', **kw))
    target = tmp_path / "x.md"
    r = run_one("gemini", s, tmp_path, scope=FileScope(base=tmp_path, writes=[target]))
    assert not r.ok and r.error_category == category and words in r.error, r.error
    assert not target.exists() and len(s.requests) == 1


@needs_genai
@pytest.mark.parametrize("status, kind, reason, category, sent", [
    (400, "INVALID_ARGUMENT", "API_KEY_INVALID", "environment", 1), (403, "PERMISSION_DENIED", None, "environment", 1),
    (404, "NOT_FOUND", None, "environment", 1), (429, "RESOURCE_EXHAUSTED", None, "external_service", 1),
    (500, "INTERNAL", None, "external_service", 1), (503, "UNAVAILABLE", None, "external_service", 1),
    (504, "DEADLINE_EXCEEDED", None, "timeout", 1), (400, "INVALID_ARGUMENT", None, "tool_invocation", 2)])
def test_gemini_http_failures_are_classified(tmp_path, fake, status, kind, reason, category, sent):
    details = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}] if reason else []
    s = fake(lambda body, n: (status, {"error": {"code": status, "message": "nope", "status": kind,
                                                 "details": details}}, 0.0))
    r = run_one("gemini", s, tmp_path)
    assert not r.ok and r.error_category == category and f"HTTP {status}" in r.error, r.error
    assert len(s.requests) == sent                     # a 400 of another kind: once more without the schema


@needs_genai
def test_gemini_a_request_refused_for_its_schema_is_sent_once_more_without_it(tmp_path, fake):
    def responder(body, n):
        if n == 1:
            return 400, {"error": {"code": 400, "message": "schema too complex", "status": "INVALID_ARGUMENT"}}, 0.0
        return gemini_answer(files(("x.md", "ok")))
    s = fake(responder)
    r = run_one("gemini", s, tmp_path, scope=FileScope(base=tmp_path, writes=[tmp_path / "x.md"]))
    assert r.ok, r.error
    first, second = (q["generationConfig"] for q in s.requests)
    assert "responseJsonSchema" in first and "responseJsonSchema" not in second
    assert second["responseMimeType"] == "application/json"               # still JSON, decoded under no schema


@needs_genai
def test_gemini_a_revision_continues_the_conversation_as_user_and_model_turns(tmp_path, fake):
    s = fake(lambda body, n: gemini_answer(files(("x.md", f"# version {n}"))))
    scope = FileScope(base=tmp_path, writes=[tmp_path / "x.md"])
    prov = GeminiProvider(cfg_for("gemini", s))
    r = prov.run(WorkerRequest(task="Write x.md", system="the rules", cwd=tmp_path, scope=scope))
    prov.run(WorkerRequest(task="fix it", system="the rules", cwd=tmp_path, scope=scope, resume=r.session_id))
    contents = s.requests[1]["contents"]
    assert [c["role"] for c in contents] == ["user", "model", "user"]
    assert contents[1]["parts"][0]["text"] == files(("x.md", "# version 1"))
    assert (tmp_path / "x.md").read_text() == "# version 2\n"


@needs_genai
def test_gemini_a_stream_past_its_time_limit_is_closed_as_a_timeout(tmp_path, fake):
    s = fake(lambda body, n: gemini_answer(files(("x.md", "late")), delay=1.5))
    t0 = time.time()
    r = run_one("gemini", s, tmp_path, scope=FileScope(base=tmp_path, writes=[tmp_path / "x.md"]), timeout=1)
    assert not r.ok and r.error_category == "timeout", r.error         # the deadline, or the read timeout first
    assert time.time() - t0 < 3 and not (tmp_path / "x.md").exists()


@needs_genai
def test_gemini_without_a_key_or_the_sdk_the_worker_says_so(tmp_path, monkeypatch):
    for v in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_ENTERPRISE"):
        monkeypatch.delenv(v, raising=False)
    r = GeminiProvider(HarnessConfig(worker="gemini")).run(WorkerRequest(task="t", system="s", cwd=tmp_path))
    assert not r.ok and r.error_category == "environment" and "GEMINI_API_KEY" in r.error, r.error
    monkeypatch.setitem(sys.modules, "google.genai", None)
    r = GeminiProvider(HarnessConfig(worker="gemini")).run(WorkerRequest(task="t", system="s", cwd=tmp_path))
    assert not r.ok and r.error_category == "environment" and "pip install" in r.error


def test_gemini_prices_follow_the_announced_dates_and_the_long_prompt_tier():
    u = lambda prompt=0, read=0, out=0, thoughts=0: SimpleNamespace(     # noqa: E731
        prompt_token_count=prompt, cached_content_token_count=read, candidates_token_count=out,
        thoughts_token_count=thoughts)
    m = 1_000_000
    assert gemini.price("gemini-4-argon", u(prompt=m, out=m), day="2026-11-30") == pytest.approx(2 + 10)
    assert gemini.price("gemini-4-argon", u(prompt=m, out=m), day="2026-12-01") == pytest.approx(4 + 20)
    assert gemini.price("gemini-3.6-flash", u(out=m // 2, thoughts=m // 2), day="2027-01-02") == pytest.approx(7.5)
    assert gemini.price("gemini-3.1-pro-preview", u(prompt=300_000, read=100_000)) == \
        pytest.approx(0.2 * 4 + 0.1 * 0.40)                                 # over 200k: the long tier
    assert gemini.price("gemini-unknown", u(prompt=m)) == 0


# ------------------------------------------------------------------------------------------------- both
def test_the_config_names_each_model_and_refuses_a_bad_setting():
    assert HarnessConfig(worker="gpt").model == "gpt-6-astra" and HarnessConfig(worker="gemini").model == "gemini-4-argon"
    assert GPTProvider(HarnessConfig(worker="gpt", model="gpt-6.1-sol")).label == "gpt:gpt-6.1-sol"
    assert GeminiProvider.window(HarnessConfig(worker="gemini")) == 1_048_576
    assert (HarnessConfig(worker="gpt").parallel(), HarnessConfig(worker="gemini").batch_budget()) == (4, 40000)
    for worker, bad in (("gpt", {"effort": "extreme"}), ("gpt", {"store": "yes"}), ("gemini", {"effort": "xhigh"}),
                        ("gemini", {"max_tokens": 0})):
        with pytest.raises(ValueError, match=next(iter(bad))):
            HarnessConfig(worker=worker, provider_options={worker: bad})


@pytest.mark.parametrize("worker", [pytest.param("gpt", marks=needs_openai), pytest.param("gemini", marks=needs_genai)])
def test_the_executor_runs_a_write_step_on_each_api(tmp_path, fake, monkeypatch, worker):
    """The write step a Claude or Ollama worker gets: the conductor runs the lookups and writes the answer."""
    rd = tmp_path / "t_research"
    rd.mkdir()
    target = rd / "notes.json"
    answer = files((str(target), '{"ok": true}'))
    s = fake(lambda body, n: gpt_answer(answer) if worker == "gpt" else gemini_answer(answer))
    cfg = cfg_for(worker, s)
    ctx = RunContext(Registry.load(), cfg, Skill(cfg), rd, tmp_path / "t.md", say=lambda m: None)
    monkeypatch.setattr(ctx.skill, "run", lambda cmd, subs, timeout=None: CommandResult(cmd, [], 0, "paper_001 x\n"))
    recipe = parse({"recipes": [{"unit": "B6", "scope": "generation", "phases": {"main": [
        {"write": {"task": "Write the notes", "writes": [str(target)], "rules": [],
                   "commands": ["ideate_tools.py list-papers"]}}]}}]})[0]
    res = RecipeExecutor().execute(ctx, "B6", recipe, "main", 1, 1)
    assert res.ok, res.errors
    assert json.loads(target.read_text()) == {"ok": True}
    sent = json.dumps(s.requests[0])
    assert "paper_001" in sent and ctx.usage["calls"] == 1 and ctx.usage["cost_usd"] > 0
