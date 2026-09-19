"""The runner: executes steps in order, enforcing inputs, checkpoints and the manifest."""
from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Any, Callable

from . import checkpoints
from .manifest import RunManifest, StepRecord
from .session import CHECKPOINT_AFTER, STEP_INPUTS, STEP_NAMES, Session, now_iso
from .steps import s1_init, s2_search, s3_screen, s4_export, s5_fulltext, s6_sota, s7_gaps, s8_hypothesis, s9_write
from .steps.base import Context, StepOutput
from .utils import sha256_file

STEPS: dict[int, Callable[[Context], StepOutput]] = {1: s1_init.run, 2: s2_search.run, 3: s3_screen.run, 4: s4_export.run, 5: s5_fulltext.run, 6: s6_sota.run, 7: s7_gaps.run, 8: s8_hypothesis.run, 9: s9_write.run}


class PipelineError(RuntimeError):
    pass


def run_range(ctx: Context, first: int, last: int, *, run_id: str | None = None, stop_at_checkpoint: bool = True) -> RunManifest:
    s = ctx.session
    rid = run_id or time.strftime("%Y%m%dT%H%M%S")
    manifest = RunManifest(s.dir, rid, now_iso(), ctx.config.public_dict(), s.cache.mode, ctx.checkpoint_mode)
    try:
        for step in range(first, last + 1):
            # checkpoint gate before this step
            prev_cp = CHECKPOINT_AFTER.get(step - 1)
            if prev_cp:
                try:
                    checkpoints.resolve(ctx, prev_cp)
                except checkpoints.NeedsHuman as e:
                    ctx.say(e.material)
                    ctx.say(f"\n⏸ Paused at Checkpoint {e.checkpoint}. Record a decision with `scholar-research checkpoint {e.checkpoint} …` or pass --decisions / --auto, then `run` again.")
                    manifest.add_step(StepRecord(step=step, name=STEP_NAMES[step], status="blocked", notes=[f"checkpoint {e.checkpoint} pending"]))
                    break
            missing = s.missing_inputs(step)
            if missing:
                raise PipelineError(f"step {step} ({STEP_NAMES[step]}) missing inputs: {', '.join(missing)} — run earlier steps first")
            rec = StepRecord(step=step, name=STEP_NAMES[step], started_at=now_iso())
            rec.inputs = {f: sha256_file(s.path(f)) for f in STEP_INPUTS[step]}
            cache_before = dict(s.cache.stats.as_dict())
            llm_before = s.ledger.totals.as_dict()
            t0 = time.time()
            ctx.say(f"\n▶ Step {step}: {STEP_NAMES[step]}")
            try:
                out = STEPS[step](ctx)
            except Exception as e:  # noqa: BLE001
                rec.status = "failed"
                rec.error = f"{type(e).__name__}: {e}"
                rec.wall_seconds = round(time.time() - t0, 3)
                manifest.add_step(rec)
                ctx.say(traceback.format_exc(limit=3))
                raise PipelineError(f"step {step} failed: {rec.error}") from e
            rec.status = "ok"
            rec.wall_seconds = round(time.time() - t0, 3)
            rec.outputs = manifest.hash_outputs(out.files)
            rec.notes = out.notes
            rec.prompt_versions = dict(ctx.llm.prompt_versions) if ctx._llm is not None else {}
            rec.cache = _delta(cache_before, s.cache.stats.as_dict())
            rec.llm = _delta(llm_before, s.ledger.totals.as_dict())
            manifest.add_step(rec)
            s.set_current_step(step)
            _print_summary(ctx, step, out)
            # checkpoint after this step (only if there is a next step to run or we want to surface it)
            cp = CHECKPOINT_AFTER.get(step)
            if cp and stop_at_checkpoint and step == last and not s.checkpoint_resolved(cp):
                try:
                    checkpoints.resolve(ctx, cp)
                except checkpoints.NeedsHuman as e:
                    ctx.say(e.material)
                    ctx.say(f"\n⏸ Checkpoint {e.checkpoint} pending. Record a decision with `scholar-research checkpoint {e.checkpoint} …` then `run`.")
    finally:
        manifest.finalize(s.cache.stats.as_dict(), s.ledger.totals.as_dict())
        ctx.close()
    return manifest


def _delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k in ("hits", "misses", "writes", "calls", "cache_hits", "input_tokens", "output_tokens"):
        if k in after:
            out[k] = after[k] - before.get(k, 0)
    return out


def _print_summary(ctx: Context, step: int, out: StepOutput) -> None:
    for k, v in out.summary.items():
        if isinstance(v, list) and v and isinstance(v[0], (tuple, list)):
            ctx.say(f"  {k}:")
            for row in v[:10]:
                ctx.say("    - " + " | ".join(str(x) for x in row))
        elif isinstance(v, list):
            ctx.say(f"  {k}: {', '.join(str(x) for x in v[:15])}{' …' if len(v) > 15 else ''}")
        else:
            ctx.say(f"  {k}: {v}")
    for n in out.notes:
        ctx.say(f"  ⚠ {n}")
    ctx.say("  files: " + ", ".join(str(f.relative_to(ctx.session.dir)) for f in out.files))


def snapshot(session: Session, steps: list[int]) -> dict[str, str]:
    from .session import STEP_OUTPUTS

    out = {}
    for st in steps:
        for f in STEP_OUTPUTS[st]:
            p = session.path(f)
            if p.exists():
                out[f] = sha256_file(p)
        extra = session.path(f"step{st}_full_text") if st == 5 else None
        if extra and extra.exists():
            for p in sorted(extra.glob("*.md")):
                out[str(p.relative_to(session.dir))] = sha256_file(p)
    return out
