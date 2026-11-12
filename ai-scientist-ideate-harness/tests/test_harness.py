"""The code conductor (harness/): recipes, the skill boundary, providers, the shell, steps, loops and whole dry runs."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from harness import providers
from harness import recipes as rcp
from harness.cli import main as cli
from harness.config import HarnessConfig
from harness.context import RunContext
from harness.executors import RecipeExecutor
from harness.providers import (PROVIDERS, ClaudeProvider, OllamaProvider, Provider, WorkerRequest, WorkerResult,
                               provider_class, register)
from harness.providers.agent import AGENT_RULES, AgentProvider
from harness.providers.base import rules_text
from harness.providers.chat import CHAT_RULES
from harness.recipes import parse
from harness.shell import UnitAgent
from harness.skill import CommandResult, Skill, Subs, classify_failure, parse_findings
from ideate_v2.registry import Registry

MODULE = Path(__file__).resolve().parent.parent
TOPIC = MODULE / "evals" / "datasets" / "fusion_ready" / "eeg_topic.md"


# --------------------------------------------------------------------------------------------- recipes
def test_every_unit_has_a_valid_recipe(reg):
    found = rcp.validate(rcp.load(), reg)
    assert not [f for f in found if f["level"] == "ERROR"], found
    assert set(rcp.load()) == set(reg.units)


def test_recipe_validation_catches_kind_and_command_mistakes(reg):
    bad = parse({"recipes": [
        {"unit": "A2.s", "scope": "topic", "phases": {"main": [{"write": {"task": "t", "writes": ["x"]}}]}},
        {"unit": "A3", "scope": "topic", "phases": {"main": [{"run": "rm -rf $RD"}]}},
        {"unit": "P1", "scope": "topic", "phases": {"main": [{"write": {"task": "$NOPE", "writes": ["x"]}}]}}]})
    codes = {(f["unit"], f["code"]) for f in rcp.validate({r.unit: r for r in bad}, reg)}
    assert ("A2.s", "R-KIND") in codes and ("A3", "R-COMMAND") in codes and ("A3", "R-KIND") in codes
    assert ("P1", "R-SCOPE") in codes and ("P1", "R-PLACEHOLDER") in codes


def test_rules_sections_are_extracted():
    a1p = rules_text(MODULE, "references/search/A1-frame.md#a1p")
    assert a1p.startswith("## A1.p") and "## A1.q" not in a1p
    a6d = rules_text(MODULE, "references/scholar-pipeline.md#a6d")       # an anchor inside a paragraph
    assert a6d.startswith('<a id="a6d"></a>') and 'id="a6c"' not in a6d
    assert rules_text(MODULE, "references/planning/P3-decision-tree.md").startswith("# P3")


def test_a_heading_inside_a_code_block_does_not_end_the_section(tmp_path):
    (tmp_path / "r.md").write_text('<a id="x"></a>\n## X\n\n```bash\ncmd one\n#   a bash comment\ncmd two\n```\n\n'
                                   '~~~markdown\n## a template heading\n```json\n{}\n```\n## still the template\n~~~\n\n'
                                   'tail of X\n\n## Y\nnot X\n')
    x = rules_text(tmp_path, "r.md#x")
    assert "cmd two" in x and "still the template" in x and x.endswith("tail of X") and "not X" not in x
    a1q = rules_text(MODULE, "references/search/A1-frame.md#a1q")    # its Commands block has `#   {...}` lines
    assert "frame anchors-revise" in a1q and "## A1.v" not in a1q


# --------------------------------------------------------------------------------------------- skill
def test_expand_quotes_paths_with_spaces_and_apostrophes(tmp_path):
    rd = tmp_path / "Justin's Master" / "x_research"
    skill = Skill(HarnessConfig())
    line = skill.expand("ideate_tools.py a2-check $RD", Subs(rd))
    argv = skill.argv(line)
    assert argv[-1] == str(rd) and argv[1].endswith("scripts/ideate_tools.py")
    assert skill.expand("$RD/x.json", Subs(rd), quote=False) == f"{rd}/x.json"
    with pytest.raises(ValueError):
        skill.argv("rm -rf /")


def test_failures_are_classified():
    assert classify_failure("HTTP 429 Too Many Requests") == "external_service"
    assert classify_failure("ModuleNotFoundError: No module named 'mcp'") == "environment"
    assert classify_failure("error: run `frame set-protocol` first") == "input_contract"
    assert classify_failure("Traceback (most recent call last):\n  ...\nKeyError: 'x'") == "tool_invocation"


def test_findings_are_parsed_from_both_shapes():
    assert parse_findings('noise\n[{"level": "error", "code": "C05", "msg": "m", "unit": "A3"}]')[0] == \
        {"level": "ERROR", "code": "C05", "message": "m", "unit": "A3"}
    assert parse_findings('{"findings": [{"level": "WARN", "code": "C1", "message": "w"}]}')[0]["level"] == "WARN"
    assert parse_findings("no json here") is None


# --------------------------------------------------------------------------------------------- dry runs
def _dry(tmp_path, *extra, gens=1) -> tuple[int, dict, Path]:
    d = tmp_path / "topic dir"
    d.mkdir(exist_ok=True)
    topic = d / "eeg_topic.md"
    shutil.copy(TOPIC, topic)
    code = cli(["run", str(topic), "--dry-run", "--generations", str(gens), "--json", *extra])
    rd = d / "eeg_topic_research"
    run_id = json.loads((rd / "_state" / "errors" / "latest.json").read_text())["run_id"]
    summary = json.loads((rd / "_state" / "harness" / run_id / "summary.json").read_text())
    return code, summary, rd


def _units(summary, unit):
    return [u for u in summary["units"] if u["unit"] == unit]


def test_dry_run_end_to_end(tmp_path, capsys):
    code, s, rd = _dry(tmp_path, gens=2)
    assert code == 0 and not s["failed"] and s["status"] == "degraded"          # the fixture's caveats
    assert [g["status"] for g in s["generations"]] == ["finalized", "finalized"]
    assert all(g["passed"] for g in s["gates"]) and len(s["gates"]) == 9 + 2 * 6
    assert {u["unit"] for u in s["units"]} == set(Registry.load().units)       # every Unit ran as an agent
    assert len(_units(s, "A3")) == 2                                            # LOOP-04: re-screened after A5
    assert set(s["must_disclose"]) >= {"accept-weak", "questions-short"}
    ideas = json.loads((rd.parent / "eeg_topic.json").read_text())
    assert len(ideas) == 2 and (rd / "ERRORS.md").is_file()
    assert (rd / "_state" / "errors" / s["run_id"] / "events.jsonl").is_file()


def test_resume_skips_done_units(tmp_path):
    _dry(tmp_path)
    code, s, _ = _dry(tmp_path, "--to", "F4")
    assert code == 0 and all(u["status"] == "skipped" for u in s["units"])


def test_transient_failure_is_retried_by_the_orchestrator(tmp_path):
    code, s, _ = _dry(tmp_path, "--to", "S2", "--inject", "A2.s=external_service")
    a2s = _units(s, "A2.s")[0]
    assert code == 0 and a2s["status"] == "done" and a2s["attempts"] == 2
    assert not s["root_causes"]                                                 # the retry superseded it


def test_exhausted_failure_propagates_to_one_root_cause(tmp_path):
    code, s, rd = _dry(tmp_path, "--to", "S2", "--inject", "A2.s=external_service,external_service")
    assert code == 1 and _units(s, "A2.m")[0]["status"] == "stopped"
    assert [r["origin"] for r in s["root_causes"]] == ["A2.s@-"]
    rec = json.loads(next((rd / "_state" / "errors" / s["run_id"] / "units").glob("A2.m*.jsonl")).read_text()
                     .splitlines()[0])
    out = json.loads(_trace(rd, rec["error_id"]))
    assert out["root_cause"]["unit_id"] == "A2.s" and "A2.m" in out["downstream_units"]


def _trace(rd, eid):
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert cli(["trace", str(rd), eid]) == 0
    return buf.getvalue()


def test_check_failure_is_not_retried(tmp_path):
    code, s, _ = _dry(tmp_path, "--to", "S3", "--inject", "A3=check:C05")
    a3 = _units(s, "A3")[0]
    assert code == 1 and a3["status"] == "failed" and a3["attempts"] == 1 and a3["errors"] == ["A3:C05"]


def test_a_failed_gate_stops_the_run(tmp_path):
    code, s, _ = _dry(tmp_path, "--inject", "GATE-a2-check=fail")
    assert code == 1 and s["steps"][-1] == {"step": "STEP-S2", "instance": "-", "status": "failed",
                                            "stopped_by": s["steps"][-1]["stopped_by"]}
    assert not _units(s, "A3")


def test_round2_revision_reenters_planning(tmp_path):
    code, s, _ = _dry(tmp_path, "--inject", "B5=revise:P2")
    assert code == 0 and len(_units(s, "P2")) == 2 and len(_units(s, "P3")) == 2 and len(_units(s, "P1")) == 1
    assert len(_units(s, "P4")) == 2 and len(_units(s, "P5")) == 2             # round 3: P4, P5 again


def test_a_rerun_after_a_failed_round_3_starts_at_round_3(tmp_path):
    """A failed B5 round is the only one run again: rounds 1 and 2 (and the revision) are not repeated while the
    design is as they left it - and a change to it starts the rounds over."""
    code, s, rd = _dry(tmp_path, "--inject", "B5=revise:P2", "--inject", "B5/round3=model_output")
    assert code == 1
    assert {u["instance"] for u in _units(s, "B5")} >= {"gen_1/round1", "gen_1/round2", "gen_1/round3"}
    prog = json.loads((rd / "_state" / "harness" / "decisions" / "gen_1" / "B5.progress.json").read_text())
    assert prog["stages"] == ["round1", "round2", "revised"]
    code, s, _ = _dry(tmp_path)
    assert code == 0 and s["generations"][0]["status"] == "finalized"
    assert [u["instance"] for u in _units(s, "B5")][:1] == ["gen_1/round3"]
    assert not _units(s, "P2") and not _units(s, "P4")                         # the revision is not repeated


def test_a_changed_design_starts_the_rounds_over(tmp_path):
    code, s, rd = _dry(tmp_path, "--inject", "B5/round3=model_output")
    assert code == 1
    arg = rd / "gen_1" / "argument.json"
    arg.write_text(arg.read_text().rstrip() + "\n\n")                         # the design changed since round 2
    code, s, _ = _dry(tmp_path)
    ran = [u["instance"] for u in _units(s, "B5") if u["status"] != "skipped"]
    assert code == 0 and "gen_1/round2" in ran and "gen_1/round3" in ran        # round 1: its own unit resume


def test_a_rerun_resumes_a_failed_forced_revision(tmp_path):
    """The forced revision after a failed coherence gate changes the design itself: a re-run after a failure in it
    resumes it - rounds 1 to 3 are not repeated for the changes it made."""
    code, s, rd = _dry(tmp_path, "--inject", "GATE-coherence=fail",
                       "--inject", "P2=finalize,model_output,model_output,model_output")
    assert code == 1
    prog = json.loads((rd / "_state" / "harness" / "decisions" / "gen_1" / "B5.progress.json").read_text())
    assert prog["stages"][-1] == "forcing"
    (rd / "gen_1" / "argument.json").write_text((rd / "gen_1" / "argument.json").read_text() + "\n")  # its change
    code, s, _ = _dry(tmp_path, "--inject", "GATE-coherence=fail")
    ran = [u["instance"] for u in _units(s, "B5") if u["status"] != "skipped"]
    assert code == 0 and s["generations"][0]["status"] == "finalized"
    assert "gen_1/round1" not in ran and "gen_1/round2" not in ran and ran[0] == "gen_1/round3"


def test_a_question_taken_by_a_generation_is_not_left(tmp_path):
    """question-take writes the question's id as "question" (the dry run's fixture says "id"): either counts as taken,
    so LOOP-11 and LOOP-12 see what is really left."""
    from harness import loops
    rd = tmp_path / "t_research"
    (rd / "questions").mkdir(parents=True)
    (rd / "questions" / "index.json").write_text(json.dumps({"questions": [
        {"id": "Q_001", "status": "ready"}, {"id": "Q_002", "status": "ready"}, {"id": "Q_003", "status": "ready"}]}))
    (rd / "gen_1").mkdir()
    (rd / "gen_1" / "question.json").write_text(json.dumps({"question": "Q_002", "gap": "GAP_002"}))
    (rd / "gen_2").mkdir()
    (rd / "gen_2" / "question.json").write_text(json.dumps({"id": "Q_001"}))
    assert loops.ready_questions_left(rd) == ["Q_003"]


def test_only_the_decision_gate_counts_as_a_failed_tree():
    """LOOP-11 abandons a question for T09 (or the weak-mass rule) - not for another tree finding such as T14."""
    from harness.skill import COHERENCE, CommandResult
    from harness.steps import GateResult

    def gate(out):
        r = CommandResult("ideate_tools.py tree-check gen_1", [], 1, out)
        r.command_template = COHERENCE[1]
        return GateResult("GATE-coherence", "gen_1", False, {"findings": []}, [r])
    assert gate("ERROR T09: decision gate: the likeliest outcome is a weak one\n").tree_failed
    t14 = gate("ERROR T14: publishable leaves ['L2'] of the round-1 tree are gone\n")
    assert not t14.tree_failed and t14.failing_steps() == ["P3"]
    weak = GateResult("GATE-coherence", "gen_1", False, {"findings": [
        {"level": "ERROR", "code": "GATE.RULE.decision_tree_weak_mass", "message": "x"}]}, [])
    assert weak.tree_failed


def test_coherence_failure_gets_one_forced_revision(tmp_path):
    code, s, _ = _dry(tmp_path, "--inject", "GATE-coherence=fail")
    assert code == 0 and s["generations"][0]["status"] == "finalized"
    coh = [g for g in s["gates"] if g["gate"] == "GATE-coherence"]
    assert [g["passed"] for g in coh] == [False, True]
    assert s["status"] != "failed" and not s["root_causes"]      # the forced revision answered the first failure


def test_decision_gate_abandons_the_question_and_the_next_one_is_taken(tmp_path):
    code, s, rd = _dry(tmp_path, "--inject", "GATE-coherence=fail,fail", gens=1)
    assert [g["status"] for g in s["generations"]] == ["abandoned", "finalized"]
    assert [g["question"] for g in s["generations"]] == ["Q_001", "Q_002"]
    assert len(json.loads((rd.parent / "eeg_topic.json").read_text())) == 1
    assert s["status"] != "failed" and not s["root_causes"]      # an abandonment resolves the gate's failure


def test_last_question_is_finalized_with_the_doubt_disclosed(tmp_path):
    code, s, _ = _dry(tmp_path, "--inject", "GATE-coherence=" + ",".join(["fail"] * 6), gens=1)
    assert [g["status"] for g in s["generations"]] == ["abandoned", "abandoned", "finalized-with-doubt"]
    assert "uninformative-branch" in s["must_disclose"]
    assert s["status"] == "degraded"                              # waived and disclosed: degraded, not failed


# --------------------------------------------------------------------------------------------- providers
class EchoProvider(Provider):
    """A provider of one's own, as small as the interface allows: it writes every file its scope names."""
    name = "echo"

    def __init__(self, cfg, state_dir=None):
        super().__init__(cfg, state_dir)
        self.requests: list[WorkerRequest] = []
        self.fail_first = 0                              # calls that fail in transport before one goes through

    def run(self, req: WorkerRequest) -> WorkerResult:
        self.requests.append(req)
        if len(self.requests) <= self.fail_first:
            return WorkerResult(False, error="HTTP 503", error_category="external_service")
        for w in req.scope.writes:
            w.parent.mkdir(parents=True, exist_ok=True)
            w.write_text(json.dumps({"by": self.name}))
        return WorkerResult(True, text="wrote", session_id=f"e-{len(self.requests)}", tokens_in=3, tokens_out=2)

    def retry_delay(self, ctx, wr, attempt, error_id):
        return 0.0 if attempt == 1 else None


