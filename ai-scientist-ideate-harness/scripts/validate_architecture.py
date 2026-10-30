#!/usr/bin/env python3
"""Validate ARCHITECTURE.md against the contracts.

Checks: the file exists; the required sections and subsections are present, once; every generated block is present
and up to date; Mermaid blocks are well-formed (>= 3); every Unit, step, gate and loop id of the registry appears;
every Unit has exactly one specification heading (missing or duplicated Unit ids); every typed id the document cites
(STEP-, GATE-, LOOP-, ART-, OQ-, D-, RP-, INFRA-, EXT-, STORE-, MCP-) exists; local links resolve.
TBD markers are reported as information with line numbers - they are tracked, not syntax errors.

    python scripts/validate_architecture.py [--doc ARCHITECTURE.md] [--json]

Exit codes: 0 no ERROR, 1 ERROR findings, 2 the document or the contracts could not be read.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # the module root: ideate_v2 importable,
                                                                  # also under python -I

from ideate_v2 import ARCHITECTURE_DOC
from ideate_v2.docs import RENDERERS, blocks_in, stale_blocks
from ideate_v2.registry import Registry

REQUIRED_SECTIONS = [
    "Executive Summary", "Sources, Evidence and Provenance", "Architecture Overview",
    "Standardized Unit Specification", "Unit Necessity and Design Rationality",
    "Error Handling, Debugging, and Traceability", "Original Architecture vs. New Architecture",
    "Migration and Transition Plan", "Testing, Evaluation, and Acceptance Criteria", "Open Questions and Decision Log",
]
REQUIRED_SUBSECTIONS = [
    "Hierarchical breakdown", "Component inventory", "Architecture diagram", "Execution flow", "Dependency graph",
    "Boundaries", "Canonical schema", "Shared definitions", "Unit specifications", "Vertical error handling",
    "Horizontal error handling", "Error taxonomy", "Debugging and traceability", "Debugging runbook",
    "Component mapping", "Milestones", "Acceptance criteria", "Decision log",
]
REQUIRED_BLOCKS = ["inventory", "dependency-graph", "unit-specs", "verdict-summary", "verdict-details",
                   "error-taxonomy", "decisions", "open-questions"]
MERMAID_TYPES = ("flowchart", "graph", "sequenceDiagram", "stateDiagram", "stateDiagram-v2", "classDiagram")
# a typed id never starts inside a longer token (EV-LOOP-004 is an eval case, not LOOP-00)
TYPED_ID = re.compile(r"(?<![\w\-])(STEP-[A-Z0-9]+|GATE-[a-z0-9]+(?:-[a-z0-9]+)*|LOOP-\d{2}(?!\d)|OQ-\d{2}(?!\d)|"
                      r"D-\d{2}(?!\d)|RP-[A-Z]+(?:-[A-Z]+)*|INFRA-[a-z0-9]+(?:-[a-z0-9]+)*|"
                      r"EXT-[a-z0-9]+(?:-[a-z0-9]+)*|STORE-[a-z0-9]+(?:-[a-z0-9]+)*|MCP-[a-z0-9]+(?:-[a-z0-9]+)*|"
                      r"ART-[A-Za-z0-9_]+(?:[.\-][A-Za-z0-9_]+)*)")
LINK = re.compile(r"\]\((?!https?:|#|mailto:)([^)\s]+)\)")


def heading_titles(text: str, level: int) -> list[tuple[int, str]]:
    out = []
    in_code = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.startswith("```"):
            in_code = not in_code
        if in_code:
            continue
        m = re.match(r"^(#{%d})\s+(?:\d+(?:\.\d+)*\.?\s+)?(.*?)\s*$" % level, line)
        if m:
            out.append((i, m.group(2)))
    return out


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def check(doc: Path, reg: Registry) -> list[dict]:
    text = doc.read_text(encoding="utf-8")
    lines = text.splitlines()
    out = []

    def f(level, code, message, line=None):
        out.append({"level": level, "code": code, "line": line, "message": message})

    h2 = heading_titles(text, 2)
    for sec in REQUIRED_SECTIONS:
        hits = [ln for ln, t in h2 if norm(t).startswith(norm(sec))]
        if not hits:
            f("ERROR", "A-SECTION", f"missing section '{sec}'")
        elif len(hits) > 1:
            f("ERROR", "A-SECTION", f"section '{sec}' appears {len(hits)} times", hits[1])
    h34 = heading_titles(text, 3) + heading_titles(text, 4)
    for sub in REQUIRED_SUBSECTIONS:
        if not any(norm(sub) in norm(t) for _, t in h34):
            f("ERROR", "A-SUBSECTION", f"missing subsection '{sub}'")
    present = blocks_in(text)
    for b in REQUIRED_BLOCKS:
        if b not in present:
            f("ERROR", "A-GENERATED", f"generated block '{b}' missing")
    for b in present:
        if b not in RENDERERS:
            f("ERROR", "A-GENERATED", f"unknown generated block '{b}'")
    stale = stale_blocks(reg, doc) if all(b in RENDERERS for b in present) else []
    for b in stale:
        f("ERROR", "A-STALE", f"generated block '{b}' is out of date (run scripts/render_docs.py)")
    fences = [i for i, ln in enumerate(lines, 1) if ln.startswith("```")]
    if len(fences) % 2:
        f("ERROR", "A-FENCE", "unbalanced code fences", fences[-1])
    mermaid = [i for i, ln in enumerate(lines, 1) if ln.strip() == "```mermaid"]
    if len(mermaid) < 3:
        f("ERROR", "A-MERMAID", f"{len(mermaid)} Mermaid diagram(s); at least 3 required (architecture, flow, DAG)")
    for i in mermaid:
        first = lines[i].strip() if i < len(lines) else ""
        if not first.startswith(MERMAID_TYPES):
            f("ERROR", "A-MERMAID", f"Mermaid block does not start with a diagram type: {first[:40]!r}", i + 1)
    for eid in list(reg.units) + [s["id"] for s in reg.steps()] + [g["id"] for g in reg.arch["gates"]] + \
            [lp["id"] for lp in reg.arch["loops"]]:
        if not re.search(r"(?<![A-Za-z0-9.])" + re.escape(eid) + r"(?![A-Za-z0-9])", text):
            f("ERROR", "A-ID-MISSING", f"registry id {eid} does not appear in the document")
    spec_heads = {}
    for ln, t in heading_titles(text, 5):
        m = re.match(r"^(\S+) - ", t)
        if m and m.group(1) in reg.units:
            spec_heads.setdefault(m.group(1), []).append(ln)
    for u in reg.units:
        n = len(spec_heads.get(u, []))
        if n == 0:
            f("ERROR", "A-UNIT-SPEC", f"no specification heading for Unit {u}")
        elif n > 1:
            f("ERROR", "A-UNIT-SPEC", f"Unit {u} has {n} specification headings (duplicated id)", spec_heads[u][1])
    for i, ln in enumerate(lines, 1):
        for m in TYPED_ID.finditer(ln):
            tok = m.group(1).rstrip(".")
            if reg.kind_of(tok) is None:
                f("ERROR", "A-ID-UNKNOWN", f"cites {tok}, which is not in the registry", i)
        for m in LINK.finditer(ln):
            target = m.group(1).split("#")[0]
            if target and not (doc.parent / target).exists():
                f("ERROR", "A-LINK", f"link target {target} does not exist", i)
        if "TBD" in ln:
            f("INFO", "A-TBD", ln.strip()[:160], i)
    return out


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):        # a console code page (cp1252) must not crash on a path
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    ap = argparse.ArgumentParser(description="Validate ARCHITECTURE.md against the contracts.")
    ap.add_argument("--doc", type=Path, default=ARCHITECTURE_DOC)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="hide INFO findings (TBD lines)")
    a = ap.parse_args(argv)
    if not a.doc.is_file():
        print(f"error: {a.doc} not found", file=sys.stderr)
        return 2
    try:
        reg = Registry.load()
    except (OSError, ValueError) as e:
        print(f"error: cannot load the contracts: {e}", file=sys.stderr)
        return 2
    findings = check(a.doc, reg)
    counts = {lvl: sum(1 for x in findings if x["level"] == lvl) for lvl in ("ERROR", "WARN", "INFO")}
    if a.json:
        print(json.dumps({"doc": str(a.doc), "counts": counts, "passed": counts["ERROR"] == 0, "findings": findings},
                         indent=2, ensure_ascii=False))
    else:
        for x in findings:
            if a.quiet and x["level"] == "INFO":
                continue
            loc = f"line {x['line']}" if x["line"] else "-"
            print(f"{x['level']:5} {x['code']:13} {loc:10} {x['message']}")
        print(f"\n{a.doc.name}: {counts['ERROR']} error(s), {counts['INFO']} TBD line(s) tracked -> "
              f"{'PASS' if counts['ERROR'] == 0 else 'FAIL'}")
    return 0 if counts["ERROR"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
