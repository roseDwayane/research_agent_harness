"""The Ollama worker (harness/ollama_worker.py) against a fake Ollama server: no network, no model."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from harness import ollama_worker as ow
from harness.config import HarnessConfig
from harness.context import RunContext
from harness.executors import RecipeExecutor
from harness.recipes import parse
from harness.skill import CommandResult, Skill
from ideate_v2.registry import Registry

IDEA = {"Name": "fake_idea", "Title": "A title", "Short Hypothesis": "H", "Related Work": "RW",
        "Abstract": " ".join(["word"] * 200), "Experiments": ["E1 [tests C1] x"], "Risk Factors and Limitations": ["r"]}


def answer(files: list[tuple[str, str]], note: str = "done", **extra) -> tuple[int, dict]:
    content = json.dumps({"files": [{"path": p, "content": c} for p, c in files], "note": note})
    return 200, {"model": "m", "message": {"role": "assistant", "content": content}, "done": True,
                 "done_reason": extra.get("done_reason", "stop"), "prompt_eval_count": extra.get("tin", 100),
                 "eval_count": 20}


class FakeOllama:
    """Records every request; answers with responder(request_body, n) -> (status, body)."""

    def __init__(self, responder):
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        self.responder = responder
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):                              # noqa: N802 - http.server's name
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                outer.headers.append(dict(self.headers))
                status, out = outer.responder(body, len(outer.requests))
                data = json.dumps(out).encode() if isinstance(out, dict) else str(out).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

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
def fake():
    servers = []

    def make(responder):
        s = FakeOllama(responder)
        servers.append(s)
        return s
    yield make
    for s in servers:
        s.close()


def cfg_for(url: str, **kw) -> HarnessConfig:
    return HarnessConfig(worker="ollama", model="m", ollama_url=url, num_ctx=kw.pop("num_ctx", 8192), **kw)


def ctx_for(tmp_path: Path, cfg: HarnessConfig) -> RunContext:
    rd = tmp_path / "t_research"
    rd.mkdir(exist_ok=True)
    return RunContext(Registry.load(), cfg, Skill(cfg), rd, tmp_path / "t.md", say=lambda s: None)


# ------------------------------------------------------------------------------------------------- the worker
def test_request_shape_auth_and_write(tmp_path, fake, monkeypatch):
    s = fake(lambda body, n: answer([("out/x.md", "# hello")]))
    monkeypatch.setenv("OLLAMA_API_KEY", "k-123")
    scope = ow.FileScope(base=tmp_path, writes=[tmp_path / "out" / "x.md"])
    r = ow.run_worker(cfg_for(s.url), task="Write x.md", system=ow.cw.SHELL_RULES + "\n# Unit X\n", cwd=tmp_path,
                      scope=scope)
    assert r.ok and r.session_id and r.tokens_in == 100 and r.tokens_out == 20 and r.cost_usd == 0
    assert (tmp_path / "out" / "x.md").read_text() == "# hello\n"
    body = s.requests[0]
    assert body["model"] == "m" and body["stream"] is True and body["options"]["num_ctx"] == 8192
    assert body["format"] == ow.RESPONSE_SCHEMA and "think" not in body
    assert body["messages"][0]["role"] == "system" and "cannot open files or run commands" in body["messages"][0]["content"]
    assert s.headers[0].get("Authorization") == "Bearer k-123"
    assert s.headers[0].get("User-Agent", "").startswith("ideate-harness/")      # not Python-urllib (Cloudflare 1010)


def test_every_turn_logs_the_whole_request_untruncated(tmp_path, fake):
    def responder(body, n):
        return answer([("y.json", "{bad")]) if n == 1 else answer([("y.json", '{"fine": true}')])
    s = fake(responder)
    log = tmp_path / "log"
    task = "T" * 11000             # longer than the head (6000) + tail (4000) the old log kept; short of WARM_CHARS
    scope = ow.FileScope(base=tmp_path, writes=[tmp_path / "y.json"])
    r = ow.run_worker(cfg_for(s.url), task=task, system="S", cwd=tmp_path, scope=scope, log_dir=log, label="w")
    assert r.ok and len(s.requests) == 2
    for turn in (1, 2):
        rec = json.loads((log / f"w.ollama.{turn}.messages.json").read_text())
        assert rec["messages"] == s.requests[turn - 1]["messages"]          # exactly what was sent, every message
        assert rec["format"] == s.requests[turn - 1]["format"] and rec["model"] == "m"
        assert rec["session_id"] == r.session_id and rec["tokens_in"] == 100
    first = json.loads((log / "w.ollama.1.messages.json").read_text())
    assert task in first["messages"][-1]["content"] and first["answer"] == answer([("y.json", "{bad")])[1]["message"]["content"]


def test_only_allowed_paths_are_written_and_a_bad_answer_is_corrected_once(tmp_path, fake):
    def responder(body, n):
        if n == 1:
            return answer([("x.md", "ok"), ("../evil.md", "no"), ("_state/ledger.jsonl", "{}"), ("y.json", "{bad")])
        return answer([("y.json", '{"fine": true}'), ("_work/notes.md", "scratch")])
    s = fake(responder)
    (tmp_path / "_state").mkdir()
    scope = ow.FileScope(base=tmp_path, writes=[tmp_path / "x.md", tmp_path / "y.json"], globs=list(ow.SCRATCH))
    r = ow.run_worker(cfg_for(s.url), task="t", system="s", cwd=tmp_path, scope=scope)
    assert r.ok and len(s.requests) == 2
    fix = s.user(1)
    assert "../evil.md: not a file you may write" in fix and "_state/ledger.jsonl" in fix and "not valid JSON" in fix
    assert not (tmp_path.parent / "evil.md").exists() and not (tmp_path / "_state" / "ledger.jsonl").exists()
    assert json.loads((tmp_path / "y.json").read_text()) == {"fine": True}
    assert (tmp_path / "_work" / "notes.md").is_file()


def test_still_unusable_after_the_correction_is_a_model_output_failure(tmp_path, fake):
    s = fake(lambda body, n: answer([("y.json", "{bad")]))
    scope = ow.FileScope(base=tmp_path, writes=[tmp_path / "y.json"])
    r = ow.run_worker(cfg_for(s.url), task="t", system="s", cwd=tmp_path, scope=scope)
    assert not r.ok and r.error_category == "model_output" and len(s.requests) == 2


def test_the_prompt_carries_the_files_and_lookups_but_not_forbidden_ones(tmp_path, fake):
    s = fake(lambda body, n: answer([]))
    (tmp_path / "a.md").write_text("ALPHA")
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir" / "b.json").write_text('{"beta": 1}')
    (tmp_path / "secret.json").write_text("SECRET")
    (tmp_path / "draft.json").write_text('{"draft": "OLD"}')
    scope = ow.FileScope(base=tmp_path, reads=[("a.md", tmp_path / "a.md"), ("dir", tmp_path / "dir"),
                                               ("secret.json", tmp_path / "secret.json")],
                         writes=[tmp_path / "draft.json"], forbid=[tmp_path / "secret.json"],
                         lookups=[("ideate_tools.py list-papers RD", "paper_001 A title")])
    ow.run_worker(cfg_for(s.url), task="the task", system="s", cwd=tmp_path, scope=scope)
    msg = s.user()
    assert msg.startswith("the task") and "=== FILE: a.md ===\nALPHA" in msg and '"beta": 1' in msg
    assert "SECRET" not in msg and "OLD" in msg and "left by an earlier run" in msg   # context, not an answer to keep
    assert "$ ideate_tools.py list-papers RD\npaper_001 A title" in msg


def test_a_prompt_too_long_for_the_context_is_refused_before_sending(tmp_path, fake):
    s = fake(lambda body, n: answer([]))
    (tmp_path / "big.md").write_text("x" * 50000)
    scope = ow.FileScope(base=tmp_path, reads=[("big.md", tmp_path / "big.md")])
    r = ow.run_worker(cfg_for(s.url, num_ctx=2000), task="t", system="s", cwd=tmp_path, scope=scope)
    assert not r.ok and r.error_category == "budget" and "num_ctx" in r.error and not s.requests


def test_a_silently_cut_prompt_or_answer_is_detected(tmp_path, fake):
    s = fake(lambda body, n: answer([("x.md", "ok")], tin=8192))
    r = ow.run_worker(cfg_for(s.url), task="t", system="s", cwd=tmp_path, scope=ow.FileScope(base=tmp_path))
    assert not r.ok and r.error_category == "budget" and "filled the whole context" in r.error
    s2 = fake(lambda body, n: answer([("x.md", "ok")], done_reason="length"))
    r2 = ow.run_worker(cfg_for(s2.url), task="t", system="s", cwd=tmp_path, scope=ow.FileScope(base=tmp_path))
    assert not r2.ok and r2.error_category == "budget" and "num_predict" in r2.error


@pytest.mark.parametrize("status,category", [(404, "environment"), (401, "environment"), (503, "external_service"),
                                             (429, "external_service"), (400, "tool_invocation")])
def test_http_failures_are_classified(tmp_path, fake, status, category):
    s = fake(lambda body, n: (status, {"error": "nope"}))
    r = ow.run_worker(cfg_for(s.url), task="t", system="s", cwd=tmp_path, scope=ow.FileScope(base=tmp_path))
    assert not r.ok and r.error_category == category


def test_an_unreachable_server_is_external(tmp_path):
    r = ow.run_worker(cfg_for("http://127.0.0.1:9"), task="t", system="s", cwd=tmp_path,
                      scope=ow.FileScope(base=tmp_path), timeout=5)
    assert not r.ok and r.error_category in ("external_service", "timeout")


def test_a_step_that_needs_commands_run_by_the_worker_is_refused_at_once(tmp_path, fake):
    s = fake(lambda body, n: answer([]))
    scope = ow.FileScope(base=tmp_path, unavailable=["ideate_tools.py questions-prefill"])
    r = ow.run_worker(cfg_for(s.url), task="t", system="s", cwd=tmp_path, scope=scope)
    assert not r.ok and r.error_category == "environment" and "questions-prefill" in r.error and not s.requests


def test_ollama_needs_a_model():
    with pytest.raises(ValueError):
        HarnessConfig(worker="ollama")


# ------------------------------------------------------------------------------------------------- in the executor
def test_executor_feedback_continues_the_same_conversation(tmp_path, fake):
    """write -> `validate` refuses -> the refusal goes into the same history -> fixed -> validate passes."""
    target = tmp_path / "ideas.json"

    def responder(body, n):
        good = n > 1
        return answer([(str(target), json.dumps([IDEA] if good else [{"Name": "Bad Name"}]))])
    s = fake(responder)
    ctx = ctx_for(tmp_path, cfg_for(s.url))
    recipe = parse({"recipes": [{"unit": "B6", "scope": "generation", "phases": {"main": [
        {"write": {"task": "Write the ideas list", "writes": [str(target)], "rules": []}},
        {"run": f"ideate_tools.py validate {target}", "submit": True}]}}]})[0]
    res = RecipeExecutor().execute(ctx, "B6", recipe, "main", 1, 1)
    assert res.ok, res.errors
    assert len(s.requests) == 2
    roles = [m["role"] for m in s.requests[1]["messages"]]
    assert roles == ["system", "user", "assistant", "user"] and "refused them" in s.user(1)
    assert "as you wrote them" in s.user(1) and "=== FILE:" not in s.user(1)   # its own answer is not repeated
    assert json.loads(target.read_text())[0]["Name"] == "fake_idea"


def test_executor_isolated_reader_sees_its_copies_under_their_names(tmp_path, fake):
    def responder(body, n):
        return answer([("./a.json", '{"verdict": "approved"}')])
    s = fake(responder)
    ctx = ctx_for(tmp_path, cfg_for(s.url))
    view = ctx.rd / "step1_protocol.md"
    view.write_text("# the protocol\n")
    out = ctx.rd / "a.json"
    recipe = parse({"recipes": [{"unit": "A1.e", "phases": {"main": [{"write": {
        "task": f"Read {view} and judge it.", "rules": [], "reads": [str(view)], "writes": [str(out)],
        "isolated": True}}]}}]})[0]
    res = RecipeExecutor().execute(ctx, "A1.e", recipe, "main", None, 1)
    assert res.ok, res.errors
    assert json.loads(out.read_text()) == {"verdict": "approved"}
    assert f"=== FILE: {view} ===\n# the protocol" in s.user()


def test_executor_fanout_gives_each_batch_its_named_files(tmp_path, fake):
    def responder(body, n):
        msg = [m for m in body["messages"] if m["role"] == "user"][-1]["content"]
        path = msg.split("You may write only: ")[1].split(";")[0].rstrip(".")
        return answer([(path, json.dumps({"key": Path(path).stem}))])
    s = fake(responder)
    ctx = ctx_for(tmp_path, cfg_for(s.url))
    work = ctx.rd / "knowledge" / "_work" / "A7D"
    work.mkdir(parents=True)
    (ctx.rd / "step5_full_text").mkdir()
    for k in ("smith2020", "lee2021"):
        (ctx.rd / "step5_full_text" / f"{k}.md").write_text(f"FULL TEXT OF {k}")
        (work / f"batch_{k}.json").write_text(json.dumps({"papers": [
            {"citation_key": k, "full_text": f"step5_full_text/{k}.md", "answer": f"knowledge/_work/A7D/answers/{k}.json"}]}))
    recipe = parse({"recipes": [{"unit": "A7.D", "phases": {"main": [{"fanout": {
        "batches": "$RD/knowledge/_work/A7D/batch_*.json", "out": "items:papers.answer",
        "task": "Read {batch}; write {out}.", "rules": []}}]}}]})[0]
    res = RecipeExecutor().execute(ctx, "A7.D", recipe, "main", None, 1)
    assert res.ok, res.errors
    assert {json.loads((work / "answers" / f"{k}.json").read_text())["key"] for k in ("smith2020", "lee2021")} == \
        {"smith2020", "lee2021"}
    texts = [m["content"] for b in s.requests for m in b["messages"] if m["role"] == "user"]
    assert any("FULL TEXT OF smith2020" in t and "lee2021" not in t.split("# Your answer")[0] for t in texts)


def test_executor_runs_the_lookups_and_refuses_worker_commands(tmp_path, fake, monkeypatch):
    s = fake(lambda body, n: answer([]))
    ctx = ctx_for(tmp_path, cfg_for(s.url))
    ran = []

    def fake_run(cmd, subs, timeout=None):
        ran.append(cmd)
        return CommandResult(cmd, [], 0, "paper_001 Label smoothing\n")
    monkeypatch.setattr(ctx.skill, "run", fake_run)
    recipe = parse({"recipes": [{"unit": "B2", "phases": {"main": [{"write": {
        "task": "Write the review.", "rules": [], "writes": [str(ctx.rd / "r.md")],
        "commands": ["ideate_tools.py list-papers", "ideate_tools.py trace"]}}]}}]})[0]
    RecipeExecutor().execute(ctx, "B2", recipe, "main", None, 1)
    assert ran == ["ideate_tools.py list-papers $RD --abstract-chars 300"]
    assert "paper_001 Label smoothing" in s.user(0)
    assert "You have not written" in s.user()                 # it wrote nothing: asked again in the same history
    n = len(s.requests)
    recipe2 = parse({"recipes": [{"unit": "B3.5", "phases": {"main": [{"write": {
        "task": "For each gap run `ideate-tool questions-prefill <RD> GAP_NNN`, then write the question.", "rules": [],
        "writes": [], "commands": ["ideate_tools.py questions-prefill"]}}]}}]})[0]
    res = RecipeExecutor().execute(ctx, "B3.5", recipe2, "main", None, 1)
    assert not res.ok and len(s.requests) == n
    assert "questions-prefill" in res.errors[0].error_message


# ------------------------------------------------------------------------------------------------- schema answers
def reply(obj: dict) -> tuple[int, dict]:
    return 200, {"model": "m", "message": {"role": "assistant", "content": json.dumps(obj)}, "done": True,
                 "done_reason": "stop", "prompt_eval_count": 100, "eval_count": 20}


def test_a_step_with_a_schema_is_decoded_as_that_object(tmp_path, fake):
    """The archived engine's fence: the file's own structure is the grammar, not a string inside {"files"}."""
    schema = {"type": "object", "properties": {"flat": {"type": "object"}}, "required": ["flat"]}
    s = fake(lambda body, n: reply({"answer": {"flat": {"Q1": ["a", "b", "c"]}}, "note": "filled"}))
    target = tmp_path / "_state" / "A1" / "strategy_fill.json"
    scope = ow.FileScope(base=tmp_path, writes=[target], schema=schema)
    r = ow.run_worker(cfg_for(s.url), task="Fill it", system="s", cwd=tmp_path, scope=scope)
    assert r.ok and r.text == "filled"
    assert s.requests[0]["format"]["properties"]["answer"] == schema
    assert '{"answer": <the content of' in s.user(0) and '"files"' not in s.user(0)
    assert json.loads(target.read_text()) == {"flat": {"Q1": ["a", "b", "c"]}}


def test_executor_passes_the_step_schema_to_the_worker(tmp_path, fake):
    rd = tmp_path / "t_research"
    (rd / "_state" / "A1").mkdir(parents=True)
    (rd / "_state" / "A1" / "fill.schema.json").write_text(json.dumps({"type": "object"}))
    s = fake(lambda body, n: reply({"answer": {"flat": {"Q1": ["new", "words", "here"]}}, "note": "x"}))
    ctx = ctx_for(tmp_path, cfg_for(s.url))
    recipe = parse({"recipes": [{"unit": "A1.q", "scope": "topic", "phases": {"main": [
        {"write": {"task": "Fill it", "writes": ["$RD/_state/A1/strategy_fill.json"],
                   "schema": "$RD/_state/A1/fill.schema.json", "rules": []}}]}}]})[0]
    res = RecipeExecutor().execute(ctx, "A1.q", recipe, "main", None, 1)
    assert res.ok, res.errors
    assert s.requests[0]["format"]["properties"]["answer"] == {"type": "object"}
    assert json.loads((rd / "_state" / "A1" / "strategy_fill.json").read_text())["flat"]["Q1"][0] == "new"


def test_executor_refuses_a_file_left_from_an_earlier_run(tmp_path, fake):
    """A draft an earlier run left is not this call's answer: a worker that writes nothing is asked to write it."""
    rd = tmp_path / "t_research"
    rd.mkdir()
    target = rd / "strategy.json"
    target.write_text('{"old": true}\n')
    s = fake(lambda body, n: answer([] if n == 1 else [(str(target), '{"new": true}')], note="I cannot"))
    ctx = ctx_for(tmp_path, cfg_for(s.url))
    recipe = parse({"recipes": [{"unit": "A1.q", "scope": "topic", "phases": {"main": [
        {"write": {"task": "Write it", "writes": [str(target)], "rules": []}}]}}]})[0]
    res = RecipeExecutor().execute(ctx, "A1.q", recipe, "main", None, 1)
    assert res.ok, res.errors
    assert len(s.requests) == 2 and "You have not written" in s.user(1)
    assert json.loads(target.read_text()) == {"new": True}


