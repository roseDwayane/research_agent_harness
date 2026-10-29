"""ideate-harness - run and inspect the ideate stage as a harness of Unit agents.

  ideate-harness run <topic.md> [--from S1] [--to B6] [--depth quick|standard|deep] [--generations N]
                                [--worker claude|ollama [--ollama-url URL --model NAME --num-ctx N]]
                                [--dry-run [--fixtures DIR] [--inject KEY=TOKEN,...]] [--replay]
                                [--agent UNIT=package.module:Class] [--config harness.toml] [--no-resume]
  ideate-harness status  <RD>                 every Unit's state (ledger + generations) and what runs next
  ideate-harness report  <RD> [--run-id R]    rebuild the three-level report and print ERRORS.md
  ideate-harness trace   <RD> <error_id | unit> [--run-id R]
  ideate-harness recipes [--json]             validate contracts/recipes/ against the contracts
  ideate-harness check   [--strict]           scripts/run_checks.py (contracts, docs, tests, evals, lint)

<RD> is <topic>_research/ next to the topic file. A run's records: <RD>/_state/errors/<run_id>/, <RD>/ERRORS.md,
<RD>/_state/harness/<run_id>/ (summary.json, worker prompts and outputs, command logs).
"""
from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
from pathlib import Path

from ideate_v2.errors import IdeateError
from ideate_v2.jsonio import read_json
from ideate_v2.ledger import load_events, next_runnable, planning_status, unit_states
from ideate_v2.registry import Registry
from ideate_v2.report import build_report
from ideate_v2.trace import trace_error, trace_unit

from . import recipes as rcp
from .config import MODULE_ROOT, HarnessConfig
from .context import RunContext
from .executors import RecipeExecutor
from .fake import FakeExecutor, FakeSkill, FaultBook, parse_inject
from .pipeline import PipelineAgent, render_summary
from .skill import Skill


def _load_agent(spec: str):
    unit, _, target = spec.partition("=")
    mod, _, cls = target.partition(":")
    if not (unit and mod and cls):
        raise SystemExit(f"--agent {spec!r}: UNIT=package.module:Class")
    obj = getattr(importlib.import_module(mod), cls)
    return unit, obj() if isinstance(obj, type) else obj


def cmd_run(a) -> int:
    cfg = HarnessConfig.load(a.config, depth=a.depth, max_num_generations=a.generations,
                             num_reflections=a.reflections, python=a.python, claude=a.claude, model=a.model,
                             max_parallel=a.max_parallel, smoke_cap=a.smoke_cap, worker=a.worker,
                             ollama_url=a.ollama_url, num_ctx=a.num_ctx)
    cfg.dry_run, cfg.replay, cfg.resume = a.dry_run, a.replay, not a.no_resume
    if a.budget:
        cfg.default_budget_usd = a.budget
    cfg.inject = parse_inject(a.inject)
    if cfg.inject and not cfg.dry_run:
        raise SystemExit("--inject works only with --dry-run")
    if a.fixtures:
        cfg.fixtures = Path(a.fixtures)
    topic = Path(a.topic).expanduser().resolve()
    if not topic.is_file() and not cfg.dry_run:
        raise SystemExit(f"topic file not found: {topic}")
    rd = Path(a.research_dir).expanduser().resolve() if a.research_dir else topic.with_name(topic.stem + "_research")
    rd.mkdir(parents=True, exist_ok=True)
    reg = Registry.load()
    recipes = rcp.load()
    problems = [f for f in rcp.validate(recipes, reg) if f["level"] == "ERROR"]
    if problems and not cfg.dry_run:
        for f in problems[:20]:
            print(f"recipe ERROR {f['unit']}: {f['message']}", file=sys.stderr)
        raise SystemExit("fix the recipes first (ideate-harness recipes)")
    custom = dict(_load_agent(s) for s in a.agent or [])
    unknown = sorted(set(custom) - set(reg.units))
    if unknown:
        raise SystemExit(f"--agent for unknown Unit(s): {', '.join(unknown)}")
    if cfg.dry_run:
        faults = FaultBook(cfg.inject)
        skill = FakeSkill(cfg, faults)
        fx = cfg.fixtures
        fake = FakeExecutor(faults, topic_fixture=fx / "topic" if fx and (fx / "topic").is_dir() else fx,
                            gen_fixture=fx / "gen" if fx and (fx / "gen").is_dir() else None)
        default = fake
    else:
        skill = Skill(cfg)
        default = RecipeExecutor()
    ctx = RunContext(reg, cfg, skill, rd, topic)
    pipe = PipelineAgent(reg, recipes, lambda u: custom.get(u, default))
    try:
        summary = pipe.run(ctx, a.frm, a.to)
    except KeyboardInterrupt:
        ctx.emit("RUN_CANCELLED", message="interrupted from the keyboard")
        build_report(reg, rd, ctx.run_id)
        print(f"\ninterrupted: run {ctx.run_id}; resume with the same command (done Units are skipped)", file=sys.stderr)
        return 130
    print(json.dumps(summary, indent=1, ensure_ascii=False) if a.json else render_summary(summary))
    return 1 if summary["failed"] else 0


