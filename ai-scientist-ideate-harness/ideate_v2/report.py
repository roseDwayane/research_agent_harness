"""Error records and the three-level report: Unit instance -> step -> overall.

Layout (decision D-07; all under paths the legacy ledger ignores):
  <RD>/_state/errors/<run_id>/units/<unit>@<instance>.jsonl   error records of one Unit instance
  <RD>/_state/errors/<run_id>/events.jsonl                    lifecycle events (ideate_v2.events)
  <RD>/_state/errors/<run_id>/steps/<STEP-id>.json            step reports
  <RD>/_state/errors/<run_id>/overall.json                    the run's report
  <RD>/_state/errors/latest.json                              the latest overall report
  <RD>/ERRORS.md                                              the human view
"""
from __future__ import annotations

from pathlib import Path

from .errors import SEVERITY_RANK, ErrorRecord, IdeateError, now_iso, root_cause
from .events import read_events
from .jsonio import FileLock, append_jsonl_unlocked, read_json, read_jsonl, write_json_atomic, write_text_atomic
from .ledger import ledger_block, load_events, planning_status, unit_states
from .paths import observability_dir, safe_component
from .registry import Registry

REPORT_SCHEMA = "ideate-v2-report/1"
CAVEAT_FILES = ("search_caveats.json", "fulltext_caveats.json", "fusion_caveats.json")
STEP_STATUSES = ("todo", "done", "degraded", "incomplete", "failed", "stopped")


def error_file(run_dir: Path, rec: ErrorRecord) -> Path:
    name = safe_component(f"{rec.unit_id or '_run'}@{rec.instance or '-'}")
    return observability_dir(run_dir, rec.run_id) / "units" / f"{name}.jsonl"


def record_error(run_dir: Path, rec: ErrorRecord) -> dict:
    """Append an error record; an idempotency_key already recorded for that Unit instance returns the earlier one."""
    path = error_file(run_dir, rec)
    with FileLock(path):
        existing, problems = read_jsonl(path)
        if problems:
            raise IdeateError("IDEATE.LEDGER.MALFORMED", f"{path.name} line {problems[0]['line']}: {problems[0]['error']}")
        if rec.idempotency_key:
            for e in existing:
                if e.get("idempotency_key") == rec.idempotency_key:
                    return {"error": e, "deduplicated": True}
        append_jsonl_unlocked(path, rec.to_dict())
    return {"error": rec.to_dict(), "deduplicated": False}


def collect_errors(run_dir: Path, run_id: str) -> tuple[list[dict], list[dict]]:
    d = observability_dir(run_dir, run_id) / "units"
    records, problems = [], []
    for f in sorted(d.glob("*.jsonl")) if d.is_dir() else []:
        recs, probs = read_jsonl(f)
        records += recs
        problems += [{"file": f.name, **p} for p in probs]
    return records, problems


def active_errors(records: list[dict], events: list[dict] | None = None) -> list[dict]:
    """Only the latest attempt of each Unit instance counts; earlier attempts stay as history. With the run's events,
    an attempt started later supersedes too - a retry that succeeded leaves no record of its own, and the failure it
    recovered from is history, not an active error."""
    latest: dict[tuple, int] = {}
    for r in records:
        k = (r.get("unit_id"), r.get("instance", "-"))
        latest[k] = max(latest.get(k, 0), int(r.get("attempt", 1)))
    for e in events or []:
        if e.get("event_type") == "UNIT_STARTED":
            k = (e.get("unit_id"), e.get("instance", "-"))
            if k in latest:
                latest[k] = max(latest[k], int(e.get("attempt", 1)))
    return [r for r in records if int(r.get("attempt", 1)) == latest[(r.get("unit_id"), r.get("instance", "-"))]]


def read_caveats(run_dir: Path) -> list[dict]:
    out = []
    for name in CAVEAT_FILES:
        p = Path(run_dir) / name
        if p.is_file():
            try:
                for c in (read_json(p) or {}).get("caveats") or []:
                    out.append({**c, "source": name})
            except (ValueError, AttributeError):
                out.append({"code": "caveat-file-unreadable", "unit": None, "text": name, "must_disclose": True,
                            "source": name})
    return out


def _step_status(unit_states_: list[str], errs: list[dict], caveats: list[dict]) -> str:
    sev = {e.get("severity") for e in errs}
    if "fatal" in sev:
        return "stopped"
    if "failed" in unit_states_ or "error" in sev:
        return "failed"
    if not unit_states_ or all(s == "todo" for s in unit_states_):
        return "todo" if not errs else "incomplete"
    if any(s != "done" for s in unit_states_):
        return "incomplete"
    if "degraded" in sev or caveats:
        return "degraded"
    return "done"


def _overall_status(statuses: list[str]) -> str:
    if "stopped" in statuses:
        return "stopped"
    if "failed" in statuses:
        return "failed"
    if statuses and all(s in ("done", "degraded") for s in statuses):
        return "degraded" if "degraded" in statuses else "done"
    if all(s == "todo" for s in statuses):
        return "todo"
    return "incomplete"


