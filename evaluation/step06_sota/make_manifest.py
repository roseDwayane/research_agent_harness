#!/usr/bin/env python3
"""Provenance snapshot of what a Step 6 review was checked against (fusion-block architecture).

The checks read the research folder directly (step6_world.py); this file records what they found there, so a result can
be read later without the folder: how many papers, Planes, collisions, experiments, how many papers were read from a
full text, and the harness commit that produced the session when it can be told.

    python evaluation/step06_sota/make_manifest.py --session <research folder> --output <eval_dir>/manifest.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path

from step6_world import load_world


def build_manifest(session_dir: Path) -> dict:
    session_dir = Path(session_dir).resolve()
    w = load_world(session_dir)
    evidence = w.evidence_papers()
    run_id = None
    status = session_dir / "ERRORS.md"
    if status.exists():
        head = status.read_text(encoding="utf-8").splitlines()[:1]
        run_id = head[0].split("run", 1)[-1].strip() if head and "run" in head[0] else None
    return {
        "schema_version": 2,
        "architecture": "fusion-block (B2 step6_sota_review.md; ids X####, key#E1, P_/D_/E_draft_)",
        "session": str(session_dir),
        "harness_run": run_id,
        "bib_keys": len(w.bib_keys),
        "papers_in_planes": len(evidence),
        "decon_records": len(w.decon),
        "basis": dict(Counter(w.paper_basis(k) for k in evidence)),
        "papers_with_abstract_text": sum(1 for k in evidence if k in w.abstracts),
        "planes": [{"n": p["n"], "name": p.get("name"), "papers": len(p.get("member_papers") or [])} for p in w.planes],
        "collisions": dict(Counter(r["result"] for r in w.collisions.values())),
        "collision_evidence_levels": dict(Counter(r.get("evidence_level") for r in w.collisions.values())),
        "experiments": len(w.exps),
        "points": len(w.points),
        "lines": len(w.lines),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True, help="research folder")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    manifest = build_manifest(Path(args.session))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out), "papers": manifest["papers_in_planes"], "planes": len(manifest["planes"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
