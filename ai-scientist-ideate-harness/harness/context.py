"""RunContext: one run of the conductor - its ids, where it writes, and the events and error records it leaves.

Every record goes through ideate_v2 (events.append_event validates the lifecycle under a lock; report.record_error
writes <RD>/_state/errors/<run_id>/units/<unit>@<instance>.jsonl), so a run's trail reads the same whether the
conductor or a Claude session conducting through the ideate_v2 MCP server left it.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ideate_v2 import events as ev
from ideate_v2.errors import CATEGORIES, CODES, ErrorRecord, IdeateError, new_run_id, new_trace_id
from ideate_v2.registry import Registry
from ideate_v2.report import record_error

from .config import HarnessConfig
from .skill import Skill, Subs

# a category -> the v2 code the conductor records a failure of that category under (a Unit's own check finding is
# recorded as <unit>:<code> instead)
CODE_FOR = {
    "external_service": "IDEATE.EXTERNAL.UNAVAILABLE", "environment": "IDEATE.ENV.MISSING",
    "input_contract": "IDEATE.ARTIFACT.MISSING", "tool_invocation": "IDEATE.TOOL.FAILED",
    "timeout": "IDEATE.TOOL.TIMEOUT", "interrupted": "IDEATE.UNIT.INTERRUPTED", "model_output": "IDEATE.WORKER.OUTPUT",
    "budget": "IDEATE.BUDGET.EXCEEDED", "schema": "IDEATE.ARTIFACT.UNREADABLE", "state": "IDEATE.STATE.LIFECYCLE",
    "policy": "IDEATE.LOOP.BOUND_REACHED", "internal": "IDEATE.INTERNAL", "check_failed": "IDEATE.UNIT.OUTPUT_MISSING",
}


def instance_of(gen: int | None, phase: str = "main") -> str:
    """The instance events and errors are recorded under: "-" (topic), "gen_k", and "<that>/<phase>" for a phase
    other than main (B5's rounds) - so a later phase is not taken for a retry of an earlier one."""
    base = f"gen_{gen}" if gen is not None else "-"
    return base if phase == "main" else f"{base}/{phase}"


@dataclass
class RunContext:
    reg: Registry
    cfg: HarnessConfig
    skill: Skill
    rd: Path
    topic: Path | None = None
    run_id: str = field(default_factory=new_run_id)
    trace_id: str = field(default_factory=new_trace_id)
    say: Callable[[str], None] = field(default=lambda s: print(s, file=sys.stderr, flush=True))
    executors: dict = field(default_factory=dict)          # unit -> a custom executor (--agent U=pkg:Class)
    errors: list[ErrorRecord] = field(default_factory=list)
    gates_passed: set = field(default_factory=set)          # (gate, instance) that passed in this run
    usage: dict = field(default_factory=lambda: {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "calls": 0})
    attempts: dict = field(default_factory=dict)            # (unit, instance) -> the last attempt number of this run
    units: list = field(default_factory=list)               # UnitResults, in the order they ran
    fresh_gens: set = field(default_factory=set)            # generations this run started (P0 ran in it)

    def __post_init__(self) -> None:
        self.rd = Path(self.rd)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    @property
    def state_dir(self) -> Path:
        """Conductor scratch: shims, worker prompts and logs, decisions (<RD>/_state/harness/<run_id>/)."""
        return self.rd / "_state" / "harness" / self.run_id

    def decision_path(self, gen: int | None) -> Path:
        """Where B5's round-2 worker records its one decision: {"decision": "finalize"} or
        {"decision": "revise", "enters": "P1" | "P2" | "P3", "reason": ...} (run-independent, so a resume reads it)."""
        return self.rd / "_state" / "harness" / "decisions" / f"gen_{gen}" / "B5.round2.json"

    def subs(self, gen: int | None = None, round: int | None = None) -> Subs:
        return Subs(self.rd, self.topic, gen, round)

    # ------------------------------------------------------------------------------------------------ events
    def emit(self, event_type: str, **kw) -> dict | None:
        try:
            return ev.append_event(self.rd, ev.build_event(event_type, run_id=self.run_id, trace_id=self.trace_id,
                                                           actor=kw.pop("actor", "orchestrator"), **kw))["event"]
        except IdeateError as e:              # a lifecycle slip is the conductor's bug: recorded, never fatal to the run
            self.say(f"    ! event {event_type} not recorded: {e}")
            self.error("IDEATE.STATE.LIFECYCLE", str(e), unit=kw.get("unit_id"), step=kw.get("step_id"),
                       instance=kw.get("instance", "-"), attempt=kw.get("attempt", 1))
            return None

    # ------------------------------------------------------------------------------------------------ errors
    def error(self, code: str, message: str, *, unit: str | None = None, step: str | None = None,
              instance: str = "-", attempt: int = 1, category: str | None = None, severity: str | None = None,
              parent: str | None = None, context: dict | None = None, caveat: str | None = None,
              must_disclose: bool = False, recovery_action: str | None = None) -> ErrorRecord:
        if code in CODES:
            category = CODES[code][0]
        category = category or "check_failed"
        retryable, default_sev, _ = CATEGORIES[category]
        rec = ErrorRecord(error_code=code, error_category=category, error_message=message,
                          severity=severity or default_sev, retryable=retryable, unit_id=unit,
                          step_id=step or (self.reg.step_of(unit) if unit else None), run_id=self.run_id,
                          trace_id=self.trace_id, attempt=attempt, parent_error_id=parent, context=context or {},
                          recovery_action=recovery_action or ("retry" if retryable else "stop"), instance=instance,
                          caveat=caveat, must_disclose=must_disclose,
                          origin={"actor": "harness", "unit": unit, "instance": instance, "attempt": attempt})
        record_error(self.rd, rec)
        self.errors.append(rec)
        return rec

    def last_error(self, unit: str, instance: str = "-") -> ErrorRecord | None:
        """The latest error of a Unit instance at degraded severity or worse (the parent of what it causes)."""
        for r in reversed(self.errors):
            if r.unit_id == unit and r.instance == instance and r.severity in ("degraded", "error", "fatal"):
                return r
        return None

    def next_attempt(self, unit: str, instance: str) -> int:
        """Attempt numbers grow per Unit instance over the whole run (a re-run in a loop is a new attempt)."""
        n = self.attempts.get((unit, instance), 0) + 1
        self.attempts[(unit, instance)] = n
        return n

    def add_unit(self, result) -> None:
        self.units.append(result)

    def add_usage(self, metrics: dict) -> None:
        for k in ("tokens_in", "tokens_out", "cost_usd", "calls"):
            self.usage[k] = self.usage.get(k, 0) + metrics.get(k, 0)
