"""The response envelope and the execution wrapper every tool goes through.

validate the arguments against mcp/ideate_v2_mcp/schemas/tools.json -> run the handler (in a worker thread under a time limit when
served) -> validate the handler's data against the tool's output schema -> wrap {ok, tool, trace_id, duration_ms,
data | error}. Every exception becomes a structured error (no stack traces leave the server). One JSON log line per
call goes to stderr with metadata only (tool, trace id, duration, outcome, error code) - never arguments or payloads.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

from ideate_v2 import MCP_SCHEMAS_DIR
from ideate_v2.errors import IdeateError, from_exception, new_trace_id
from ideate_v2.schema_lite import validate

CATALOG: dict = json.loads((Path(MCP_SCHEMAS_DIR) / "tools.json").read_text(encoding="utf-8"))
DEFAULT_TIMEOUT_S = float(os.environ.get("IDEATE_TOOL_TIMEOUT_S", "30"))
Handler = Callable[[Any, dict], dict]

log = logging.getLogger("ideate_v2.mcp")
if not log.handlers:
    _h = logging.StreamHandler(sys.stderr)              # stdout carries the stdio transport: never log there
    _h.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_h)
    log.setLevel(os.environ.get("IDEATE_LOG_LEVEL", "INFO").upper())
    log.propagate = False


def validate_args(tool: str, args: dict) -> dict:
    """Drop None values (optional arguments not given), then validate. -> the cleaned arguments."""
    if tool not in CATALOG["tools"]:
        raise IdeateError("IDEATE.INPUT.UNKNOWN_ID", f"no tool {tool!r}")
    clean = {k: v for k, v in args.items() if v is not None}
    problems = validate(clean, CATALOG["tools"][tool]["input"], CATALOG)
    if problems:
        raise IdeateError("IDEATE.INPUT.INVALID", "; ".join(problems[:5]), context={"problems": problems[:20]})
    return clean


def check_output(tool: str, data: Any) -> None:
    problems = validate(data, CATALOG["tools"][tool]["output"], CATALOG)
    if problems:
        raise IdeateError("IDEATE.OUTPUT.SCHEMA", f"{tool} produced data violating its output schema: {problems[0]}",
                          context={"problems": problems[:10]})


def _finish(tool: str, trace_id: str, start: float, data: Any = None, exc: BaseException | None = None) -> dict:
    if exc is None:
        env = {"ok": True, "tool": tool, "trace_id": data.get("trace_id", trace_id), "data": data}
    else:
        err = exc if isinstance(exc, IdeateError) else from_exception(exc)
        if not isinstance(exc, IdeateError):
            log.debug("unexpected exception in %s", tool, exc_info=exc)
        env = {"ok": False, "tool": tool, "trace_id": trace_id, "error": err.payload()}
    env["duration_ms"] = round((time.monotonic() - start) * 1000, 2)
    rec = {"event": "tool_call", "tool": tool, "trace_id": env["trace_id"], "ok": env["ok"],
           "duration_ms": env["duration_ms"]}
    if not env["ok"]:
        rec.update(error_code=env["error"]["error_code"], severity=env["error"]["severity"])
    (log.info if env["ok"] else log.warning)(json.dumps(rec))
    return env


def execute(tool: str, handler: Handler, ctx: Any, args: dict) -> dict:
    """Synchronous call (tests, evals): same validation and envelope, no thread and no time limit."""
    start, trace_id = time.monotonic(), args.get("trace_id") or new_trace_id()
    try:
        data = handler(ctx, validate_args(tool, args))
        check_output(tool, data)
    except Exception as e:  # noqa: BLE001 - every failure leaves as a structured error
        return _finish(tool, trace_id, start, exc=e)
    return _finish(tool, trace_id, start, data=data)


async def run_tool(tool: str, handler: Handler, ctx: Any, args: dict, timeout_s: float | None = None) -> dict:
    """Served call: the handler runs in a worker thread under ``timeout_s``.

    On timeout the caller gets IDEATE.TOOL.TIMEOUT immediately; the abandoned thread may still finish. Its writes are
    atomic or idempotent (lock + idempotency_key), so a retry with the same key cannot duplicate a side effect."""
    import anyio

    start, trace_id = time.monotonic(), args.get("trace_id") or new_trace_id()
    limit = DEFAULT_TIMEOUT_S if timeout_s is None else timeout_s
    try:
        clean = validate_args(tool, args)
        data = None
        with anyio.move_on_after(limit) as scope:        # not fail_after: a handler's own TimeoutError (a lock
            data = await anyio.to_thread.run_sync(lambda: handler(ctx, clean), abandon_on_cancel=True)
        if scope.cancelled_caught:                       # timeout) must keep its own error code
            raise IdeateError("IDEATE.TOOL.TIMEOUT", f"{tool} exceeded {limit}s", context={"timeout_s": limit})
        check_output(tool, data)
    except Exception as e:  # noqa: BLE001
        return _finish(tool, trace_id, start, exc=e)
    return _finish(tool, trace_id, start, data=data)
