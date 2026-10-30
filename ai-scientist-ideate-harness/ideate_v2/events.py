"""v2 lifecycle events: RUN_STARTED -> UNIT_STARTED -> TOOL_CALLED -> ... -> UNIT_COMPLETED, and the failure, retry,
cancellation and recovery events. One JSONL file per run: <RD>/_state/errors/<run_id>/events.jsonl.

Every append validates the event against the lifecycle *under the file lock*, so check-then-write cannot race, and
an ``idempotency_key`` already in the log returns the earlier event instead of writing a duplicate.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from .errors import IdeateError, new_span_id, now_iso, valid_run_id
from .jsonio import FileLock, append_jsonl_unlocked, read_jsonl
from .paths import observability_dir
from .redact import redact, redact_text

SCHEMA = "ideate-v2-event/1"
RUN_EVENTS = ("RUN_STARTED", "RUN_COMPLETED", "RUN_FAILED", "RUN_CANCELLED")
STEP_EVENTS = ("STEP_STARTED", "STEP_COMPLETED", "GATE_CHECKED")
UNIT_OPEN = ("UNIT_STARTED",)
UNIT_TOOL = ("TOOL_CALLED", "TOOL_RETURNED", "TOOL_FAILED")
UNIT_TERMINAL = ("UNIT_COMPLETED", "UNIT_DEGRADED", "UNIT_PENDING", "UNIT_FAILED", "UNIT_CANCELLED")
CONTROL = ("RETRY_SCHEDULED", "RETRY_EXHAUSTED", "LOOP_ITERATION", "LOOP_BOUND_REACHED", "RECOVERY_STARTED",
           "RECOVERY_COMPLETED", "ESCALATED")
EVENT_TYPES = RUN_EVENTS + STEP_EVENTS + UNIT_OPEN + UNIT_TOOL + UNIT_TERMINAL + CONTROL
NEEDS_UNIT = set(UNIT_OPEN + UNIT_TOOL + UNIT_TERMINAL + ("RETRY_SCHEDULED", "RETRY_EXHAUSTED", "RECOVERY_STARTED",
                                                          "RECOVERY_COMPLETED"))
METRIC_KEYS = {"tokens_in", "tokens_out", "cost_usd", "calls", "items", "duration_ms"}
_KEY = re.compile(r"^[A-Za-z0-9._:@/\-]{1,200}$")


def events_path(run_dir: Path, run_id: str) -> Path:
    return observability_dir(run_dir, run_id) / "events.jsonl"


def read_events(run_dir: Path, run_id: str) -> tuple[list[dict], list[dict]]:
    return read_jsonl(events_path(run_dir, run_id))


def _open_attempts(events: list[dict]) -> dict[tuple, dict]:
    """(unit, instance) -> the UNIT_STARTED event of an attempt with no terminal yet."""
    open_: dict[tuple, dict] = {}
    for e in events:
        key = (e.get("unit_id"), e.get("instance", "-"))
        t = e.get("event_type")
        if t == "UNIT_STARTED":
            open_[key] = e
        elif t in UNIT_TERMINAL or t == "RECOVERY_STARTED":
            open_.pop(key, None)
    return open_


def _last_terminal(events: list[dict], key: tuple) -> dict | None:
    for e in reversed(events):
        if (e.get("unit_id"), e.get("instance", "-")) == key and e.get("event_type") in UNIT_TERMINAL:
            return e
    return None


def lifecycle_problems(events: list[dict], ev: dict) -> list[str]:
    """Why ``ev`` may not follow ``events`` (empty when it may)."""
    t, key = ev["event_type"], (ev.get("unit_id"), ev.get("instance", "-"))
    started = any(e.get("event_type") == "RUN_STARTED" for e in events)
    ended = any(e.get("event_type") in RUN_EVENTS[1:] for e in events)
    if t == "RUN_STARTED":
        return ["the run already started"] if started else []
    if not started:
        return ["no RUN_STARTED for this run yet"]
    if ended and t != "RUN_STARTED":
        return ["the run already ended"]
    open_ = _open_attempts(events)
    if t == "UNIT_STARTED":
        if key in open_:
            return [f"{key[0]}@{key[1]} attempt {open_[key].get('attempt')} is still open"]
        previous = [e.get("attempt", 1) for e in events if e.get("event_type") == "UNIT_STARTED" and
                    (e.get("unit_id"), e.get("instance", "-")) == key]
        if previous and ev.get("attempt", 1) <= max(previous):
            return [f"attempt {ev.get('attempt', 1)} of {key[0]}@{key[1]} already started (next is {max(previous) + 1})"]
        return []
    if t in UNIT_TOOL or t in UNIT_TERMINAL:
        if key not in open_:
            return [f"{t} for {key[0]}@{key[1]} without an open UNIT_STARTED"]
        if ev.get("attempt", 1) != open_[key].get("attempt", 1):
            return [f"{t} names attempt {ev.get('attempt', 1)}, the open attempt is {open_[key].get('attempt', 1)}"]
        return []
    if t == "RETRY_SCHEDULED":
        last = _last_terminal(events, key)
        if key in open_:
            return [f"{key[0]}@{key[1]} is still running"]
        if last is None or last.get("event_type") not in ("UNIT_FAILED", "UNIT_CANCELLED"):
            return [f"RETRY_SCHEDULED needs a failed attempt of {key[0]}@{key[1]}"]
        return []
    if t == "RECOVERY_STARTED" and key not in open_:
        return [f"RECOVERY_STARTED needs an interrupted (open) attempt of {key[0]}@{key[1]}"]
    return []


def build_event(event_type: str, *, run_id: str, trace_id: str, unit_id: str | None = None, step_id: str | None = None,
                instance: str = "-", attempt: int = 1, actor: str | None = None, tool: str | None = None,
                status: str | None = None, message: str | None = None, error_id: str | None = None,
                metrics: dict | None = None, context: dict | None = None, idempotency_key: str | None = None,
                parent_span_id: str | None = None) -> dict:
    if event_type not in EVENT_TYPES:
        raise IdeateError("IDEATE.INPUT.INVALID", f"unknown event_type {event_type!r}",
                          context={"allowed": list(EVENT_TYPES)})
    if not valid_run_id(run_id):
        raise IdeateError("IDEATE.INPUT.INVALID", f"run_id {run_id!r} does not match r_YYYYMMDD_HHMMSS_xxxx")
    if not re.fullmatch(r"[0-9a-f]{32}", trace_id or ""):
        raise IdeateError("IDEATE.INPUT.INVALID", "trace_id must be 32 lowercase hex characters")
    if event_type in NEEDS_UNIT and not unit_id:
        raise IdeateError("IDEATE.INPUT.INVALID", f"{event_type} needs a unit_id")
    if not isinstance(attempt, int) or attempt < 1:
        raise IdeateError("IDEATE.INPUT.INVALID", "attempt must be an integer >= 1")
    if idempotency_key is not None and not _KEY.match(idempotency_key):
        raise IdeateError("IDEATE.INPUT.INVALID", "idempotency_key: 1-200 characters of [A-Za-z0-9._:@/-]")
    m = {}
    for k, v in (metrics or {}).items():
        if k not in METRIC_KEYS or not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
            raise IdeateError("IDEATE.INPUT.INVALID", f"metric {k!r}: allowed keys {sorted(METRIC_KEYS)}, "
                              "non-negative numbers")
        m[k] = v
    ev = {"schema": SCHEMA, "event_id": "EV-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" +
          secrets.token_hex(4), "event_type": event_type, "timestamp": now_iso(), "run_id": run_id,
          "trace_id": trace_id, "span_id": new_span_id(), "parent_span_id": parent_span_id, "unit_id": unit_id,
          "step_id": step_id, "instance": instance or "-", "attempt": attempt, "actor": actor, "tool": tool,
          "status": status, "message": redact_text(message, 500) if message else None, "error_id": error_id,
          "metrics": m, "context": redact(context or {}), "idempotency_key": idempotency_key}
    return {k: v for k, v in ev.items() if v not in (None, {}) or k in ("unit_id", "metrics", "context")}


def append_event(run_dir: Path, ev: dict) -> dict:
    """Validate against the lifecycle and append under the lock. -> {"event": ev, "deduplicated": bool}"""
    path = events_path(run_dir, ev["run_id"])
    with FileLock(path):
        events, problems = read_jsonl(path)
        if problems:
            raise IdeateError("IDEATE.LEDGER.MALFORMED", f"events.jsonl line {problems[0]['line']}: "
                              f"{problems[0]['error']}", context={"path": str(path)})
        key = ev.get("idempotency_key")
        if key:
            for e in events:
                if e.get("idempotency_key") == key:
                    return {"event": e, "deduplicated": True}
        bad = lifecycle_problems(events, ev)
        if bad:
            raise IdeateError("IDEATE.STATE.LIFECYCLE", "; ".join(bad), context={"event_type": ev["event_type"],
                              "unit_id": ev.get("unit_id"), "instance": ev.get("instance")})
        append_jsonl_unlocked(path, ev)
    return {"event": ev, "deduplicated": False}
