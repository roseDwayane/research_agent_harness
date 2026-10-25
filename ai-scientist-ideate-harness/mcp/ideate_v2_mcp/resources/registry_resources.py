"""Resource bodies (JSON text). URIs:

  ideate://architecture                 summary: blocks, steps, gates, loops, counts
  ideate://units/{unit_id}              a Unit's contract, canonical 27-field spec and substeps
  ideate://entities/{entity_id}         any other registry entity (step, gate, loop, artifact, policy, decision, ...)
  ideate://schemas/{name}               a schema file of mcp/ideate_v2_mcp/schemas/ (name without .json)
  ideate://errors/taxonomy              categories, codes, severities, recovery actions
"""
from __future__ import annotations

import json
import re

from ideate_v2 import MCP_SCHEMAS_DIR
from ideate_v2.errors import CATEGORIES, CODES, RECOVERY_ACTIONS, SEVERITIES, IdeateError
from ideate_v2.registry import Registry
from ideate_v2.spec import canonical_spec, classification

_NAME = re.compile(r"^[a-z_]{1,40}$")


def _dump(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def architecture(reg: Registry) -> str:
    a = reg.arch
    return _dump({"schema": a["schema"], "version": a["version"], "status": a["status"], "updated": a["updated"],
                  "blocks": a["blocks"], "steps": a["steps"],
                  "gates": [{k: g[k] for k in ("id", "name", "scope", "from_step", "to_step")} for g in a["gates"]],
                  "loops": [{k: lp[k] for k in ("id", "name", "from", "to", "bound")} for lp in a["loops"]],
                  "counts": {"units": len(reg.units), "substeps": len(reg.substeps), "artifacts": len(a["artifacts"]),
                             "open_questions": len(a["open_questions"])}})


def unit(reg: Registry, unit_id: str) -> str:
    if unit_id not in reg.units:
        raise IdeateError("IDEATE.INPUT.UNKNOWN_ID", f"no Unit {unit_id!r}")
    return _dump({"contract": reg.units[unit_id], "classification": classification(reg, unit_id),
                  "canonical_spec": canonical_spec(reg, unit_id), "substeps": reg.substeps_of(unit_id)})


def entity(reg: Registry, entity_id: str) -> str:
    kind = reg.kind_of(entity_id)
    if kind is None:
        raise IdeateError("IDEATE.INPUT.UNKNOWN_ID", f"no registry entity {entity_id!r}")
    return _dump({"id": entity_id, "kind": kind, "entity": reg.get(entity_id)})


def schema(name: str) -> str:
    """Only files that exist in mcp/ideate_v2_mcp/schemas/ under a simple name: no path traversal is expressible."""
    if not _NAME.match(name or ""):
        raise IdeateError("IDEATE.INPUT.INVALID", "schema name: lower-case letters and underscores only")
    path = MCP_SCHEMAS_DIR / f"{name}.json"
    if not path.is_file():
        path = MCP_SCHEMAS_DIR / f"{name}.schema.json"
    if not path.is_file():
        raise IdeateError("IDEATE.INPUT.UNKNOWN_ID", f"no schema {name!r}",
                          context={"available": sorted(p.stem.replace(".schema", "") for p in MCP_SCHEMAS_DIR.glob("*.json"))})
    return path.read_text(encoding="utf-8")


def taxonomy() -> str:
    return _dump({"severities": list(SEVERITIES), "recovery_actions": list(RECOVERY_ACTIONS),
                  "categories": {c: {"retryable": r, "default_severity": s, "meaning": m}
                                 for c, (r, s, m) in CATEGORIES.items()},
                  "codes": {c: {"category": cat, "meaning": m} for c, (cat, m) in CODES.items()},
                  "unit_check_codes": "<unit>:<code> (e.g. A2.c:R03), category check_failed"})