def build_report(reg: Registry, run_dir: Path, run_id: str, generation: int | None = None, write: bool = True) -> dict:
    rd = Path(run_dir)
    obs = observability_dir(rd, run_id)
    records, problems = collect_errors(rd, run_id)
    run_events, _ = read_events(rd, run_id)
    active = active_errors(records, run_events)
    by_id = {r["error_id"]: r for r in records if "error_id" in r}
    events, ledger_problems = load_events(rd)
    states = unit_states(reg, rd, events)
    caveats = read_caveats(rd)
    plan = planning_status(rd, generation) if generation is not None else None

    steps_out = {}
    for sid in reg.step_order():
        step = reg.get(sid)
        units = step["units"]
        st_list = []
        for u in units:
            if ledger_block(reg, u) is not None:
                st_list.append(states.get(u, {}).get("state", "todo"))
            elif plan and plan.get("exists"):
                st_list.append({"done": "done", "partial": "running"}.get(plan["units"].get(u, {}).get("state"), "todo"))
        errs = [e for e in active if e.get("step_id") == sid or reg.step_of(e.get("unit_id") or "") == sid]
        cav = [c for c in caveats if c.get("unit") in units]
        tracked = bool(st_list) or bool(errs)
        status = _step_status(st_list, errs, cav) if tracked else "todo"
        steps_out[sid] = {
            "schema": REPORT_SCHEMA, "step": sid, "name": step["name"], "status": status,
            "gate": {"entry": step.get("entry_gate"), "exit": step.get("exit_gate")},
            "units": {u: {"state": (states.get(u) or {}).get("state", "not-tracked" if ledger_block(reg, u) is None
                                                                 else "todo"),
                          **{s: sum(1 for e in errs if e.get("unit_id") == u and e.get("severity") == s)
                             for s in ("fatal", "error", "degraded", "warning")}} for u in units},
            "caveats": [{"code": c.get("code"), "unit": c.get("unit"), "must_disclose": bool(c.get("must_disclose"))}
                        for c in cav],
            "error_ids": [e["error_id"] for e in errs if "error_id" in e],
        }
    order = reg.step_order()
    statuses = [steps_out[s]["status"] for s in order]
    roots = []
    for e in active:
        if SEVERITY_RANK.get(e.get("severity"), 0) < SEVERITY_RANK["degraded"]:
            continue
        root, chain = root_cause(by_id, e["error_id"]) if "error_id" in e else (e, [])
        if root is not None and root.get("error_id") == e.get("error_id"):
            down = reg.downstream(e["unit_id"]) if e.get("unit_id") in reg.units else set()
            affected = sorted({reg.step_of(u) for u in down | {e.get("unit_id")} if reg.step_of(u)},
                              key=lambda s: order.index(s) if s in order else 999)
            roots.append({"error_id": e["error_id"], "error_code": e.get("error_code"),
                          "category": e.get("error_category"), "severity": e.get("severity"),
                          "origin": f"{e.get('unit_id')}@{e.get('instance', '-')}", "affected_steps": affected,
                          "must_disclose": bool(e.get("must_disclose")), "recovery_action": e.get("recovery_action")})
    must = sorted({c["code"] for c in caveats if c.get("must_disclose")} |
                  {e["caveat"] for e in active if e.get("must_disclose") and e.get("caveat")})
    overall = {
        "schema": REPORT_SCHEMA, "run_id": run_id, "generated_at": now_iso(), "status": _overall_status(statuses),
        "stopped_at": next((s for s in order if steps_out[s]["status"] in ("stopped", "failed")), None),
        "by_step": {s: steps_out[s]["status"] for s in order},
        "root_causes": roots,
        "propagated": len([e for e in active if e.get("parent_error_id")]),
        "must_disclose": must,
        "counts": {s: sum(1 for e in active if e.get("severity") == s) for s in ("fatal", "error", "degraded", "warning")},
        "history": {"error_records": len(records), "superseded_attempts": len(records) - len(active)},
        "problems": {"error_files": problems, "ledger": ledger_problems},
        "generation": plan,
    }
    if write:
        for sid, rep in steps_out.items():
            write_json_atomic(obs / "steps" / f"{sid}.json", rep)
        write_json_atomic(obs / "overall.json", overall)
        write_json_atomic(rd / "_state" / "errors" / "latest.json", overall)
        write_text_atomic(rd / "ERRORS.md", render_errors_md(overall, steps_out))
    return {"overall": overall, "steps": steps_out}


def render_errors_md(overall: dict, steps: dict) -> str:
    lines = [f"# Errors - run {overall['run_id']}", "",
             f"Status **{overall['status']}**" + (f", stopped at {overall['stopped_at']}" if overall["stopped_at"] else "")
             + f" · generated {overall['generated_at']} by ideate_v2 (do not edit; rebuild with ideate_build_report).",
             "", "| Step | Status | Exit gate | Caveats |", "|---|---|---|---|"]
    for sid, rep in steps.items():
        cav = ", ".join(c["code"] + ("*" if c["must_disclose"] else "") for c in rep["caveats"]) or "-"
        lines.append(f"| {sid} {rep['name']} | {rep['status']} | {rep['gate']['exit'] or '-'} | {cav} |")
    lines += ["", "## Root causes", ""]
    if overall["root_causes"]:
        lines += ["| Error | Code | Category | Severity | Origin | Affects | Action |", "|---|---|---|---|---|---|---|"]
        for r in overall["root_causes"]:
            lines.append(f"| {r['error_id']} | {r['error_code']} | {r['category']} | {r['severity']} | {r['origin']} | "
                         f"{', '.join(r['affected_steps'])} | {r['recovery_action']} |")
    else:
        lines.append("None.")
    lines += ["", "## Must disclose in the idea's Risk Factors", "",
              ", ".join(overall["must_disclose"]) if overall["must_disclose"] else "Nothing.", "",
              "`*` = must disclose. To intervene: edit `_human/` inputs and re-run the Unit named by `next`.", ""]
    return "\n".join(lines)
