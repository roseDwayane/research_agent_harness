"""Business adapters of the ideate_v2 MCP tools. Each handler takes (ctx, validated args) and returns the tool's data
object (mcp/ideate_v2_mcp/schemas/tools.json). The logic itself lives in ideate_v2; handlers only map arguments, enforce the path
policy, and record events when the caller supplies a run."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ideate_v2.errors import (CATEGORIES, ErrorRecord, IdeateError, category_of, new_run_id, new_trace_id)
from ideate_v2.events import append_event, build_event, read_events
from ideate_v2.gates import evaluate_gate
from ideate_v2.ledger import load_events, next_runnable, planning_status, unit_states
from ideate_v2.paths import PathPolicy
from ideate_v2.registry import Registry
from ideate_v2.report import build_report as _build_report
from ideate_v2.report import record_error as _record_error
from ideate_v2.retry import decide
from ideate_v2.rules import evaluate_loop
from ideate_v2.spec import canonical_spec, classification
from ideate_v2.trace import trace_error, trace_unit


@dataclass
class Context:
    registry: Registry
    policy: PathPolicy

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Context":
        return cls(Registry.load(), PathPolicy.from_env(env if env is not None else dict(os.environ)))


def _unit_checked(ctx: Context, unit_id: str | None) -> str | None:
    if unit_id is not None and unit_id not in ctx.registry.units:
        raise IdeateError("IDEATE.INPUT.UNKNOWN_ID", f"no Unit {unit_id!r}", context={"unit_id": unit_id})
    return unit_id


def _run_trace_id(rd: Path, run_id: str, given: str | None) -> str:
    """The run's trace id: the one given, else the one RUN_STARTED recorded, else a new one."""
    if given:
        return given
    events, _ = read_events(rd, run_id)
    return next((e["trace_id"] for e in events if e.get("event_type") == "RUN_STARTED"), None) or new_trace_id()


def _record(rd: Path, event_type: str, run_id: str, trace_id: str | None, **fields) -> tuple[str, str]:
    """Append an event in the run's trace. -> (event_id, trace_id); the caller answers under that trace id."""
    ev = build_event(event_type, run_id=run_id, trace_id=_run_trace_id(rd, run_id, trace_id), **fields)
    saved = append_event(rd, ev)["event"]
    return saved["event_id"], saved["trace_id"]


# ------------------------------------------------------------------------------------------------ registry
def list_units(ctx: Context, a: dict) -> dict:
    reg = ctx.registry
    out = []
    for uid in reg.unit_order():
        u = reg.units[uid]
        block = reg.get(u["step"])["block"]
        if (a.get("block") and block != a["block"]) or (a.get("step") and u["step"] != a["step"]) or \
                (a.get("kind") and u["kind"] != a["kind"]):
            continue
        out.append({"id": uid, "name": u["name"], "name_zh": u["name_zh"], "step": u["step"], "block": block,
                    "kind": u["kind"], "deterministic": u["deterministic"], "llm": u["llm"], "on_ledger": u["on_ledger"],
                    "maturity": (reg.legacy_card(uid) or {}).get("achieved_level", "no card"),
                    "verdict": u["verdict"]["decision"]})
    return {"count": len(out), "units": out}


def get_contract(ctx: Context, a: dict) -> dict:
    reg, eid = ctx.registry, a["entity_id"]
    kind = reg.kind_of(eid)
    if kind is None:
        raise IdeateError("IDEATE.INPUT.UNKNOWN_ID", f"no registry entity {eid!r}", context={"entity_id": eid})
    out = {"id": eid, "kind": kind, "entity": reg.get(eid)}
    if kind == "unit":
        out["canonical_spec"] = canonical_spec(reg, eid)
        out["substeps"] = reg.substeps_of(eid)
        out["classification"] = classification(reg, eid)
    return out


# ------------------------------------------------------------------------------------------------ run state
def run_status(ctx: Context, a: dict) -> dict:
    rd = ctx.policy.resolve_run_dir(a["run_dir"])
    events, problems = load_events(rd)
    states = unit_states(ctx.registry, rd, events)
    return {"run_dir": str(rd), "ledger": {"events": len(events), "problems": problems}, "units": states,
            "next": next_runnable(ctx.registry, states),
            "planning": planning_status(rd, a["generation"]) if a.get("generation") else None}


