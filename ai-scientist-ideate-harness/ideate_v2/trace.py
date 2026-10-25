"""Traceability: reconstruct what happened to a Unit, or how an error came about and what it reaches."""
from __future__ import annotations

from pathlib import Path

from .errors import IdeateError, root_cause
from .events import read_events
from .ledger import load_events, unit_states
from .registry import Registry
from .report import collect_errors

MAX_ITEMS = 100


def contract_summary(reg: Registry, unit_id: str) -> dict:
    u = reg.units[unit_id]
    step = u["step"]
    return {"step": step, "requires": reg.requires(unit_id), "dependents": reg.dependents(unit_id),
            "gates_out": [g["id"] for g in reg.arch.get("gates") or [] if unit_id in g.get("requires_done", [])],
            "entry_gate": reg.get(step).get("entry_gate"),
            "loops": [lp["id"] for lp in reg.arch.get("loops") or []
                      if lp["from"] == unit_id or unit_id in lp["to"] or step in lp["to"]],
            "substeps": [s["id"] for s in reg.substeps_of(unit_id)]}


def trace_unit(reg: Registry, run_dir: Path, unit_id: str, run_id: str | None = None) -> dict:
    if unit_id not in reg.units:
        raise IdeateError("IDEATE.INPUT.UNKNOWN_ID", f"no Unit {unit_id!r}")
    rd = Path(run_dir)
    ledger, problems = load_events(rd)
    mine = [e for e in ledger if e.get("unit") == unit_id]
    state = unit_states(reg, rd, ledger).get(unit_id)
    out = {"unit": unit_id, "contract": contract_summary(reg, unit_id), "state": state,
           "ledger_events": [{k: e.get(k) for k in ("ev", "inst", "at", "why", "degraded", "model", "counts")
                              if e.get(k) is not None} for e in mine[-MAX_ITEMS:]],
           "ledger_problems": problems}
    if run_id:
        events, _ = read_events(rd, run_id)
        records, _ = collect_errors(rd, run_id)
        out["v2_events"] = [e for e in events if e.get("unit_id") == unit_id][-MAX_ITEMS:]
        out["errors"] = [r for r in records if r.get("unit_id") == unit_id][-MAX_ITEMS:]
    return out


def trace_error(reg: Registry, run_dir: Path, run_id: str, error_id: str) -> dict:
    records, _ = collect_errors(Path(run_dir), run_id)
    by_id = {r["error_id"]: r for r in records if "error_id" in r}
    if error_id not in by_id:
        raise IdeateError("IDEATE.INPUT.UNKNOWN_ID", f"no error {error_id!r} in run {run_id}")
    root, chain = root_cause(by_id, error_id)
    unit = (root or {}).get("unit_id")
    reach = sorted(reg.downstream(unit)) if unit in reg.units else []
    events, _ = read_events(Path(run_dir), run_id)
    related = [e for e in events if e.get("error_id") in set(chain)]
    return {"error": by_id[error_id], "chain": chain, "root_cause": root, "is_root": chain[-1:] == [error_id],
            "downstream_units": reach, "related_events": related[-MAX_ITEMS:]}