class ShimAgent(AgentProvider):
    """An agent of one's own (none is built in): it runs nothing, but asks for the shims an agent runs the skill
    commands through."""
    name = "shim-agent"

    def run(self, req: WorkerRequest) -> WorkerResult:
        return WorkerResult(True, text=str(self.bin_dir()))


def _ctx(tmp_path, worker: str = "claude") -> RunContext:
    cfg = HarnessConfig(worker=worker)
    rd = tmp_path / "t_research"
    rd.mkdir(exist_ok=True)
    return RunContext(Registry.load(), cfg, Skill(cfg), rd, tmp_path / "t.md", say=lambda s: None)


def _echo_ctx(tmp_path, monkeypatch) -> RunContext:
    """A run whose provider writes every file its scope names, and whose lookups run nothing for real."""
    monkeypatch.setitem(PROVIDERS, "echo", EchoProvider)
    ctx = _ctx(tmp_path, "echo")
    monkeypatch.setattr(ctx.skill, "run", lambda cmd, subs, timeout=None: CommandResult(cmd, [], 0, ""))
    return ctx


def test_the_worker_names_a_provider_from_the_registry_or_an_import_path(monkeypatch):
    assert provider_class("claude") is ClaudeProvider and provider_class("ollama") is OllamaProvider
    assert HarnessConfig(worker="harness.providers.claude:ClaudeProvider").provider_class() is ClaudeProvider
    for bad in ("nope", "claude-code", "harness.providers.base:WorkerResult", "no_such_module:X"):
        with pytest.raises(ValueError):
            HarnessConfig(worker=bad)
    monkeypatch.setattr(providers, "PROVIDERS", dict(PROVIDERS))
    register(EchoProvider)
    assert HarnessConfig(worker="echo").provider_class() is EchoProvider


