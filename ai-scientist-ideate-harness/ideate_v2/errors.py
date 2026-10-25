"""The v2 error model: categories, severities, codes, the ErrorRecord, and exceptions that carry them.

This file is the single source of the taxonomy; references/error_handling.md and ARCHITECTURE.md section 6 render
or cite it. Domain check codes of the legacy Units keep their own codes, namespaced as ``<unit>:<code>`` (the same
code means different things in different Units: T01 in B1 and in P3, R03 in A2.c and in P4).
"""
from __future__ import annotations

import re
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from .redact import redact, redact_text

SCHEMA = "ideate-v2-error/1"
SEVERITIES = ("fatal", "error", "degraded", "warning")
SEVERITY_RANK = {s: i for i, s in enumerate(reversed(SEVERITIES))}       # warning 0 ... fatal 3
RECOVERY_ACTIONS = ("none", "retry", "rerun-upstream", "degrade", "stop", "escalate", "fix-input", "revise")

# category -> (retryable by default, default severity, meaning). retryable is a property of the failure class; the
# retry *decision* (who retries, how often) belongs to the retry policy that owns the level (ideate_v2.retry).
CATEGORIES: dict[str, tuple[bool, str, str]] = {
    "input_validation": (False, "error", "a tool or MCP call received arguments that violate its input schema"),
    "input_contract": (False, "fatal", "an upstream artifact is missing or violates its contract"),
    "stale": (False, "error", "an input changed after the Unit's done; re-run the upstream chain, not a retry"),
    "external_service": (True, "degraded", "a network service failed (429, 5xx, timeout, missing key)"),
    "tool_invocation": (False, "error", "a CLI command could not start or crashed without a check finding"),
    "model_output": (True, "error", "a model or subagent answer was rejected by the Unit's tool"),
    "schema": (False, "error", "a file on disk or a script output does not match its schema"),
    "state": (False, "error", "ledger or lifecycle state is inconsistent (malformed line, illegal transition)"),
    "environment": (False, "fatal", "a package, binary, data root or credential is missing on this machine"),
    "timeout": (True, "error", "an operation exceeded its time limit"),
    "cancelled": (False, "error", "an operation was cancelled by its caller"),
    "interrupted": (True, "error", "a Unit began and never finished (crash, kill, power loss)"),
    "check_failed": (False, "error", "the Unit's own done_when checks failed"),
    "budget": (False, "error", "a token, cost or time budget was exceeded"),
    "policy": (False, "error", "a rule refused the action (path outside the allowed roots, loop bound, nested retry)"),
    "human": (False, "warning", "an intervention through _human/ changed a decision"),
    "internal": (False, "fatal", "an unexpected exception in v2 itself (a bug)"),
}