def test_one_file_keyed_by_its_name_is_unwrapped(tmp_path, fake):
    """A batch schema keyed by its items (A7.D: one record per citation key) with one item: the record is the file."""
    s = fake(lambda body, n: reply({"answer": {"smith2020": {"summary": {"problem": "p"}}}, "note": "x"}))
    target = tmp_path / "answers" / "smith2020.json"
    scope = ow.FileScope(base=tmp_path, writes=[target], schema={"type": "object"})
    r = ow.run_worker(cfg_for(s.url), task="t", system="s", cwd=tmp_path, scope=scope)
    assert r.ok and json.loads(target.read_text()) == {"summary": {"problem": "p"}}


def test_a_stream_cut_before_done_is_a_dropped_connection_not_an_answer(tmp_path, fake):
    """A proxy that closes a long answer leaves half a JSON object: it is retried as a transport failure, never parsed."""
    s = fake(lambda body, n: (200, {"model": "m", "message": {"role": "assistant", "content": '{"files": [{"pa'},
                                    "done": False}))
    res, content = ow.chat(cfg_for(s.url), [{"role": "user", "content": "x"}], timeout=30)
    assert not res.ok and res.error_category == "external_service" and "dropped" in res.error and content == ""


def test_a_revision_shows_a_file_again_only_where_a_tool_changed_it(tmp_path, fake):
    s = fake(lambda body, n: answer([(str(tmp_path / "x.md"), "# mine")]))
    scope = ow.FileScope(base=tmp_path, writes=[tmp_path / "x.md"])
    r = ow.run_worker(cfg_for(s.url), task="Write x.md", system="s", cwd=tmp_path, scope=scope)
    ow.run_worker(cfg_for(s.url), task="fix it", system="s", cwd=tmp_path, scope=scope, resume=r.session_id)
    assert "as you wrote them" in s.user(1)
    (tmp_path / "x.md").write_text("# mine\nadded by a tool\n")
    ow.run_worker(cfg_for(s.url), task="fix it", system="s", cwd=tmp_path, scope=scope, resume=r.session_id)
    assert "added by a tool" in s.user(2)


