"""Validation of the v2 contracts. Each finding: {level ERROR|WARN|INFO, code, entity, message}.

ERROR = the contracts are inconsistent (schema, duplicate or dangling ids, cycles, ownership conflicts, empty fields).
WARN  = a design problem the contracts reveal (an input read without any ordering guarantee, an undeclared deviation
        from the legacy registry, drift of the snapshot).
INFO  = facts worth seeing (inputs ordered only by a gate, TBD markers, legacy-only ordering holes v2 fixes).
"""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from pathlib import Path

from . import ARCHITECTURE_SCHEMA
from .gates import RULES
from .jsonio import read_json
from .registry import ORCHESTRATOR, CycleError, Registry
from .schema_lite import validate as schema_validate
from .spec import FIELDS, canonical_spec, implicit_dependencies

VERDICTS = ("KEEP", "MERGE", "SPLIT", "REFACTOR", "OPTIONAL", "REMOVE", "TBD")


def _f(level: str, code: str, entity: str | None, message: str) -> dict:
    return {"level": level, "code": code, "entity": entity, "message": message}


def _empty(v) -> bool:
    if isinstance(v, list):
        return not v or all(not str(x).strip() for x in v)
    return not str(v or "").strip()


def _placeholder_problem(v) -> str | None:
    """'N/A' needs a justification and 'TBD' a follow-up action after a dash."""
    for x in (v if isinstance(v, list) else [v]):
        t = str(x).strip()
        for tag in ("N/A", "TBD"):
            if t.upper().startswith(tag) and len(t.split("-", 1)[-1].strip()) < 8:
                return f"'{tag}' without a justification or follow-up action"
    return None


def schema_findings(reg: Registry, schema: dict) -> list[dict]:
    """Validate the registry as loaded (in memory), so mutated or generated registries are checked too."""
    out = [_f("ERROR", "C-SCHEMA", "architecture.json", e) for e in schema_validate(reg.arch, schema)]
    unit_file_schema = {"$ref": "#/$defs/unit_file", "$defs": schema["$defs"]}
    names = reg.arch.get("unit_files") or []
    for i, doc in enumerate(reg.unit_docs):
        label = names[i] if i < len(names) else f"unit document {i}"
        out += [_f("ERROR", "C-SCHEMA", label, e) for e in schema_validate(doc, unit_file_schema)]
    return out