# v2 harness codes. Each maps to exactly one category.
CODES: dict[str, tuple[str, str]] = {
    "IDEATE.INPUT.INVALID": ("input_validation", "arguments do not match the tool's input schema"),
    "IDEATE.INPUT.UNKNOWN_ID": ("input_validation", "no Unit, step, gate, loop or policy with that id"),
    "IDEATE.PATH.DENIED": ("policy", "the path resolves outside every allowed root"),
    "IDEATE.PATH.NOT_A_RUN_DIR": ("input_validation", "the directory is not a research folder"),
    "IDEATE.FILE.TOO_LARGE": ("policy", "a file exceeds the read limit"),
    "IDEATE.ARTIFACT.MISSING": ("input_contract", "a required artifact is absent"),
    "IDEATE.ARTIFACT.UNREADABLE": ("schema", "a required artifact does not parse"),
    "IDEATE.EXTERNAL.UNAVAILABLE": ("external_service", "a network service did not answer usefully (429, 5xx, "
                                                        "timeout, missing key) after the transport's own retries"),
    "IDEATE.UNIT.INTERRUPTED": ("interrupted", "a Unit attempt began and never finished"),
    "IDEATE.LEDGER.MALFORMED": ("state", "a ledger line does not parse"),
    "IDEATE.STATE.LIFECYCLE": ("state", "an event violates the lifecycle (e.g. UNIT_COMPLETED without UNIT_STARTED)"),
    "IDEATE.STATE.LOCK_TIMEOUT": ("timeout", "a file lock could not be taken in time"),
    "IDEATE.GATE.FAILED": ("check_failed", "a handover gate has ERROR findings"),
    "IDEATE.LOOP.BOUND_REACHED": ("policy", "a declared loop reached its bound"),
    "IDEATE.RETRY.EXHAUSTED": ("policy", "the owning retry policy has no attempts left"),
    "IDEATE.RETRY.NESTED": ("policy", "a level tried to retry an error owned by another level"),
    "IDEATE.TOOL.TIMEOUT": ("timeout", "a tool handler exceeded its time limit"),
    "IDEATE.OUTPUT.SCHEMA": ("schema", "a tool produced output that violates its own output schema"),
    "IDEATE.INTERNAL": ("internal", "unexpected exception"),
    # the code conductor (harness/): a Unit run as an agent
    "IDEATE.UPSTREAM.NOT_DONE": ("input_contract", "a Unit was asked to run before an upstream Unit it requires is done"),
    "IDEATE.UNIT.OUTPUT_MISSING": ("check_failed", "a Unit finished without leaving an artifact its contract names"),
    "IDEATE.TOOL.FAILED": ("tool_invocation", "a skill command exited non-zero without a check finding"),
    "IDEATE.ENV.MISSING": ("environment", "a package, binary, key or data root the Unit needs is missing"),
    "IDEATE.WORKER.OUTPUT": ("model_output", "a Claude worker's files were rejected by the Unit's tool or checks"),
    "IDEATE.WORKER.FAILED": ("tool_invocation", "a Claude worker could not complete (no result, crash)"),
    "IDEATE.BUDGET.EXCEEDED": ("budget", "a worker reached its cost or turn budget"),
}

