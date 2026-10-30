"""The canonical Unit specification: 27 fields composed from the v2 contract (contracts/units/*.json) and the
implementation snapshot (contracts/legacy_snapshot.json). Validators and the documentation use this one function,
so a field can never be complete in one and empty in the other.

Rule for empty fields: a value is either content, ``N/A - <justification>``, or ``TBD - <follow-up action>``.
"""
from __future__ import annotations

from .registry import ORCHESTRATOR, Registry

FIELDS: list[tuple[str, str]] = [
    ("unit_id", "Unit ID"), ("name", "Name"), ("parent_step", "Parent Step"), ("purpose", "Purpose"),
    ("necessity", "Necessity"), ("trigger", "Trigger"), ("input", "Input"), ("input_schema", "Input Schema"),
    ("output", "Output"), ("output_schema", "Output Schema"), ("resources", "Resources"), ("tools", "Tools"),
    ("mcp_dependencies", "MCP Dependencies"), ("preconditions", "Preconditions"), ("postconditions", "Postconditions"),
    ("dependencies", "Dependencies"), ("execution_logic", "Execution Logic"), ("state_management", "State Management"),
    ("failure_modes", "Failure Modes"), ("error_handling", "Error Handling"), ("observability", "Observability"),
    ("validation", "Validation"), ("idempotency", "Idempotency"), ("security", "Security"),
    ("performance", "Performance"), ("testing", "Testing"), ("open_questions", "Open Questions"),
]
V2_OBSERVABILITY = ("v2 events UNIT_STARTED / TOOL_* / UNIT_COMPLETED|DEGRADED|PENDING|FAILED with run_id, trace_id, "
                    "span_id, instance, attempt; error records in _state/errors/<run_id>/units/")


def _list(xs) -> list[str]:
    return [str(x) for x in xs or [] if str(x).strip()]


def _codes(done_when) -> list[str]:
    out = []
    for c in done_when or []:
        if isinstance(c, dict):
            codes = "/".join(c.get("codes") or [])
            neg = c.get("negative_fixture")
            out.append(f"{codes}: {c.get('check')}" + (f" (counter-example {neg})" if neg else ""))
    return out


def _art(reg: Registry, aid: str) -> str:
    if aid not in reg.index:
        return f"{aid} (unknown)"
    a = reg.get(aid)
    part = f" [{a['part']}]" if a.get("part") else ""
    return f"{aid} = {a['path']}{part}"


def _art_schema(reg: Registry, aid: str) -> str:
    return f"{aid}: {reg.get(aid)['schema']}" if aid in reg.index else f"{aid}: (unknown)"


def implicit_dependencies(reg: Registry, unit_id: str, requires: dict[str, list[str]] | None = None) -> list[dict]:
    """Inputs whose producer is not upstream through ``requires``. Each is either covered by a gate on the path into
    the consumer's step, covered by a declared loop, or uncovered (a real ordering hole)."""
    req = requires if requires is not None else {u: reg.requires(u) for u in reg.units}

    def upstream(u: str) -> set[str]:
        seen, stack = set(), list(req.get(u, []))
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack += req.get(x, [])
        return seen

    u = reg.units[unit_id]
    ups = upstream(unit_id)
    gates = reg.gates_into(u["step"])
    out = []
    for aid in (u["inputs"]["required"] + u["inputs"]["optional"]):
        prods = reg.producers(aid)
        if not prods or prods & (ups | {unit_id}):
            continue
        for p in sorted(prods):
            gate = next((g["id"] for g in gates if p in g.get("requires_done", [])), None)
            loop = reg.loop_covers(p, unit_id)
            out.append({"consumer": unit_id, "artifact": aid, "producer": p, "covered_by_gate": gate,
                        "covered_by_loop": loop, "optional": aid in u["inputs"]["optional"]})
    return out


