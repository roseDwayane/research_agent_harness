"""The declared loops (contracts/architecture.json `loops`) as the conductor runs them.

Every iteration asks ideate_v2.rules.evaluate_loop first; a loop the contracts leave unbounded (OQ-07) gets the bound
from HarnessConfig.loop_bounds, so nothing loops without a number. LOOP_ITERATION / LOOP_BOUND_REACHED are recorded.

Run by the conductor (the others are declared revisions a worker makes inside its own Unit - screen-amend,
align-set --reason, decon-merge --revise, tier1 --targets - and are counted, not driven):
  LOOP-01  A2.c asks for a re-plan -> the replan phase of A2.c (A1.q revision + search --only) -> A2.m -> A2.c again
  LOOP-02  A1.e: revision-required -> A1.p, A1.q revised -> A1.e again (once)
  LOOP-04  A5 added papers -> A3.b, A3.g, A3 on the additions (then a second snowball round only after >= 10 % growth)
  LOOP-08  A6.d: paywalls ate the budget -> one top-up pass
  LOOP-09  B5 round 2 ReviseHypothesis -> P1 | P2 | P3 .. P3 again
  LOOP-10  coherence gate failed -> one forced revision entering at the step the finding belongs to
  LOOP-11  T09 still failing -> abandon the question, the next generation takes the next one
  LOOP-12  next generation, up to max_num_generations
"""
from __future__ import annotations

import json
from pathlib import Path

from ideate_v2 import rules
from ideate_v2.jsonio import read_json

from .context import RunContext


def allowed(ctx: RunContext, loop_id: str, completed: int, observed: dict | None = None, *, unit: str | None = None,
            step: str | None = None, instance: str = "-") -> dict:
    loop = dict(ctx.reg.get(loop_id))
    bound = dict(loop.get("bound") or {})
    if bound.get("max_iterations") is None and loop_id in ctx.cfg.loop_bounds:
        bound["max_iterations"] = int(ctx.cfg.loop_bounds[loop_id])
        loop["bound"] = bound
    d = rules.evaluate_loop(loop, completed, observed)
    ctx.emit("LOOP_ITERATION" if d["allowed"] else "LOOP_BOUND_REACHED", step_id=step, unit_id=unit, instance=instance,
             message=d["reason"], context={"loop": loop_id, "completed": completed, "observed": observed or {}})
    ctx.say(f"    ⟲ {loop_id}: {d['reason']}")
    return d


# ---------------------------------------------------------------------------------------------- measurements
def relevance_rounds(rd: Path) -> tuple[int, list[str]]:
    """A2.c: (rounds recorded, the query ids of the last round judged `replan`)."""
    p = rd / "step2_relevance_check.json"
    if not p.is_file():
        return 0, []
    data = read_json(p)
    rounds = data.get("rounds") or []
    if not rounds:
        return 0, []
    last = rounds[-1]
    verdicts = last.get("verdicts") or last.get("queries") or []
    if isinstance(verdicts, dict):
        verdicts = [{"id": k, **(v if isinstance(v, dict) else {"verdict": v})} for k, v in verdicts.items()]
    return len(rounds), [str(v.get("id") or v.get("query")) for v in verdicts
                         if isinstance(v, dict) and v.get("verdict") == "replan"]


def protocol_verdict(rd: Path) -> tuple[int, str | None]:
    """A1.e: (rounds, the latest verdict)."""
    p = rd / "step1_protocol_evaluation.json"
    if not p.is_file():
        return 0, None
    data = read_json(p)
    rounds = data.get("rounds") or []
    final = (data.get("final") or {}).get("status")
    last = (rounds[-1] if rounds else {}).get("verdict") if rounds else None
    return len(rounds), final or last


def snowball_growth(rd: Path) -> float | None:
    """A5 round 1's growth of the included set - the same formula as the skill's it_snowball.growth: included
    round-1 snowball papers / included papers before it (None when it cannot be measured)."""
    sb, sl = rd / "step2b_snowball_papers.json", rd / "step3_shortlist.json"
    if not (sb.is_file() and sl.is_file()):
        return None
    s = read_json(sb)
    r1 = next((r for r in s.get("rounds") or [] if r.get("round") == 1), None)
    if not r1 or not r1.get("included_before"):
        return None
    ids = {p.get("id") for p in s.get("papers") or [] if p.get("round") == 1}
    return sum(1 for p in read_json(sl).get("papers") or [] if p.get("id") in ids) / r1["included_before"]


def ready_questions_left(rd: Path) -> list[str]:
    """Ready questions no generation has consumed or abandoned yet."""
    idx = rd / "questions" / "index.json"
    if not idx.is_file():
        return []
    ready = [q["id"] for q in (read_json(idx).get("questions") or []) if q.get("status") == "ready"]
    cfg = rd / "step0_session_config.json"
    used = set()
    if cfg.is_file():
        for c in read_json(cfg).get("consumed") or []:
            used.add(c.get("question") if isinstance(c, dict) else None)
    for gd in rd.glob("gen_*/question.json"):
        try:
            used.add(json.loads(gd.read_text(encoding="utf-8")).get("id"))
        except ValueError:
            pass
    return [q for q in ready if q not in used]
