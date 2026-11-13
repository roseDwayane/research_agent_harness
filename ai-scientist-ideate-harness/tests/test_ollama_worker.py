"""The Ollama provider (harness/providers/ollama.py, the chat flow of chat.py) against a fake Ollama server: no
network, no model."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from harness.config import MODULE_ROOT, HarnessConfig
from harness.context import RunContext
from harness.providers import FileScope, WorkerRequest, WorkerResult, chat
from harness.providers import ollama as ow
from harness.providers.base import SCRATCH
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


def run_worker(cfg: HarnessConfig, **kw) -> WorkerResult:
    """One call through the provider interface, as the executor makes it."""
    return ow.OllamaProvider(cfg).run(WorkerRequest(**kw))


# ------------------------------------------------------------------------------------------------- the worker
def test_request_shape_auth_and_write(tmp_path, fake, monkeypatch):
    s = fake(lambda body, n: answer([("out/x.md", "# hello")]))
    monkeypatch.setenv("OLLAMA_API_KEY", "k-123")
    cfg = cfg_for(s.url)
    system = ow.OllamaProvider(cfg).system_prompt(MODULE_ROOT, {"id": "X", "name": "x"}, None, [],
                                                  ["ideate_tools.py list-papers"])
    scope = FileScope(base=tmp_path, writes=[tmp_path / "out" / "x.md"])
    r = run_worker(cfg, task="Write x.md", system=system, cwd=tmp_path, scope=scope)
    assert r.ok and r.session_id and r.tokens_in == 100 and r.tokens_out == 20 and r.cost_usd == 0
    assert (tmp_path / "out" / "x.md").read_text() == "# hello\n"
    body = s.requests[0]
    assert body["model"] == "m" and body["stream"] is True and body["options"]["num_ctx"] == 8192
    assert body["format"] == chat.TYPED_RESPONSE_SCHEMA and "think" not in body
    sys_msg = body["messages"][0]
    assert sys_msg["role"] == "system" and "cannot open files or run commands" in sys_msg["content"]
    assert "# Unit X - x" in sys_msg["content"] and "Commands you may run" not in sys_msg["content"]
    assert s.headers[0].get("Authorization") == "Bearer k-123"
    assert s.headers[0].get("User-Agent", "").startswith("ideate-harness/")      # not Python-urllib (Cloudflare 1010)


def test_only_allowed_paths_are_written_and_a_bad_answer_is_corrected_once(tmp_path, fake):
    def responder(body, n):
        if n == 1:
            return answer([("x.md", "ok"), ("../evil.md", "no"), ("_state/ledger.jsonl", "{}"), ("y.json", "{bad")])
        return answer([("y.json", '{"fine": true}'), ("_work/notes.md", "scratch")])
    s = fake(responder)
    (tmp_path / "_state").mkdir()
    scope = FileScope(base=tmp_path, writes=[tmp_path / "x.md", tmp_path / "y.json"], globs=list(SCRATCH))
    r = run_worker(cfg_for(s.url), task="t", system="s", cwd=tmp_path, scope=scope)
    assert r.ok and len(s.requests) == 2
    fix = s.user(1)
    assert "../evil.md: not a file you may write" in fix and "_state/ledger.jsonl" in fix and "not valid JSON" in fix
    assert not (tmp_path.parent / "evil.md").exists() and not (tmp_path / "_state" / "ledger.jsonl").exists()
    assert json.loads((tmp_path / "y.json").read_text()) == {"fine": True}
    assert (tmp_path / "_work" / "notes.md").is_file()


def test_a_json_file_is_written_from_its_json_value(tmp_path, fake):
    """Under Ollama's grammar a .json file's content is its object (no JSON text escaped in a string); a .md file's
    content stays text, and an object for it is sent back."""
    def responder(body, n):
        files = [{"path": "a.json", "content": {"claims": [{"id": "C1", "n": 2}]}},
                 {"path": "b.jsonl", "content": [{"k": 1}, {"k": 2}]}, {"path": "c.md", "content": "# c"}]
        if n == 1:
            files.append({"path": "d.md", "content": {"not": "text"}})
        content = json.dumps({"files": files, "note": "ok"})
        return 200, {"model": "m", "message": {"role": "assistant", "content": content}, "done": True,
                     "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5}
    s = fake(responder)
    names = ("a.json", "b.jsonl", "c.md", "d.md")
    scope = FileScope(base=tmp_path, writes=[tmp_path / x for x in names])
    r = run_worker(cfg_for(s.url), task="t", system="s", cwd=tmp_path, scope=scope)
    assert "its JSON object itself, not a string" in s.user(0)
    assert s.requests[0]["format"]["properties"]["files"]["items"]["properties"]["content"]["anyOf"][1] == {"type": "object"}
    assert "d.md: its content must be the file's text" in s.user(1)
    assert json.loads((tmp_path / "a.json").read_text()) == {"claims": [{"id": "C1", "n": 2}]}
    assert [json.loads(x) for x in (tmp_path / "b.jsonl").read_text().splitlines()] == [{"k": 1}, {"k": 2}]
    assert r.ok and len(s.requests) == 2 and (tmp_path / "c.md").read_text() == "# c\n"


def test_optional_fields_are_sent_in_place_and_their_nulls_dropped(tmp_path, fake):
    """A grammar writes required properties first and optional ones after the last of them (live: {"a", "c", "b"});
    sent required-but-nullable, an optional field comes in its place, and a null one is taken out of the file."""
    gap = {"type": "object", "additionalProperties": False,
           "properties": {"id": {"type": "string"}, "move": {"enum": ["add-evidence", "kind"]},
                          "move_reason": {"type": "string"}, "not_done": {"type": "array", "items": {"type": "string"}},
                          "source_check": {"anyOf": [
                              {"type": "object", "properties": {"key": {"type": "string"}, "where": {"type": "string"}},
                               "required": ["key"]},
                              {"type": "array", "items": {"type": "object", "properties": {
                                  "key": {"type": "string"}, "where": {"type": "string"}}, "required": ["key"]}}]}},
           "required": ["id", "move"]}
    schema = {"type": "object", "properties": {"gaps": {"type": "array", "items": gap}}, "required": ["gaps"]}

    def responder(body, n):
        ans = {"answer": {"gaps": [
            {"id": "GAP_001", "move": "kind", "move_reason": "the collision is a kind contrast", "not_done": None,
             "source_check": {"key": "p1", "where": None}},
            {"id": "GAP_002", "move": "add-evidence", "move_reason": None, "not_done": ["p2#N1"],
             "source_check": [{"key": "p2", "where": "Results"}, {"key": "p3", "where": None}]}]}, "note": "ok"}
        return 200, {"model": "m", "message": {"role": "assistant", "content": json.dumps(ans)}, "done": True,
                     "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5}
    s = fake(responder)
    out = tmp_path / "gaps.json"
    r = run_worker(cfg_for(s.url), task="t", system="s", cwd=tmp_path,
                   scope=FileScope(base=tmp_path, writes=[out], schema=schema))
    assert r.ok
    sent = s.requests[0]["format"]["properties"]["answer"]["properties"]["gaps"]["items"]
    assert sent["required"] == ["id", "move", "move_reason", "not_done", "source_check"]
    assert sent["properties"]["move_reason"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert sent["properties"]["move"] == {"enum": ["add-evidence", "kind"]}                   # required: as it was
    branch = sent["properties"]["source_check"]["anyOf"][0]["anyOf"][0]
    assert branch["required"] == ["key", "where"] and branch["properties"]["where"]["anyOf"][1] == {"type": "null"}
    g1, g2 = json.loads(out.read_text())["gaps"]
    assert g1 == {"id": "GAP_001", "move": "kind", "move_reason": "the collision is a kind contrast",
                  "source_check": {"key": "p1"}}
    assert g2 == {"id": "GAP_002", "move": "add-evidence", "not_done": ["p2#N1"],
                  "source_check": [{"key": "p2", "where": "Results"}, {"key": "p3"}]}


def test_in_order_keeps_a_schema_without_optional_fields():
    s = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"], "additionalProperties": False}
    assert chat.in_order(s) == s and chat.in_order({"type": "string"}) == {"type": "string"}
    m = {"type": "object", "additionalProperties": {"type": "object", "properties": {"x": {"type": "string"}}}}
    assert chat.in_order(m)["additionalProperties"]["required"] == ["x"]
    assert chat.drop_nulls({"k": {"x": None}}, m) == {"k": {}}


def test_a_strict_api_keeps_the_text_envelope():
    """Anthropic's and OpenAI's strict outputs cannot hold an open object: their envelope stays text-only."""
    from harness.providers.claude import ClaudeProvider
    from harness.providers.gpt import GPTProvider
    scope = FileScope(base=Path("."), writes=[Path("x.json")])
    assert not ClaudeProvider.grammar and not GPTProvider.grammar
    assert chat.answer_format(scope) == chat.RESPONSE_SCHEMA
    assert "its JSON object itself" not in chat.build_message("t", scope)


def test_still_unusable_after_the_correction_is_a_model_output_failure(tmp_path, fake):
    s = fake(lambda body, n: answer([("y.json", "{bad")]))
    scope = FileScope(base=tmp_path, writes=[tmp_path / "y.json"])
    r = run_worker(cfg_for(s.url), task="t", system="s", cwd=tmp_path, scope=scope)
    assert not r.ok and r.error_category == "model_output" and len(s.requests) == 2


def test_the_prompt_carries_the_files_and_lookups_but_not_forbidden_ones(tmp_path, fake):
    s = fake(lambda body, n: answer([]))
    (tmp_path / "a.md").write_text("ALPHA")
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir" / "b.json").write_text('{"beta": 1}')
    (tmp_path / "secret.json").write_text("SECRET")
    (tmp_path / "draft.json").write_text('{"draft": "OLD"}')
    scope = FileScope(base=tmp_path, reads=[("a.md", tmp_path / "a.md"), ("dir", tmp_path / "dir"),
                                               ("secret.json", tmp_path / "secret.json")],
                         writes=[tmp_path / "draft.json"], forbid=[tmp_path / "secret.json"],
                         lookups=[("ideate_tools.py list-papers RD", "paper_001 A title")])
    run_worker(cfg_for(s.url), task="the task", system="s", cwd=tmp_path, scope=scope)
    msg = s.user()
    assert msg.startswith("the task") and "=== FILE: a.md ===\nALPHA" in msg and '"beta": 1' in msg
    assert "SECRET" not in msg and "OLD" in msg and "left by an earlier run" in msg   # context, not an answer to keep
    assert "$ ideate_tools.py list-papers RD\npaper_001 A title" in msg


def test_a_prompt_too_long_for_the_context_is_refused_before_sending(tmp_path, fake):
    s = fake(lambda body, n: answer([]))
    (tmp_path / "big.md").write_text("x" * 50000)
    scope = FileScope(base=tmp_path, reads=[("big.md", tmp_path / "big.md")])
    r = run_worker(cfg_for(s.url, num_ctx=2000), task="t", system="s", cwd=tmp_path, scope=scope)
    assert not r.ok and r.error_category == "budget" and "num_ctx" in r.error and not s.requests


def test_a_silently_cut_prompt_or_answer_is_detected(tmp_path, fake):
    s = fake(lambda body, n: answer([("x.md", "ok")], tin=8192))
    r = run_worker(cfg_for(s.url), task="t", system="s", cwd=tmp_path, scope=FileScope(base=tmp_path))
    assert not r.ok and r.error_category == "budget" and "filled the whole context" in r.error
    s2 = fake(lambda body, n: answer([("x.md", "ok")], done_reason="length"))
    r2 = run_worker(cfg_for(s2.url), task="t", system="s", cwd=tmp_path, scope=FileScope(base=tmp_path))
    assert not r2.ok and r2.error_category == "budget" and "num_predict" in r2.error


@pytest.mark.parametrize("status,category", [(404, "environment"), (401, "environment"), (503, "external_service"),
                                             (429, "external_service"), (400, "tool_invocation")])
def test_http_failures_are_classified(tmp_path, fake, status, category):
    s = fake(lambda body, n: (status, {"error": "nope"}))
    r = run_worker(cfg_for(s.url), task="t", system="s", cwd=tmp_path, scope=FileScope(base=tmp_path))
    assert not r.ok and r.error_category == category


def test_an_unreachable_server_is_external(tmp_path):
    r = run_worker(cfg_for("http://127.0.0.1:9"), task="t", system="s", cwd=tmp_path,
                   scope=FileScope(base=tmp_path), timeout=5)
    assert not r.ok and r.error_category in ("external_service", "timeout")


def test_a_step_that_needs_commands_run_by_the_worker_is_refused_at_once(tmp_path, fake):
    s = fake(lambda body, n: answer([]))
    scope = FileScope(base=tmp_path, unavailable=["ideate_tools.py questions-prefill"])
    r = run_worker(cfg_for(s.url), task="t", system="s", cwd=tmp_path, scope=scope)
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
    assert ran == ["ideate_tools.py list-papers $RD --file shortlist --slice 0:80 --abstract-chars 160"]
    assert "paper_001 Label smoothing" in s.user(0)
    assert "You have not written" in s.user()                 # it wrote nothing: asked again in the same history
    n = len(s.requests)
    recipe2 = parse({"recipes": [{"unit": "B3.5", "phases": {"main": [{"write": {
        "task": "For each gap run `ideate-tool questions-prefill <RD> GAP_NNN`, then write the question.", "rules": [],
        "writes": [], "commands": ["ideate_tools.py questions-prefill"]}}]}}]})[0]
    res = RecipeExecutor().execute(ctx, "B3.5", recipe2, "main", None, 1)
    assert not res.ok and len(s.requests) == n
    assert "questions-prefill" in res.errors[0].error_message


def test_a_check_that_finds_errors_shows_its_findings(tmp_path, fake, monkeypatch):
    """A check exits 1 exactly when it has findings: the worker gets all of them, not the last lines of the output
    (B5 round 1 pasted `(exit 1) ], "notes": [] }` and round 2 never fixed what argument-check reported)."""
    s = fake(lambda body, n: answer([]))
    ctx = ctx_for(tmp_path, cfg_for(s.url))
    findings = "".join(f"ERROR C{i} C1: finding number {i}\n" for i in range(1, 9)) + "argument-check: 8 error(s) - REVISE\n"
    monkeypatch.setattr(ctx.skill, "run", lambda cmd, subs, timeout=None: CommandResult(cmd, [], 1, findings))
    recipe = parse({"recipes": [{"unit": "B5", "scope": "generation", "phases": {"round1": [{"write": {
        "task": "Paste the checks.", "rules": [], "writes": [str(ctx.rd / "log.md")],
        "commands": ["ideate_tools.py argument-check"]}}]}}]})[0]
    (ctx.rd / "gen_1").mkdir()
    RecipeExecutor().execute(ctx, "B5", recipe, "round1", 1, 1)
    prompt = s.user(0)
    assert "(exit 1: it reports findings)" in prompt
    assert "ERROR C1 C1: finding number 1" in prompt and "argument-check: 8 error(s) - REVISE" in prompt


def test_a_may_write_file_is_allowed_but_not_required(tmp_path, fake):
    """P2's revision may leave step8_hypothesis.md as it is (a design change alone): allowed, never asked for."""
    s = fake(lambda body, n: answer([("arg.json", '{"a": 1}')]))
    ctx = ctx_for(tmp_path, cfg_for(s.url))
    recipe = parse({"recipes": [{"unit": "B2", "phases": {"main": [{"write": {
        "task": "Revise.", "rules": [], "writes": ["$RD/arg.json"], "may_write": ["$RD/step8.md", "/etc/passwd"]}}]}}]})[0]
    res = RecipeExecutor().execute(ctx, "B2", recipe, "main", None, 1)
    assert res.ok and len(s.requests) == 1                          # step8.md not written: not asked for
    assert f"{ctx.rd}/step8.md" in s.user(0) and "/etc/passwd" not in s.user(0)


