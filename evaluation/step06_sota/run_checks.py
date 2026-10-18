#!/usr/bin/env python3
"""Step 6 deterministic checks for every session of a batch: make_manifest → check_step6_contract → check_numeric_claims.

    python evaluation/step06_sota/run_checks.py --batch evaluation/runs/<batch_id> [--only <ids>]

Per session with a step6_sota_review.md, written to eval/{id}/step06/:
    manifest.json   Step 6 manifest (from step5_full_text frontmatter and the .bib)
    contract.json   check_step6_contract.py output (citation integrity, structure, coverage)
    numeric.json    check_numeric_claims.py output
    summary.json    the few fields aggregate.py averages; status "checker_error" if a checker crashed

Sessions without a Step 6 review are skipped. Exit 1 if any checker crashed (a failed check is a result, not an error).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # evaluation/: eval_common

from eval_common import batch_paths, read_json, read_runs, run_script, tail, write_json  # noqa: E402


def check_session(topic_id: str, session_dir: Path, batch_dir: Path) -> dict[str, Any]:
    out_dir = batch_paths(batch_dir)["eval"] / topic_id / "step06"
    out_dir.mkdir(parents=True, exist_ok=True)
    log = batch_paths(batch_dir)["logs"] / f"{topic_id}.step06.log"
    manifest = out_dir / "manifest.json"
    result: dict[str, Any] = {}

    proc = run_script("step06_sota/make_manifest.py", ["--session", str(session_dir), "--output", str(manifest)], log)
    if proc.returncode != 0:
        result = {"status": "checker_error", "stage": "make_manifest", "stderr": tail(proc.stderr)}
        write_json(out_dir / "summary.json", result)
        return result
    # Exit 1 means "checks ran and something failed" — that is a result, not an error.
    for name, script, output in (("contract", "step06_sota/check_step6_contract.py", out_dir / "contract.json"),
                                 ("numeric", "step06_sota/check_numeric_claims.py", out_dir / "numeric.json")):
        proc = run_script(script, ["--manifest", str(manifest), "--output", str(output)], log)
        if proc.returncode not in (0, 1) or not output.exists():
            result[name] = {"status": "checker_error", "stderr": tail(proc.stderr)}
            continue
        result[name] = summarize_contract(read_json(output)) if name == "contract" else summarize_numeric(read_json(output))
    result["status"] = "ok" if all(r.get("status") != "checker_error" for r in result.values()) else "checker_error"
    write_json(out_dir / "summary.json", result)
    return result


def summarize_contract(c: dict[str, Any]) -> dict[str, Any]:
    s, cov = c["structure"], c["coverage"]["primary"]
    return {
        "integrity_fail": c["citation_integrity"]["integrity_fail"],
        "invalid_keys": c["citation_integrity"]["invalid_keys"],
        "structure_pass": s["pass"],
        "theme_count": s["found_themes"],
        "theme_count_range": s["theme_count_range"],
        "failing_themes": [t["theme"] for t in s["themes"] if not t["pass"]],
        "cross_theme_pass": c["cross_theme_analysis"]["pass"],
        "coverage_rate": cov["rate"],
        "coverage": f"{cov['numerator']}/{cov['denominator']}",
        "coverage_pass": c["coverage"]["pass"],
        "source_integrity_pass": c["source_integrity"]["pass"],
        "overall_pass": c["overall_pass"],
    }


def summarize_numeric(n: dict[str, Any]) -> dict[str, Any]:
    s6 = n["step6"]
    return {
        "numeric_attestation": s6["numeric_attestation"],
        "claims": f"{s6['attested_claims']}/{s6['numeric_citable_claims']}",
        "pass": s6["pass"],
        "numeric_sentences_without_citation": s6["numeric_sentences_without_citation"],
    }


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch", type=Path, required=True)
    ap.add_argument("--only", nargs="+", help="topic / review ids to check (default: all)")
    args = ap.parse_args(argv)

    batch_dir = args.batch.resolve()
    crashed = []
    for run in read_runs(batch_dir):
        if args.only and run["id"] not in args.only:
            continue
        session_dir = batch_dir / run["session_dir"]
        if not (session_dir / "step6_sota_review.md").exists():
            print(f"skip {run['id']}: no step6_sota_review.md")
            continue
        result = check_session(run["id"], session_dir, batch_dir)
        contract = result.get("contract", {})
        print(f"{result['status']:13} {run['id']}: overall_pass={contract.get('overall_pass')} "
              f"coverage={contract.get('coverage')} numeric={result.get('numeric', {}).get('claims')}")
        if result["status"] != "ok":
            crashed.append(run["id"])
    print(f"\ndone; checker errors: {crashed or 'none'}")
    return 1 if crashed else 0


if __name__ == "__main__":
    raise SystemExit(main())