def reference_findings(reg: Registry) -> list[dict]:
    out = []

    def need(eid: str, kinds: tuple, where: str) -> None:
        k = reg.kind_of(eid)
        if k not in kinds:
            out.append(_f("ERROR", "C-REF", where, f"{eid!r} should be a {'/'.join(kinds)}, found {k or 'nothing'}"))

    for d in reg.duplicates:
        out.append(_f("ERROR", "C-DUP-ID", d, f"id {d!r} is defined more than once"))
    for s in reg.arch.get("stages") or []:
        for b in s["blocks"]:
            need(b, ("block",), s["id"])
    for b in reg.arch.get("blocks") or []:
        need(b["stage"], ("stage",), b["id"])
        need(b["exit_gate"], ("gate",), b["id"])
        for s in b["steps"]:
            need(s, ("step",), b["id"])
        for a in b["exit_contract"]:
            need(a, ("artifact",), b["id"])
    for st in reg.steps():
        need(st["block"], ("block",), st["id"])
        for g in ("entry_gate", "exit_gate"):
            if st.get(g):
                need(st[g], ("gate",), st["id"])
        for u in st["units"]:
            need(u, ("unit",), st["id"])
    for uid, u in reg.units.items():
        need(u["step"], ("step",), uid)
        for r in u["requires"]:
            need(r, ("unit",), uid)
        for a in u["inputs"]["required"] + u["inputs"]["optional"] + u["outputs"]["artifacts"]:
            need(a, ("artifact",), uid)
        need(u["error_boundary"]["retry_policy"], ("retry_policy",), uid)
        for q in u["open_questions"]:
            need(q, ("open_question",), uid)
        for s in u.get("substeps") or []:
            need(s, ("substep",), uid)
    for sid, s in reg.substeps.items():
        need(s["parent"], ("unit",), sid)
        if sid not in (reg.units.get(s["parent"], {}).get("substeps") or []):
            out.append(_f("ERROR", "C-REF", sid, f"parent {s['parent']} does not list this substep"))
    for g in reg.arch.get("gates") or []:
        need(g["from_step"], ("step",), g["id"])
        need(g["to_step"], ("step",), g["id"])
        for u in g["requires_done"]:
            need(u, ("unit",), g["id"])
        for a in g["requires_artifacts"]:
            need(a, ("artifact",), g["id"])
        for r in g["rules"]:
            if r["rule"] not in RULES:
                out.append(_f("ERROR", "C-REF", g["id"], f"unknown gate rule {r['rule']!r}"))
    for lp in reg.arch.get("loops") or []:
        need(lp["from"], ("unit", "step", "gate"), lp["id"])
        for t in lp["to"]:
            need(t, ("unit", "step"), lp["id"])
    for a in reg.arch.get("artifacts") or []:
        for o in a["owners"]:
            if o["unit"] != ORCHESTRATOR:
                need(o["unit"], ("unit",), a["id"])
        for d in a.get("derived_from") or []:
            need(d, ("artifact",), a["id"])
        for r in a.get("revised_by") or []:
            need(r, ("unit",), a["id"])
    for e in reg.arch.get("external_services") or []:
        for u in e["used_by"]:
            need(u, ("unit",), e["id"])
    for q in reg.arch.get("open_questions") or []:
        for r in q["refs"]:
            if reg.kind_of(r) is None:
                out.append(_f("ERROR", "C-REF", q["id"], f"refers to unknown id {r!r}"))
    return out


def structure_findings(reg: Registry) -> list[dict]:
    out = []
    homes = defaultdict(list)
    for st in reg.steps():
        for u in st["units"]:
            homes[u].append(st["id"])
    for uid, u in reg.units.items():
        if homes.get(uid) != [u["step"]]:
            out.append(_f("ERROR", "C-STEP-MEMBERSHIP", uid, f"declares step {u['step']} but is listed by "
                          f"{homes.get(uid) or 'no step'}"))
    for st in reg.steps():
        if st.get("exit_gate") and st["exit_gate"] in reg.index and reg.get(st["exit_gate"])["from_step"] != st["id"]:
            out.append(_f("ERROR", "C-GATE-CHAIN", st["id"], f"exit gate {st['exit_gate']} starts at "
                          f"{reg.get(st['exit_gate'])['from_step']}"))
        if st.get("entry_gate") and st["entry_gate"] in reg.index and reg.get(st["entry_gate"])["to_step"] != st["id"]:
            out.append(_f("ERROR", "C-GATE-CHAIN", st["id"], f"entry gate {st['entry_gate']} leads to "
                          f"{reg.get(st['entry_gate'])['to_step']}"))
    try:
        reg.topo_order()
    except CycleError as e:
        out.append(_f("ERROR", "C-CYCLE", e.cycle[0], str(e)))
    order = reg.step_order()
    for uid, u in reg.units.items():
        for r in u["requires"]:
            if r in reg.units and reg.step_of(r) in order and u["step"] in order and \
                    order.index(reg.step_of(r)) > order.index(u["step"]):
                out.append(_f("ERROR", "C-FORWARD-REF", uid, f"requires {r}, which runs in a later step"))
    return out


