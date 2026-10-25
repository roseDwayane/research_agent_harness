# ideate_v2 MCP server

Orchestration support for the v2 ideate architecture: run status, gate checks, loop bounds, retry ownership,
structured errors and lifecycle events, reports and traces. Built on the official MCP Python SDK (`FastMCP`, stdio).
It reads research folders and writes only `<run_dir>/_state/errors/**` and `<run_dir>/ERRORS.md`; it never calls the
network, never runs a command, and never writes the legacy ledger or an artifact.

```
mcp/
├── server.py                      registration only (tools, resources, envelope model)
├── tools/envelope.py              validation against schemas/tools.json, time limit, structured errors, stderr logs
├── tools/handlers.py              argument mapping and path policy around ../ideate_v2 (no SDK import: unit-testable)
├── resources/registry_resources.py
└── schemas/                       tools.json (input + output of every tool), envelope, error_record, event
```

This directory deliberately has no `__init__.py`: it shares its name with the SDK package, and a regular package
(the SDK) always wins over a plain directory during import.

## Run

```
pip install -r requirements.txt          # mcp>=1.27,<2 (tested with 1.30.0)
python mcp/ideate_v2_mcp/server.py --check             # loads the contracts, prints tools and allowed roots
python mcp/ideate_v2_mcp/server.py                     # stdio server
```

Register it in the project's `.mcp.json` (not done automatically):

```json
{"mcpServers": {"ideate_v2": {
  "command": "python",
  "args": ["mcp/ideate_v2_mcp/server.py"],
  "env": {"IDEATE_ALLOWED_ROOTS": "ai_scientist/ideas", "IDEATE_TOOL_TIMEOUT_S": "30", "IDEATE_LOG_LEVEL": "INFO"}}}}
```

| Variable | Default | Meaning |
|---|---|---|
| `IDEATE_ALLOWED_ROOTS` | the working directory | `os.pathsep`-separated roots; a `run_dir` must resolve (symlinks followed) inside one |
| `IDEATE_TOOL_TIMEOUT_S` | 30 | per-call time limit; on expiry the caller gets `IDEATE.TOOL.TIMEOUT` |
| `IDEATE_LOG_LEVEL` | INFO | stderr logging (one JSON line per call, metadata only) |

## Tools

Every tool returns an envelope `{ok, tool, trace_id, duration_ms, data | error}` as structured content
(`outputSchema` = the envelope); a failure sets `isError: true` and carries `{error_code, error_category,
error_message, severity, retryable, recovery_action, context}`. Arguments of the wrong JSON type are rejected by the
SDK before the handler runs (`isError: true`, text message); every other problem uses the envelope.

| Tool | Purpose | Side effects |
|---|---|---|
| `ideate_list_units` | Units, filtered by block / step / kind | none |
| `ideate_get_contract` | any entity; for a Unit its 27-field spec and substeps | none |
| `ideate_run_status` | ledger state of every Unit, `next`, planning presence for `generation` | none |
| `ideate_check_gate` | contract-level gate (Units done, artifacts parse, rules) | GATE_CHECKED with `run_id` |
| `ideate_check_loop` | may a declared loop iterate (fails closed) | LOOP_* with `run_dir` + `run_id` |
| `ideate_record_event` | lifecycle event, validated, idempotent by key | appends events.jsonl |
| `ideate_record_error` | structured error record, idempotent by key | appends units/&lt;unit&gt;@&lt;instance&gt;.jsonl |
| `ideate_retry_decision` | retry / stop / refuse (nested) / escalate with delay | RETRY_* / ESCALATED with `record` |
| `ideate_build_report` | step and overall reports, root causes, must-disclose list | writes reports + ERRORS.md (`write`) |
| `ideate_trace` | a Unit's history, or an error's chain to its root cause | none |

Full input and output schemas: [schemas/tools.json](schemas/tools.json).

## Resources

`ideate://architecture` · `ideate://units/{unit_id}` · `ideate://entities/{entity_id}` · `ideate://schemas/{name}`
(`tools`, `envelope`, `error_record`, `event`) · `ideate://errors/taxonomy`

## Example calls

```json
{"tool": "ideate_record_event", "arguments": {"run_dir": "ai_scientist/ideas/eeg_research", "event_type": "RUN_STARTED"}}
{"tool": "ideate_run_status", "arguments": {"run_dir": "ai_scientist/ideas/eeg_research"}}
{"tool": "ideate_check_gate", "arguments": {"run_dir": "ai_scientist/ideas/eeg_research", "gate_id": "GATE-a2-check",
                                            "run_id": "r_20261022_100000_abcd"}}
{"tool": "ideate_check_loop", "arguments": {"loop_id": "LOOP-04", "completed": 1, "observed": {"growth": 0.07}}}
{"tool": "ideate_retry_decision", "arguments": {"policy_id": "RP-UNIT", "attempts_done": 1, "requested_by": "orchestrator",
                                                "error": {"error_category": "interrupted"}}}
```

## Security notes

* Trust boundary: arguments are untrusted. Paths are resolved and confined to the allowed roots; schema names are a
  closed pattern; ids are checked against the registry.
* Event `context`, `message` and error records are redacted (sensitive keys, bearer tokens, `?api_key=` query
  values) and size-bounded before they are written; logs carry no arguments.
* A timed-out handler thread may still finish; its writes are atomic and keyed, so a retried call with the same
  `idempotency_key` cannot duplicate them.

## Tests

`python -m pytest tests/test_mcp_server.py` drives the server through the SDK's in-memory client
(tool list vs `tools.json`, parameter parity, envelopes, `isError`, resources, time limit vs lock timeout).