def _rd(path: str) -> Path:
    rd = Path(path).expanduser().resolve()
    if not rd.is_dir():
        raise SystemExit(f"not a directory: {rd}")
    return rd


def _latest_run(rd: Path) -> str | None:
    p = rd / "_state" / "errors" / "latest.json"
    return read_json(p).get("run_id") if p.is_file() else None


def cmd_status(a) -> int:
    reg, rd = Registry.load(), _rd(a.research_dir)
    events, problems = load_events(rd)
    states = unit_states(reg, rd, events)
    out = {"units": states, "next": next_runnable(reg, states), "ledger_problems": problems,
           "generations": [planning_status(rd, int(p.name[4:])) for p in sorted(rd.glob("gen_*"))
                           if p.name[4:].isdigit()], "latest_run": _latest_run(rd)}
    if a.json:
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return 0
    for sid in reg.step_order():
        us = [u for u in reg.get(sid)["units"] if u in states]
        if us:
            print(f"{sid:<10} " + "  ".join(f"{u}:{states[u]['state']}" for u in us))
    for g in out["generations"]:
        print(f"gen_{g['generation']:<6} " + "  ".join(f"{u}:{v['state']}" for u, v in g["units"].items()))
    print("next: " + (", ".join(f"{n['unit']} ({n['action']})" for n in out["next"]) or "nothing on the ledger"))
    return 0


def cmd_report(a) -> int:
    reg, rd = Registry.load(), _rd(a.research_dir)
    run_id = a.run_id or _latest_run(rd)
    if not run_id:
        raise SystemExit("no run recorded in this folder")
    rep = build_report(reg, rd, run_id)
    print(json.dumps(rep["overall"], indent=1, ensure_ascii=False) if a.json else
          (rd / "ERRORS.md").read_text(encoding="utf-8"))
    return 0


def cmd_trace(a) -> int:
    reg, rd = Registry.load(), _rd(a.research_dir)
    run_id = a.run_id or _latest_run(rd)
    try:
        out = trace_unit(reg, rd, a.id, run_id) if a.id in reg.units else trace_error(reg, rd, run_id, a.id)
    except IdeateError as e:
        raise SystemExit(str(e))
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    return 0


