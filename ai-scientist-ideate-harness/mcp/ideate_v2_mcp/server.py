#!/usr/bin/env python3
"""ideate_v2 MCP server - orchestration support for the v2 ideate architecture (slides 3-5).

Registration only: every tool delegates to mcp/ideate_v2_mcp/tools/handlers.py through mcp/ideate_v2_mcp/tools/envelope.py (validation, time
limit, structured errors, metadata-only logging); the logic lives in ../ideate_v2/. Resources expose the contracts.

Tools (contracts in mcp/ideate_v2_mcp/schemas/tools.json):
  ideate_list_units  ideate_get_contract  ideate_run_status  ideate_check_gate  ideate_check_loop
  ideate_record_event  ideate_record_error  ideate_retry_decision  ideate_build_report  ideate_trace

Run (stdio):  python mcp/ideate_v2_mcp/server.py
Smoke check:  python mcp/ideate_v2_mcp/server.py --check
Environment:  IDEATE_ALLOWED_ROOTS (os.pathsep-separated; default: the working directory)
              IDEATE_TOOL_TIMEOUT_S (default 30)   IDEATE_LOG_LEVEL (default INFO; logs go to stderr)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

# Resolve the official SDK first: this directory is also called "mcp" (it has no __init__.py, so a regular package
# always wins over it during import, and once imported the SDK stays bound in sys.modules).
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent.parent), str(HERE)):   # the module root (ideate_v2), this directory
    if _p not in sys.path:
        sys.path.insert(0, _p)

from resources import registry_resources as res  # noqa: E402
from tools.envelope import CATALOG, run_tool  # noqa: E402
from tools.handlers import HANDLERS, Context  # noqa: E402

INSTRUCTIONS = (
    "Orchestration support for the ai-scientist ideate pipeline (v2 architecture). Use ideate_run_status to see which "
    "Unit runs next, ideate_check_gate before crossing a step boundary, ideate_check_loop before another iteration of "
    "a declared loop, ideate_record_event / ideate_record_error to log the lifecycle, ideate_retry_decision before any "
    "retry (it refuses nested retries), and ideate_build_report at the end. Every response is an envelope "
    "{ok, tool, trace_id, duration_ms, data | error}. The server reads research folders only inside the allowed roots "
    "and writes only under <run_dir>/_state/errors/ and <run_dir>/ERRORS.md."
)

mcp = FastMCP("ideate_v2", instructions=INSTRUCTIONS)
_CTX: Context | None = None


def ctx() -> Context:
    global _CTX
    if _CTX is None:
        _CTX = Context.from_env()
    return _CTX


class ErrorPayload(BaseModel):
    error_code: str
    error_category: str
    error_message: str
    severity: Literal["fatal", "error", "degraded", "warning"]
    retryable: bool
    recovery_action: str
    context: dict[str, Any] = {}


class Envelope(BaseModel):
    """Response envelope of every tool (mcp/ideate_v2_mcp/schemas/envelope.schema.json)."""
    ok: bool
    tool: str
    trace_id: str
    duration_ms: float
    data: dict[str, Any] | None = None
    error: ErrorPayload | None = None


# resolve the postponed annotations now: the module may be loaded under any name (tests load it by path)
ErrorPayload.model_rebuild(_types_namespace={"Any": Any, "Literal": Literal})
Envelope.model_rebuild(_types_namespace={"Any": Any, "ErrorPayload": ErrorPayload})
Result = Annotated[CallToolResult, Envelope]
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
APPEND = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

RunDir = Annotated[str, Field(description="Research folder <topic>_research/ (absolute, or relative to the first "
                                          "allowed root)")]
RunId = Annotated[str | None, Field(description="v2 run id returned by RUN_STARTED (r_YYYYMMDD_HHMMSS_xxxx)")]
TraceId = Annotated[str | None, Field(description="32-hex trace id of the run (default: the run's own)")]
UnitId = Annotated[str | None, Field(description="Unit id, e.g. A2.s, A7.X2, P3")]
Gen = Annotated[int | None, Field(description="Generation number k of gen_k/ (planning scope)")]


async def _call(tool: str, args: dict) -> CallToolResult:
    env = await run_tool(tool, HANDLERS[tool], ctx(), args)
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(env, ensure_ascii=False))],
                          structuredContent=env, isError=not env["ok"])


def _desc(tool: str) -> str:
    t = CATALOG["tools"][tool]
    return f"{t['description']} Side effects: {t['side_effects']}."


@mcp.tool(name="ideate_list_units", description=_desc("ideate_list_units"), annotations=READ_ONLY)
async def ideate_list_units(
        block: Annotated[str | None, Field(description="BLK-search | BLK-fusion | BLK-planning")] = None,
        step: Annotated[str | None, Field(description="Step id, e.g. STEP-S2")] = None,
        kind: Annotated[str | None, Field(description="script | model | subagent | fanout | hybrid")] = None) -> Result:
    return await _call("ideate_list_units", {"block": block, "step": step, "kind": kind})


@mcp.tool(name="ideate_get_contract", description=_desc("ideate_get_contract"), annotations=READ_ONLY)
async def ideate_get_contract(
        entity_id: Annotated[str, Field(description="Any registry id: A3, STEP-F2, GATE-a4-check, LOOP-04, ART-gaps, RP-UNIT, OQ-04, ...")]) -> Result:
    return await _call("ideate_get_contract", {"entity_id": entity_id})


@mcp.tool(name="ideate_run_status", description=_desc("ideate_run_status"), annotations=READ_ONLY)
async def ideate_run_status(run_dir: RunDir, generation: Gen = None) -> Result:
    return await _call("ideate_run_status", {"run_dir": run_dir, "generation": generation})


@mcp.tool(name="ideate_check_gate", description=_desc("ideate_check_gate"), annotations=APPEND)
async def ideate_check_gate(run_dir: RunDir,
                            gate_id: Annotated[str, Field(description="Gate id, e.g. GATE-a2-check, GATE-recon-check")],
                            generation: Gen = None, run_id: RunId = None, trace_id: TraceId = None) -> Result:
    return await _call("ideate_check_gate", {"run_dir": run_dir, "gate_id": gate_id, "generation": generation,
                                             "run_id": run_id, "trace_id": trace_id})


@mcp.tool(name="ideate_check_loop", description=_desc("ideate_check_loop"), annotations=APPEND)
async def ideate_check_loop(loop_id: Annotated[str, Field(description="Loop id LOOP-01 ... LOOP-12")],
                            completed: Annotated[int, Field(description="Iterations already run")],
                            observed: Annotated[dict[str, float] | None,
                                                Field(description="Measurements: growth, new_share, items")] = None,
                            run_dir: Annotated[str | None, Field(description="Research folder (to record)")] = None,
                            run_id: RunId = None, trace_id: TraceId = None, unit_id: UnitId = None) -> Result:
    return await _call("ideate_check_loop", {"loop_id": loop_id, "completed": completed, "observed": observed,
                                             "run_dir": run_dir, "run_id": run_id, "trace_id": trace_id,
                                             "unit_id": unit_id})


@mcp.tool(name="ideate_record_event", description=_desc("ideate_record_event"), annotations=APPEND)
async def ideate_record_event(
        run_dir: RunDir,
        event_type: Annotated[str, Field(description="RUN_STARTED, UNIT_STARTED, TOOL_CALLED, UNIT_COMPLETED, ...")],
        run_id: RunId = None, trace_id: TraceId = None, unit_id: UnitId = None,
        step_id: Annotated[str | None, Field(description="Step id (default: the Unit's)")] = None,
        instance: Annotated[str | None, Field(description="Unit instance (query id, citation key, gen_k)")] = None,
        attempt: Annotated[int | None, Field(description="Attempt number, from 1")] = None,
        actor: Annotated[str | None, Field(description="script | model | subagent:<id> | orchestrator")] = None,
        tool: Annotated[str | None, Field(description="Command or MCP tool invoked")] = None,
        status: Annotated[str | None, Field(description="Short outcome label")] = None,
        message: Annotated[str | None, Field(description="Human-readable note (redacted, <= 2000 chars)")] = None,
        error_id: Annotated[str | None, Field(description="Related error record")] = None,
        metrics: Annotated[dict[str, float] | None,
                           Field(description="tokens_in, tokens_out, cost_usd, calls, items, duration_ms")] = None,
        context: Annotated[dict[str, Any] | None, Field(description="Metadata only (redacted); no payloads")] = None,
        idempotency_key: Annotated[str | None, Field(description="Dedupe key for retried calls")] = None,
        parent_span_id: Annotated[str | None, Field(description="16-hex span id of the parent")] = None) -> Result:
    return await _call("ideate_record_event", {
        "run_dir": run_dir, "event_type": event_type, "run_id": run_id, "trace_id": trace_id, "unit_id": unit_id,
        "step_id": step_id, "instance": instance, "attempt": attempt, "actor": actor, "tool": tool, "status": status,
        "message": message, "error_id": error_id, "metrics": metrics, "context": context,
        "idempotency_key": idempotency_key, "parent_span_id": parent_span_id})


@mcp.tool(name="ideate_record_error", description=_desc("ideate_record_error"), annotations=APPEND)
async def ideate_record_error(
        run_dir: RunDir,
        run_id: Annotated[str, Field(description="v2 run id")],
        trace_id: Annotated[str, Field(description="32-hex trace id of the run")],
        error_code: Annotated[str, Field(description="IDEATE.* code or <unit>:<check code>, e.g. A2.s:S02")],
        error_message: Annotated[str, Field(description="What went wrong (redacted)")],
        severity: Annotated[str | None, Field(description="fatal | error | degraded | warning")] = None,
        retryable: Annotated[bool | None, Field(description="Override the category default")] = None,
        unit_id: UnitId = None,
        step_id: Annotated[str | None, Field(description="Step id (default: the Unit's)")] = None,
        instance: Annotated[str | None, Field(description="Unit instance")] = None,
        attempt: Annotated[int | None, Field(description="Attempt number, from 1")] = None,
        parent_error_id: Annotated[str | None, Field(description="Upstream error that caused this one")] = None,
        context: Annotated[dict[str, Any] | None, Field(description="Metadata only (redacted)")] = None,
        recovery_action: Annotated[str | None, Field(description="none|retry|rerun-upstream|degrade|stop|escalate|fix-input|revise")] = None,
        caveat: Annotated[str | None, Field(description="Caveat code when degraded, e.g. source-failed")] = None,
        must_disclose: Annotated[bool | None, Field(description="Must reach the idea's Risk Factors")] = None,
        origin: Annotated[dict[str, Any] | None, Field(description="actor, command, service, evidence path")] = None,
        idempotency_key: Annotated[str | None, Field(description="Dedupe key for retried calls")] = None) -> Result:
    return await _call("ideate_record_error", {
        "run_dir": run_dir, "run_id": run_id, "trace_id": trace_id, "error_code": error_code,
        "error_message": error_message, "severity": severity, "retryable": retryable, "unit_id": unit_id,
        "step_id": step_id, "instance": instance, "attempt": attempt, "parent_error_id": parent_error_id,
        "context": context, "recovery_action": recovery_action, "caveat": caveat, "must_disclose": must_disclose,
        "origin": origin, "idempotency_key": idempotency_key})


@mcp.tool(name="ideate_retry_decision", description=_desc("ideate_retry_decision"), annotations=APPEND)
async def ideate_retry_decision(
        policy_id: Annotated[str, Field(description="RP-NONE, RP-TRANSPORT, RP-MODEL-OUTPUT, RP-FANOUT-BATCH, RP-UNIT, RP-GATE-REVISION")],
        attempts_done: Annotated[int, Field(description="The attempt that just failed (from 1)")],
        requested_by: Annotated[str, Field(description="orchestrator | unit | unit-tool | unit-transport")],
        error: Annotated[dict[str, Any], Field(description="{error_category, severity?, retryable?, error_id?}")],
        record: Annotated[bool | None, Field(description="Record RETRY_SCHEDULED / RETRY_EXHAUSTED / ESCALATED")] = None,
        run_dir: Annotated[str | None, Field(description="Research folder (to record)")] = None,
        run_id: RunId = None, trace_id: TraceId = None, unit_id: UnitId = None,
        instance: Annotated[str | None, Field(description="Unit instance")] = None) -> Result:
    return await _call("ideate_retry_decision", {
        "policy_id": policy_id, "attempts_done": attempts_done, "requested_by": requested_by, "error": error,
        "record": record, "run_dir": run_dir, "run_id": run_id, "trace_id": trace_id, "unit_id": unit_id,
        "instance": instance})


@mcp.tool(name="ideate_build_report", description=_desc("ideate_build_report"), annotations=APPEND)
async def ideate_build_report(run_dir: RunDir, run_id: Annotated[str, Field(description="v2 run id")],
                              generation: Gen = None,
                              write: Annotated[bool | None, Field(description="Write the report files (default true)")] = None) -> Result:
    return await _call("ideate_build_report", {"run_dir": run_dir, "run_id": run_id, "generation": generation,
                                               "write": write})


@mcp.tool(name="ideate_trace", description=_desc("ideate_trace"), annotations=READ_ONLY)
async def ideate_trace(run_dir: RunDir, unit_id: UnitId = None,
                       error_id: Annotated[str | None, Field(description="Error record id E-...")] = None,
                       run_id: RunId = None) -> Result:
    return await _call("ideate_trace", {"run_dir": run_dir, "unit_id": unit_id, "error_id": error_id, "run_id": run_id})


# ------------------------------------------------------------------------------------------------ resources
@mcp.resource("ideate://architecture", name="architecture", mime_type="application/json",
              description="Blocks, steps, gates, loops and counts of the v2 architecture")
def r_architecture() -> str:
    return res.architecture(ctx().registry)


@mcp.resource("ideate://units/{unit_id}", name="unit", mime_type="application/json",
              description="A Unit's contract, 27-field canonical specification and substeps")
def r_unit(unit_id: str) -> str:
    return res.unit(ctx().registry, unit_id)


@mcp.resource("ideate://entities/{entity_id}", name="entity", mime_type="application/json",
              description="Any registry entity (step, gate, loop, artifact, policy, decision, open question)")
def r_entity(entity_id: str) -> str:
    return res.entity(ctx().registry, entity_id)


@mcp.resource("ideate://schemas/{name}", name="schema", mime_type="application/json",
              description="A schema of mcp/ideate_v2_mcp/schemas/: tools, envelope, error_record, event")
def r_schema(name: str) -> str:
    return res.schema(name)


@mcp.resource("ideate://errors/taxonomy", name="error-taxonomy", mime_type="application/json",
              description="Error categories, codes, severities and recovery actions")
def r_taxonomy() -> str:
    return res.taxonomy()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--check" in argv:
        c = ctx()
        print(json.dumps({"server": "ideate_v2", "units": len(c.registry.units), "tools": sorted(HANDLERS),
                          "allowed_roots": [str(r) for r in c.policy.roots]}, indent=2), file=sys.stderr)
        return 0
    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