def test_the_provider_sets_the_fan_out_width_and_the_batch_size(monkeypatch):
    monkeypatch.setitem(PROVIDERS, "shim-agent", ShimAgent)
    claude, ollama = HarnessConfig(max_parallel=4), HarnessConfig(worker="ollama", model="m", max_parallel=4)
    agent = HarnessConfig(worker="shim-agent", max_parallel=4)
    assert (agent.parallel(), agent.batch_budget()) == (4, 0)          # an agent reads its batch itself
    assert (claude.parallel(), claude.batch_budget(), claude.file_chars()) == (4, 40000, 1_500_000)   # a 1M window
    assert (ollama.parallel(), ollama.batch_budget(), ollama.file_chars()) == (1, 40000, 98304)
    assert HarnessConfig(worker="ollama", model="m", num_ctx=8192).batch_budget() == 9830     # 40% of the window
    assert HarnessConfig(batch_chars=5000).batch_budget() == 5000                         # the config's own wins


def test_each_kind_of_provider_gets_its_rules_and_the_commands_it_can_run(reg, tmp_path):
    cmds = ["ideate_tools.py list-papers", "mcp_bridge.py search"]
    shim_agent = ShimAgent(HarnessConfig(), tmp_path / "state")
    agent = shim_agent.system_prompt(MODULE, reg.units["A3"], None, [], cmds)
    chat = OllamaProvider(HarnessConfig(worker="ollama", model="m")).system_prompt(MODULE, reg.units["A3"], None, [],
                                                                                  cmds)
    assert ClaudeProvider(HarnessConfig()).system_prompt(MODULE, reg.units["A3"], None, [], cmds) == chat   # same kind
    assert agent.startswith(AGENT_RULES) and "- `ideate-tool list-papers`" in agent and "- `ideate-bridge search`" in agent
    assert chat.startswith(CHAT_RULES) and "Commands you may run" not in chat
    assert agent[len(AGENT_RULES):].startswith(chat[len(CHAT_RULES):])            # the Unit's part is the same
    assert not (tmp_path / "state").exists()                                     # made without a trace
    shim_agent.run(WorkerRequest(task="t", system="s", cwd=tmp_path))
    assert (tmp_path / "state" / "bin" / "ideate-tool").is_file()                 # the shims, on its first call