def check_gate(ctx: Context, a: dict) -> dict:
    rd = ctx.policy.resolve_run_dir(a["run_dir"])
    res = evaluate_gate(ctx.registry, rd, a["gate_id"], a.get("generation"))
    if a.get("run_id"):
        res["recorded_event_id"], res["trace_id"] = _record(
            rd, "GATE_CHECKED", a["run_id"], a.get("trace_id"), step_id=res["to_step"],
            status="passed" if res["passed"] else "failed", context={"gate": res["gate"], "counts": res["counts"]})
    return res


def check_loop(ctx: Context, a: dict) -> dict:
    reg, lid = ctx.registry, a["loop_id"]
    if reg.kind_of(lid) != "loop":
        raise IdeateError("IDEATE.INPUT.UNKNOWN_ID", f"no loop {lid!r}")
    res = {"loop": lid, **evaluate_loop(reg.get(lid), a["completed"], a.get("observed"))}
    if a.get("run_dir") and a.get("run_id"):
        rd = ctx.policy.resolve_run_dir(a["run_dir"])
        res["recorded_event_id"], res["trace_id"] = _record(
            rd, "LOOP_ITERATION" if res["allowed"] else "LOOP_BOUND_REACHED", a["run_id"], a.get("trace_id"),
            unit_id=_unit_checked(ctx, a.get("unit_id")), message=res["reason"],
            context={"loop": lid, "completed": a["completed"], "observed": a.get("observed") or {}})
    elif a.get("run_dir") or a.get("run_id"):
        raise IdeateError("IDEATE.INPUT.INVALID", "recording a loop decision needs both run_dir and run_id")
    return res


# ------------------------------------------------------------------------------------------------ observability
def record_event(ctx: Context, a: dict) -> dict:
    rd = ctx.policy.resolve_run_dir(a["run_dir"])
    et = a["event_type"]
    run_id = a.get("run_id")
    if run_id is None:
        if et != "RUN_STARTED":
            raise IdeateError("IDEATE.INPUT.INVALID", f"{et} needs the run_id returned by RUN_STARTED")
        run_id = new_run_id()
    trace_id = a.get("trace_id") or (new_trace_id() if et == "RUN_STARTED" else _run_trace_id(rd, run_id, None))
    unit = _unit_checked(ctx, a.get("unit_id"))
    step = a.get("step_id")
    if unit and step and ctx.registry.step_of(unit) != step:
        raise IdeateError("IDEATE.INPUT.INVALID", f"{unit} belongs to {ctx.registry.step_of(unit)}, not {step}")
    if step and ctx.registry.kind_of(step) != "step":
        raise IdeateError("IDEATE.INPUT.UNKNOWN_ID", f"no step {step!r}")
    ev = build_event(et, run_id=run_id, trace_id=trace_id, unit_id=unit,
                     step_id=step or (ctx.registry.step_of(unit) if unit else None), instance=a.get("instance", "-"),
                     attempt=a.get("attempt", 1), actor=a.get("actor"), tool=a.get("tool"), status=a.get("status"),
                     message=a.get("message"), error_id=a.get("error_id"), metrics=a.get("metrics"),
                     context=a.get("context"), idempotency_key=a.get("idempotency_key"),
                     parent_span_id=a.get("parent_span_id"))
    res = append_event(rd, ev)
    return {"event": res["event"], "deduplicated": res["deduplicated"], "run_id": run_id,
            "trace_id": res["event"]["trace_id"]}


