#!/usr/bin/env python3
"""Generate the Step 6 source manifest for one harness session.

Replaces the hand-written ``step6_source_manifest.json``: ``sources`` come from the
``access_level`` frontmatter of ``step5_full_text/*.md`` (restricted to keys in
``step4_references.bib``), and the theme-count range follows the same paper-count
rule as ``check_step6_contract.theme_count_range`` and the s6_sota prompt.

    python evaluation/step06_sota/make_manifest.py --session <session_dir> --output <eval_dir>/step6_manifest.json
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from check_step6_contract import DEFAULT_KEY_RESULTS_HEADER, theme_count_range
from step6_common import load_access_levels, parse_bib_keys

# The harness tries arXiv HTML before PDFs, so full-text-html sources are full texts too.
COVERAGE_DENOMINATOR = ["full-text-pdf", "full-text-html"]
NUMERIC_SUPPORT_LEVELS = ["full-text-pdf", "full-text-html", "partial-text-html"]


def build_manifest(session_dir: Path, output: Path) -> dict:
    session_dir, output = Path(session_dir).resolve(), Path(output).resolve()
    legal = parse_bib_keys((session_dir / "step4_references.bib").read_text(encoding="utf-8"))
    access = load_access_levels(session_dir / "step5_full_text")
    lo, hi = theme_count_range(len(legal))
    return {
        "schema_version": 1,
        "project_dir": Path(os.path.relpath(session_dir, output.parent)).as_posix(),
        "review": "step6_sota_review.md",
        "bibliography": "step4_references.bib",
        "full_text_dir": "step5_full_text",
        "gap_analysis": "step7_gap_analysis.md",
        "coverage_threshold": 0.8,
        "coverage_denominator": COVERAGE_DENOMINATOR,
        "key_results_header": DEFAULT_KEY_RESULTS_HEADER,
        "numeric_support_levels": NUMERIC_SUPPORT_LEVELS,
        "numeric_attestation_threshold": 0.9,
        "theme_count_min": lo,
        "theme_count_max": hi,
        # A missing access_level stays null so check_step6_contract's source_integrity reports it.
        "sources": {key: access[key] for key in sorted(access) if key in legal},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True, help="harness session folder")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    manifest = build_manifest(Path(args.session), Path(args.output))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out), "sources": len(manifest["sources"]),
                      "themes": [manifest["theme_count_min"], manifest["theme_count_max"]]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
