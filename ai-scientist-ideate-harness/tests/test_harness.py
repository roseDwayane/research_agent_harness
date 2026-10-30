"""The code conductor (harness/): recipes, the skill boundary, workers, the shell, steps, loops and whole dry runs."""
from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from harness import claude_worker as cw
from harness import recipes as rcp
from harness.cli import main as cli
from harness.config import HarnessConfig
from harness.context import RunContext
from harness.executors import RecipeExecutor
from harness.recipes import parse
from harness.shell import UnitAgent
from harness.skill import Skill, Subs, classify_failure, parse_findings
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
    a1p = cw.rules_text(MODULE, "references/search/A1-frame.md#a1p")
    assert a1p.startswith("## A1.p") and "## A1.q" not in a1p
    a6d = cw.rules_text(MODULE, "references/scholar-pipeline.md#a6d")       # an anchor inside a paragraph
    assert a6d.startswith('<a id="a6d"></a>') and 'id="a6c"' not in a6d
    assert cw.rules_text(MODULE, "references/planning/P3-decision-tree.md").startswith("# P3")


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


def test_coherence_failure_gets_one_forced_revision(tmp_path):
    code, s, _ = _dry(tmp_path, "--inject", "GATE-coherence=fail")
    assert code == 0 and s["generations"][0]["status"] == "finalized"
    coh = [g for g in s["gates"] if g["gate"] == "GATE-coherence"]
    assert [g["passed"] for g in coh] == [False, True]


def test_decision_gate_abandons_the_question_and_the_next_one_is_taken(tmp_path):
    code, s, rd = _dry(tmp_path, "--inject", "GATE-coherence=fail,fail", gens=1)
    assert [g["status"] for g in s["generations"]] == ["abandoned", "finalized"]
    assert [g["question"] for g in s["generations"]] == ["Q_001", "Q_002"]
    assert len(json.loads((rd.parent / "eeg_topic.json").read_text())) == 1


def test_last_question_is_finalized_with_the_doubt_disclosed(tmp_path):
    code, s, _ = _dry(tmp_path, "--inject", "GATE-coherence=" + ",".join(["fail"] * 6), gens=1)
    assert [g["status"] for g in s["generations"]] == ["abandoned", "abandoned", "finalized-with-doubt"]
    assert "uninformative-branch" in s["must_disclose"]


# --------------------------------------------------------------------------------------------- workers
FAKE_CLAUDE = r'''#!/usr/bin/env python3
"""A stand-in for `claude -p`: writes what the task asks for, answers in the CLI's JSON format."""
import json, os, re, sys
args = sys.argv[1:]
task = args[args.index("-p") + 1]
resume = args[args.index("--resume") + 1] if "--resume" in args else None
log = os.environ["FAKE_CLAUDE_LOG"]
with open(log, "a") as f:
    f.write(json.dumps({{"task": task[:200], "resume": resume, "cwd": os.getcwd(), "args": args}}) + "\n")
for path in re.findall(r"; write (\S+\.json)", task):               # fan-out: "Read ...; write <out>."
    open(path.rstrip("."), "w").write(json.dumps({{"answer": "ok"}}))
target = os.environ.get("FAKE_CLAUDE_TARGET")
if target:
    good = resume is not None or os.environ.get("FAKE_CLAUDE_GOOD") == "1"
    open(target, "w").write(json.dumps(os.environ["FAKE_CLAUDE_IDEA"] and [json.loads(os.environ["FAKE_CLAUDE_IDEA"])]
                                       if good else [{{"Name": "Bad Name"}}]))
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": "done", "session_id": "s-1",
                  "total_cost_usd": 0.01, "num_turns": 2, "duration_ms": 5,
                  "usage": {{"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 0}}}}))
'''

IDEA = {"Name": "fake_idea", "Title": "A title", "Short Hypothesis": "H", "Related Work": "RW",
        "Abstract": " ".join(["word"] * 200), "Experiments": ["E1 [tests C1] x"], "Risk Factors and Limitations": ["r"]}


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    exe = tmp_path / "bin" / "claude"
    exe.parent.mkdir()
    exe.write_text(FAKE_CLAUDE.format())
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "claude_log.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("FAKE_CLAUDE_IDEA", json.dumps(IDEA))
    return exe, log


def _ctx(tmp_path, exe) -> RunContext:
    cfg = HarnessConfig(claude=str(exe))
    rd = tmp_path / "t_research"
    rd.mkdir(exist_ok=True)
    return RunContext(Registry.load(), cfg, Skill(cfg), rd, tmp_path / "t.md", say=lambda s: None)


def test_worker_result_is_parsed_and_costed(tmp_path, fake_claude):
    exe, log = fake_claude
    ctx = _ctx(tmp_path, exe)
    wr = cw.run_worker(ctx.cfg, task="say hi", system="rules", cwd=ctx.rd, allowed=["Bash(ideate-tool list-papers:*)"],
                       add_dirs=[], deny_read=[ctx.rd / "step3_bibliometrics.json"], budget_usd=1.5,
                       bin_dir=cw.write_shims(ctx.state_dir / "bin", ctx.cfg), log_dir=ctx.state_dir)
    assert wr.ok and wr.session_id == "s-1" and wr.tokens_in == 100 and wr.cost_usd == 0.01
    args = json.loads(log.read_text().splitlines()[0])["args"]
    assert "--max-budget-usd" in args and any(a.startswith("Read(") and "bibliometrics" in a for a in args)
    assert (ctx.state_dir / "bin" / "ideate-tool").is_file()


def test_a_refused_submission_goes_back_to_the_same_session(tmp_path, fake_claude):
    """write -> `validate` refuses the bad idea list -> feedback with --resume -> fixed -> validate passes."""
    exe, log = fake_claude
    ctx = _ctx(tmp_path, exe)
    target = tmp_path / "ideas.json"
    os.environ["FAKE_CLAUDE_TARGET"] = str(target)
    os.environ["FAKE_CLAUDE_GOOD"] = "0"
    try:
        recipe = parse({"recipes": [{"unit": "B6", "scope": "generation", "phases": {"main": [
            {"write": {"task": "Write the ideas list", "writes": [str(target)], "rules": []}},
            {"run": f"ideate_tools.py validate {target}", "submit": True}]}}]})[0]
        res = RecipeExecutor().execute(ctx, "B6", recipe, "main", 1, 1)
    finally:
        os.environ.pop("FAKE_CLAUDE_TARGET")
        os.environ.pop("FAKE_CLAUDE_GOOD")
    calls = [json.loads(x) for x in log.read_text().splitlines()]
    assert res.ok, res.errors
    assert len(calls) == 2 and calls[0]["resume"] is None and calls[1]["resume"] == "s-1"
    assert "refused them" in calls[1]["task"]
    assert json.loads(target.read_text())[0]["Name"] == "fake_idea"


def test_fanout_answers_every_batch(tmp_path, fake_claude):
    exe, log = fake_claude
    ctx = _ctx(tmp_path, exe)
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
    assert len(log.read_text().splitlines()) == 2


def test_a_custom_agent_still_goes_through_the_shell(tmp_path):
    """A swapped-in executor that writes nothing fails the Unit's output contract."""
    class Lazy:
        def execute(self, ctx, unit, recipe, phase, gen, attempt):
            from harness.executors import ExecResult
            return ExecResult(True)
    ctx = _ctx(tmp_path, "claude")
    r = UnitAgent("A1.p", rcp.load()["A1.p"], Lazy()).run(ctx, force=True)
    assert r.status == "failed" and "IDEATE.UNIT.OUTPUT_MISSING" in [e.error_code for e in r.errors]
