"""Retry ownership (decision D-08): one owner per level, bounded attempts, no nested retries.

Levels and owners (contracts/architecture.json retry_policies):
  unit-transport  one network request inside a script Unit      (RP-TRANSPORT)
  unit-tool       one model/subagent answer or fan-out batch     (RP-MODEL-OUTPUT, RP-FANOUT-BATCH)
  unit            a gate's single forced revision                (RP-GATE-REVISION)
  orchestrator    re-running a whole Unit instance               (RP-UNIT, RP-NONE)
A level asking to retry under a policy it does not own is refused (IDEATE.RETRY.NESTED): the error was already
retried by its owner, and a second retry loop multiplies attempts and side effects.
"""
from __future__ import annotations

import hashlib

from .errors import CATEGORIES, IdeateError
from .registry import Registry

OWNERS = ("orchestrator", "unit", "unit-tool", "unit-transport")


def _jitter_fraction(seed: str) -> float:
    """Deterministic 'random' fraction in [0, 1) - reproducible delays for tests and replays."""
    return int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) / 0x100000000


def backoff_delay(backoff: dict | None, attempt_done: int, seed: str) -> float:
    """Delay before attempt ``attempt_done + 1``: min(cap, base * factor^(attempt_done - 1)), full jitter."""
    if not backoff:
        return 0.0
    raw = min(float(backoff["cap_s"]), float(backoff["base_s"]) * float(backoff["factor"]) ** max(attempt_done - 1, 0))
    if backoff.get("jitter") == "full":
        raw *= _jitter_fraction(seed)
    return round(raw, 3)


def decide(reg: Registry, policy_id: str, error: dict, attempts_done: int, requested_by: str) -> dict:
    """Should ``requested_by`` retry ``error`` (a dict with error_category, severity, retryable, error_id)?

    -> {action: retry|stop|degrade|escalate|error|continue|refuse, policy, owner, attempt_next, delay_s, reason, code?}
    """
    if reg.kind_of(policy_id) != "retry_policy":
        raise IdeateError("IDEATE.INPUT.UNKNOWN_ID", f"no retry policy {policy_id!r}")
    if requested_by not in OWNERS:
        raise IdeateError("IDEATE.INPUT.INVALID", f"requested_by must be one of {OWNERS}")
    if not isinstance(attempts_done, int) or attempts_done < 1:
        raise IdeateError("IDEATE.INPUT.INVALID", "attempts_done must be an integer >= 1 (the attempt that failed)")
    cat = error.get("error_category")
    if cat not in CATEGORIES:
        raise IdeateError("IDEATE.INPUT.INVALID", f"unknown error_category {cat!r}")
    pol = reg.get(policy_id)
    base = {"policy": policy_id, "owner": pol["owner"], "attempt_next": None, "delay_s": 0.0}
    if requested_by != pol["owner"]:
        return {**base, "action": "refuse", "code": "IDEATE.RETRY.NESTED",
                "reason": f"{policy_id} is owned by {pol['owner']}; {requested_by} must not retry this error again "
                          "(no nested retries)"}
    retryable = bool(error.get("retryable", CATEGORIES[cat][0]))
    severity = error.get("severity") or CATEGORIES[cat][1]
    if not retryable or cat not in pol["retry_on"]:
        action = "continue" if severity in ("degraded", "warning") else "stop"
        return {**base, "action": action, "reason": f"{cat} is not retried under {policy_id} "
                f"(retry_on: {', '.join(pol['retry_on']) or 'nothing'}); severity {severity} -> {action}"}
    if attempts_done >= pol["max_attempts"]:
        return {**base, "action": pol["on_exhausted"], "code": "IDEATE.RETRY.EXHAUSTED",
                "reason": f"{policy_id}: {attempts_done} of {pol['max_attempts']} attempts used -> {pol['on_exhausted']}"}
    delay = backoff_delay(pol.get("backoff"), attempts_done, f"{error.get('error_id', '')}:{attempts_done}")
    return {**base, "action": "retry", "attempt_next": attempts_done + 1, "delay_s": delay,
            "reason": f"{policy_id}: attempt {attempts_done + 1} of {pol['max_attempts']} after {delay}s"}