_RUN_ID = re.compile(r"^r_[0-9]{8}_[0-9]{6}_[0-9a-f]{4}$")
_UNIT_CODE = re.compile(r"^[A-Z][A-Za-z0-9.]*(/[A-Za-z0-9.\-]+)?:[A-Z][A-Z0-9_.\-]*$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_span_id() -> str:
    return secrets.token_hex(8)


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("r_%Y%m%d_%H%M%S_") + secrets.token_hex(2)


def valid_run_id(run_id: str) -> bool:
    return bool(_RUN_ID.match(run_id or ""))


def new_error_id() -> str:
    return "E-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(4)


def category_of(code: str) -> str:
    """The category a code belongs to: v2 codes from CODES, Unit check codes (<unit>:<code>) are check_failed."""
    if code in CODES:
        return CODES[code][0]
    if _UNIT_CODE.match(code or ""):
        return "check_failed"
    raise ValueError(f"unknown error code {code!r}: use a code from CODES or <unit>:<check code>")


@dataclass
class ErrorRecord:
    """One error, wherever it was found. ``unit_id`` is where it was *found*; ``parent_error_id`` points to the
    upstream error that caused it (the chain ends at the root cause)."""
    error_code: str
    error_category: str
    error_message: str
    severity: str
    retryable: bool
    unit_id: str | None
    step_id: str | None
    run_id: str
    trace_id: str
    timestamp: str = field(default_factory=now_iso)
    attempt: int = 1
    parent_error_id: str | None = None
    context: dict = field(default_factory=dict)
    recovery_action: str = "none"
    error_id: str = field(default_factory=new_error_id)
    instance: str = "-"
    span_id: str | None = None
    caveat: str | None = None
    must_disclose: bool = False
    origin: dict = field(default_factory=dict)
    idempotency_key: str | None = None
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        problems = self.problems()
        if problems:
            raise IdeateError("IDEATE.INPUT.INVALID", "invalid error record: " + "; ".join(problems))
        self.error_message = redact_text(self.error_message, 1000)
        self.context = redact(self.context or {})
        self.origin = redact(self.origin or {})

    def problems(self) -> list[str]:
        out = []
        if self.error_category not in CATEGORIES:
            out.append(f"unknown category {self.error_category!r}")
        try:
            if category_of(self.error_code) != self.error_category and self.error_code in CODES:
                out.append(f"code {self.error_code} belongs to category {category_of(self.error_code)}")
        except ValueError as e:
            out.append(str(e))
        if self.severity not in SEVERITIES:
            out.append(f"unknown severity {self.severity!r}")
        if self.recovery_action not in RECOVERY_ACTIONS:
            out.append(f"unknown recovery_action {self.recovery_action!r}")
        if not isinstance(self.attempt, int) or self.attempt < 1:
            out.append("attempt must be an integer >= 1")
        if not valid_run_id(self.run_id):
            out.append(f"run_id {self.run_id!r} does not match r_YYYYMMDD_HHMMSS_xxxx")
        if not re.fullmatch(r"[0-9a-f]{32}", self.trace_id or ""):
            out.append("trace_id must be 32 lowercase hex characters")
        if self.parent_error_id is not None and self.parent_error_id == self.error_id:
            out.append("an error cannot be its own parent")
        return out

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ErrorRecord":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


class IdeateError(Exception):
    """An error with a code. ``category``, ``severity`` and ``retryable`` default from the code's category."""

    def __init__(self, code: str, message: str, *, severity: str | None = None, retryable: bool | None = None,
                 context: dict | None = None, recovery_action: str | None = None):
        super().__init__(message)
        self.code = code
        self.category = category_of(code)
        default_retry, default_sev, _ = CATEGORIES[self.category]
        self.severity = severity or default_sev
        self.retryable = default_retry if retryable is None else retryable
        self.context = context or {}
        self.recovery_action = recovery_action or ("retry" if self.retryable else
                                                   "fix-input" if self.category == "input_validation" else "stop")

    @property
    def message(self) -> str:
        return str(self)

    def payload(self) -> dict:
        """The error as returned to an MCP client (no stack trace, redacted)."""
        return {"error_code": self.code, "error_category": self.category, "error_message": redact_text(str(self), 1000),
                "severity": self.severity, "retryable": self.retryable, "recovery_action": self.recovery_action,
                "context": redact(self.context)}


def cause_chain(exc: BaseException, limit: int = 5) -> list[str]:
    """Root-cause preservation: the chain of __cause__ / __context__ as 'Type: message' strings (redacted)."""
    out, seen, cur = [], set(), exc
    while cur is not None and id(cur) not in seen and len(out) < limit:
        seen.add(id(cur))
        out.append(f"{type(cur).__name__}: {redact_text(str(cur), 300)}")
        cur = cur.__cause__ or cur.__context__
    return out


def from_exception(exc: BaseException) -> IdeateError:
    """Wrap any exception as an IdeateError, keeping the original as __cause__ and its chain in context."""
    if isinstance(exc, IdeateError):
        return exc
    from .jsonio import FileTooLarge, LockTimeout          # local import: jsonio does not depend on errors
    import json
    if isinstance(exc, LockTimeout):
        code = "IDEATE.STATE.LOCK_TIMEOUT"
    elif isinstance(exc, FileTooLarge):
        code = "IDEATE.FILE.TOO_LARGE"
    elif isinstance(exc, FileNotFoundError):
        code = "IDEATE.ARTIFACT.MISSING"
    elif isinstance(exc, json.JSONDecodeError):
        code = "IDEATE.ARTIFACT.UNREADABLE"
    elif isinstance(exc, TimeoutError):
        code = "IDEATE.TOOL.TIMEOUT"
    else:
        code = "IDEATE.INTERNAL"
    err = IdeateError(code, f"{type(exc).__name__}: {exc}", context={"cause_chain": cause_chain(exc)})
    err.__cause__ = exc
    return err


def root_cause(errors: dict[str, dict], error_id: str) -> tuple[dict | None, list[str]]:
    """Follow parent_error_id to the root. -> (root record or None, chain of ids). Cycle-safe."""
    chain, cur = [], errors.get(error_id)
    while cur is not None:
        if cur["error_id"] in chain:
            break
        chain.append(cur["error_id"])
        parent = cur.get("parent_error_id")
        if not parent or parent not in errors:
            return cur, chain
        cur = errors[parent]
    return (errors.get(chain[-1]) if chain else None), chain