def io_findings(reg: Registry) -> list[dict]:
    out = []
    by_path = defaultdict(list)
    for a in reg.arch.get("artifacts") or []:
        by_path[a["path"]].append(a)
        parts = Counter(o.get("part", "") for o in a["owners"])
        for part, n in parts.items():
            if n > 1:
                out.append(_f("ERROR", "C-IO-OWNER", a["id"], f"{n} owners for the same part {part or '(whole)'}"))
        for o in a["owners"]:
            u = reg.units.get(o["unit"])
            if u is not None and a["id"] not in u["outputs"]["artifacts"]:
                out.append(_f("ERROR", "C-IO-OWNER", a["id"], f"owner {o['unit']} does not list it in its outputs"))
    for path, arts in by_path.items():
        parts = [a.get("part") for a in arts]
        if len(arts) > 1 and (None in parts or len(set(parts)) != len(parts)):
            out.append(_f("ERROR", "C-IO-OWNER", path, "several artifacts share this path without distinct parts"))
    for uid, u in reg.units.items():
        for a in u["outputs"]["artifacts"]:
            if a in reg.index and uid not in {o["unit"] for o in reg.get(a)["owners"]}:
                out.append(_f("ERROR", "C-IO-OWNER", uid, f"outputs {a} but is not among its owners"))
        for a in u["inputs"]["required"] + u["inputs"]["optional"]:
            if a not in reg.index:
                continue
            kind = reg.get(a)["kind"]
            if kind in ("external", "infrastructure"):
                continue
            if not reg.producers(a):
                out.append(_f("ERROR", "C-IO-PRODUCER", uid, f"reads {a}, which no Unit produces"))
    for uid in reg.units:
        for imp in implicit_dependencies(reg, uid):
            if imp["covered_by_loop"]:
                continue
            if imp["covered_by_gate"]:
                out.append(_f("INFO", "C-IO-ORDER", uid, f"reads {imp['artifact']} from {imp['producer']} without "
                              f"requiring it; ordered only by {imp['covered_by_gate']}"))
            else:
                out.append(_f("WARN", "C-IO-ORDER", uid, f"reads {imp['artifact']} from {imp['producer']}, but neither "
                              "requires nor any gate on its path guarantees that it ran (implicit dependency)"))
    return out


def completeness_findings(reg: Registry) -> list[dict]:
    out = []
    for uid in reg.units:
        spec = canonical_spec(reg, uid)
        for key, label in FIELDS:
            v = spec.get(key)
            if _empty(v):
                out.append(_f("ERROR", "C-FIELD-EMPTY", uid, f"field '{label}' is empty"))
            elif _placeholder_problem(v):
                out.append(_f("ERROR", "C-FIELD-EMPTY", uid, f"field '{label}': {_placeholder_problem(v)}"))
        v = reg.units[uid]["verdict"]
        if v["decision"] not in VERDICTS:
            out.append(_f("ERROR", "C-VERDICT", uid, f"unknown verdict {v['decision']!r}"))
    return out


def tbd_findings(reg: Registry) -> list[dict]:
    out = []
    for uid in reg.units:
        spec = canonical_spec(reg, uid)
        for key, label in FIELDS:
            vals = spec[key] if isinstance(spec[key], list) else [spec[key]]
            for x in vals:
                if str(x).strip().upper().startswith("TBD"):
                    out.append(_f("INFO", "C-TBD", uid, f"{label}: {x}"))
    for lp in reg.arch.get("loops") or []:
        if lp["bound"].get("tbd"):
            out.append(_f("INFO", "C-TBD", lp["id"], f"bound: {lp['bound']['tbd']}"))
    for q in reg.arch.get("open_questions") or []:
        out.append(_f("INFO", "C-OPEN-QUESTION", q["id"], f"[{q['priority']}] {q['question']}"))
    return out


