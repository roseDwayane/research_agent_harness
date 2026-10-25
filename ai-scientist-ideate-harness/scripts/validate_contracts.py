#!/usr/bin/env python3
"""Validate the v2 Unit contracts (contracts/architecture.json + contracts/units/*.json + the legacy snapshot).

Checks: JSON Schema; duplicate and dangling ids; step membership and gate chaining; dependency cycles and forward
references; artifact ownership (one owner per part), producers and ordering (implicit dependencies); completeness of
the 27 canonical fields per Unit; verdicts; drift against the legacy registry; MCP schema files parse.

    python scripts/validate_contracts.py [--json] [--strict] [--quiet]
         [--legacy-registry <path to ideate_units.json> | env IDEATE_LEGACY_SKILL_DIR]

Exit codes: 0 no ERROR (and no WARN with --strict), 1 findings, 2 the contracts could not be read.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # the module root: ideate_v2 importable,
                                                                  # also under python -I

from ideate_v2 import ARCHITECTURE_JSON, LEGACY_SKILL_DIR, MCP_SCHEMAS_DIR
from ideate_v2.contracts import summary, validate_registry
from ideate_v2.registry import Registry


def mcp_schema_findings() -> list[dict]:
    out = []
    files = sorted(MCP_SCHEMAS_DIR.glob("*.json")) if MCP_SCHEMAS_DIR.is_dir() else []
    if not files:
        out.append({"level": "WARN", "code": "C-MCP-SCHEMA", "entity": str(MCP_SCHEMAS_DIR),
                    "message": "no MCP schema files found"})
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            out.append({"level": "ERROR", "code": "C-MCP-SCHEMA", "entity": f.name, "message": f"does not parse: {e}"})
            continue
        if not isinstance(data, dict) or not ("type" in data or "$defs" in data or "tools" in data):
            out.append({"level": "ERROR", "code": "C-MCP-SCHEMA", "entity": f.name,
                        "message": "not a JSON Schema (no type/$defs) nor a tool catalogue (no tools)"})
    return out


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):        # a console code page (cp1252) must not crash on a path
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    ap = argparse.ArgumentParser(description="Validate the v2 Unit contracts.")
    ap.add_argument("--registry", type=Path, default=ARCHITECTURE_JSON)
    ap.add_argument("--legacy-registry", type=Path, help="live legacy ideate_units.json for the drift check")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--strict", action="store_true", help="WARN findings also fail")
    ap.add_argument("--quiet", action="store_true", help="print only ERROR and WARN findings")
    a = ap.parse_args(argv)
    live = a.legacy_registry
    if live is None:
        live = LEGACY_SKILL_DIR / "scripts" / "ideate_units.json"
    try:
        reg = Registry.load(a.registry)
    except (OSError, ValueError, KeyError) as e:
        print(f"error: cannot load the contracts: {e}", file=sys.stderr)
        return 2
    findings = validate_registry(reg, live_registry=live) + mcp_schema_findings()
    if live is None:
        findings.append({"level": "INFO", "code": "C-LEGACY-LIVE", "entity": "legacy registry",
                         "message": "drift against the live legacy registry not checked (no --legacy-registry or "
                                    "IDEATE_LEGACY_SKILL_DIR)"})
    counts = summary(findings)
    failed = counts["ERROR"] > 0 or (a.strict and counts["WARN"] > 0)
    if a.json:
        print(json.dumps({"registry": str(a.registry), "units": len(reg.units), "substeps": len(reg.substeps),
                          "counts": counts, "passed": not failed, "findings": findings}, indent=2, ensure_ascii=False))
    else:
        for f in findings:
            if a.quiet and f["level"] == "INFO":
                continue
            print(f"{f['level']:5} {f['code']:18} {f['entity'] or '-':22} {f['message']}")
        print(f"\n{len(reg.units)} units, {len(reg.substeps)} substeps: {counts['ERROR']} error(s), {counts['WARN']} "
              f"warning(s), {counts['INFO']} info -> {'FAIL' if failed else 'PASS'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