def test_each_provider_owns_its_transport_wait(tmp_path):
    ctx = _ctx(tmp_path)
    wr = WorkerResult(False, error="HTTP 503", error_category="external_service")
    first = ctx.provider.retry_delay(ctx, wr, 1, "B6:x")              # the Claude API: the contract's RP-TRANSPORT,
    assert first is not None and 0 <= first <= 30 and ctx.provider.retry_delay(ctx, wr, 2, "B6:x") is None  # 2 tries
    ollama = OllamaProvider(HarnessConfig(worker="ollama", model="m", ollama_busy_wait_s=120, ollama_busy_retries=4))
    assert [ollama.retry_delay(ctx, wr, a, "B6:x") for a in (1, 2, 3, 4, 5)] == [120, 240, 480, 900, None]


def test_a_provider_of_ones_own_drives_the_executor(tmp_path, monkeypatch):
    """The executor speaks only the interface: a registered provider does a write step - with the lookups a worker
    without commands is given, its own settings, and its own transport wait."""
    monkeypatch.setitem(PROVIDERS, "echo", EchoProvider)
    cfg = HarnessConfig(worker="echo", provider_options={"echo": {"greeting": "hi"}})
    rd = tmp_path / "t_research"
    rd.mkdir()
    ctx = RunContext(Registry.load(), cfg, Skill(cfg), rd, tmp_path / "t.md", say=lambda s: None)
    assert isinstance(ctx.provider, EchoProvider) and ctx.provider.options() == {"greeting": "hi"}
    ctx.provider.fail_first = 1
    ran = []
    monkeypatch.setattr(ctx.skill, "run", lambda cmd, subs, timeout=None: ran.append(cmd) or
                        CommandResult(cmd, [], 0, "paper_001 Label smoothing\n"))
    target = rd / "notes.json"
    recipe = parse({"recipes": [{"unit": "B6", "scope": "generation", "phases": {"main": [
        {"write": {"task": "Write the notes", "writes": [str(target)], "rules": [],
                   "commands": ["ideate_tools.py list-papers"]}}]}}]})[0]
    res = RecipeExecutor().execute(ctx, "B6", recipe, "main", 1, 1)
    assert res.ok, res.errors
    assert json.loads(target.read_text()) == {"by": "echo"}
    first, again = ctx.provider.requests
    assert first.label.endswith(".a1") and again.label.endswith(".a2")       # sent again after its own wait
    assert first.scope.writes == [target] and first.commands == ["ideate_tools.py list-papers"]
    assert ran == ["ideate_tools.py list-papers $RD --file shortlist --slice 0:80 --abstract-chars 160"]     # it runs no commands: the conductor did
    assert "paper_001" in first.scope.lookups[0][1] and "Commands you may run" not in first.system
    assert ctx.usage["calls"] == 2 and ctx.usage["tokens_in"] == 3