def legacy_findings(reg: Registry, live_registry: Path | None = None) -> list[dict]:
    out = []
    snap = reg.legacy or {}
    if not snap:
        return [_f("WARN", "C-LEGACY-MISSING", "legacy_snapshot.json", "no legacy snapshot: implementation facts "
                   "are missing from the canonical specs (run scripts/import_legacy_registry.py)")]
    legacy_units = set(snap.get("units") or {})
    ledger_units = {u for u, spec in reg.units.items() if spec["on_ledger"]}
    for u in sorted(legacy_units - set(reg.units)):
        out.append(_f("ERROR", "C-LEGACY-UNIT", u, "a legacy Unit card has no v2 contract"))
    for u in sorted(ledger_units - legacy_units):
        out.append(_f("ERROR", "C-LEGACY-UNIT", u, "on_ledger is true but there is no legacy card"))
    for u in sorted(set(reg.units) & legacy_units):
        legacy_req = {str(r).split()[0].strip("(),") for r in snap["units"][u].get("requires") or []}
        legacy_req = {r for r in legacy_req if r in legacy_units}
        v2_req = set(reg.requires(u))
        if legacy_req != v2_req and not reg.units[u].get("legacy_deviation"):
            out.append(_f("WARN", "C-LEGACY-DEVIATION", u, f"requires {sorted(v2_req)} differ from legacy "
                          f"{sorted(legacy_req)} without a declared legacy_deviation"))
    # ordering holes in the legacy graph that the v2 graph closes (shown so the change is auditable)
    legacy_requires = {}
    for u in reg.units:
        card = (snap.get("units") or {}).get(u)
        legacy_requires[u] = ([t for t in ({str(r).split()[0].strip("(),") for r in card.get("requires") or []})
                               if t in reg.units] if card else reg.requires(u))
    v2_holes = {(i["consumer"], i["artifact"], i["producer"]) for uid in reg.units for i in implicit_dependencies(reg, uid)
                if not i["covered_by_gate"] and not i["covered_by_loop"]}
    for uid in reg.units:
        for i in implicit_dependencies(reg, uid, legacy_requires):
            key = (i["consumer"], i["artifact"], i["producer"])
            if not i["covered_by_gate"] and not i["covered_by_loop"] and key not in v2_holes:
                out.append(_f("INFO", "C-LEGACY-HOLE", uid, f"legacy graph: reads {i['artifact']} from {i['producer']} "
                              "with no ordering guarantee - closed in v2"))
    if live_registry is not None:
        if not Path(live_registry).is_file():
            out.append(_f("WARN", "C-LEGACY-LIVE", str(live_registry), "live legacy registry not found; drift not checked"))
        else:
            live = hashlib.sha256(Path(live_registry).read_bytes()).hexdigest()
            pinned = (snap.get("source") or {}).get("sha256")
            if live != pinned:
                out.append(_f("WARN", "C-LEGACY-DRIFT", "legacy_snapshot.json", f"live registry sha256 {live[:12]} != "
                              f"snapshot {str(pinned)[:12]}: re-run scripts/import_legacy_registry.py"))
            else:
                out.append(_f("INFO", "C-LEGACY-DRIFT", "legacy_snapshot.json", "snapshot matches the live registry"))
    return out


def validate_registry(reg: Registry, schema: dict | None = None, live_registry: Path | None = None,
                      include_info: bool = True) -> list[dict]:
    schema = schema if schema is not None else read_json(ARCHITECTURE_SCHEMA)
    findings = schema_findings(reg, schema)
    if any(f["level"] == "ERROR" for f in findings):
        return findings                            # semantic checks on a schema-invalid registry would be noise
    findings += reference_findings(reg)
    findings += structure_findings(reg)
    if not any(f["code"] in ("C-REF", "C-DUP-ID") for f in findings):
        findings += io_findings(reg)
        findings += completeness_findings(reg)
        findings += legacy_findings(reg, live_registry)
        findings += tbd_findings(reg)
    return [f for f in findings if include_info or f["level"] != "INFO"]


def summary(findings: list[dict]) -> dict:
    return {lvl: sum(1 for f in findings if f["level"] == lvl) for lvl in ("ERROR", "WARN", "INFO")}
