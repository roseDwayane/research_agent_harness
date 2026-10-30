"""UnitAgent: the shell every Unit runs in, whatever executes it. The executor cannot skip any of it.

  1. resume       a Unit already done (on the ledger and not stale; for a generation: its files present) is skipped
  2. upstream     every Unit it requires is done, or it does not start (IDEATE.UPSTREAM.NOT_DONE, caused by the
                  upstream Unit's last error)
  3. execute      UNIT_STARTED -> the executor (recipe steps, or a custom agent) -> its errors and metrics
  4. outputs      every file/part artifact the Unit's contract names exists and parses (IDEATE.UNIT.OUTPUT_MISSING)
  5. checks       the Unit's own check commands; an ERROR finding is <unit>:<code> (check_failed)
  6. close        UNIT_COMPLETED | UNIT_DEGRADED | UNIT_FAILED; a failure goes to the orchestrator's retry policy
                  (RP-UNIT): interrupted, timeout and external_service are retried with a backoff, deterministic
                  failures are not (they are fixed, not retried), a degraded failure lets the step go on
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from ideate_v2 import retry
from ideate_v2.errors import SEVERITY_RANK
from ideate_v2.gates import artifact_paths
from ideate_v2.jsonio import read_json
from ideate_v2.ledger import ledger_block, load_events, planning_status, unit_states
from ideate_v2.report import read_caveats

from .context import RunContext, instance_of
from .executors import Executor, ExecResult, RecipeExecutor
from .recipes import Recipe

STATUSES = ("done", "degraded", "failed", "stopped", "skipped")


@dataclass
class UnitResult:
    unit: str
    instance: str
    status: str
    attempts: int = 0
    errors: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    seconds: float = 0.0
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("done", "degraded", "skipped")


def unit_done(ctx: RunContext, unit: str, gen: int | None) -> tuple[bool, str]:
    """(done, why) - from the ledger for a Unit on it, from the generation's files for a planning Unit."""
    if ledger_block(ctx.reg, unit) is not None:
        events, _ = load_events(ctx.rd)
        st = unit_states(ctx.reg, ctx.rd, events).get(unit, {"state": "todo", "why": ""})
        return st["state"] == "done", f"{st['state']}" + (f": {st['why']}" if st.get("why") else "")
    if gen is not None:
        plan = planning_status(ctx.rd, gen)
        st = (plan.get("units") or {}).get(unit, {}).get("state", "todo")
        return st == "done", st
    return not missing_outputs(ctx, unit, gen), "outputs present" if not missing_outputs(ctx, unit, gen) else "todo"


def is_planning(ctx: RunContext, unit: str) -> bool:
    step = ctx.reg.step_of(unit)
    return bool(step) and ctx.reg.get(step).get("block") == "BLK-planning"


def missing_outputs(ctx: RunContext, unit: str, gen: int | None) -> list[str]:
    """The contract's file and part artifacts of the Unit that are absent or do not parse."""
    out = []
    for art_id in ctx.reg.units[unit]["outputs"]["artifacts"]:
        art = ctx.reg.get(art_id)
        if art.get("kind") not in ("file", "part"):
            continue
        if art_id == "ART-ideas-archive":
            files = [ctx.topic.with_suffix(".json")] if ctx.topic and ctx.topic.with_suffix(".json").is_file() else []
        else:
            base = ctx.rd / f"gen_{gen}" if art["path"].startswith("gen_k/") and gen is not None else ctx.rd
            files = artifact_paths(ctx.reg, art_id, base)
        if not files:
            # a collection (pdfs/<key>.pdf, knowledge/lines/*.md) may be legitimately empty - every paper paywalled,
            # nothing promotable from abstracts; the Unit's own checks judge its coverage (A6.d: F06 warns)
            if "<key>" not in art["path"] and "*" not in art["path"]:
                out.append(f"{art_id} ({art['path']})")
            continue
        for f in files[:50]:
            if f.suffix == ".json":
                try:
                    read_json(f)
                except ValueError as e:
                    out.append(f"{art_id}: {f.name} does not parse ({e})")
                    break
    return out


