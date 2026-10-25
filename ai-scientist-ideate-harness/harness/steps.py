"""Big steps: StepAgent (one step between two gates) and GenerationAgent (Stage B for one idea, B5's rounds).

A gate passes only when ideate_v2's contract check (gates.evaluate_gate: requires_done, requires_artifacts, rules)
AND the skill's own command (`legacy_command`) pass - decision D-10. In a step the Units run in `requires` order; the
first that fails or stops ends the step (the rest are skipped, with the reason). Loops the conductor drives are in
loops.py; each iteration asks for permission first.

Stage B (research-cycle.md section 5 "On the fusion block"; references/planning/README.md):
  round 1   P1 -> P5, their checks recorded, not blocking (the round's ERRORs are fixed by the round-2 revision);
            B5 round1: lookups, the draft, the round-1 copies (cp -n), blind restatement 1
  round 2   B5 round2: the critique; ONE decision -> finalize, or ReviseHypothesis entering at P1 | P2 | P3
            (LOOP-09: once) -> the steps from there to P3 are produced again, never patched
  round 3   P4, P5 again on a revised design; B5 round3: the draft, the compute gate, restatement 2 if the
            primary claim changed; then the coherence gate (blocking). A failure gets one forced revision (LOOP-10)
            entering at the step the finding belongs to; still failing: the decision gate T09 abandons the question
            when another ready one remains (LOOP-11), anything else is finalized with the doubt disclosed
  finalize  B5 finalize (FinalizeIdea -> idea.json), then STEP-B6 (append, consume, Body, journals)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ideate_v2 import gates
from ideate_v2.errors import IdeateError

from . import loops
from .context import RunContext, instance_of
from .shell import UnitAgent, UnitResult
from .skill import COHERENCE

PLANNING_STEPS = ("STEP-P1", "STEP-P2", "STEP-P3", "STEP-P4", "STEP-P5")
REVISION_ENTRIES = ("P1", "P2", "P3")
# a failing coherence command -> the step its finding belongs to (research-cycle.md section 5, round 3)
COHERENCE_STEP = dict(zip(COHERENCE, ("P2", "P3", "P4", "P5")))
RULE_STEP = {"GATE.RULE.decision_tree_weak_mass": "P3", "GATE.RULE.abstract_word_limit": "P5"}


@dataclass
class GateResult:
    gate: str
    instance: str
    passed: bool
    contract: dict = field(default_factory=dict)
    legacy: list = field(default_factory=list)          # CommandResults
    error: object = None                                # the IDEATE.GATE.FAILED record
    waived: bool = False

    @property
    def warnings(self) -> list[str]:
        return [f["message"] for f in self.contract.get("findings") or [] if f["level"] == "WARN"]

    def failing_steps(self) -> list[str]:
        """Planning steps the failure belongs to (for the coherence gate's forced revision)."""
        out = {COHERENCE_STEP[r.command_template] for r in self.legacy if not r.ok and
               getattr(r, "command_template", None) in COHERENCE_STEP}
        out |= {RULE_STEP[f["code"]] for f in self.contract.get("findings") or []
                if f["level"] == "ERROR" and f["code"] in RULE_STEP}
        return sorted(out)

    @property
    def tree_failed(self) -> bool:
        return "P3" in self.failing_steps()


def check_gate(ctx: RunContext, gate_id: str, gen: int | None, *, blocking: bool = True) -> GateResult:
    gate = ctx.reg.get(gate_id)
    inst = instance_of(gen) if gate["scope"] == "generation" else "-"
    try:
        contract = gates.evaluate_gate(ctx.reg, ctx.rd, gate_id, generation=gen if gate["scope"] == "generation" else None)
    except IdeateError as e:
        contract = {"passed": False, "findings": [{"level": "ERROR", "code": e.code, "message": str(e)}]}
    subs = ctx.subs(gen)
    from .skill import gate_commands
    templates = gate_commands(gate)
    legacy_ok, results = ctx.skill.gate_check(gate, subs)
    for r, tpl in zip(results, templates):
        r.command_template = tpl                         # type: ignore[attr-defined]
    passed = bool(contract.get("passed")) and legacy_ok
    errs = [f for f in contract.get("findings") or [] if f["level"] == "ERROR"]
    ctx.emit("GATE_CHECKED", step_id=gate["from_step"], instance=inst, status="passed" if passed else "failed",
             message=gate_id, context={"gate": gate_id, "counts": contract.get("counts", {}), "legacy_ok": legacy_ok,
                                       "blocking": blocking})
    res = GateResult(gate_id, inst, passed, contract, results)
    mark = "✓" if passed else ("✗" if blocking else "·")
    ctx.say(f"  {mark} {gate_id}" + ("" if passed else f": {len(errs)} contract error(s), legacy "
                                    f"{'ok' if legacy_ok else 'failed'}") + "".join(f"\n      WARN {w}" for w in res.warnings))
    if passed:
        ctx.gates_passed.add((gate_id, inst))
        return res
    why = "; ".join(f"{f['code']}: {f['message']}" for f in errs[:4])
    why += ("; " if why else "") + "; ".join(f"`{r.command.split('/')[-1][:80]}` exited {r.returncode}"
                                             for r in results if not r.ok)
    from_units = ctx.reg.get(gate["from_step"]).get("units") or []
    parent = next((ctx.last_error(u, inst) for u in reversed(from_units) if ctx.last_error(u, inst)), None)
    # recorded on the step's last Unit: the gate refused what the step's Units left
    res.error = ctx.error("IDEATE.GATE.FAILED", f"{gate_id}: {why}", unit=from_units[-1] if from_units else None,
                          step=gate["from_step"], instance=inst,
                          parent=parent.error_id if parent else None, severity="error" if blocking else "warning",
                          context={"gate": gate_id, "findings": errs[:20]},
                          recovery_action="revise" if gate["scope"] == "generation" else "stop")
    return res


@dataclass
class StepResult:
    step: str
    instance: str
    status: str                                          # done | degraded | failed | stopped | skipped
    units: list[UnitResult] = field(default_factory=list)
    gates: list[GateResult] = field(default_factory=list)
    stopped_by: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("done", "degraded", "skipped")


class StepAgent:
    def __init__(self, step_id: str, agents: dict[str, UnitAgent]):
        self.step_id, self.agents = step_id, agents

    def run(self, ctx: RunContext, gen: int | None = None, *, blocking: bool = True, force: bool = False,
            phase: str = "main", check_entry: bool = True, units: list[str] | None = None) -> StepResult:
        step = ctx.reg.get(self.step_id)
        inst = instance_of(gen) if step.get("block") == "BLK-planning" else "-"
        res = StepResult(self.step_id, inst, "done")
        ctx.say(f"▶ {self.step_id} {step['name']}" + (f" @{inst}" if inst != "-" else ""))
        entry = step.get("entry_gate")
        if check_entry and entry:
            ginst = instance_of(gen) if ctx.reg.get(entry)["scope"] == "generation" else "-"
            if (entry, ginst) not in ctx.gates_passed:
                g = check_gate(ctx, entry, gen, blocking=blocking)
                res.gates.append(g)
                if not g.passed and blocking:
                    res.status, res.stopped_by = "stopped", g.error.error_id if g.error else entry
                    return self._close(ctx, res, step)
        ctx.emit("STEP_STARTED", step_id=self.step_id, instance=inst)
        order = ctx.reg.topo_order(units or step["units"])
        for i, u in enumerate(order):
            agent = self.agents[u]
            ph = phase if agent.recipe and phase in agent.recipe.phases else "main"
            r = agent.run(ctx, gen, ph, force=force, strict=blocking)
            res.units.append(r)
            if not r.ok:
                res.status = "stopped" if r.status == "stopped" else "failed"
                res.stopped_by = r.errors[-1].error_id if r.errors else u
                res.units += [UnitResult(x, inst, "skipped", note=f"not run: {u} {r.status}") for x in order[i + 1:]]
                return self._close(ctx, res, step)
            if r.status == "degraded":
                res.status = "degraded"
            for extra in (self.after_unit(ctx, u, gen) if r.status != "skipped" else []):
                res.units.append(extra)
                if not extra.ok:
                    res.status, res.stopped_by = "failed", extra.errors[-1].error_id if extra.errors else extra.unit
                    return self._close(ctx, res, step)
        exit_gate = step.get("exit_gate")
        if exit_gate and self.step_id != "STEP-B5":       # B5's exit (coherence) is the GenerationAgent's
            g = check_gate(ctx, exit_gate, gen, blocking=blocking)
            res.gates.append(g)
            if not g.passed and blocking:
                res.status, res.stopped_by = "failed", g.error.error_id if g.error else exit_gate
            elif g.warnings and res.status == "done":
                res.status = "degraded"
        return self._close(ctx, res, step)

    def _close(self, ctx: RunContext, res: StepResult, step: dict) -> StepResult:
        ctx.emit("STEP_COMPLETED", step_id=self.step_id, instance=res.instance, status=res.status)
        return res

    # ------------------------------------------------------------------------------------------- loops (Stage A)
    def rerun(self, ctx: RunContext, unit: str, gen: int | None = None, phase: str = "main") -> UnitResult:
        agent = self.agents[unit]
        ph = phase if agent.recipe and phase in agent.recipe.phases else "main"
        return agent.run(ctx, gen, ph, force=True)

    def after_unit(self, ctx: RunContext, unit: str, gen: int | None) -> list[UnitResult]:
        hook = {"A1.e": self._loop02, "A2.c": self._loop01, "A5": self._loop04, "A6.d": self._loop08}.get(unit)
        return hook(ctx) if hook else []

    def _loop02(self, ctx: RunContext) -> list[UnitResult]:
        out, completed = [], 0
        while True:
            rounds, verdict = loops.protocol_verdict(ctx.rd)
            if verdict != "revision-required":
                return out
            if not loops.allowed(ctx, "LOOP-02", completed, unit="A1.e", step=self.step_id)["allowed"]:
                return out                                # A1.e itself records accepted-with-doubts
            for u in ("A1.p", "A1.q", "A1.e"):
                r = self.rerun(ctx, u, phase="revise")
                out.append(r)
                if not r.ok:
                    return out
            completed += 1

    def _loop01(self, ctx: RunContext) -> list[UnitResult]:
        out, completed = [], 0
        while True:
            rounds, replan = loops.relevance_rounds(ctx.rd)
            if not replan:
                return out
            if not loops.allowed(ctx, "LOOP-01", completed, unit="A2.c", step=self.step_id)["allowed"]:
                return out                                # bound reached: A2.c accepts weak, with the caveat
            for u, ph in (("A2.c", "replan"), ("A2.m", "main"), ("A2.c", "main")):
                r = self.rerun(ctx, u, phase=ph)
                out.append(r)
                if not r.ok:
                    return out
            completed += 1

    def _loop04(self, ctx: RunContext) -> list[UnitResult]:
        """A5's additions are screened again (always, when it added papers); a second round only after >= 10 %."""
        out = []
        for completed in (0, 1):
            if completed == 1:
                d = loops.allowed(ctx, "LOOP-04", 1, {"growth": g} if (g := loops.snowball_growth(ctx.rd)) is not None
                                  else {}, unit="A5", step=self.step_id)
                if not d["allowed"]:
                    return out
                r = self.rerun(ctx, "A5", phase="round2")
                out.append(r)
                if not r.ok:
                    return out
            elif not loops.allowed(ctx, "LOOP-04", 0, unit="A5", step=self.step_id)["allowed"]:
                return out
            for u in ("A3.b", "A3.g", "A3"):
                r = self.rerun(ctx, u)
                out.append(r)
                if not r.ok:
                    return out
        return out

    def _loop08(self, ctx: RunContext) -> list[UnitResult]:
        from ideate_v2.report import read_caveats
        short = any(c.get("unit") == "A6.d" and c.get("code") == "fulltext-short" for c in read_caveats(ctx.rd))
        if not short or not loops.allowed(ctx, "LOOP-08", 0, unit="A6.d", step=self.step_id)["allowed"]:
            return []
        return [self.rerun(ctx, "A6.d", phase="topup")]


# =============================================================================================== Stage B
@dataclass
class GenerationResult:
    gen: int
    status: str                              # finalized | finalized-with-doubt | abandoned | failed | stopped
    steps: list[StepResult] = field(default_factory=list)
    question: str | None = None
    doubts: list[str] = field(default_factory=list)


class GenerationAgent:
    """One generation (gen_k): P0, the B5 rounds around P1-P5, the coherence gate, B6."""

    def __init__(self, agents: dict[str, UnitAgent]):
        self.agents = agents
        self.steps = {s: StepAgent(s, agents) for s in ("STEP-P0", *PLANNING_STEPS, "STEP-B5", "STEP-B6")}

    def _planning(self, ctx: RunContext, k: int, res: GenerationResult, frm: str, to: str, *, force: bool,
                  phase: str = "main") -> bool:
        ids = [s.split("-")[1] for s in PLANNING_STEPS]
        for s in PLANNING_STEPS[ids.index(frm): ids.index(to) + 1]:
            sr = self.steps[s].run(ctx, k, blocking=False, force=force, phase=phase, check_entry=False)
            res.steps.append(sr)
            if not sr.ok:
                return False
        return True

    def _b5(self, ctx: RunContext, k: int, res: GenerationResult, phase: str) -> bool:
        r = self.agents["B5"].run(ctx, k, phase, force=phase != "round1")
        res.steps.append(StepResult("STEP-B5", instance_of(k), r.status if r.ok else r.status, [r]))
        return r.ok

    def run(self, ctx: RunContext, k: int) -> GenerationResult:
        res = GenerationResult(k, "failed")
        if not (ctx.rd / f"gen_{k}" / "question.json").is_file():
            ctx.fresh_gens.add(k)                          # a new generation: nothing in it is resumed
        p0 = self.steps["STEP-P0"].run(ctx, k)
        res.steps.append(p0)
        if not p0.ok:
            res.status = p0.status if p0.status == "stopped" else "failed"
            return res
        q = ctx.rd / f"gen_{k}" / "question.json"
        if q.is_file():
            import json
            res.question = json.loads(q.read_text(encoding="utf-8")).get("id")

        # round 1
        if not self._planning(ctx, k, res, "P1", "P5", force=False) or not self._b5(ctx, k, res, "round1"):
            return self._stop(res)
        # round 2: one decision
        if not self._b5(ctx, k, res, "round2"):
            return self._stop(res)
        decision = self._decision(ctx, k)
        revised = False
        if decision.get("decision") == "revise":
            enters = decision.get("enters")
            if enters not in REVISION_ENTRIES:
                ctx.error("IDEATE.WORKER.OUTPUT", f"B5 round 2 decided revise entering at {enters!r} (P1 | P2 | P3)",
                          unit="B5", instance=instance_of(k), severity="degraded", caveat="revision-unclear",
                          must_disclose=True)
            elif loops.allowed(ctx, "LOOP-09", 0, unit="B5", step="STEP-B5", instance=instance_of(k))["allowed"]:
                if not self._planning(ctx, k, res, enters, "P3", force=True, phase="revise"):
                    return self._stop(res)
                revised = True
        # round 3
        if revised and not self._planning(ctx, k, res, "P4", "P5", force=True):
            return self._stop(res)
        if not self._b5(ctx, k, res, "round3"):
            return self._stop(res)
        g = check_gate(ctx, "GATE-coherence", k)
        res.steps[-1].gates.append(g)
        if not g.passed:
            entry = (g.failing_steps() or ["P2"])[0]
            if loops.allowed(ctx, "LOOP-10", 0, unit="B5", step="STEP-B5", instance=instance_of(k))["allowed"]:
                ctx.say(f"    forced revision entering at {entry}")
                if not self._planning(ctx, k, res, entry, "P5", force=True, phase="revise" if entry in REVISION_ENTRIES
                                      else "main") or not self._b5(ctx, k, res, "round3"):
                    return self._stop(res)
                g = check_gate(ctx, "GATE-coherence", k)
                res.steps[-1].gates.append(g)
            if not g.passed:
                left = [x for x in loops.ready_questions_left(ctx.rd) if x != res.question]
                if g.tree_failed and left and loops.allowed(ctx, "LOOP-11", 0, unit="B5", step="STEP-B5",
                                                            instance=instance_of(k))["allowed"]:
                    ab = self.agents["B6"].run(ctx, k, "abandon", force=True)
                    res.steps.append(StepResult("STEP-B6", instance_of(k), ab.status, [ab]))
                    res.status = "abandoned" if ab.ok else "failed"
                    res.doubts.append(f"decision gate T09 still failing: question {res.question} abandoned")
                    if ab.ok:
                        import json
                        mark = ctx.decision_path(k).with_name("abandoned.json")
                        mark.parent.mkdir(parents=True, exist_ok=True)
                        mark.write_text(json.dumps({"question": res.question, "run_id": ctx.run_id,
                                                    "why": "T09 after the forced revision (LOOP-11)"}) + "\n",
                                        encoding="utf-8")
                    return res
                caveat = "uninformative-branch" if g.tree_failed else "coherence-unresolved"
                ctx.error("IDEATE.GATE.FAILED", f"GATE-coherence still failing after the forced revision: finalized "
                          f"with the doubt in Risk Factors ({caveat})", unit="B5", step="STEP-B5",
                          instance=instance_of(k), severity="degraded", caveat=caveat, must_disclose=True,
                          parent=g.error.error_id if g.error else None)
                res.doubts.append(caveat)
                ctx.gates_passed.add(("GATE-coherence", instance_of(k)))      # waived: the doubt is disclosed
                g.waived = True
        if not self._b5(ctx, k, res, "finalize"):
            return self._stop(res)
        b6 = self.steps["STEP-B6"].run(ctx, k)
        res.steps.append(b6)
        if not b6.ok:
            return self._stop(res)
        res.status = "finalized-with-doubt" if res.doubts else "finalized"
        return res

    @staticmethod
    def _stop(res: GenerationResult) -> GenerationResult:
        last = res.steps[-1] if res.steps else None
        res.status = "stopped" if last is not None and last.status == "stopped" else "failed"
        return res

    @staticmethod
    def _decision(ctx: RunContext, k: int) -> dict:
        import json
        p = ctx.decision_path(k)
        if not p.is_file():
            ctx.error("IDEATE.WORKER.OUTPUT", "B5 round 2 recorded no decision: finalize assumed", unit="B5",
                      instance=instance_of(k), severity="warning")
            return {"decision": "finalize"}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return {"decision": "finalize"}