def test_an_independent_reader_that_wrote_nothing_is_asked_once_more_afresh(tmp_path, fake):
    """An isolated reader has no session to resume: it is asked again in a new conversation, as blind as the first
    time - once; a second empty answer fails the step."""
    replies = iter([answer([]), answer([("restatement_2.json", '{"claim": "x"}')])])
    s = fake(lambda body, n: next(replies))
    ctx = ctx_for(tmp_path, cfg_for(s.url))
    (ctx.rd / "gen_1").mkdir()
    (ctx.rd / "gen_1" / "idea_draft.json").write_text('{"Name": "n"}')
    recipe = parse({"recipes": [{"unit": "B5", "scope": "generation", "phases": {"round3": [{"write": {
        "task": "Restate this idea as a blind reader.", "rules": [], "isolated": True,
        "reads": ["$GEN/idea_draft.json"], "writes": ["$GEN/restatement_2.json"]}}]}}]})[0]
    res = RecipeExecutor().execute(ctx, "B5", recipe, "round3", 1, 1)
    assert res.ok and len(s.requests) == 2
    assert json.loads((ctx.rd / "gen_1" / "restatement_2.json").read_text()) == {"claim": "x"}
    second = s.requests[1]["messages"]
    assert [m["role"] for m in second] == ["system", "user"]            # a new conversation, not a resume
    assert "wrote no file" in second[-1]["content"] and "./restatement_2.json now" in second[-1]["content"]
    s2 = fake(lambda body, n: answer([]))
    (tmp_path / "b").mkdir()
    ctx2 = ctx_for(tmp_path / "b", cfg_for(s2.url))
    (ctx2.rd / "gen_1").mkdir()
    (ctx2.rd / "gen_1" / "idea_draft.json").write_text('{"Name": "n"}')
    res2 = RecipeExecutor().execute(ctx2, "B5", recipe, "round3", 1, 1)
    assert not res2.ok and len(s2.requests) == 2


