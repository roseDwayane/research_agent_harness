"""Executors: what does a Unit's work. The shell (shell.py) calls ``execute`` and then checks what it left.

  Executor            the protocol; a custom implementation (``--agent A3=pkg:Class``) is any class with
                      ``execute(ctx, unit, recipe, phase, gen, attempt) -> ExecResult``
  RecipeExecutor      the default: walks the Unit's recipe step by step
     run step         ScriptStep: a skill command
     write step       ClaudeStep: one claude -p worker (an isolated one for A1.e)
     fanout step      FanoutStep: one worker per batch file, max_parallel at once, a failed batch re-dispatched once

Retry levels (ideate_v2.retry, decision D-08) - each failure is retried by exactly one owner:
  a worker's rejected or missing files   RP-MODEL-OUTPUT  unit-tool       feedback into the same session
  a fan-out batch without an answer      RP-FANOUT-BATCH  unit-tool       the batch re-dispatched
  a network failure of a worker          RP-TRANSPORT     unit-transport  the call repeated after a backoff
  the whole Unit                         RP-UNIT          orchestrator    shell.py, not here
"""
from __future__ import annotations

import json
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ideate_v2 import retry

from . import claude_worker as cw
from .context import CODE_FOR, RunContext, instance_of
from .recipes import Recipe, Step
from .skill import CommandResult, Subs, classify_failure


@dataclass
class ExecResult:
    ok: bool
    errors: list = field(default_factory=list)           # ErrorRecords already recorded
    metrics: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    stopped_at: str | None = None                        # the step that failed (for the report)


class Executor(Protocol):
    def execute(self, ctx: RunContext, unit: str, recipe: Recipe | None, phase: str, gen: int | None,
                attempt: int) -> ExecResult: ...


def _add(m: dict, more: dict) -> dict:
    for k, v in more.items():
        m[k] = m.get(k, 0) + v
    return m