def test_a_revision_sends_only_the_latest_answer_in_full(tmp_path, fake):
    """Each answer writes the whole file again: the earlier ones are cut to a line, so revisions do not grow the prompt."""
    s = fake(lambda body, n: answer([(str(tmp_path / "x.md"), f"# version {n}")]))
    scope = ow.FileScope(base=tmp_path, writes=[tmp_path / "x.md"])
    r = ow.run_worker(cfg_for(s.url), task="Write x.md", system="s", cwd=tmp_path, scope=scope)
    for _ in range(2):
        ow.run_worker(cfg_for(s.url), task="fix it", system="s", cwd=tmp_path, scope=scope, resume=r.session_id)
    said = [m["content"] for m in s.requests[-1]["messages"] if m["role"] == "assistant"]
    assert said[:-1] == [ow.SUPERSEDED] and "version" in said[-1]
    assert [m["content"] for m in s.requests[-1]["messages"] if m["role"] == "user"][0].startswith("Write x.md")


def test_a_dropped_call_is_sent_again_only_once_the_server_is_free(tmp_path, fake, monkeypatch):
    """524, then a probe that finds the server busy (still writing the dropped answer), one that finds it free, and
    only then the call again: a re-send to a busy server would queue one more whole answer behind the first."""
    import time
    monkeypatch.setattr(ow, "IDLE_PROBE_S", 0.3)
    monkeypatch.setattr(ow, "IDLE_PAUSE_S", 0.0)
    target = tmp_path / "t_research" / "ideas.json"

    def responder(body, n):
        if n == 1:
            return 524, "error code: 524"
        if n == 2:
            time.sleep(1.0)                                  # busy: the probe gives up first
        return answer([(str(target), json.dumps([IDEA]))])
    s = fake(responder)
    ctx = ctx_for(tmp_path, cfg_for(s.url, ollama_busy_wait_s=0.0))
    recipe = parse({"recipes": [{"unit": "B6", "scope": "generation", "phases": {"main": [
        {"write": {"task": "Write the ideas list", "writes": [str(target)], "rules": []}}]}}]})[0]
    res = RecipeExecutor().execute(ctx, "B6", recipe, "main", 1, 1)
    assert res.ok, res.errors
    assert [r["options"]["num_predict"] for r in s.requests] == [16384, 1, 1, 16384]
    assert s.requests[1]["messages"] == s.requests[0]["messages"]       # the probe re-reads the call's own prompt