def test_fanout_answers_every_batch(tmp_path, monkeypatch):
    ctx = _echo_ctx(tmp_path, monkeypatch)
    fan = ctx.rd / "_state" / "fanout" / "A3"
    fan.mkdir(parents=True)
    (fan / "brief.md").write_text("brief")
    for k in (1, 2, 3):
        (fan / f"batch_{k:02d}.in.json").write_text(json.dumps({"batch": k, "out": f"batch_{k:02d}.out.json"}))
    (fan / "batch_02.out.json").write_text("{}")                                # answered before: not re-dispatched
    recipe = rcp.load()["A3"]
    fanout = next(s for s in recipe.steps("main") if s.kind == "fanout")
    one = parse({"recipes": [{"unit": "A3", "phases": {"main": [fanout.spec]}}]})[0]
    res = RecipeExecutor().execute(ctx, "A3", one, "main", None, 1)
    assert res.ok and all((fan / f"batch_{k:02d}.out.json").is_file() for k in (1, 2, 3))
    assert len(ctx.provider.requests) == 2


def test_a_fanout_task_may_spell_out_a_json_shape(tmp_path, monkeypatch):
    """A7.A2's task names its answer as {unit id: {axis: [concept ids]}}: only {batch} {out} {brief} are filled in."""
    ctx = _echo_ctx(tmp_path, monkeypatch)
    wd = ctx.rd / "knowledge" / "_work" / "A7A"
    wd.mkdir(parents=True)
    (wd / "coord_batch_001.json").write_text(json.dumps({"answer": "knowledge/_work/A7A/canswers/coord_batch_001.json"}))
    fanout = next(s for s in rcp.load()["A7.A2"].steps("main") if s.kind == "fanout")
    one = parse({"recipes": [{"unit": "A7.A2", "phases": {"main": [fanout.spec]}}]})[0]
    res = RecipeExecutor().execute(ctx, "A7.A2", one, "main", None, 1)   # the echo answers nothing valid: no matter
    assert "IDEATE.INTERNAL" not in [e.error_code for e in res.errors]
    assert ctx.provider.requests[0].task.startswith(f"Read the batch {wd / 'coord_batch_001.json'}: ")


