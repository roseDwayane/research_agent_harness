"""MCP protocol tests: registration matches the published schemas, envelopes and isError, resources, time limits."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time

import pytest

pytest.importorskip("mcp", reason="the official MCP SDK is not installed (pip install -r requirements.txt)")

from mcp.shared.memory import create_connected_server_and_client_session  # noqa: E402

from conftest import MODULE  # noqa: E402


@pytest.fixture(scope="module")
def server():
    spec = importlib.util.spec_from_file_location("ideate_v2_server_under_test", MODULE / "mcp" / "ideate_v2_mcp" / "server.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def run(coro):
    return asyncio.run(coro)


def test_registered_tools_match_the_catalogue(server):
    from tools.envelope import CATALOG

    async def go():
        async with create_connected_server_and_client_session(server.mcp) as c:
            return (await c.list_tools()).tools
    tools = {t.name: t for t in run(go())}
    assert set(tools) == set(CATALOG["tools"])
    for name, t in tools.items():
        published = CATALOG["tools"][name]["input"]
        assert set(t.inputSchema["properties"]) == set(published.get("properties", {})), name
        assert set(t.inputSchema.get("required", [])) == set(published.get("required", [])), name
        assert set((t.outputSchema or {}).get("properties", {})) == {"ok", "tool", "trace_id", "duration_ms", "data",
                                                                      "error"}, name
        assert t.annotations is not None


def test_envelopes_and_is_error(server, dataset, monkeypatch):
    root, run_dir = dataset("search_complete")
    monkeypatch.setenv("IDEATE_ALLOWED_ROOTS", str(root))
    server._CTX = None                                    # pick up the allowed root of this test

    async def go():
        async with create_connected_server_and_client_session(server.mcp) as c:
            ok = await c.call_tool("ideate_run_status", {"run_dir": str(run_dir)})
            bad = await c.call_tool("ideate_run_status", {"run_dir": str(root.parent)})
            wrong_type = await c.call_tool("ideate_check_loop", {"loop_id": "LOOP-04", "completed": "three"})
            return ok, bad, wrong_type
    ok, bad, wrong_type = run(go())
    server._CTX = None
    assert ok.isError is False and ok.structuredContent["data"]["units"]["A4.b"]["state"] == "done"
    assert json.loads(ok.content[0].text)["ok"] is True
    assert bad.isError is True and bad.structuredContent["error"]["error_code"] == "IDEATE.PATH.DENIED"
    assert "Traceback" not in bad.content[0].text
    assert wrong_type.isError is True                      # rejected by the SDK's schema check before the handler


def test_resources(server):
    async def go():
        async with create_connected_server_and_client_session(server.mcp) as c:
            unit = await c.read_resource("ideate://units/B3.5")
            tax = await c.read_resource("ideate://errors/taxonomy")
            schema = await c.read_resource("ideate://schemas/event")
            return unit, tax, schema
    unit, tax, schema = run(go())
    assert json.loads(unit.contents[0].text)["contract"]["step"] == "STEP-F4"
    assert "external_service" in json.loads(tax.contents[0].text)["categories"]
    assert json.loads(schema.contents[0].text)["$id"] == "ideate-v2-event/1"


def test_schema_resource_refuses_traversal():
    from resources import registry_resources as res
    from ideate_v2.errors import IdeateError
    with pytest.raises(IdeateError):
        res.schema("../contracts/architecture")


def test_time_limit_and_lock_timeout_are_distinguished():
    from tools.envelope import run_tool
    from ideate_v2.jsonio import LockTimeout

    def slow(ctx, a):
        time.sleep(1.0)
        return {"count": 0, "units": []}

    def locked(ctx, a):
        raise LockTimeout("events.jsonl.lock held")

    env = asyncio.run(run_tool("ideate_list_units", slow, None, {}, timeout_s=0.1))
    assert env["ok"] is False and env["error"]["error_code"] == "IDEATE.TOOL.TIMEOUT"
    env = asyncio.run(run_tool("ideate_list_units", locked, None, {}))
    assert env["error"]["error_code"] == "IDEATE.STATE.LOCK_TIMEOUT" and env["error"]["retryable"] is True


def test_output_schema_violation_is_an_error():
    from tools.envelope import execute
    env = execute("ideate_list_units", lambda c, a: {"units": []}, None, {})       # "count" missing
    assert env["ok"] is False and env["error"]["error_code"] == "IDEATE.OUTPUT.SCHEMA"