def test_a_long_prompt_is_read_into_the_cache_before_the_call(tmp_path, fake, monkeypatch):
    """A prompt a proxy would drop before its first byte: one-token calls of the same prompt first (the first gives up
    while the server reads it), then the call - whose answer is written once, not once for nobody and again."""
    import time
    monkeypatch.setattr(ow, "WARM_CHARS", 100)
    monkeypatch.setattr(ow, "IDLE_PROBE_S", 0.3)
    monkeypatch.setattr(ow, "IDLE_PAUSE_S", 0.0)
    said = []

    def responder(body, n):
        if n == 1:
            time.sleep(1.0)                                  # reading the long prompt: the probe gives up first
        return answer([("x.md", "ok")])
    s = fake(responder)
    r = ow.run_worker(cfg_for(s.url), task="Write x.md from this: " + "words " * 50, system="# Unit X\n", cwd=tmp_path,
                      scope=ow.FileScope(base=tmp_path, writes=[tmp_path / "x.md"]), say=said.append)
    assert r.ok, r.error
    assert [q["options"]["num_predict"] for q in s.requests] == [1, 1, 16384]
    assert s.requests[0]["messages"] == s.requests[2]["messages"]       # the probe reads the call's own prompt
    assert said and "cache" in said[0]


def test_a_short_prompt_is_sent_at_once(tmp_path, fake):
    s = fake(lambda body, n: answer([("x.md", "ok")]))
    r = ow.run_worker(cfg_for(s.url), task="Write x.md", system="# Unit X\n", cwd=tmp_path,
                      scope=ow.FileScope(base=tmp_path, writes=[tmp_path / "x.md"]))
    assert r.ok and [q["options"]["num_predict"] for q in s.requests] == [16384]


