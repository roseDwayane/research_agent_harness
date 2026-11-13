"""The Claude provider (harness/providers/claude.py) against a fake Messages API: the SDK's own streaming client, no
network, no key."""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("anthropic")

from harness.config import MODULE_ROOT, HarnessConfig  # noqa: E402
from harness.context import RunContext  # noqa: E402
from harness.executors import RecipeExecutor  # noqa: E402
from harness.providers import ClaudeProvider, FileScope, WorkerRequest, WorkerResult  # noqa: E402
from harness.providers import claude  # noqa: E402
from harness.providers.chat import CHAT_RULES  # noqa: E402
from harness.recipes import parse  # noqa: E402
from harness.skill import CommandResult, Skill  # noqa: E402
from ideate_v2.registry import Registry  # noqa: E402


def message(text: str, stop: str = "end_turn", tin: int = 100, tout: int = 20, model: str = "claude-opus-5-5",
            details: dict | None = None, delay: float = 0.0):
    """A streamed answer, as the API sends it: an (empty, adaptive) thinking block, then the text."""
    start = {"id": "msg_1", "type": "message", "role": "assistant", "model": model, "content": [], "stop_reason": None,
             "stop_sequence": None, "usage": {"input_tokens": tin, "output_tokens": 1,
                                              "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}
    delta = {"stop_reason": stop, "stop_sequence": None, **({"stop_details": details} if details else {})}
    events = [
        ("message_start", {"type": "message_start", "message": start}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "thinking", "thinking": "", "signature": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "signature_delta", "signature": "sig"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 1}),
        ("message_delta", {"type": "message_delta", "delta": delta, "usage": {"output_tokens": tout}}),
        ("message_stop", {"type": "message_stop"})]
    return 200, events, delay


def files(*pairs: tuple[str, str], note: str = "done") -> str:
    return json.dumps({"files": [{"path": p, "content": c} for p, c in pairs], "note": note})


def error(status: int, kind: str, msg: str = "nope"):
    return status, {"type": "error", "error": {"type": kind, "message": msg}}, 0.0


class FakeAPI:
    """Records every request; answers with responder(body, n) -> (200, events, delay) or (status, error body, 0)."""

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
                    parts = [f"event: {e}\ndata: {json.dumps(d)}\n\n".encode() for e, d in out]
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

    def user(self, i: int = -1) -> str:
        return [m for m in self.requests[i]["messages"] if m["role"] == "user"][-1]["content"]


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    for v in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(v, raising=False)
    servers = []

    def make(responder):
        s = FakeAPI(responder)
        servers.append(s)
        return s
    yield make
    for s in servers:
        s.close()


def cfg_for(url: str, model: str | None = None, **opts) -> HarnessConfig:
    return HarnessConfig(worker="claude", model=model,
                         provider_options={"claude": {"base_url": url, "max_retries": 0, **opts}})


def run_one(s: FakeAPI, tmp_path: Path, scope: FileScope | None = None, **kw) -> WorkerResult:
    req = dict(task="Write x.md", system="the rules", cwd=tmp_path, scope=scope or FileScope(base=tmp_path))
    return ClaudeProvider(cfg_for(s.url, **kw.pop("cfg", {}))).run(WorkerRequest(**{**req, **kw}))


# ------------------------------------------------------------------------------------------------- the request
def test_request_shape_caching_structured_output_and_write(tmp_path, fake):
    s = fake(lambda body, n: message(files(("out/x.md", "# hello"))))
    cfg = cfg_for(s.url)
    assert cfg.model == "claude-opus-5-5"                                  # the provider's default model
    prov = ClaudeProvider(cfg)
    system = prov.system_prompt(MODULE_ROOT, {"id": "X", "name": "x"}, None, [], ["ideate_tools.py list-papers"])
    r = prov.run(WorkerRequest(task="Write x.md", system=system, cwd=tmp_path,
                               scope=FileScope(base=tmp_path, writes=[tmp_path / "out" / "x.md"])))
    assert r.ok, r.error
    assert (tmp_path / "out" / "x.md").read_text() == "# hello\n"
    assert r.tokens_in == 100 and r.tokens_out == 20 and r.cost_usd == pytest.approx((100 * 4 + 20 * 20) / 1e6)
    body, head = s.requests[0], s.headers[0]
    assert s.paths[0].startswith("/v1/messages") and body["stream"] is True
    assert body["model"] == "claude-opus-5-5" and body["max_tokens"] == 64000
    sys_block = body["system"][0]
    assert sys_block["text"].startswith(CHAT_RULES) and "# Unit X - x" in sys_block["text"]
    assert "Commands you may run" not in sys_block["text"]                  # it runs none: the conductor does
    assert sys_block["cache_control"] == {"type": "ephemeral"} and body["cache_control"] == {"type": "ephemeral"}
    assert [m["role"] for m in body["messages"]] == ["user"] and s.user(0).startswith("Write x.md")
    assert body["output_config"]["effort"] == "medium"
    fmt = body["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False
    assert fmt["schema"]["properties"]["files"]["items"]["additionalProperties"] is False
    assert "temperature" not in body and "thinking" not in body             # adaptive thinking is the model's own
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in head.get("anthropic-beta", "")
    assert head.get("x-api-key") == "sk-test" or "sk-test" in head.get("authorization", "")


def test_a_model_without_server_side_fallback_gets_the_plain_request(tmp_path, fake):
    s = fake(lambda body, n: message(files(), model="claude-haiku-5-5"))
    r = run_one(s, tmp_path, cfg={"model": "claude-haiku-5-5", "effort": "low"})
    assert r.ok, r.error
    assert "fallbacks" not in s.requests[0] and "server-side-fallback" not in s.headers[0].get("anthropic-beta", "")
    assert s.requests[0]["model"] == "claude-haiku-5-5" and s.requests[0]["output_config"]["effort"] == "low"
    assert r.cost_usd == pytest.approx((100 * 0.10 + 20 * 0.50) / 1e6)


def test_a_fixed_schema_is_a_structured_output_with_its_extra_constraints_described(tmp_path, fake):
    schema = {"type": "object", "additionalProperties": False, "required": ["terms"],
              "properties": {"terms": {"type": "array", "items": {"type": "string"}, "minItems": 2}}}
    s = fake(lambda body, n: message(json.dumps({"answer": {"terms": ["a", "b"]}, "note": "ok"})))
    target = tmp_path / "terms.json"
    r = run_one(s, tmp_path, scope=FileScope(base=tmp_path, writes=[target], schema=schema))
    assert r.ok, r.error
    assert json.loads(target.read_text()) == {"terms": ["a", "b"]}
    terms = s.requests[0]["output_config"]["format"]["schema"]["properties"]["answer"]["properties"]["terms"]
    assert "minItems" not in terms and "minItems: 2" in terms["description"]      # the SDK's transform_schema
    assert schema["properties"]["terms"]["minItems"] == 2                          # the step's own is untouched


def test_an_open_map_is_asked_for_in_the_prompt_and_read_out_of_the_text(tmp_path, fake):
    schema = {"type": "object", "properties": {"flat": {"type": "object"}}, "required": ["flat"]}
    s = fake(lambda body, n: message('Here it is:\n```json\n{"answer": {"flat": {"Q1": ["a", "b"]}}, "note": "x"}\n```'))
    target = tmp_path / "strategy_fill.json"
    r = run_one(s, tmp_path, scope=FileScope(base=tmp_path, writes=[target], schema=schema))
    assert r.ok, r.error
    assert json.loads(target.read_text()) == {"flat": {"Q1": ["a", "b"]}}
    assert "format" not in s.requests[0]["output_config"]                  # {} only, under additionalProperties false
    assert '{"answer": <the content of' in s.user(0)                        # the prompt says the shape


def test_a_revision_continues_the_conversation_with_the_same_cached_prefix(tmp_path, fake):
    s = fake(lambda body, n: message(files(("x.md", f"# version {n}"))))
    scope = FileScope(base=tmp_path, writes=[tmp_path / "x.md"])
    prov = ClaudeProvider(cfg_for(s.url))
    r = prov.run(WorkerRequest(task="Write x.md", system="the rules", cwd=tmp_path, scope=scope))
    again = prov.run(WorkerRequest(task="fix it", system="the rules", cwd=tmp_path, scope=scope, resume=r.session_id))
    assert again.ok and again.session_id == r.session_id
    first, second = s.requests
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "user"]
    assert second["messages"][0] == first["messages"][0] and second["system"] == first["system"]
    assert second["messages"][1]["content"] == files(("x.md", "# version 1"))      # its own answer, as text
    assert s.user(1).startswith("fix it") and (tmp_path / "x.md").read_text() == "# version 2\n"


# ------------------------------------------------------------------------------------------------- failures
@pytest.mark.parametrize("stop, category, words", [("max_tokens", "budget", "max_tokens"),
                                                   ("refusal", "model_output", "declined the request (refusal: bio)")])
def test_a_cut_or_declined_answer_is_not_used(tmp_path, fake, stop, category, words):
    details = {"type": "refusal", "category": "bio", "explanation": None} if stop == "refusal" else None
    s = fake(lambda body, n: message('{"files": [{"path": "x.md", "content": "par', stop=stop, details=details))
    target = tmp_path / "x.md"
    r = run_one(s, tmp_path, scope=FileScope(base=tmp_path, writes=[target]))
    assert not r.ok and r.error_category == category and words in r.error, r.error
    assert not target.exists() and len(s.requests) == 1


@pytest.mark.parametrize("status, kind, category", [
    (401, "authentication_error", "environment"), (403, "permission_error", "environment"),
    (404, "not_found_error", "environment"), (413, "request_too_large", "budget"),
    (429, "rate_limit_error", "external_service"), (500, "api_error", "external_service"),
    (529, "overloaded_error", "external_service")])
def test_http_failures_are_classified(tmp_path, fake, status, kind, category):
    s = fake(lambda body, n: error(status, kind))
    r = run_one(s, tmp_path)
    assert not r.ok and r.error_category == category and f"HTTP {status}" in r.error, r.error
    assert len(s.requests) == 1                                   # max_retries 0: the SDK sent it once


def test_a_request_refused_for_its_extras_is_sent_once_more_without_them(tmp_path, fake):
    def responder(body, n):
        if n == 1:
            return error(400, "invalid_request_error", "output_config.format.schema: too complex")
        return message(files(("x.md", "ok")))
    s = fake(responder)
    r = run_one(s, tmp_path, scope=FileScope(base=tmp_path, writes=[tmp_path / "x.md"]))
    assert r.ok, r.error
    first, second = s.requests
    assert "format" in first["output_config"] and "fallbacks" in first
    assert "format" not in second["output_config"] and "fallbacks" not in second
    s2 = fake(lambda body, n: error(400, "invalid_request_error", "max_tokens: too large"))
    r2 = run_one(s2, tmp_path)                                    # a 400 of its own: the step's failure
    assert not r2.ok and r2.error_category == "tool_invocation" and len(s2.requests) == 2


def test_a_stream_past_its_time_limit_is_closed_as_a_timeout(tmp_path, fake):
    s = fake(lambda body, n: message(files(("x.md", "late")), delay=0.4))
    t0 = time.time()
    r = run_one(s, tmp_path, scope=FileScope(base=tmp_path, writes=[tmp_path / "x.md"]), timeout=1)
    assert not r.ok and r.error_category == "timeout" and "within 1s" in r.error, r.error
    assert time.time() - t0 < 3 and not (tmp_path / "x.md").exists()


def test_a_step_that_needs_the_worker_to_run_commands_is_refused_before_any_request(tmp_path, fake):
    """B6 (`consume`): refused before any request, with what could run it named."""
    s = fake(lambda body, n: message(files()))
    r = run_one(s, tmp_path, scope=FileScope(base=tmp_path, unavailable=["ideate_tools.py consume"]))
    assert not r.ok and r.error_category == "environment" and not s.requests
    assert "ideate_tools.py consume" in r.error and "AgentProvider" in r.error


def test_without_the_sdk_the_worker_says_what_to_install(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)            # `import anthropic` raises ImportError
    r = ClaudeProvider(HarnessConfig()).run(WorkerRequest(task="t", system="s", cwd=tmp_path))
    assert not r.ok and r.error_category == "environment" and "pip install" in r.error


# ------------------------------------------------------------------------------------------------- settings
def test_the_config_names_the_model_and_refuses_a_bad_setting(monkeypatch, tmp_path):
    monkeypatch.delenv("IDEATE_LLM_MODEL", raising=False)
    cfg = HarnessConfig()
    assert cfg.worker == "claude" and cfg.model == "claude-opus-5-5"
    assert ClaudeProvider(cfg).label == "claude:claude-opus-5-5" and cfg.env()["IDEATE_LLM_MODEL"] == "claude-opus-5-5"
    with pytest.raises(ValueError, match="removed"):                         # claude -p is gone
        HarnessConfig(worker="claude-code")
    toml = tmp_path / "harness.toml"
    toml.write_text('[harness]\nclaude = "claude"\ndefault_budget_usd = 3.0\n')
    with pytest.raises(ValueError, match="went with the claude -p worker: claude, default_budget_usd"):
        HarnessConfig.load(toml)
    assert HarnessConfig(model="claude-sonnet-5-5").model == "claude-sonnet-5-5"
    assert ClaudeProvider.window(HarnessConfig(provider_options={"claude": {"context_window": 200000}})) == 200000
    for bad in ({"effort": "extreme"}, {"max_tokens": "lots"}, {"max_retries": -1}, {"price_per_mtok": [1]}):
        with pytest.raises(ValueError, match=next(iter(bad))):
            HarnessConfig(provider_options={"claude": bad})


def test_the_cost_is_the_list_price_of_what_was_read_written_and_cached():
    u = lambda fresh=0, wrote=0, read=0, out=0: SimpleNamespace(       # noqa: E731
        input_tokens=fresh, cache_creation_input_tokens=wrote, cache_read_input_tokens=read, output_tokens=out)
    m = 1_000_000
    assert claude.price("claude-opus-5-5", u(fresh=m, out=m)) == pytest.approx(4 + 20)
    assert claude.price("claude-opus-5-5", u(wrote=m, read=m)) == pytest.approx(4 * 1.25 + 4 * 0.05)
    assert claude.price("claude-sonnet-4-6", u(read=m)) == pytest.approx(3 * 0.1)          # 0.1x where not listed
    assert claude.price("claude-haiku-5-5", u(fresh=200_000)) == pytest.approx(0.2 * 0.50)  # a long prompt
    assert claude.price("a-model-of-its-own", u(fresh=m)) == 0
    assert claude.price("a-model-of-its-own", u(fresh=m), {"price_per_mtok": [1.5, 6]}) == pytest.approx(1.5)


# ------------------------------------------------------------------------------------------------- the executor
def test_the_executor_runs_a_write_step_on_the_api(tmp_path, fake, monkeypatch):
    """The same write step an Ollama worker gets: the conductor runs the lookups and writes the answer."""
    rd = tmp_path / "t_research"
    rd.mkdir()
    target = rd / "notes.json"
    s = fake(lambda body, n: message(files((str(target), '{"ok": true}')), tin=1000, tout=200))
    cfg = cfg_for(s.url)
    ctx = RunContext(Registry.load(), cfg, Skill(cfg), rd, tmp_path / "t.md", say=lambda m: None)
    ran = []
    monkeypatch.setattr(ctx.skill, "run", lambda cmd, subs, timeout=None: ran.append(cmd) or
                        CommandResult(cmd, [], 0, "paper_001 Label smoothing\n"))
    recipe = parse({"recipes": [{"unit": "B6", "scope": "generation", "phases": {"main": [
        {"write": {"task": "Write the notes", "writes": [str(target)], "rules": [],
                   "commands": ["ideate_tools.py list-papers"]}}]}}]})[0]
    res = RecipeExecutor().execute(ctx, "B6", recipe, "main", 1, 1)
    assert res.ok, res.errors
    assert json.loads(target.read_text()) == {"ok": True}
    assert ran == ["ideate_tools.py list-papers $RD --file shortlist --slice 0:80 --abstract-chars 160"] and "paper_001" in s.user(0)
    assert ctx.usage["calls"] == 1 and ctx.usage["cost_usd"] == pytest.approx((1000 * 4 + 200 * 20) / 1e6)
    logs = list((ctx.state_dir).rglob("*.claude.1.json"))
    assert logs and json.loads(logs[0].read_text())["model"] == "claude-opus-5-5"