def test_a_long_lookup_keeps_its_head_and_its_tail():
    from harness.executors import _clip
    text = "HEADER\n" + "x" * 50000 + "\nSUMMARY"
    out = _clip(text, 1000)
    assert out.startswith("HEADER") and out.endswith("SUMMARY") and "characters cut" in out and len(out) < 1100
    assert _clip("short", 1000) == "short"


# ------------------------------------------------------------------------------------------------- schema answers
def reply(obj: dict) -> tuple[int, dict]:
    return 200, {"model": "m", "message": {"role": "assistant", "content": json.dumps(obj)}, "done": True,
                 "done_reason": "stop", "prompt_eval_count": 100, "eval_count": 20}


def test_a_step_with_a_schema_is_decoded_as_that_object(tmp_path, fake):
    """The archived engine's fence: the file's own structure is the grammar, not a string inside {"files"}."""
    schema = {"type": "object", "properties": {"flat": {"type": "object"}}, "required": ["flat"]}
    s = fake(lambda body, n: reply({"answer": {"flat": {"Q1": ["a", "b", "c"]}}, "note": "filled"}))
    target = tmp_path / "_state" / "A1" / "strategy_fill.json"
    scope = FileScope(base=tmp_path, writes=[target], schema=schema)
    r = run_worker(cfg_for(s.url), task="Fill it", system="s", cwd=tmp_path, scope=scope)
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
    scope = FileScope(base=tmp_path, writes=[target], schema={"type": "object"})
    r = run_worker(cfg_for(s.url), task="t", system="s", cwd=tmp_path, scope=scope)
    assert r.ok and json.loads(target.read_text()) == {"summary": {"problem": "p"}}


