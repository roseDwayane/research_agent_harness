"""Render the generated blocks of ARCHITECTURE.md and references/unit_contracts.md from the contracts.

A generated block sits between ``<!-- BEGIN GENERATED:<name> -->`` and ``<!-- END GENERATED:<name> -->``; everything
outside the markers is hand-written. ``scripts/render_docs.py --check`` fails when a block is out of date.
"""
from __future__ import annotations

import re
from pathlib import Path

from .errors import CATEGORIES, CODES
from .registry import Registry
from .spec import FIELDS, canonical_spec, classification, implicit_dependencies

BEGIN = "<!-- BEGIN GENERATED:{name} (scripts/render_docs.py - do not edit by hand) -->"
END = "<!-- END GENERATED:{name} -->"
_BLOCK = re.compile(r"<!-- BEGIN GENERATED:(?P<name>[a-z0-9-]+) [^>]*-->\n(?P<body>.*?)<!-- END GENERATED:(?P=name) -->",
                    re.S)


def _esc(x) -> str:
    """Escape for a Markdown table cell: '<id>' would otherwise be read as an HTML tag and vanish."""
    return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "\\|").replace("\n", " ")


def cell(v) -> str:
    if isinstance(v, (list, tuple)):
        return "<br>".join(_esc(x) for x in v).strip() or "-"
    return _esc(v).strip() or "-"


