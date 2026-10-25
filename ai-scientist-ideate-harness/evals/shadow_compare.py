#!/usr/bin/env python3
"""Shadow comparison (migration milestone M7): v2 Unit states vs the legacy ``ideate_tools.py status`` on the same
research folders. Runs only where the legacy skill is available (IDEATE_LEGACY_SKILL_DIR or --legacy-skill-dir).

Each folder is copied to a temporary directory first (legacy status writes STATUS.md and caveat views into it).
A difference is EXPECTED when it traces to an input v2 cannot hash (decision D-11: topic, basis:*, part=, view=,
kinds=, strip), directly or through an upstream that differs for that reason; anything else is UNEXPECTED and fails.

    python evals/shadow_compare.py [--legacy-skill-dir DIR] [--json] [folder ...]   (default: evals/datasets/*)

Exit codes: 0 no unexpected difference, 1 unexpected differences, 2 legacy skill not available.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from ideate_v2.ledger import unit_states  # noqa: E402
from ideate_v2.registry import Registry  # noqa: E402

UNVERIFIABLE = re.compile(r"\btopic\b|basis:| part=| view=| kinds=| -[a-z_]")
UPSTREAM = re.compile(r"^upstream (\S+) is ")


def legacy_states(tools: Path, rd: Path) -> tuple[dict, list[str]]:
    states, errors = {}, []
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    for block in ("search", "fulltext", "fusion"):
        p = subprocess.run([sys.executable, str(tools), "status", str(rd), "--json", "--block", block],
                           capture_output=True, text=True, encoding="utf-8", env=env, timeout=300)
        if p.returncode != 0:
            errors.append(f"{block}: exit {p.returncode}: {(p.stderr.strip().splitlines() or ['?'])[-1][:200]}")
            continue
        states.update(json.loads(p.stdout))
    return states, errors


def compare(reg: Registry, tools: Path, folder: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        rd = Path(tmp) / folder.name
        shutil.copytree(folder, rd)
        v2 = unit_states(reg, rd)
        legacy, errors = legacy_states(tools, rd)
    diffs = {u: {"legacy": s["state"], "v2": v2[u]["state"], "legacy_why": s.get("why", "")}
             for u, s in legacy.items() if u in v2 and s["state"] != v2[u]["state"]}
    expected: set[str] = set()
    changed = True
    while changed:                                # resolve chains: upstream X is stale, X expected -> expected
        changed = False
        for u, d in diffs.items():
            if u in expected:
                continue
            m = UPSTREAM.match(d["legacy_why"])
            if (d["v2"] == "done" and d["legacy"] == "stale" and
                    (UNVERIFIABLE.search(d["legacy_why"]) or (m and m.group(1) in expected))):
                expected.add(u)
                changed = True
    for u, d in diffs.items():
        d["class"] = "expected (D-11)" if u in expected else "UNEXPECTED"
    compared = sum(1 for u in legacy if u in v2)
    return {"folder": folder.name, "legacy_errors": errors, "compared": compared,
            "agree": compared - len(diffs), "differences": diffs,
            "unexpected": sorted(u for u in diffs if u not in expected)}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):        # a console code page (cp1252) must not crash on a path
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    ap = argparse.ArgumentParser(description="Compare v2 and legacy Unit states.")
    ap.add_argument("--legacy-skill-dir", type=Path, default=os.environ.get("IDEATE_LEGACY_SKILL_DIR") or HERE.parent)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("folders", nargs="*", type=Path)
    a = ap.parse_args(argv)
    if not a.legacy_skill_dir:
        print("SKIP: legacy skill not available (set IDEATE_LEGACY_SKILL_DIR or --legacy-skill-dir)", file=sys.stderr)
        return 2
    tools = Path(a.legacy_skill_dir) / "scripts" / "ideate_tools.py"
    if not tools.is_file():
        print(f"SKIP: {tools} not found", file=sys.stderr)
        return 2
    reg = Registry.load()
    folders = a.folders or sorted(p for p in (HERE / "datasets").iterdir() if p.is_dir())
    results = [compare(reg, tools, f) for f in folders]
    unexpected = sum(len(r["unexpected"]) for r in results)
    if a.json:
        print(json.dumps({"results": results, "unexpected": unexpected}, indent=2, ensure_ascii=False))
    else:
        for r in results:
            print(f"{r['folder']}: compared {r['compared']}, agree {r['agree']}, differ {len(r['differences'])}, "
                  f"unexpected {len(r['unexpected'])}" + (f"; legacy errors: {'; '.join(r['legacy_errors'])}"
                                                          if r["legacy_errors"] else ""))
            for u, d in r["differences"].items():
                print(f"    {u}: legacy {d['legacy']} / v2 {d['v2']} [{d['class']}] {d['legacy_why'][:90]}")
        total = sum(r["compared"] for r in results)
        agree = sum(r["agree"] for r in results)
        print(f"\nTOTAL compared {total}, agree {agree}, unexpected differences {unexpected}")
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