class UnitAgent:
    def __init__(self, unit: str, recipe: Recipe | None, executor: Executor | None = None):
        self.unit, self.recipe = unit, recipe
        self.executor: Executor = executor or RecipeExecutor()

    def closes(self, phase: str) -> bool:
        """Whether this phase ends the Unit: the output contract and the checks apply (recipes.Recipe.partial)."""
        return not (self.recipe and phase in self.recipe.partial)

    def run(self, ctx: RunContext, gen: int | None = None, phase: str = "main", force: bool = False,
            strict: bool = True) -> UnitResult:
        """strict=False (Stage B before the coherence gate): an ERROR of the Unit's own checks is recorded as a
        warning and carried to the round-2 revision instead of failing the Unit (research-cycle.md section 5)."""
        unit, inst = self.unit, instance_of(gen)
        rec_inst = instance_of(gen, phase)                 # what this call's events and errors are recorded under
        step = ctx.reg.step_of(unit)
        t0 = time.time()
        final_phase = self.closes(phase)

        # 1. resume
        # (a generation this run started is never resumed from file presence: its files are this run's own)
        first_phase = phase == list((self.recipe.phases if self.recipe else {"main": []}))[0]
        if ctx.cfg.resume and not force and first_phase and gen not in ctx.fresh_gens:
            done, why = unit_done(ctx, unit, gen)
            if done:
                ctx.say(f"    · {unit}{'@' + inst if gen is not None else ''} already done - skipped")
                return self._closed(ctx, UnitResult(unit, inst, "skipped", note=why))

        # 2. upstream
        for up in ctx.reg.requires(unit):
            if up not in ctx.reg.units:
                continue
            up_gen = gen if is_planning(ctx, up) else None
            if up_gen is None and ledger_block(ctx.reg, up) is None:
                continue                               # neither on the ledger nor in a generation: nothing to read
            ok, why = unit_done(ctx, up, up_gen)
            if not ok:
                parent = ctx.last_error(up, instance_of(up_gen))
                rec = ctx.error("IDEATE.UPSTREAM.NOT_DONE", f"{unit} requires {up}, which is {why}", unit=unit,
                                step=step, instance=rec_inst, parent=parent.error_id if parent else None,
                                context={"upstream": up})
                return self._closed(ctx, UnitResult(unit, inst, "stopped", 0, [rec], seconds=round(time.time() - t0, 3)))

        # 3-6. attempts
        attempt = ctx.next_attempt(unit, rec_inst)
        result = UnitResult(unit, rec_inst, "failed")
        tries = 1                                          # attempts of this call (a loop's re-run is a new call)
        while True:
            ctx.say(f"    ▸ {unit}{'@' + inst if gen is not None else ''}" + (f" [{phase}]" if phase != "main" else "")
                    + (f" retry {tries - 1}" if tries > 1 else ""))
            ctx.emit("UNIT_STARTED", unit_id=unit, step_id=step, instance=rec_inst, attempt=attempt,
                     context={"phase": phase})
            try:
                ex = self.executor.execute(ctx, unit, self.recipe, phase, gen, attempt)
            except Exception as e:  # noqa: BLE001 - a custom agent's bug is recorded, not raised
                rec = ctx.error("IDEATE.INTERNAL", f"{type(e).__name__}: {e}", unit=unit, instance=rec_inst,
                                attempt=attempt)
                ex = ExecResult(False, [rec])
            result.attempts = tries
            result.metrics = {k: result.metrics.get(k, 0) + v for k, v in ex.metrics.items()} | \
                {k: v for k, v in result.metrics.items() if k not in ex.metrics}
            errs = list(ex.errors)
            if ex.ok and final_phase:
                for m in missing_outputs(ctx, unit, gen):
                    errs.append(ctx.error("IDEATE.UNIT.OUTPUT_MISSING", f"{unit} left no {m}", unit=unit,
                                          instance=rec_inst, attempt=attempt))
                if not errs and self.recipe and self.recipe.check:
                    findings, _ = ctx.skill.unit_findings(unit, self.recipe.check, ctx.subs(gen))
                    for f in findings:
                        if f["level"] in ("ERROR", "WARN"):
                            blocking = f["level"] == "ERROR" and strict
                            errs.append(ctx.error(f"{unit}:{_code(f['code'])}", f["message"] or f["code"], unit=unit,
                                                  instance=rec_inst, attempt=attempt, category="check_failed",
                                                  severity="error" if blocking else "warning",
                                                  recovery_action="fix-input" if f["level"] == "ERROR" else "none",
                                                  context={} if strict or f["level"] != "ERROR" else
                                                  {"carried": "fixed by the round-2 revision or the coherence gate"}))
            bad = [e for e in errs if SEVERITY_RANK[e.severity] >= SEVERITY_RANK["error"]]
            degraded = [e for e in errs if e.severity == "degraded"]
            metrics = {k: v for k, v in result.metrics.items() if k in ("tokens_in", "tokens_out", "cost_usd", "calls")}
            if not bad and not degraded:
                cav = [c for c in read_caveats(ctx.rd) if c.get("unit") == unit and c.get("must_disclose")]
                kind = "UNIT_DEGRADED" if cav else "UNIT_COMPLETED"
                ctx.emit(kind, unit_id=unit, step_id=step, instance=rec_inst, attempt=attempt, metrics=metrics,
                         status="degraded" if cav else "done",
                         message=("caveats: " + ", ".join(c["code"] for c in cav)) if cav else None)
                result.status, result.errors = ("degraded" if cav else "done"), result.errors + errs
                break
            worst = max(bad or degraded, key=lambda e: SEVERITY_RANK[e.severity])
            d = retry.decide(ctx.reg, "RP-UNIT", worst.to_dict(), tries, "orchestrator")
            # an attempt that will be retried failed, whatever its severity (RETRY_SCHEDULED follows UNIT_FAILED)
            ctx.emit("UNIT_FAILED" if bad or d["action"] == "retry" else "UNIT_DEGRADED", unit_id=unit, step_id=step,
                     instance=rec_inst, attempt=attempt, error_id=worst.error_id, metrics=metrics,
                     message=worst.error_message[:300])
            result.errors += errs
            if d["action"] == "retry":
                ctx.emit("RETRY_SCHEDULED", unit_id=unit, step_id=step, instance=rec_inst, attempt=attempt,
                         message=d["reason"], error_id=worst.error_id)
                ctx.say(f"    ↻ {unit}: {d['reason']}")
                if not ctx.cfg.dry_run:
                    time.sleep(d["delay_s"])
                attempt = ctx.next_attempt(unit, rec_inst)
                tries += 1
                continue
            if d["action"] in ("escalate",) or d.get("code") == "IDEATE.RETRY.EXHAUSTED":
                ctx.emit("RETRY_EXHAUSTED", unit_id=unit, step_id=step, instance=rec_inst, attempt=attempt,
                         message=d["reason"], error_id=worst.error_id)
            if not bad:                                   # degraded only: the step goes on with a caveat
                result.status = "degraded"
            elif worst.severity == "fatal":
                result.status = "stopped"
            else:
                result.status = "failed"
            break
        result.seconds = round(time.time() - t0, 3)
        return self._closed(ctx, result)

    @staticmethod
    def _closed(ctx: RunContext, result: UnitResult) -> UnitResult:
        ctx.add_unit(result)
        return result


def _code(code: str) -> str:
    """A legacy check code as the tail of <unit>:<code> (upper case, no spaces)."""
    c = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(code)).upper()
    return c if c and c[0].isalpha() else f"X{c}"


def outputs_summary(ctx: RunContext, unit: str, gen: int | None) -> list[Path]:
    """The files a Unit's outputs resolve to now (for the run summary)."""
    files: list[Path] = []
    for art_id in ctx.reg.units[unit]["outputs"]["artifacts"]:
        art = ctx.reg.get(art_id)
        base = ctx.rd / f"gen_{gen}" if art["path"].startswith("gen_k/") and gen is not None else ctx.rd
        if art.get("kind") in ("file", "part") and art_id != "ART-ideas-archive":
            files += artifact_paths(ctx.reg, art_id, base)
    return files
