"""The API provider worker (harness/api_worker.py) against a fake /chat/completions server: no network, no key."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from harness import ollama_worker as ow
from harness import api_worker as aw
from harness.config import API_PROVIDERS, HarnessConfig
from harness.context import RunContext
from harness.executors import RecipeExecutor
from harness.recipes import parse
from harness.skill import Skill
from ideate_v2.registry import Registry

IDEA = {"Name": "fake_idea", "Title": "A title", "Short Hypothesis": "H", "Related Work": "RW",
        "Abstract": " ".join(["word"] * 200), "Experiments": ["E1 [tests C1] x"], "Risk Factors and Limitations": ["r"]}


def completion(files: list[tuple[str, str]], note: str = "done", finish: str = "stop", tin: int = 100,
               tout: int = 20) -> tuple[int, dict]:
    content = json.dumps({"files": [{"path": p, "content": c} for p, c in files], "note": note})
    return 200, {"id": "c1", "object": "chat.completion", "model": "m",
                 "choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": content}}],
                 "usage": {"prompt_tokens": tin, "completion_tokens": tout, "total_tokens": tin + tout}}


class FakeAPI:
    """Records every request; answers with responder(request_body, n) -> (status, body)."""

    def __init__(self, responder):
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        self.paths: list[str] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):                              # noqa: N802 - http.server's name
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                outer.headers.append(dict(self.headers))
                outer.paths.append(self.path)
                status, out = responder(body, len(outer.requests))
                data = json.dumps(out).encode() if isinstance(out, dict) else str(out).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()

    def user(self, i: int = -1) -> str:
        return [m for m in self.requests[i]["messages"] if m["role"] == "user"][-1]["content"]


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "sk-test-123")
    aw._SPENT["usd"] = 0.0
    servers = []

    def make(responder):
        s = FakeAPI(responder)
        servers.append(s)
        return s
    yield make
    for s in servers:
        s.close()


def cfg_for(url: str, **kw) -> HarnessConfig:
    return HarnessConfig(worker="openai", model="m", api_base=url, api_key_env="TEST_API_KEY",
                         max_context=kw.pop("max_context", 8192), **kw)


# ------------------------------------------------------------------------------------------------- the worker
def test_request_shape_key_and_write(tmp_path, fake):
    s = fake(lambda body, n: completion([("out/x.md", "# hello")]))
    scope = ow.FileScope(base=tmp_path, writes=[tmp_path / "out" / "x.md"])
    cfg = cfg_for(s.url, num_predict=4096)
    r = aw.run_worker(cfg, task="Write x.md", system=ow.cw.SHELL_RULES + "\n# Unit X\n", cwd=tmp_path, scope=scope)
    assert r.ok and r.session_id and r.tokens_in == 100 and r.tokens_out == 20
    assert (tmp_path / "out" / "x.md").read_text() == "# hello\n"
    body = s.requests[0]
    assert s.paths[0] == "/v1/chat/completions" and body["model"] == "m" and body["max_completion_tokens"] == 4096
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == ow.RESPONSE_SCHEMA
    assert body["messages"][0]["role"] == "system" and "cannot open files or run commands" in body["messages"][0]["content"]
    assert s.headers[0].get("Authorization") == "Bearer sk-test-123"
    assert s.headers[0].get("User-Agent", "").startswith("ideate-harness/")


def test_a_bad_answer_is_corrected_once_in_the_same_conversation(tmp_path, fake):
    def responder(body, n):
        return completion([("y.json", "{bad")]) if n == 1 else completion([("y.json", '{"fine": true}')])
    s = fake(responder)
    scope = ow.FileScope(base=tmp_path, writes=[tmp_path / "y.json"])
    r = aw.run_worker(cfg_for(s.url), task="t", system="s", cwd=tmp_path, scope=scope)
    assert r.ok and len(s.requests) == 2 and "not valid JSON" in s.user(1)
    assert [m["role"] for m in s.requests[1]["messages"]] == ["system", "user", "assistant", "user"]
    assert json.loads((tmp_path / "y.json").read_text()) == {"fine": True}


def test_an_api_turn_logs_the_whole_request_too(tmp_path, fake):
    s = fake(lambda body, n: completion([("x.md", "ok")]))
    log = tmp_path / "log"
    r = aw.run_worker(cfg_for(s.url), task="T" * 11000, system="S", cwd=tmp_path, log_dir=log, label="w",
                      scope=ow.FileScope(base=tmp_path, writes=[tmp_path / "x.md"]))
    rec = json.loads((log / "w.api.1.messages.json").read_text())
    assert r.ok and rec["messages"] == s.requests[0]["messages"] and "sk-test-123" not in json.dumps(rec)


def test_no_key_is_an_environment_error_and_nothing_is_sent(tmp_path, fake, monkeypatch):
    s = fake(lambda body, n: completion([]))
    monkeypatch.delenv("TEST_API_KEY")
    r = aw.run_worker(cfg_for(s.url), task="t", system="s", cwd=tmp_path, scope=ow.FileScope(base=tmp_path))
    assert not r.ok and r.error_category == "environment" and "TEST_API_KEY" in r.error and not s.requests


@pytest.mark.parametrize("status,category", [(401, "environment"), (404, "environment"), (429, "external_service"),
                                             (503, "external_service"), (422, "tool_invocation")])
def test_http_failures_are_classified(tmp_path, fake, status, category):
    s = fake(lambda body, n: (status, {"error": {"message": "nope"}}))
    r = aw.run_worker(cfg_for(s.url), task="t", system="s", cwd=tmp_path, scope=ow.FileScope(base=tmp_path))
    assert not r.ok and r.error_category == category
    assert "sk-test-123" not in r.error                          # the key never reaches an error message


def test_a_refused_schema_falls_back_to_json_mode_with_the_schema_in_the_prompt(tmp_path, fake):
    def responder(body, n):
        if body["response_format"]["type"] == "json_schema":
            return 400, {"error": {"message": "Invalid JSON payload: unknown field in response_format.json_schema"}}
        return completion([("x.md", "ok")])
    s = fake(responder)
    scope = ow.FileScope(base=tmp_path, writes=[tmp_path / "x.md"])
    r = aw.run_worker(cfg_for(s.url), task="Write x.md", system="s", cwd=tmp_path, scope=scope)
    assert r.ok and len(s.requests) == 2
    assert s.requests[1]["response_format"] == {"type": "json_object"}
    assert "must follow this JSON schema" in s.user(1)


def test_a_cut_answer_and_an_empty_answer_are_failures(tmp_path, fake):
    s = fake(lambda body, n: completion([("x.md", "partial")], finish="length"))
    r = aw.run_worker(cfg_for(s.url), task="t", system="s", cwd=tmp_path,
                      scope=ow.FileScope(base=tmp_path, writes=[tmp_path / "x.md"]))
    assert not r.ok and r.error_category == "budget" and "output limit" in r.error
    s2 = fake(lambda body, n: (200, {"choices": [{"finish_reason": "content_filter", "message": {"content": ""}}],
                                     "usage": {}}))
    r2 = aw.run_worker(cfg_for(s2.url), task="t", system="s", cwd=tmp_path, scope=ow.FileScope(base=tmp_path))
    assert not r2.ok and r2.error_category == "model_output" and "content_filter" in r2.error


def test_a_prompt_too_long_for_the_context_is_refused_before_sending(tmp_path, fake):
    s = fake(lambda body, n: completion([]))
    scope = ow.FileScope(base=tmp_path)
    r = aw.run_worker(cfg_for(s.url, max_context=100), task="t" * 2000, system="s", cwd=tmp_path, scope=scope)
    assert not r.ok and r.error_category == "budget" and "max_context" in r.error and not s.requests


def test_cost_is_counted_and_the_budget_stops_the_run(tmp_path, fake):
    s = fake(lambda body, n: completion([("x.md", "ok")], tin=1_000_000, tout=100_000))
    cfg = cfg_for(s.url, max_context=10_000_000, api_price_in=2.0, api_price_out=8.0, api_budget_usd=2.5)
    scope = ow.FileScope(base=tmp_path, writes=[tmp_path / "x.md"])
    r = aw.run_worker(cfg, task="t", system="s", cwd=tmp_path, scope=scope)
    assert r.ok and r.cost_usd == pytest.approx(2.8) and aw.spent() == pytest.approx(2.8)
    r2 = aw.run_worker(cfg, task="t", system="s", cwd=tmp_path, scope=scope)
    assert not r2.ok and r2.error_category == "budget" and len(s.requests) == 1


def test_hidden_reasoning_is_counted_as_output_and_named_when_it_cuts_the_answer(tmp_path, fake):
    """Gemini leaves its reasoning out of completion_tokens but counts it in total_tokens, the limit and the bill."""
    def responder(body, n):
        status, out = completion([("x.md", "ok")], tin=37, tout=70)
        out["usage"]["total_tokens"] = 589
        if n == 2:
            out["choices"][0]["finish_reason"] = "length"
        return status, out
    s = fake(responder)
    cfg = cfg_for(s.url, num_predict=512, api_reasoning_effort="low", api_price_in=1.0, api_price_out=1.0)
    scope = ow.FileScope(base=tmp_path, writes=[tmp_path / "x.md"])
    r = aw.run_worker(cfg, task="t", system="s", cwd=tmp_path, scope=scope)
    assert r.ok and r.tokens_out == 552 and r.cost_usd == pytest.approx((37 + 552) / 1e6)
    assert s.requests[0]["reasoning_effort"] == "low"
    r2 = aw.run_worker(cfg, task="t", system="s", cwd=tmp_path, scope=scope)
    assert not r2.ok and "hidden reasoning" in r2.error and "api_reasoning_effort" in r2.error


def test_max_tokens_field_can_be_renamed(tmp_path, fake):
    s = fake(lambda body, n: completion([]))
    aw.run_worker(cfg_for(s.url, num_predict=512, api_max_tokens_field="max_tokens"), task="t", system="s",
                  cwd=tmp_path, scope=ow.FileScope(base=tmp_path))
    assert s.requests[0]["max_tokens"] == 512 and "max_completion_tokens" not in s.requests[0]


def test_config_needs_a_model_and_sizes_batches_from_max_context():
    for w in API_PROVIDERS:
        with pytest.raises(ValueError):
            HarnessConfig(worker=w)
    c = HarnessConfig(worker="openai", model="m", max_context=200_000)
    assert c.inline and c.context_tokens() == 200_000 and c.file_chars() == 300_000 and c.batch_budget() == 40_000
    assert not HarnessConfig().inline and HarnessConfig().batch_budget() == 0


def test_each_provider_brings_its_endpoint_and_key_variable_and_both_can_be_overridden():
    g = HarnessConfig(worker="gemini", model="gemini-3.5-flash")
    assert g.api and g.inline
    assert g.api_base == "https://generativelanguage.googleapis.com/v1beta/openai" and g.api_key_env == "GEMINI_API_KEY"
    o = HarnessConfig(worker="openai", model="m")
    assert o.api_base == "https://api.openai.com/v1" and o.api_key_env == "OPENAI_API_KEY"
    c = HarnessConfig(worker="gemini", model="m", api_base="https://proxy.example/v1", api_key_env="MY_KEY")
    assert c.api_base == "https://proxy.example/v1" and c.api_key_env == "MY_KEY"
    assert not HarnessConfig(worker="ollama", model="q").api and HarnessConfig().api_base is None


def test_a_gemini_worker_sends_to_its_endpoint_with_its_key(tmp_path, fake, monkeypatch):
    s = fake(lambda body, n: completion([("x.md", "ok")]))
    monkeypatch.setenv("GEMINI_API_KEY", "g-key-456")
    cfg = HarnessConfig(worker="gemini", model="gemini-3.5-flash", api_base=s.url)     # the endpoint faked, the key not
    r = aw.run_worker(cfg, task="t", system="s", cwd=tmp_path, scope=ow.FileScope(base=tmp_path, writes=[tmp_path / "x.md"]))
    assert r.ok and s.headers[0].get("Authorization") == "Bearer g-key-456" and s.requests[0]["model"] == "gemini-3.5-flash"
    monkeypatch.delenv("GEMINI_API_KEY")
    r2 = aw.run_worker(cfg, task="t", system="s", cwd=tmp_path, scope=ow.FileScope(base=tmp_path))
    assert not r2.ok and "GEMINI_API_KEY" in r2.error and 'worker = "gemini"' in r2.error and len(s.requests) == 1


# ------------------------------------------------------------------------------------------------- in the executor
def test_executor_runs_the_api_worker_and_feedback_continues_the_conversation(tmp_path, fake):
    target = tmp_path / "ideas.json"

    def responder(body, n):
        return completion([(str(target), json.dumps([IDEA] if n > 1 else [{"Name": "Bad Name"}]))])
    s = fake(responder)
    cfg = cfg_for(s.url)
    rd = tmp_path / "t_research"
    rd.mkdir()
    ctx = RunContext(Registry.load(), cfg, Skill(cfg), rd, tmp_path / "t.md", say=lambda m: None)
    recipe = parse({"recipes": [{"unit": "B6", "scope": "generation", "phases": {"main": [
        {"write": {"task": "Write the ideas list", "writes": [str(target)], "rules": []}},
        {"run": f"ideate_tools.py validate {target}", "submit": True}]}}]})[0]
    res = RecipeExecutor().execute(ctx, "B6", recipe, "main", 1, 1)
    assert res.ok, res.errors
    assert len(s.requests) == 2 and "refused them" in s.user(1)
    assert [m["role"] for m in s.requests[1]["messages"]] == ["system", "user", "assistant", "user"]
    assert json.loads(target.read_text())[0]["Name"] == "fake_idea"