class RecipeExecutor:
    """The default executor: the recipe's steps, in order, with the retry levels above."""

    def __init__(self) -> None:
        self._sessions: dict[tuple, str] = {}

    # ------------------------------------------------------------------------------------------------ driver
    def execute(self, ctx: RunContext, unit: str, recipe: Recipe | None, phase: str, gen: int | None,
                attempt: int) -> ExecResult:
        if recipe is None:
            rec = ctx.error("IDEATE.ENV.MISSING", f"{unit} has no recipe (contracts/recipes/)", unit=unit,
                            instance=instance_of(gen, phase), attempt=attempt)
            return ExecResult(False, [rec])
        subs = ctx.subs(gen)
        subs.phase = phase
        inst = instance_of(gen, phase)
        log = ctx.state_dir / f"{unit}@{inst}" / f"attempt_{attempt}"
        log.mkdir(parents=True, exist_ok=True)
        steps = [s for s in recipe.steps(phase) if ctx.cfg.depth in (s.spec.get("depth") or [ctx.cfg.depth])]
        res = ExecResult(True)
        i, last_write, feedback_rounds = 0, None, 1
        while i < len(steps):
            s = steps[i]
            label = f"{phase}.{i:02d}.{s.kind}"
            if s.spec.get("when_file") and not Path(ctx.skill.expand(s.spec["when_file"], subs, quote=False)).exists():
                i += 1
                continue
            if s.kind == "freeze":
                for src in s.spec["freeze"]:
                    f = Path(ctx.skill.expand(src, subs, quote=False))
                    dst = f.with_name(f"{f.stem}_r1{f.suffix}")
                    if f.is_file() and not dst.exists():
                        shutil.copy2(f, dst)
                        res.notes.append(f"froze {dst.name}")
                i += 1
                continue
            if s.kind == "run":
                r = self._run(ctx, unit, s, subs, log, label)
                if r.ok and s.spec.get("capture"):
                    cap = s.spec["capture"]
                    m = re.search(cap["regex"], r.stdout or "")
                    if not m:
                        rec = ctx.error("IDEATE.TOOL.FAILED", f"`{_short(r.command)}` printed no {cap['name']} "
                                        f"(/{cap['regex']}/): {r.tail()}", unit=unit, instance=inst, attempt=attempt)
                        return self._fail(res, rec, label)
                    subs.extra[cap["name"]] = m.group(1)
                if r.ok:
                    i += 1
                    continue
                if s.spec.get("optional"):
                    res.notes.append(f"optional step failed: {r.command}: {r.tail()}")
                    ctx.error(f"{unit}:OPTIONAL", f"optional step failed: {r.tail()}", unit=unit, instance=inst,
                              attempt=attempt, category="tool_invocation", severity="warning",
                              context={"command": r.command})
                    i += 1
                    continue
                if s.spec.get("submit") and last_write is not None:
                    err = {"error_category": "model_output", "severity": "error", "retryable": True,
                           "error_id": f"{unit}:{label}"}
                    d = retry.decide(ctx.reg, "RP-MODEL-OUTPUT", err, feedback_rounds, "unit-tool")
                    if d["action"] == "retry":
                        ctx.say(f"      ↺ {unit}: {r.command.split()[1] if len(r.command.split()) > 1 else ''} "
                                f"refused - back to the worker ({d['reason']})")
                        ok, m = self._feedback(ctx, unit, steps[last_write], subs, log, label, r, attempt)
                        _add(res.metrics, m)
                        feedback_rounds += 1
                        if ok:
                            i = last_write + 1
                            continue
                    rec = ctx.error("IDEATE.WORKER.OUTPUT", f"`{_short(r.command)}` refused the worker's files after "
                                    f"{feedback_rounds - 1} revision(s): {r.tail()}", unit=unit, instance=inst,
                                    attempt=attempt, context={"command": r.command, "stdout": r.stdout[-2000:]})
                    return self._fail(res, rec, label)
                return self._fail(res, self._command_error(ctx, unit, inst, attempt, r), label)
            if s.kind == "write":
                ok, m, rec = self._write(ctx, unit, s, subs, log, label, attempt)
                _add(res.metrics, m)
                if not ok:
                    return self._fail(res, rec, label)
                last_write = i
                i += 1
                continue
            if s.kind == "fanout":
                ok, m, rec = self._fanout(ctx, unit, s, subs, log, label, attempt)
                _add(res.metrics, m)
                if not ok:
                    return self._fail(res, rec, label)
                i += 1
                continue
        return res

    @staticmethod
    def _fail(res: ExecResult, rec, label: str) -> ExecResult:
        res.ok, res.stopped_at = False, label
        if rec is not None:
            res.errors.append(rec)
        return res

    # ------------------------------------------------------------------------------------------------ run step
    def _run(self, ctx: RunContext, unit: str, s: Step, subs: Subs, log: Path, label: str) -> CommandResult:
        cmd = s.spec["run"]
        ctx.say(f"      $ {_short(ctx.skill.expand(cmd, subs, quote=False))}")
        r = ctx.skill.run(cmd, subs)
        (log / f"{label}.log").write_text(f"$ {r.command}\n# exit {r.returncode} in {r.seconds}s\n\n{r.stdout}\n"
                                          f"--- stderr ---\n{r.stderr}", encoding="utf-8")
        return r

    def _command_error(self, ctx: RunContext, unit: str, inst: str, attempt: int, r: CommandResult):
        text = f"{r.stdout[-1500:]}\n{r.stderr[-1500:]}"
        cat = "timeout" if r.returncode == 124 else classify_failure(text)
        return ctx.error(CODE_FOR[cat], f"`{_short(r.command)}` exited {r.returncode}: {r.tail()}", unit=unit,
                         instance=inst, attempt=attempt, context={"command": r.command, "exit": r.returncode})

    # ------------------------------------------------------------------------------------------------ write step
    def _prompt(self, ctx: RunContext, unit: str, body: dict, subs: Subs, extra: str = "") -> tuple[str, str]:
        exp = lambda t: ctx.skill.expand(t, subs, quote=False)            # noqa: E731
        task = exp(body["task"])
        reads = [exp(x) for x in body.get("reads") or []]
        writes = [exp(x) for x in body.get("writes") or []]
        lines = [task, ""]
        if reads:
            lines += ["Read first:"] + [f"- {x}" for x in reads] + [""]
        if writes:
            lines += ["You must leave these files written:"] + [f"- {x}" for x in writes] + [""]
        lines += [f"Research folder: {subs.rd}"] + ([f"Generation folder: {subs.gen_dir}"] if subs.gen_dir else [])
        if extra:
            lines += ["", extra]
        system = cw.system_prompt(ctx.cfg.module_root, ctx.reg.units[unit], ctx.reg.legacy_card(unit),
                                  list(body.get("rules") or []), list(body.get("commands") or []))
        return "\n".join(lines), system

    def _worker_kw(self, ctx: RunContext, unit: str, body: dict, subs: Subs, log: Path) -> dict:
        bin_dir = cw.write_shims(ctx.state_dir / "bin", ctx.cfg)
        deny = [Path(ctx.skill.expand(p, subs, quote=False)) for p in body.get("forbid") or []]
        return dict(allowed=cw.allowed_bash(list(body.get("commands") or [])) + list(body.get("tools") or []),
                    add_dirs=[d for d in (ctx.topic.parent if ctx.topic else None, ctx.cfg.module_root / "references")
                              if d is not None and d != subs.rd],
                    deny_read=deny,
                    budget_usd=ctx.cfg.budget(unit), bin_dir=bin_dir, log_dir=log)

    def _call(self, ctx: RunContext, unit: str, label: str, **kw) -> cw.WorkerResult:
        """One worker call with the transport retry (RP-TRANSPORT, owner unit-transport)."""
        attempt = 1
        while True:
            wr = cw.run_worker(ctx.cfg, label=f"{label}.a{attempt}", **kw)
            ctx.add_usage(wr.metrics)
            if wr.ok or wr.error_category not in ("external_service", "timeout"):
                return wr
            d = retry.decide(ctx.reg, "RP-TRANSPORT", {"error_category": wr.error_category, "severity": "degraded",
                                                       "retryable": True, "error_id": f"{unit}:{label}"},
                             attempt, "unit-transport")
            if d["action"] != "retry":
                return wr
            ctx.say(f"      … {unit}: worker {wr.error_category}, again in {d['delay_s']}s")
            time.sleep(d["delay_s"])
            attempt += 1

    def _write(self, ctx: RunContext, unit: str, s: Step, subs: Subs, log: Path, label: str, attempt: int):
        body = s.spec["write"]
        inst = instance_of(subs.gen, subs.phase)
        task, system = self._prompt(ctx, unit, body, subs)
        writes = [Path(ctx.skill.expand(x, subs, quote=False)) for x in body.get("writes") or []]
        kw = self._worker_kw(ctx, unit, body, subs, log)
        cwd = subs.rd
        if body.get("isolated"):
            kw["add_dirs"] = []                            # an independent reader sees its own folder only
            cwd = ctx.state_dir / "isolated" / f"{unit}@{inst.replace('/', '_')}.{label}"
            if cwd.exists():
                shutil.rmtree(cwd)
            cwd.mkdir(parents=True)
            for x in body.get("reads") or []:
                src = Path(ctx.skill.expand(x, subs, quote=False))
                if src.is_file():
                    shutil.copy2(src, cwd / src.name)
            task = task.replace(str(subs.rd) + "/", "./")
            task += ("\n\nYou are an independent reader: work only with the files in this folder. Write your answer as "
                     + ", ".join(f"./{w.name}" for w in writes) + ".")
        ctx.say(f"      ✎ {unit}: worker" + (" (isolated)" if body.get("isolated") else ""))
        ctx.emit("TOOL_CALLED", unit_id=unit, instance=inst, attempt=attempt, tool="claude -p", actor="worker",
                 context={"step": label})
        wr = self._call(ctx, unit, label, task=task, system=system, cwd=cwd, **kw)
        if wr.session_id:
            self._sessions[(unit, inst, label)] = wr.session_id
        if not wr.ok:
            ctx.emit("TOOL_FAILED", unit_id=unit, instance=inst, attempt=attempt, tool="claude -p", actor="worker",
                     message=wr.error[:300], metrics=wr.metrics)
            code = CODE_FOR.get(wr.error_category, "IDEATE.WORKER.FAILED")
            return False, wr.metrics, ctx.error(code, f"worker failed: {wr.error}", unit=unit, instance=inst,
                                                attempt=attempt, context={"step": label})
        ctx.emit("TOOL_RETURNED", unit_id=unit, instance=inst, attempt=attempt, tool="claude -p", actor="worker",
                 metrics=wr.metrics, message=wr.text[:300])
        if body.get("isolated"):
            for w in writes:
                if (cwd / w.name).is_file():
                    w.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(cwd / w.name, w)
        missing = [w for w in writes if not w.exists()]
        metrics = dict(wr.metrics)
        rounds = 1
        while missing:
            d = retry.decide(ctx.reg, "RP-MODEL-OUTPUT", {"error_category": "model_output", "severity": "error",
                                                          "retryable": True, "error_id": f"{unit}:{label}"},
                             rounds, "unit-tool")
            if d["action"] != "retry" or not wr.session_id or body.get("isolated"):
                return False, metrics, ctx.error("IDEATE.WORKER.OUTPUT", "the worker did not write: " +
                                                 ", ".join(str(m) for m in missing), unit=unit, instance=inst,
                                                 attempt=attempt, context={"step": label})
            msg = "You have not written: " + ", ".join(str(m) for m in missing) + ". Write them now, then stop."
            wr = self._call(ctx, unit, f"{label}.fix{rounds}", task=msg, system=system, cwd=cwd, resume=wr.session_id,
                            **kw)
            _add(metrics, wr.metrics)
            rounds += 1
            missing = [w for w in writes if not w.exists()]
        return True, metrics, None

    def _feedback(self, ctx: RunContext, unit: str, write_step: Step, subs: Subs, log: Path, label: str,
                  r: CommandResult, attempt: int) -> tuple[bool, dict]:
        """A submit command refused the worker's files: tell the same session what it said."""
        inst = instance_of(subs.gen, subs.phase)
        key = next((k for k in reversed(list(self._sessions)) if k[0] == unit and k[1] == inst), None)
        session = self._sessions.get(key) if key else None
        body = write_step.spec["write"]
        if not session or body.get("isolated"):
            return False, {}
        task, system = self._prompt(ctx, unit, body, subs)
        out = (r.stdout or "")[-3500:]
        msg = (f"The conductor ran `{_short(r.command)}` on your files and it refused them (exit {r.returncode}):\n\n"
               f"```\n{out}\n{(r.stderr or '')[-800:]}\n```\n\nFix what it reports in the same files - answer each "
               "finding, do not reword until it is silent - then stop.")
        kw = self._worker_kw(ctx, unit, body, subs, log)
        wr = self._call(ctx, unit, f"{label}.feedback", task=msg, system=system, cwd=subs.rd, resume=session, **kw)
        if wr.session_id:
            self._sessions[key] = wr.session_id
        ctx.emit("TOOL_RETURNED" if wr.ok else "TOOL_FAILED", unit_id=unit, instance=inst, attempt=attempt,
                 tool="claude -p --resume", actor="worker", metrics=wr.metrics, message=(wr.text or wr.error)[:300])
        return wr.ok, wr.metrics

    # ------------------------------------------------------------------------------------------------ fanout
    @staticmethod
    def _batch_outs(batch: Path, how: str, rd: Path) -> list[Path]:
        """The answer file(s) of one batch:
        field:<key>         batch[key], relative to the batch's folder (A3: "out": "batch_01.out.json")
        rdfield:<key>       batch[key], relative to the research folder (A7.X2: "answer": "knowledge/_work/...")
        items:<list>.<key>  one per item, research-folder relative (A7.D: papers[].answer)
        suffix:<a>><b>      the batch file's name with <a> replaced by <b>"""
        kind, _, arg = how.partition(":")
        if kind == "suffix":
            src, _, dst = arg.partition(">")
            return [batch.with_name(batch.name.replace(src, dst))]
        data = json.loads(batch.read_text(encoding="utf-8"))
        if kind == "items":
            lst, _, key = arg.partition(".")
            names = [it.get(key) for it in data.get(lst) or [] if isinstance(it, dict)]
            base = rd
        else:
            names, base = [data.get(arg)], (batch.parent if kind == "field" else rd)
        if not names or not all(names):
            raise ValueError(f"{batch.name}: no {arg!r} to name the answer")
        return [Path(n) if Path(n).is_absolute() else base / n for n in names]

    def _fanout(self, ctx: RunContext, unit: str, s: Step, subs: Subs, log: Path, label: str, attempt: int):
        body = s.spec["fanout"]
        inst = instance_of(subs.gen, subs.phase)
        pattern = ctx.skill.expand(body["batches"], subs, quote=False)
        root = subs.rd
        batches = sorted(root.glob(pattern[len(str(root)) + 1:] if pattern.startswith(str(root)) else pattern))
        brief = Path(ctx.skill.expand(body["brief"], subs, quote=False)) if body.get("brief") else None
        todo = []
        for b in batches:
            outs = self._batch_outs(b, body["out"], root)
            if not all(_valid_answer(o) for o in outs):
                todo.append((b, outs))
        ctx.say(f"      ⇉ {unit}: {len(todo)} of {len(batches)} batch(es) to answer, {ctx.cfg.max_parallel} at once")
        if not batches:
            return False, {}, ctx.error("IDEATE.ARTIFACT.MISSING", f"no batch files match {body['batches']}", unit=unit,
                                        instance=inst, attempt=attempt, context={"step": label})
        metrics: dict = {}
        system = cw.system_prompt(ctx.cfg.module_root, ctx.reg.units[unit], ctx.reg.legacy_card(unit),
                                  list(body.get("rules") or []), list(body.get("commands") or []))
        kw = self._worker_kw(ctx, unit, body, subs, log)

        def one(item, tries=1):
            b, outs = item
            out = outs[0] if len(outs) == 1 else ", ".join(str(o) for o in outs)
            task = body["task"].format(batch=b, out=out, brief=brief or "")
            task = ctx.skill.expand(task, subs, quote=False)
            wr = self._call(ctx, unit, f"{label}.{b.stem}.t{tries}", task=task, system=system, cwd=root, **kw)
            return item, wr

        tries = 1
        while todo:
            ctx.emit("TOOL_CALLED", unit_id=unit, instance=inst, attempt=attempt, tool="claude -p fan-out",
                     actor="worker", context={"step": label, "batches": len(todo), "try": tries})
            with ThreadPoolExecutor(max_workers=ctx.cfg.max_parallel) as pool:
                results = list(pool.map(lambda it: one(it, tries), todo))
            failed = []
            for (b, outs), wr in results:
                _add(metrics, wr.metrics)
                if not (wr.ok and all(_valid_answer(o) for o in outs)):
                    failed.append(((b, outs), wr))
            ctx.emit("TOOL_RETURNED", unit_id=unit, instance=inst, attempt=attempt, tool="claude -p fan-out",
                     actor="worker", metrics=metrics, context={"step": label, "failed": len(failed)})
            if not failed:
                return True, metrics, None
            d = retry.decide(ctx.reg, "RP-FANOUT-BATCH", {"error_category": "model_output", "severity": "error",
                                                          "retryable": True, "error_id": f"{unit}:{label}"},
                             tries, "unit-tool")
            if d["action"] != "retry":
                names = ", ".join(b.name for (b, _), _ in failed[:8])
                why = "; ".join((wr.error or "no valid answer file")[:120] for _, wr in failed[:3])
                return False, metrics, ctx.error("IDEATE.WORKER.OUTPUT", f"{len(failed)} batch(es) without a valid "
                                                 f"answer after {tries} dispatch(es): {names} ({why})", unit=unit,
                                                 instance=inst, attempt=attempt, context={"step": label})
            ctx.say(f"      ↺ {unit}: re-dispatching {len(failed)} batch(es) ({d['reason']})")
            todo = [it for it, _ in failed]
            tries += 1
        return True, metrics, None


def _valid_answer(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    if path.suffix == ".json":
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return False
    return True


def _short(cmd: str, width: int = 140) -> str:
    """A command line for the console: the script and its arguments, long paths shortened."""
    words = [w.split("/")[-1] if w.startswith("/") and len(w) > 40 else w for w in cmd.split()]
    words = [w for w in words if not w.endswith("python") and not w.endswith("python3")]
    s = " ".join(words)
    return s if len(s) <= width else s[:width - 1] + "…"