def table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def mid(eid: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", eid)


# --------------------------------------------------------------------------------------------- blocks
def render_inventory(reg: Registry) -> str:
    parts = ["**Steps** (hierarchy: stage > block > step > unit > substep)", "",
             table(["Step ID", "Block", "#", "Name", "Slide name", "Units", "Entry gate", "Exit gate", "Prov."],
                   [[s["id"], s["block"], s["ordinal"], s["name"], s["name_zh"], ", ".join(s["units"]),
                     s.get("entry_gate") or "-", s.get("exit_gate") or "-", s["provenance"]] for s in reg.steps()]),
             "", "**Units**", "",
             table(["Unit ID", "Name", "Slide name", "Step", "Kind", "Deterministic", "LLM", "Ledger", "Maturity",
                    "Prov."],
                   [[u, reg.units[u]["name"], reg.units[u]["name_zh"], reg.units[u]["step"], reg.units[u]["kind"],
                     reg.units[u]["deterministic"], "yes" if reg.units[u]["llm"] else "no",
                     "yes" if reg.units[u]["on_ledger"] else "no",
                     (reg.legacy_card(u) or {}).get("achieved_level", "no card"), reg.units[u]["provenance"]]
                    for u in reg.unit_order()]),
             "", "**Substeps**", "",
             table(["Substep ID", "Parent", "Name", "Kind", "Prov."],
                   [[s["id"], s["parent"], s["name"] + (f" ({s['name_zh']})" if s.get("name_zh") else ""), s["kind"],
                     s["provenance"]] for s in reg.substeps.values()]),
             "", "**Gates** (green arrows: a failing check refuses the next step)", "",
             table(["Gate ID", "Name", "Scope", "From -> To", "Units that must be done", "Artifacts", "Contract rules",
                    "Legacy command", "Prov."],
                   [[g["id"], g["name"], g["scope"], f"{g['from_step']} -> {g['to_step']}",
                     ", ".join(g["requires_done"]) or "-", ", ".join(g["requires_artifacts"]),
                     ", ".join(r["rule"] for r in g["rules"]) or "-", g["legacy_command"], g["provenance"]]
                    for g in reg.arch["gates"]]),
             "", "**Loops** (back-edges, each bounded)", "",
             table(["Loop ID", "Name", "From", "To", "Bound", "On exhaustion", "Prov."],
                   [[lp["id"], lp["name"], lp["from"], ", ".join(lp["to"]),
                     (f"max {lp['bound']['max_iterations']}" if lp["bound"]["max_iterations"] else "no numeric bound")
                     + "".join(f"; {c['name']} {c['value']}" for c in lp["bound"]["conditions"])
                     + (f"; TBD: {lp['bound']['tbd']}" if lp["bound"].get("tbd") else ""),
                     lp["on_exhausted"], lp["provenance"]] for lp in reg.arch["loops"]]),
             "", "**Artifacts** (data contracts; owners write, everyone else reads)", "",
             table(["Artifact ID", "Path", "Part", "Kind", "Owner(s)", "Schema"],
                   [[a["id"], a["path"], a.get("part") or "-", a["kind"],
                     ", ".join(o["unit"] + (f" ({o['part']})" if o.get("part") else "") for o in a["owners"]) or
                     ("derived from " + ", ".join(a.get("derived_from") or []) if a.get("derived_from") else "-"),
                     a["schema"]] for a in reg.arch["artifacts"]]),
             "", "**Infrastructure, external services, data stores, MCP servers**", "",
             table(["ID", "Name / path", "Role / used by", "Implemented by / via", "Prov."],
                   [[i["id"], i["name"], i["role"], i["implemented_by"], i["provenance"]] for i in reg.arch["infrastructure"]]
                   + [[e["id"], e["name"], "used by " + ", ".join(e["used_by"]), f"{e['via']}; credential: {e['credential']}",
                       e["provenance"]] for e in reg.arch["external_services"]]
                   + [[d["id"], d["path"], d["role"], "-", d["provenance"]] for d in reg.arch["data_stores"]]
                   + [[m["id"], m["name"], "tools: " + ", ".join(m["tools"]), f"{m['transport']} - {m['location']}",
                       m["provenance"]] for m in reg.arch["mcp_servers"]])]
    return "\n".join(parts)


def render_dependency_graph(reg: Registry) -> str:
    lines = ["```mermaid", "flowchart TD"]
    for sid in reg.step_order():
        st = reg.get(sid)
        lines.append(f"  subgraph {mid(sid)}[\"{sid} {st['name']}\"]")
        for u in st["units"]:
            shape = ("([\"{}\"])" if reg.units[u]["kind"] == "script" else "[\"{}\"]").format(u)
            lines.append(f"    {mid(u)}{shape}")
        lines.append("  end")
    for u in reg.unit_order():
        for r in reg.requires(u):
            lines.append(f"  {mid(r)} --> {mid(u)}")
    for lp in reg.arch["loops"]:
        src = lp["from"]
        if reg.kind_of(src) == "gate":
            src = reg.get(src)["from_step"]
        for t in lp["to"]:
            lines.append(f"  {mid(src)} -. {lp['id']} .-> {mid(t)}")
    lines.append("```")
    rows = []
    for u in reg.unit_order():
        rows.append([u, ", ".join(reg.requires(u)) or "-", ", ".join(reg.dependents(u)) or "-",
                     "; ".join(f"{i['artifact']} from {i['producer']} ("
                               f"{i['covered_by_gate'] or ('loop' if i['covered_by_loop'] else 'UNCOVERED')})"
                               for i in implicit_dependencies(reg, u)) or "-"])
    return "\n".join(lines) + "\n\nRounded nodes are scripts; rectangles involve a model. Solid arrows = `requires`; " \
        "dotted = declared loops.\n\n" + table(["Unit", "Upstream (requires)", "Downstream (required by)",
                                               "Implicit inputs (ordered by)"], rows)


def render_unit_specs(reg: Registry) -> str:
    out = []
    for sid in reg.step_order():
        st = reg.get(sid)
        out.append(f"#### {sid} {st['name']} ({st['name_zh']})")
        out.append("")
        for u in st["units"]:
            spec = canonical_spec(reg, u)
            out.append(f"##### {u} - {reg.units[u]['name']}")
            out.append("")
            out.append(f"*{classification(reg, u)}*")
            out.append("")
            out.append(table(["Field", "Specification"], [[label, spec[key]] for key, label in FIELDS]))
            out.append("")
            subs = reg.substeps_of(u)
            if subs:
                out.append(f"Substeps of {u} (every field not listed is inherited from {u}):")
                out.append("")
                out.append(table(["Substep", "Name", "Kind", "Purpose", "Commands", "Checks", "Error boundary",
                                  "Prov."],
                                 [[s["id"], s["name"] + (f" ({s['name_zh']})" if s.get("name_zh") else "")
                                   + (f" [legacy {s['legacy_id']}]" if s.get("legacy_id") else ""), s["kind"],
                                   s["purpose"], s["commands"], s.get("checks") or "-", s["error_boundary"],
                                   s["provenance"]] for s in subs]))
                out.append("")
    return "\n".join(out).rstrip()


VERDICT_QUESTIONS = [("problem", "What problem does it solve?"), ("why_separate", "Why a separate unit?"),
                     ("if_removed", "If removed"), ("merge", "Could it be merged?"), ("duplication", "Duplication"),
                     ("boundary", "I/O boundary"), ("dependencies", "Dependencies justified?"),
                     ("cost_risk", "Complexity, latency, cost, failure risk"),
                     ("quality", "Deterministic / testable / observable / maintainable"),
                     ("alternatives", "Alternatives considered"), ("evidence", "Evidence"), ("benefits", "Benefits"),
                     ("risks", "Risks"), ("actions", "Recommended actions")]


def render_verdict_summary(reg: Registry) -> str:
    counts: dict[str, int] = {}
    rows = []
    for u in reg.unit_order():
        v = reg.units[u]["verdict"]
        counts[v["decision"]] = counts.get(v["decision"], 0) + 1
        rows.append([u, reg.units[u]["name"], f"**{v['decision']}**", v["problem"], v["actions"]])
    head = "Verdicts: " + ", ".join(f"{k} {n}" for k, n in sorted(counts.items())) + f" (of {len(rows)} units)."
    return head + "\n\n" + table(["Unit", "Name", "Verdict", "Problem it solves", "Recommended action"], rows)


def render_verdict_details(reg: Registry) -> str:
    out = []
    for u in reg.unit_order():
        v = reg.units[u]["verdict"]
        out.append(f"##### {u} {reg.units[u]['name']} - {v['decision']}")
        out.append("")
        out.append(table(["Question", "Assessment"], [[label, v[key]] for key, label in VERDICT_QUESTIONS]))
        out.append("")
    return "\n".join(out).rstrip()


def render_error_taxonomy(reg: Registry) -> str:
    cats = table(["Category", "Retryable by default", "Default severity", "Meaning"],
                 [[c, "yes" if r else "no", s, m] for c, (r, s, m) in CATEGORIES.items()])
    codes = table(["Code", "Category", "Meaning"], [[c, cat, m] for c, (cat, m) in CODES.items()])
    pols = table(["Policy", "Owner", "Max attempts", "Retries on", "Backoff", "On exhaustion", "Applies to"],
                 [[p["id"], p["owner"], p["max_attempts"], ", ".join(p["retry_on"]) or "-",
                   (f"{p['backoff']['base_s']}s x{p['backoff']['factor']}, cap {p['backoff']['cap_s']}s, "
                    f"{p['backoff']['jitter']} jitter") if p["backoff"] else "none", p["on_exhausted"], p["applies_to"]]
                  for p in reg.arch["retry_policies"]])
    return ("**Categories** (ideate_v2/errors.py)\n\n" + cats + "\n\n**v2 codes** (Unit check codes are namespaced "
            "`<unit>:<code>`, category `check_failed`)\n\n" + codes + "\n\n**Retry policies** (one owner per level)\n\n"
            + pols)


def render_decisions(reg: Registry) -> str:
    return table(["ID", "Title", "Decision", "Rationale", "Status", "Prov."],
                 [[d["id"], d["title"], d["decision"], d["rationale"], d["status"], d["provenance"]]
                  for d in reg.arch["decisions"]])


def render_open_questions(reg: Registry) -> str:
    return table(["ID", "Priority", "Owner role", "Question", "Impact", "Resolution criteria", "Refs"],
                 [[q["id"], q["priority"], q["owner_role"], q["question"], q["impact"], q["resolution"],
                   ", ".join(q["refs"]) or "-"] for q in reg.arch["open_questions"]])


def render_contract_index(reg: Registry) -> str:
    rows = []
    for u in reg.unit_order():
        spec = reg.units[u]
        rows.append([u, spec["name"], spec["step"], spec["kind"], ", ".join(spec["requires"]) or "-",
                     ", ".join(spec["inputs"]["required"]) or "-", ", ".join(spec["outputs"]["artifacts"]),
                     spec["error_boundary"]["retry_policy"], spec["verdict"]["decision"]])
    return table(["Unit", "Name", "Step", "Kind", "Requires", "Required inputs", "Outputs", "Retry policy", "Verdict"],
                 rows)


RENDERERS = {
    "inventory": render_inventory,
    "dependency-graph": render_dependency_graph,
    "unit-specs": render_unit_specs,
    "verdict-summary": render_verdict_summary,
    "verdict-details": render_verdict_details,
    "error-taxonomy": render_error_taxonomy,
    "decisions": render_decisions,
    "open-questions": render_open_questions,
    "contract-index": render_contract_index,
}


def blocks_in(text: str) -> list[str]:
    return [m.group("name") for m in _BLOCK.finditer(text)]


def render_file(reg: Registry, text: str) -> str:
    """Replace every generated block's body; unknown block names are an error (a typo would otherwise go stale)."""
    def repl(m: re.Match) -> str:
        name = m.group("name")
        if name not in RENDERERS:
            raise KeyError(f"unknown generated block {name!r}")
        return BEGIN.format(name=name) + "\n" + RENDERERS[name](reg).rstrip() + "\n" + END.format(name=name)
    return _BLOCK.sub(repl, text)


def stale_blocks(reg: Registry, path: Path) -> list[str]:
    text = Path(path).read_text(encoding="utf-8")
    fresh = render_file(reg, text)
    if fresh == text:
        return []
    old = {m.group("name"): m.group("body") for m in _BLOCK.finditer(text)}
    new = {m.group("name"): m.group("body") for m in _BLOCK.finditer(fresh)}
    return sorted(n for n in new if old.get(n) != new[n])
