#!/usr/bin/env python3
"""MetaSyn summary of a batch: every system's mean scores and the paired difference from the harness arm.

    python evaluation/step06_sota/metasyn_summary.py --batch evaluation/runs/<batch_id> [--judge gemma4:31b]

Reads the per-review results metasyn_eval.py wrote (eval/review_*/metasyn/{judge}.json) and writes
eval/metasyn_summary_{judge}.json and .md:

  per system (macro mean over reviews)   direction accuracy (MetaSyn official), insights_consistency (official),
                                         coverage_all (ours, covered 1 / partial 0.5), coverage_answerable (reference
                                         only: its denominator depends on the system), words
  step6 minus each other system          the same four, paired by review, bootstrap 95% CI over reviews; for the
                                         direction a win/loss count (step6 right and the other wrong, and the reverse)

`step6` is the system under test (the harness arm A); the others are B0 (`naive`), B2 (`naive_fulltext`) and any MetaSyn
`baseline:*` report scored with the same judge. The damaged control forms (half_themes_removed, summary_only, offtopic)
are not systems here. Scopes: all reviews, and held-out (the 6 dev reviews left out) when the batch has dev reviews.
Only differences are meaningful: the judge is not the paper's, and the inputs of `baseline:*` are not the harness's.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # evaluation/: eval_common

from autosurvey_eval import boot_ci, is_dev  # noqa: E402
from eval_common import read_json, write_json  # noqa: E402

CONTROL_FORMS = {"half_themes_removed", "summary_only", "offtopic"}
TEST_SYSTEM = "step6"
METRICS = ("direction_accuracy", "insights_consistency", "coverage_all", "coverage_answerable", "words")
ORDER = ("naive", "naive_fulltext", "naive_fulltext_compare")


def scores_of(system: dict) -> dict[str, float | None]:
    off = system.get("official") or {}
    return {"direction_accuracy": off.get("direction_accuracy"), "insights_consistency": off.get("insights_consistency"),
            "coverage_all": system.get("coverage_all"), "coverage_answerable": system.get("coverage_answerable"),
            "words": system.get("words")}


def load(batch_dir: Path, judge: str) -> dict[int, dict]:
    name = judge.replace(":", "_") + ".json"
    out = {}
    for path in sorted((batch_dir / "eval").glob(f"review_*/metasyn/{name}")):
        r = read_json(path)
        out[int(r["review_id"])] = r
    return out


def avg(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(mean(vals), 4) if vals else None


def summarize(results: dict[int, dict]) -> dict:
    systems = [s for s in dict.fromkeys(n for r in results.values() for n in r["systems"]) if s not in CONTROL_FORMS]
    others = [s for s in systems if s != TEST_SYSTEM]
    others.sort(key=lambda s: (ORDER.index(s) if s in ORDER else len(ORDER), s))
    scopes = [("all", lambda i: True)]
    if any(is_dev(f"review_{i}") for i in results):
        scopes.append(("held-out", lambda i: not is_dev(f"review_{i}")))
    out: dict = {"systems": systems, "n_reviews": len(results),
                 "classes_not_frozen": sorted(i for i, r in results.items() if not r.get("classes_frozen")), "scopes": {}}
    for scope, keep in scopes:
        ids = [i for i in sorted(results) if keep(i)]
        means = {}
        for s in systems:
            rows = [scores_of(results[i]["systems"][s]) for i in ids if s in results[i]["systems"]]
            means[s] = {"n": len(rows), **{m: avg([r[m] for r in rows]) for m in METRICS}}
        diffs = {}
        for other in others:
            common = [i for i in ids if TEST_SYSTEM in results[i]["systems"] and other in results[i]["systems"]]
            cell = {"n_pairs": len(common)}
            for m in METRICS:
                pairs = [(scores_of(results[i]["systems"][TEST_SYSTEM])[m], scores_of(results[i]["systems"][other])[m]) for i in common]
                d = [a - b for a, b in pairs if a is not None and b is not None]
                if len(d) >= 3:
                    lo, hi = boot_ci(d)
                    cell[m] = {"diff": round(mean(d), 4), "ci95": [round(lo, 4), round(hi, 4)], "n": len(d)}
                else:
                    cell[m] = None
            wl = [(scores_of(results[i]["systems"][TEST_SYSTEM])["direction_accuracy"],
                   scores_of(results[i]["systems"][other])["direction_accuracy"]) for i in common]
            wl = [(a, b) for a, b in wl if a is not None and b is not None]
            cell["direction_wins"] = sum(1 for a, b in wl if a > b)
            cell["direction_losses"] = sum(1 for a, b in wl if a < b)
            diffs[other] = cell
        out["scopes"][scope] = {"reviews": len(ids), "means": means, "paired": diffs}
    return out


def fmt(v) -> str:
    return "–" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))


def render(summary: dict, judge: str) -> str:
    lines = ["# MetaSyn summary", "",
             f"- judge: `{judge}`; {summary['n_reviews']} reviews; system under test: `{TEST_SYSTEM}` (the harness arm)",
             "- `naive` = B0 (one prompt, abstracts), `naive_fulltext` = B2 (B0 + full-text excerpts), `baseline:*` = MetaSyn's own "
             "reports (they retrieve their papers, so their inputs differ).",
             "- direction accuracy and `insights_consistency` are MetaSyn's official metrics; `coverage_all` is ours; "
             "`coverage_answerable` is for reference (its denominator depends on the system).",
             "- Only the differences mean anything: the judge is not the paper's.", ""]
    if summary["classes_not_frozen"]:
        lines += [f"- Key-Insight classes not frozen for reviews {summary['classes_not_frozen']} (a judge classified them; "
                  "check by hand before trusting coverage).", ""]
    for scope, body in summary["scopes"].items():
        lines += [f"## Means, {scope} ({body['reviews']} reviews)", "",
                  "| system | n | direction acc. | insights_consistency | coverage_all | coverage_answerable | words |",
                  "|---|---|---|---|---|---|---|"]
        for s, m in body["means"].items():
            lines.append(f"| {s} | {m['n']} | " + " | ".join(fmt(m[k]) for k in METRICS) + " |")
        lines += ["", f"## `{TEST_SYSTEM}` minus each system, paired by review, {scope} (bootstrap 95% CI over reviews)", "",
                  "| other system | pairs | direction acc. (wins/losses) | insights_consistency | coverage_all | coverage_answerable | words |",
                  "|---|---|---|---|---|---|---|"]
        for other, c in body["paired"].items():
            def cell(m):
                d = c[m]
                return "–" if d is None else f"{d['diff']:+.3f} [{d['ci95'][0]:+.3f}, {d['ci95'][1]:+.3f}]"
            lines.append(f"| {other} | {c['n_pairs']} | {cell('direction_accuracy')} ({c['direction_wins']}/{c['direction_losses']}) | "
                         f"{cell('insights_consistency')} | {cell('coverage_all')} | {cell('coverage_answerable')} | {cell('words')} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch", type=Path, required=True)
    ap.add_argument("--judge", default="gemma4:31b")
    args = ap.parse_args()
    results = load(args.batch.resolve(), args.judge)
    if not results:
        raise SystemExit(f"no eval/review_*/metasyn/{args.judge.replace(':', '_')}.json under {args.batch} (run metasyn_eval.py first)")
    summary = summarize(results)
    tag = re.sub(r"[^A-Za-z0-9.]+", "-", args.judge.split("/")[-1]).strip("-")
    out = args.batch.resolve() / "eval" / f"metasyn_summary_{tag}"
    write_json(out.with_suffix(".json"), {"judge": args.judge, **summary})
    out.with_suffix(".md").write_text(render(summary, args.judge), encoding="utf-8")
    print(render(summary, args.judge))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