def test_a_silent_server_is_a_timeout_named_as_a_silence(tmp_path, fake, monkeypatch):
    """A server that takes the request and sends nothing (busy, reloading) hits the read limit, not the call's limit."""
    import time
    monkeypatch.setattr(ow, "STREAM_IDLE_S", 0.3)
    s = fake(lambda body, n: (time.sleep(1.0), answer([("x.md", "x")]))[1])
    res, _ = ow.chat(cfg_for(s.url), [{"role": "user", "content": "x"}], timeout=30)
    assert not res.ok and res.error_category == "timeout" and "silent for 0s" in res.error and "within 30" not in res.error


def test_a_worker_writes_only_the_scratch_its_unit_declares(tmp_path):
    """The ledger refuses a done for a file outside the Unit's declared files: the worker is held to the same list."""
    from harness.executors import RecipeExecutor
    ctx = ctx_for(tmp_path, cfg_for("http://localhost:1"))
    globs = RecipeExecutor._scratch(ctx, "B3.5")
    assert globs == ["knowledge/_work/B35/**", "_state/harness/decisions/**"]
    scope = ow.FileScope(base=tmp_path, globs=globs)
    assert scope.target("_work/B35/notes_Q_003.json") is None
    assert scope.target("knowledge/_work/B35/s9_Q_003.json") is not None



