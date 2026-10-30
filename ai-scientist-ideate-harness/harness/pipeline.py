"""PipelineAgent: the whole ideate stage - Stage A once per topic, Stage B once per idea - and the run's report.

  RUN_STARTED
  Stage A   STEP-S1 .. STEP-S5 (literature search, slide 3), STEP-F1 .. STEP-F4 (fusion, slide 4); each step's exit
            gate must pass before the next starts; the first failure ends the run (nothing downstream is attempted)
  Stage B   generations until max_num_generations ideas were added (LOOP-12) or no ready question is left;
            an abandoned question (LOOP-11) does not count as an idea
  report    ideate_v2.report.build_report -> <RD>/_state/errors/<run_id>/{units,steps,overall.json}, <RD>/ERRORS.md;
            the conductor's own summary -> <RD>/_state/harness/<run_id>/summary.json
  RUN_COMPLETED | RUN_FAILED
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ideate_v2.jsonio import write_json_atomic
from ideate_v2.report import build_report

from . import loops
from .context import RunContext
from .recipes import Recipe
from .shell import UnitAgent
from .steps import GenerationAgent, GenerationResult, StepAgent, StepResult

STAGE_A_BLOCKS = ("BLK-search", "BLK-fusion")


def step_id(short: str) -> str:
    s = short.upper()
    return s if s.startswith("STEP-") else f"STEP-{s}"


def next_generation(rd: Path) -> int:
    """The generation to work on: an unfinished one (no idea.json, not abandoned) first, else the next free number."""
    gens = sorted(int(m.group(1)) for p in rd.glob("gen_*") if p.is_dir() and (m := re.fullmatch(r"gen_(\d+)", p.name)))
    for k in gens:
        gd = rd / f"gen_{k}"
        abandoned = rd / "_state" / "harness" / "decisions" / f"gen_{k}" / "abandoned.json"
        if not abandoned.is_file() and not (gd / "step8_journal_recommendations.md").is_file():
            return k
    return (gens[-1] + 1) if gens else 1


class PipelineAgent:
    def __init__(self, reg, recipes: dict[str, Recipe], executor_for):
        """executor_for(unit) -> the executor of that Unit (the default, a fake, or a custom agent)."""
        self.reg = reg
        self.agents = {u: UnitAgent(u, recipes.get(u), executor_for(u)) for u in reg.units}

    def stage_a_steps(self) -> list[str]:
        return [s for s in self.reg.step_order() if self.reg.get(s).get("block") in STAGE_A_BLOCKS]

    def run(self, ctx: RunContext, frm: str = "S1", to: str = "B6") -> dict:
        t0 = time.time()
        frm, to = step_id(frm), step_id(to)
        a_steps = self.stage_a_steps()
        if frm not in a_steps + ["STEP-P0"]:
            raise ValueError(f"--from must be a Stage A step (S1..F4) or P0, not {frm}")
        if to not in a_steps + ["STEP-B6"]:
            raise ValueError(f"--to must be a Stage A step (S1..F4) or B6 (Stage B runs whole generations), not {to}")
        ctx.emit("RUN_STARTED", context={"from": frm, "to": to, "depth": ctx.cfg.depth, "dry_run": ctx.cfg.dry_run,
                                         "generations": ctx.cfg.max_num_generations, "topic": str(ctx.topic or "")})
        ctx.say(f"run {ctx.run_id} · {ctx.rd.name} · {frm} → {to} · depth {ctx.cfg.depth}"
                + (" · DRY RUN" if ctx.cfg.dry_run else ""))
        steps: list[StepResult] = []
        gens: list[GenerationResult] = []
        failed = False
        run_a = a_steps[a_steps.index(frm): (a_steps.index(to) + 1) if to in a_steps else None] if frm in a_steps else []
        for sid in run_a:
            sr = StepAgent(sid, self.agents).run(ctx, check_entry=sid == run_a[0])
            steps.append(sr)
            if not sr.ok:
                failed = True
                break
        if not failed and to == "STEP-B6":
            gens, failed = self._stage_b(ctx)
        last_gen = gens[-1].gen if gens else None
        report = build_report(self.reg, ctx.rd, ctx.run_id, generation=last_gen)
        status = report["overall"]["status"]
        ctx.emit("RUN_FAILED" if failed else "RUN_COMPLETED", status=status, metrics={
            "tokens_in": ctx.usage["tokens_in"], "tokens_out": ctx.usage["tokens_out"],
            "cost_usd": round(ctx.usage["cost_usd"], 6), "calls": ctx.usage["calls"],
            "duration_ms": int((time.time() - t0) * 1000)})
        summary = self._summary(ctx, steps, gens, report, failed, time.time() - t0)
        write_json_atomic(ctx.state_dir / "summary.json", summary)
        return summary

    # ------------------------------------------------------------------------------------------------ Stage B
    def _stage_b(self, ctx: RunContext) -> tuple[list[GenerationResult], bool]:
        gens: list[GenerationResult] = []
        want = ctx.cfg.max_num_generations
        ctx.cfg.loop_bounds["LOOP-12"] = want
        added = 0
        while added < want:
            if not loops.allowed(ctx, "LOOP-12", added, unit="B6", step="STEP-B6")["allowed"]:
                break
            left = loops.ready_questions_left(ctx.rd)
            k = next_generation(ctx.rd)
            if not left and not (ctx.rd / f"gen_{k}" / "question.json").is_file():
                ctx.error("IDEATE.ARTIFACT.MISSING", f"no ready question left after {added} idea(s) of {want}",
                          step="STEP-P0", severity="degraded", caveat="questions-exhausted", must_disclose=True)
                break
            ctx.say(f"══ generation {k} ({added + 1} of {want}) ══")
            g = GenerationAgent(self.agents).run(ctx, k)
            gens.append(g)
            ctx.say(f"══ gen_{k}: {g.status}" + (f" ({'; '.join(g.doubts)})" if g.doubts else ""))
            if g.status in ("finalized", "finalized-with-doubt"):
                added += 1
            elif g.status != "abandoned":
                return gens, True
        return gens, False

    # ------------------------------------------------------------------------------------------------ summary
    def _summary(self, ctx: RunContext, steps, gens, report, failed: bool, seconds: float) -> dict:
        units = [{"unit": r.unit, "instance": r.instance, "status": r.status, "attempts": r.attempts,
                  "tokens_in": r.metrics.get("tokens_in", 0), "tokens_out": r.metrics.get("tokens_out", 0),
                  "cost_usd": round(r.metrics.get("cost_usd", 0.0), 4), "seconds": r.seconds,
                  "errors": [e.error_code for e in r.errors]} for r in ctx.units]
        gate_rows = []
        for sr in steps + [s for g in gens for s in g.steps]:
            for g in sr.gates:
                gate_rows.append({"gate": g.gate, "instance": g.instance, "passed": g.passed, "waived": g.waived,
                                  "warnings": g.warnings})
        return {"schema": "ideate-harness-summary/1", "run_id": ctx.run_id, "research_dir": str(ctx.rd),
                "topic": str(ctx.topic or ""), "dry_run": ctx.cfg.dry_run, "depth": ctx.cfg.depth,
                "status": report["overall"]["status"], "failed": failed, "seconds": round(seconds, 1),
                "usage": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in ctx.usage.items()},
                "steps": [{"step": s.step, "instance": s.instance, "status": s.status, "stopped_by": s.stopped_by}
                          for s in steps],
                "generations": [{"gen": g.gen, "status": g.status, "question": g.question, "doubts": g.doubts}
                                for g in gens],
                "gates": gate_rows, "units": units,
                "root_causes": report["overall"]["root_causes"], "must_disclose": report["overall"]["must_disclose"],
                "errors_md": str(ctx.rd / "ERRORS.md")}


def render_summary(s: dict) -> str:
    lines = [f"run {s['run_id']}: {s['status']}" + (" (failed)" if s["failed"] else "") +
             f" in {s['seconds']}s" + (" · dry run" if s["dry_run"] else ""),
             f"usage: {s['usage'].get('calls', 0)} worker call(s), {s['usage'].get('tokens_in', 0):,} tokens in, "
             f"{s['usage'].get('tokens_out', 0):,} out, ${s['usage'].get('cost_usd', 0):.2f}", "",
             f"{'unit':<8}{'inst':<8}{'status':<10}{'att':>4}{'tokens':>10}{'$':>8}{'s':>8}  errors"]
    for u in s["units"]:
        lines.append(f"{u['unit']:<8}{u['instance']:<8}{u['status']:<10}{u['attempts']:>4}"
                     f"{u['tokens_in'] + u['tokens_out']:>10,}{u['cost_usd']:>8.2f}{u['seconds']:>8.1f}  "
                     + ", ".join(u["errors"][:3]))
    failed_gates = [g for g in s["gates"] if not g["passed"]]
    lines += ["", f"gates: {sum(1 for g in s['gates'] if g['passed'])} passed, {len(failed_gates)} failed"
              + "".join(f"\n  ✗ {g['gate']} @{g['instance']}" + (" (waived, doubt disclosed)" if g["waived"] else "")
                        for g in failed_gates)]
    if s["generations"]:
        lines += ["generations: " + ", ".join(f"gen_{g['gen']} {g['status']}" for g in s["generations"])]
    if s["root_causes"]:
        lines += ["root causes:"] + [f"  {r['error_code']} at {r['origin']} ({r['severity']}) -> {r['recovery_action']}"
                                     for r in s["root_causes"][:8]]
    lines += [f"must disclose: {', '.join(s['must_disclose']) or 'nothing'}", f"report: {s['errors_md']}"]
    return "\n".join(lines)


def load_summary(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