def canonical_spec(reg: Registry, unit_id: str) -> dict[str, list[str] | str]:
    """-> {field key: str | list[str]} for all 27 fields, in FIELDS order."""
    u = reg.units[unit_id]
    leg = reg.legacy_card(unit_id) or {}
    step = reg.get(u["step"]) if u["step"] in reg.index else {}
    eb = u["error_boundary"]
    s: dict[str, list[str] | str] = {}
    s["unit_id"] = unit_id
    s["name"] = f"{u['name']} ({u['name_zh']})"
    s["parent_step"] = f"{u['step']} {step.get('name', '?')} ({step.get('name_zh', '')}) in {step.get('block', '?')}"
    s["purpose"] = u.get("purpose") or leg.get("purpose") or "TBD - write the purpose on the contract"
    s["necessity"] = u["necessity"]
    s["trigger"] = u["trigger"]
    inp = [f"required: {_art(reg, a)}" for a in u["inputs"]["required"]]
    inp += [f"optional: {_art(reg, a)}" for a in u["inputs"]["optional"]]
    inp += [f"context: {c}" for c in u["inputs"]["context"]]
    inp += [f"legacy reads: {r}" for r in _list(leg.get("reads"))]
    s["input"] = inp or ["N/A - the Unit reads no artifact"]
    s["input_schema"] = [_art_schema(reg, a) for a in u["inputs"]["required"] + u["inputs"]["optional"]] or \
        ["N/A - no artifact inputs"]
    out = [_art(reg, a) for a in u["outputs"]["artifacts"]]
    out += [f"side effect: {x}" for x in u["outputs"]["side_effects"]]
    s["output"] = out
    osch = [_art_schema(reg, a) for a in u["outputs"]["artifacts"]]
    osch += [f"legacy schema {k}: {v}" for k, v in (leg.get("schemas") or {}).items()]
    s["output_schema"] = osch
    services = [e["name"] for e in reg.arch.get("external_services") or []
                if unit_id in e.get("used_by", []) and e["id"] != "EXT-llm"]
    network = leg.get("network") or (", ".join(services) if services else "none")
    res = [f"actor: {leg.get('actor') or u['kind']}", f"network: {network}"]
    if leg.get("budget"):
        res.append(f"budget: {leg['budget']}")
    if leg.get("scratch"):
        res.append(f"scratch: {leg['scratch']}")
    if u["llm"]:
        res.append("model: Claude (main session or subagents) - EXT-llm")
    s["resources"] = res
    s["tools"] = [f"command: {c}" for c in u["commands"]] + [f"code: {c}" for c in _list(leg.get("code"))]
    mcp = _list(u["mcp"]) + [f"legacy server: {x}" for x in _list(leg.get("server"))]
    s["mcp_dependencies"] = mcp or ["N/A - the Unit calls no MCP server itself; the v2 orchestrator records its "
                                    "lifecycle through MCP-ideate-v2"]
    s["preconditions"] = _list(u["preconditions"]) + [f"hard stop if: {h}" for h in _list(leg.get("hard_stop"))]
    s["postconditions"] = _list(u.get("postconditions")) or _codes(leg.get("done_when")) or \
        ["TBD - declare done_when checks on a registry card (OQ-06)"]
    deps = [f"requires: {', '.join(reg.requires(unit_id)) or 'none'}",
            f"required by: {', '.join(reg.dependents(unit_id)) or 'none'}"]
    if leg.get("invalidates"):
        deps.append("invalidates (legacy): " + "; ".join(_list(leg["invalidates"]) if isinstance(leg["invalidates"], list)
                                                         else [str(leg["invalidates"])]))
    for r in leg.get("revised_by") or []:
        if isinstance(r, dict):
            deps.append(f"revised by {r.get('by')}: {r.get('field')} via {r.get('via')}")
    for r in _list(leg.get("revises")):
        deps.append(f"revises: {r}")
    for imp in implicit_dependencies(reg, unit_id):
        cover = (f"covered by {imp['covered_by_gate']}" if imp["covered_by_gate"] else
                 "covered by a declared loop" if imp["covered_by_loop"] else "NOT covered")
        deps.append(f"implicit: reads {imp['artifact']} from {imp['producer']} ({cover})")
    if u.get("legacy_deviation"):
        deps.append(f"deviation from legacy: {u['legacy_deviation']}")
    s["dependencies"] = deps
    s["execution_logic"] = _list(u["logic"])
    st = [u["state"]]
    for k in ("instance", "frozen", "resume"):
        if leg.get(k):
            st.append(f"legacy {k}: {leg[k]}")
    s["state_management"] = st
    s["failure_modes"] = _list(u.get("failure_modes")) or _list(leg.get("failures")) or \
        ["TBD - enumerate failure modes on the registry card"]
    eh = [f"retry policy: {eb['retry_policy']}", f"local recovery: {eb['local_recovery']}",
          f"escalation: {eb['escalation']}"]
    eh += [f"degraded path: {d}" for d in _list(leg.get("degraded"))]
    s["error_handling"] = eh
    obs = [u["observability"]] if u.get("observability") else []
    if leg.get("counts"):
        obs.append("done counts: " + "; ".join(_list(leg["counts"])))
    if leg.get("status_line"):
        obs.append(f"status line: {leg['status_line']}")
    if leg.get("audit"):
        obs.append(f"audit: {leg['audit']}")
    obs.append(V2_OBSERVABILITY)
    s["observability"] = obs
    val = _codes(leg.get("done_when"))
    if leg:
        val.append(f"maturity: {leg.get('achieved_level')} ({leg.get('conditions_met')}/12 conditions, legacy units check)")
    else:
        val.append("TBD - no registry card: checks exist only as tools (see Postconditions); maturity not assessed")
    s["validation"] = val
    s["idempotency"] = u["idempotency"]
    sec = [u["security"]]
    if leg.get("forbidden"):
        sec.append("forbidden reads: " + ", ".join(_list(leg["forbidden"])))
    s["security"] = sec
    s["performance"] = u.get("performance") or (f"budget (legacy estimate): {leg['budget']}" if leg.get("budget") else
                                                 "TBD - measure per-instance duration and tokens (OQ-12)")
    if u.get("testing"):
        s["testing"] = [u["testing"]]
    else:
        t = leg.get("tests") or {}
        s["testing"] = ([f"legacy files: {', '.join(_list(t.get('files')))}"] if t.get("files") else []) + \
            ([f"fixtures: {t['fixtures']}"] if t.get("fixtures") else []) + \
            ([f"replay: {t['replay']}"] if t.get("replay") else []) + \
            ([f"interrupt: {t['interrupt']}"] if t.get("interrupt") else []) or \
            ["TBD - add contract tests and counter-examples"]
    oq = []
    for q in u["open_questions"]:
        if q in reg.index:
            oq.append(f"{q}: {reg.get(q)['question']}")
        else:
            oq.append(f"{q}: (unknown)")
    s["open_questions"] = oq or ["None open for this Unit."]
    return s


def classification(reg: Registry, unit_id: str) -> str:
    u = reg.units[unit_id]
    leg = reg.legacy_card(unit_id) or {}
    side = "network + files" if any(unit_id in e.get("used_by", []) and e["id"] != "EXT-llm"
                                    for e in reg.arch.get("external_services") or []) else "files only"
    return (f"kind {u['kind']} · deterministic {u['deterministic']} · LLM {'yes' if u['llm'] else 'no'} · "
            f"on ledger {'yes' if u['on_ledger'] else 'no'} · maturity {leg.get('achieved_level', 'n/a (no card)')} · "
            f"side effects: {side} (atomic writes; rollback = re-run from the ledger) · provenance {u['provenance']}")


def orchestrator_owned(reg: Registry) -> list[str]:
    return [a["id"] for a in reg.arch.get("artifacts") or [] if any(o.get("unit") == ORCHESTRATOR for o in a.get("owners") or [])]