def test_a_stream_cut_before_done_is_a_dropped_connection_not_an_answer(tmp_path, fake):
    """A proxy that closes a long answer leaves half a JSON object: it is retried as a transport failure, never parsed."""
    s = fake(lambda body, n: (200, {"model": "m", "message": {"role": "assistant", "content": '{"files": [{"pa'},
                                    "done": False}))
    res, content = ow.OllamaProvider(cfg_for(s.url)).chat([{"role": "user", "content": "x"}], timeout=30)
    assert not res.ok and res.error_category == "external_service" and "dropped" in res.error and content == ""


def test_a_revision_shows_a_file_again_only_where_a_tool_changed_it(tmp_path, fake):
    s = fake(lambda body, n: answer([(str(tmp_path / "x.md"), "# mine")]))
    scope = FileScope(base=tmp_path, writes=[tmp_path / "x.md"])
    r = run_worker(cfg_for(s.url), task="Write x.md", system="s", cwd=tmp_path, scope=scope)
    run_worker(cfg_for(s.url), task="fix it", system="s", cwd=tmp_path, scope=scope, resume=r.session_id)
    assert "as you wrote them" in s.user(1)
    (tmp_path / "x.md").write_text("# mine\nadded by a tool\n")
    run_worker(cfg_for(s.url), task="fix it", system="s", cwd=tmp_path, scope=scope, resume=r.session_id)
    assert "added by a tool" in s.user(2)