def record_error(ctx: Context, a: dict) -> dict:
    rd = ctx.policy.resolve_run_dir(a["run_dir"])
    code = a["error_code"]
    try:
        cat = category_of(code)
    except ValueError as e:
        raise IdeateError("IDEATE.INPUT.INVALID", str(e)) from e
    unit = _unit_checked(ctx, a.get("unit_id"))
    if ":" in code and not code.startswith("IDEATE."):
        owner = code.split(":", 1)[0].split("/", 1)[0]
        if owner not in ctx.registry.units:
            raise IdeateError("IDEATE.INPUT.INVALID", f"check code {code!r} names no Unit")
        if unit and owner != unit:
            raise IdeateError("IDEATE.INPUT.INVALID", f"check code {code!r} belongs to {owner}, not {unit}")
        unit = unit or owner
    step = a.get("step_id") or (ctx.registry.step_of(unit) if unit else None)
    default_retry, default_sev, _ = CATEGORIES[cat]
    retryable = a.get("retryable", default_retry)
    rec = ErrorRecord(
        error_code=code, error_category=cat, error_message=a["error_message"], severity=a.get("severity", default_sev),
        retryable=retryable, unit_id=unit, step_id=step, run_id=a["run_id"], trace_id=a["trace_id"],
        attempt=a.get("attempt", 1), parent_error_id=a.get("parent_error_id"), context=a.get("context") or {},
        recovery_action=a.get("recovery_action") or ("retry" if retryable else
                                                    "fix-input" if cat == "input_validation" else "stop"),
        instance=a.get("instance", "-"), caveat=a.get("caveat"), must_disclose=a.get("must_disclose", False),
        origin=a.get("origin") or {}, idempotency_key=a.get("idempotency_key"))
    return _record_error(rd, rec)


def retry_decision(ctx: Context, a: dict) -> dict:
    res = decide(ctx.registry, a["policy_id"], a["error"], a["attempts_done"], a["requested_by"])
    if a.get("record"):
        missing = [k for k in ("run_dir", "run_id", "unit_id") if not a.get(k)]
        if missing:
            raise IdeateError("IDEATE.INPUT.INVALID", f"record=true needs {', '.join(missing)}")
        event_type = ("RETRY_SCHEDULED" if res["action"] == "retry" else
                      "RETRY_EXHAUSTED" if res.get("code") == "IDEATE.RETRY.EXHAUSTED" else
                      "ESCALATED" if res["action"] == "escalate" else None)
        if event_type:
            rd = ctx.policy.resolve_run_dir(a["run_dir"])
            res["recorded_event_id"], res["trace_id"] = _record(
                rd, event_type, a["run_id"], a.get("trace_id"), unit_id=_unit_checked(ctx, a["unit_id"]),
                instance=a.get("instance", "-"), attempt=a["attempts_done"], error_id=a["error"].get("error_id"),
                message=res["reason"], context={"policy": res["policy"], "delay_s": res["delay_s"],
                                                "attempt_next": res["attempt_next"]})
    return res


def build_report(ctx: Context, a: dict) -> dict:
    rd = ctx.policy.resolve_run_dir(a["run_dir"])
    write = a.get("write", True)
    res = _build_report(ctx.registry, rd, a["run_id"], a.get("generation"), write=write)
    o = res["overall"]
    written = []
    if write:
        obs = f"_state/errors/{a['run_id']}"
        written = [f"{obs}/steps/{s}.json" for s in res["steps"]] + [f"{obs}/overall.json", "_state/errors/latest.json",
                                                                     "ERRORS.md"]
    return {"status": o["status"], "stopped_at": o["stopped_at"], "by_step": o["by_step"],
            "root_causes": o["root_causes"], "must_disclose": o["must_disclose"], "counts": o["counts"],
            "history": o["history"], "written": written}


def trace(ctx: Context, a: dict) -> dict:
    rd = ctx.policy.resolve_run_dir(a["run_dir"])
    if bool(a.get("unit_id")) == bool(a.get("error_id")):
        raise IdeateError("IDEATE.INPUT.INVALID", "give exactly one of unit_id or error_id")
    if a.get("error_id"):
        if not a.get("run_id"):
            raise IdeateError("IDEATE.INPUT.INVALID", "tracing an error needs its run_id")
        return trace_error(ctx.registry, rd, a["run_id"], a["error_id"])
    return trace_unit(ctx.registry, rd, a["unit_id"], a.get("run_id"))


HANDLERS = {
    "ideate_list_units": list_units, "ideate_get_contract": get_contract, "ideate_run_status": run_status,
    "ideate_check_gate": check_gate, "ideate_check_loop": check_loop, "ideate_record_event": record_event,
    "ideate_record_error": record_error, "ideate_retry_decision": retry_decision,
    "ideate_build_report": build_report, "ideate_trace": trace,
}