def test_a_fanout_answer_that_writes_nothing_is_asked_again_in_its_conversation(tmp_path, fake):
    """A note without the file is no answer: the batch's own conversation is asked once more ((TBD) allowed), before
    the batch counts as failed and is dispatched again from scratch."""
    def responder(body, n):
        if n == 1:
            return answer([], note="I cannot write it without the raw lookup")
        msg = [m for m in body["messages"] if m["role"] == "user"][0]["content"]
        path = msg.split("You may write only: ")[1].split(";")[0].rstrip(".")
        return answer([(path, "# (TBD) where the batch lacks it\n")])
    s = fake(responder)
    ctx = ctx_for(tmp_path, cfg_for(s.url))
    work = ctx.rd / "knowledge" / "_work" / "B35"
    work.mkdir(parents=True)
    (work / "q_batch_Q_001.json").write_text(json.dumps({"out": "questions/Q_001.md"}))
    recipe = parse({"recipes": [{"unit": "B3.5", "phases": {"main": [{"fanout": {
        "batches": "$RD/knowledge/_work/B35/q_batch_*.json", "out": "rdfield:out",
        "task": "Read {batch}; write {out}.", "rules": []}}]}}]})[0]
    res = RecipeExecutor().execute(ctx, "B3.5", recipe, "main", None, 1)
    assert res.ok, res.errors
    assert len(s.requests) == 2 and "You have not written" in s.user(1) and "(TBD)" in s.user(1)
    assert (ctx.rd / "questions" / "Q_001.md").read_text().startswith("# (TBD)")