def test_a_revision_sends_only_the_latest_answer_in_full(tmp_path, fake):
    """Each answer writes the whole file again: the earlier ones are cut to a line, so revisions do not grow the prompt."""
    s = fake(lambda body, n: answer([(str(tmp_path / "x.md"), f"# version {n}")]))
    scope = FileScope(base=tmp_path, writes=[tmp_path / "x.md"])
    r = run_worker(cfg_for(s.url), task="Write x.md", system="s", cwd=tmp_path, scope=scope)
    for _ in range(2):
        run_worker(cfg_for(s.url), task="fix it", system="s", cwd=tmp_path, scope=scope, resume=r.session_id)
    said = [m["content"] for m in s.requests[-1]["messages"] if m["role"] == "assistant"]
    assert said[:-1] == [chat.SUPERSEDED] and "version" in said[-1]
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
    r = run_worker(cfg_for(s.url), task="Write x.md from this: " + "words " * 50, system="# Unit X\n", cwd=tmp_path,
                   scope=FileScope(base=tmp_path, writes=[tmp_path / "x.md"]), say=said.append)
    assert r.ok, r.error
    assert [q["options"]["num_predict"] for q in s.requests] == [1, 1, 16384]
    assert s.requests[0]["messages"] == s.requests[2]["messages"]       # the probe reads the call's own prompt
    assert said and "cache" in said[0]