def cmd_recipes(a) -> int:
    reg = Registry.load()
    try:
        recipes = rcp.load()
    except (ValueError, KeyError) as e:
        print(f"recipes: {e}", file=sys.stderr)
        return 2
    fs = rcp.validate(recipes, reg)
    if a.json:
        print(json.dumps(fs, indent=1))
    else:
        for f in fs:
            if f["level"] != "INFO" or a.verbose:
                print(f"{f['level']:<5} {f['code']:<14} {f['unit']:<6} {f['message']}")
        n = {lvl: sum(1 for f in fs if f["level"] == lvl) for lvl in ("ERROR", "WARN", "INFO")}
        drafts = sum(1 for r in recipes.values() if r.status == "draft")
        print(f"{len(recipes)} recipe(s) for {len(reg.units)} Units: {n['ERROR']} error(s), {n['WARN']} warning(s); "
              f"{drafts} draft, {len(recipes) - drafts} reviewed")
    return 1 if any(f["level"] == "ERROR" for f in fs) else 0


def cmd_check(a) -> int:
    return subprocess.call([sys.executable, str(MODULE_ROOT / "scripts" / "run_checks.py"), *(["--strict"] if a.strict else [])])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ideate-harness", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("run", help="run the pipeline on a topic")
    sp.add_argument("topic")
    sp.add_argument("--from", dest="frm", default="S1")
    sp.add_argument("--to", default="B6")
    sp.add_argument("--depth", choices=("quick", "standard", "deep"))
    sp.add_argument("--generations", type=int, help="ideas to add (max_num_generations, default 3)")
    sp.add_argument("--reflections", type=int, help="num_reflections (default 3)")
    sp.add_argument("--config", type=Path, help="harness.toml")
    sp.add_argument("--research-dir", help="default: <topic>_research next to the topic")
    sp.add_argument("--python", help="interpreter for scripts/ (needs the mcp package)")
    sp.add_argument("--worker", choices=("claude", "ollama"), help="who does the model Units (default: claude)")
    sp.add_argument("--ollama-url", help="worker ollama: the server, e.g. http://127.0.0.1:11434 (OLLAMA_API_KEY in "
                    "the environment is sent as a Bearer token)")
    sp.add_argument("--num-ctx", type=int, help="worker ollama: the context the model runs with (default 65536)")
    sp.add_argument("--claude", help="the Claude Code CLI (default: claude)")
    sp.add_argument("--model")
    sp.add_argument("--max-parallel", type=int)
    sp.add_argument("--smoke-cap", type=int, help="a smoke test: at most N papers per source per query and per "
                    "snowball route (IDEATE_SMOKE_CAP)")
    sp.add_argument("--budget", type=float, help="default USD cap per worker call (claude -p --max-budget-usd)")
    sp.add_argument("--dry-run", action="store_true", help="fixtures instead of the skill and Claude: no network, no tokens")
    sp.add_argument("--fixtures", help="dry run: a research folder to copy from (or a folder with topic/ and gen/)")
    sp.add_argument("--inject", action="append", help="dry run: KEY=TOKEN[,TOKEN] faults (see harness/fake.py)")
    sp.add_argument("--replay", action="store_true", help="IDEATE_REPLAY=1: network answers from the recordings")
    sp.add_argument("--agent", action="append", help="UNIT=package.module:Class - a custom executor for one Unit")
    sp.add_argument("--no-resume", action="store_true", help="run Units even when already done")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_run)
    for name, fn, help_ in (("status", cmd_status, "Unit states and what runs next"),
                            ("report", cmd_report, "rebuild and print the report")):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("research_dir")
        sp.add_argument("--run-id")
        sp.add_argument("--json", action="store_true")
        sp.set_defaults(fn=fn)
    sp = sub.add_parser("trace", help="an error back to its root cause, or a Unit's history")
    sp.add_argument("research_dir")
    sp.add_argument("id")
    sp.add_argument("--run-id")
    sp.set_defaults(fn=cmd_trace)
    sp = sub.add_parser("recipes", help="validate the recipes")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--verbose", action="store_true")
    sp.set_defaults(fn=cmd_recipes)
    sp = sub.add_parser("check", help="every check of the module")
    sp.add_argument("--strict", action="store_true")
    sp.set_defaults(fn=cmd_check)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