def test_a_custom_agent_still_goes_through_the_shell(tmp_path):
    """A swapped-in executor that writes nothing fails the Unit's output contract."""
    class Lazy:
        def execute(self, ctx, unit, recipe, phase, gen, attempt):
            from harness.executors import ExecResult
            return ExecResult(True)
    ctx = _ctx(tmp_path)
    r = UnitAgent("A1.p", rcp.load()["A1.p"], Lazy()).run(ctx, force=True)
    assert r.status == "failed" and "IDEATE.UNIT.OUTPUT_MISSING" in [e.error_code for e in r.errors]


def test_a_refused_a1e_waits_on_loop02(tmp_path):
    """A1.e's own check refuses (E04) while the revision its round asked for is not made: the step runs LOOP-02
    instead of failing - as A2.c's re-plan runs LOOP-01. set-evaluation marks such a round `pending-revision`."""
    from harness import loops
    from harness.steps import StepAgent
    ctx = _ctx(tmp_path)
    (ctx.rd / "step1_protocol_evaluation.json").write_text(json.dumps({
        "rounds": [{"round": 1, "verdict": "revision-required"}], "final": {"status": "pending-revision"}}))
    assert loops.protocol_verdict(ctx.rd) == (1, "revision-required")
    step = StepAgent("STEP-S1", {})
    assert step._pending_loop(ctx, "A1.e") == step._loop02
    assert step._pending_loop(ctx, "A1.p") is None
    (ctx.rd / "step1_protocol_evaluation.json").write_text(json.dumps({
        "rounds": [{"round": 2, "verdict": "revision-required"}], "final": {"status": "accepted-with-doubts"}}))
    assert step._pending_loop(ctx, "A1.e") is None                 # round 2 settles it: no further loop


def test_loop01_reads_the_new_share_of_the_latest_re_plan_round(tmp_path):
    """LOOP-01's min_new_share condition refuses a missing measurement: the conductor reads it from search-check."""
    from harness import loops
    d = tmp_path / "_state" / "A2c"
    d.mkdir(parents=True)
    assert loops.replan_new_share(tmp_path) is None
    (d / "signals_r0.json").write_text('{"latest_round": 0}')
    (d / "signals_r10.json").write_text('{"new_share_latest_round": 0.02}')
    (d / "signals_r2.json").write_text('{"new_share_latest_round": 0.4762}')
    assert loops.replan_new_share(tmp_path) == 0.02