def test_a_short_prompt_is_sent_at_once(tmp_path, fake):
    s = fake(lambda body, n: answer([("x.md", "ok")]))
    r = run_worker(cfg_for(s.url), task="Write x.md", system="# Unit X\n", cwd=tmp_path,
                   scope=FileScope(base=tmp_path, writes=[tmp_path / "x.md"]))
    assert r.ok and [q["options"]["num_predict"] for q in s.requests] == [16384]


def test_a_silent_server_is_a_timeout_named_as_a_silence(tmp_path, fake, monkeypatch):
    """A server that takes the request and sends nothing (busy, reloading) hits the read limit, not the call's limit."""
    import time
    monkeypatch.setattr(ow, "STREAM_IDLE_S", 0.3)
    s = fake(lambda body, n: (time.sleep(1.0), answer([("x.md", "x")]))[1])
    res, _ = ow.OllamaProvider(cfg_for(s.url)).chat([{"role": "user", "content": "x"}], timeout=30)
    assert not res.ok and res.error_category == "timeout" and "silent for 0s" in res.error and "within 30" not in res.error


def test_a_worker_writes_only_the_scratch_its_unit_declares(tmp_path):
    """The ledger refuses a done for a file outside the Unit's declared files: the worker is held to the same list."""
    from harness.executors import RecipeExecutor
    ctx = ctx_for(tmp_path, cfg_for("http://localhost:1"))
    globs = RecipeExecutor._scratch(ctx, "B3.5")
    assert globs == ["knowledge/_work/B35/**", "_state/harness/decisions/**"]
    scope = FileScope(base=tmp_path, globs=globs)
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
