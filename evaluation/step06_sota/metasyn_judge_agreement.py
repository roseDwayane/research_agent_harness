#!/usr/bin/env python3
"""How far can the MetaSyn judging be trusted without human labels? Judge agreement and convergent validity.

Reads the per-judge results metasyn_eval.py writes (eval/review_*/metasyn/{judge}.json, one run per
--judge on the same batch) and reports:

1. Agreement between judges (needs ≥ 2 judges)
   coverage    per Key Insight and system: covered / partial / not_covered / contradicted
               — exact agreement, Cohen's κ per judge pair, Fleiss' κ over all judges;
               also κ on the scored value (1 / 0.5 / 0), where not_covered and contradicted coincide
   digest      per Key Insight: supported / partial / not_supported (decides "answerable")
   direction   per review and system: Positive / Negative / Mixed (MetaSyn official)
   insights_consistency  per review and system, 0–1 (MetaSyn official): Spearman ρ per judge pair
2. Convergent validity (works with one judge)
   per judge: Spearman ρ between our item-level insight coverage (coverage_all, coverage_answerable)
   and MetaSyn's insights_consistency over (review, system) units, bootstrap 95% CI over reviews.
   Insight coverage is a supplementary measure of ours; it should rank reports like the official one.

All judges share the batch's insight_classes.json, so they score the same Key Insights. Damaged control
forms (half_themes_removed, summary_only, offtopic) are left out by default: they are easy cases and would
inflate agreement.

    python evaluation/step06_sota/metasyn_judge_agreement.py --batch evaluation/runs/metasyn_v2 \
        --judges gpt-5.5 claude-x gemini-y [--systems step6 baseline:gptresearcher__gpt-5.4__ma_retriever ...]

Writes eval/judge_agreement.json and .md. Judge names as given to metasyn_eval.py --judge.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

COVERAGE_LABELS = ("covered", "partial", "not_covered", "contradicted")
COVERAGE_SCORE = {"covered": 1.0, "partial": 0.5, "not_covered": 0.0, "contradicted": 0.0}
CONTROL_FORMS = ("half_themes_removed", "summary_only", "offtopic")


def judge_file(judge: str) -> str:
    return judge.replace(":", "_") + ".json"  # as metasyn_eval.py names it


# --------------------------------------------------------------------------- #
# statistics
# --------------------------------------------------------------------------- #
def cohen_kappa(a: list, b: list) -> float | None:
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return None
    n = len(pairs)
    po = sum(x == y for x, y in pairs) / n
    ca, cb = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    pe = sum(ca[k] * cb[k] for k in ca) / n ** 2
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def fleiss_kappa(rows: list[list]) -> float | None:
    """rows = one list of labels per unit, every unit rated by the same number of judges."""
    rows = [r for r in rows if all(x is not None for x in r)]
    if not rows or len(rows[0]) < 2:
        return None
    m, n = len(rows[0]), len(rows)
    counts = [Counter(r) for r in rows]
    p_i = [(sum(c * c for c in cnt.values()) - m) / (m * (m - 1)) for cnt in counts]
    total = Counter()
    for cnt in counts:
        total.update(cnt)
    pe = sum((v / (n * m)) ** 2 for v in total.values())
    return 1.0 if pe == 1 else (mean(p_i) - pe) / (1 - pe)


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1  # average rank for ties
        i = j + 1
    return out


def spearman(x: list[float], y: list[float]) -> float | None:
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    if len(pairs) < 3:
        return None
    rx, ry = ranks([a for a, _ in pairs]), ranks([b for _, b in pairs])
    mx, my = mean(rx), mean(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx, syy = sum((a - mx) ** 2 for a in rx), sum((b - my) ** 2 for b in ry)
    return None if sxx == 0 or syy == 0 else sxy / (sxx * syy) ** 0.5


def spearman_ci(units: list[tuple[int, float, float]], n: int = 10_000) -> tuple[float | None, list[float] | None]:
    """units = (review_id, x, y); bootstrap over reviews (a review's systems are resampled together)."""
    rho = spearman([u[1] for u in units], [u[2] for u in units])
    reviews = sorted({u[0] for u in units})
    if rho is None or len(reviews) < 3:
        return rho, None
    by_review = {r: [u for u in units if u[0] == r] for r in reviews}
    rng, stats = random.Random(0), []
    for _ in range(n):
        sample = [u for r in rng.choices(reviews, k=len(reviews)) for u in by_review[r]]
        s = spearman([u[1] for u in sample], [u[2] for u in sample])
        if s is not None:
            stats.append(s)
    stats.sort()
    return rho, [stats[int(0.025 * len(stats))], stats[int(0.975 * len(stats)) - 1]] if stats else None


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #
def load(batch: Path, judges: list[str]) -> dict[str, dict[int, dict]]:
    out = {}
    for judge in judges:
        files = sorted(batch.glob(f"eval/review_*/metasyn/{judge_file(judge)}"))
        if not files:
            raise SystemExit(f"no results for judge {judge!r} (eval/review_*/metasyn/{judge_file(judge)})")
        out[judge] = {(r := json.loads(f.read_text(encoding="utf-8")))["review_id"]: r for f in files}
    return out


def default_systems(results: dict[str, dict[int, dict]]) -> list[str]:
    names = Counter(name for per in results.values() for r in per.values() for name in r["systems"])
    return [n for n in names if n not in CONTROL_FORMS]


def item_labels(results, judges, reviews, systems) -> dict[str, dict[tuple, Any]]:
    """judge → {(review, system, item index): coverage verdict}, and the digest verdicts under system '-'."""
    out = {}
    for judge in judges:
        labels = {}
        for rid in reviews:
            for system in systems:
                for item in results[judge][rid]["systems"].get(system, {}).get("items", []):
                    labels[("coverage", rid, system, item["index"])] = item.get("verdict")
                    labels[("digest", rid, "-", item["index"])] = item.get("digest", {}).get("verdict")
        out[judge] = labels
    return out


def official(results, judge, rid, system, key):
    return results[judge][rid]["systems"].get(system, {}).get("official", {}).get(key)


# --------------------------------------------------------------------------- #
def agreement(results, judges, reviews, systems) -> dict[str, Any]:
    labels = item_labels(results, judges, reviews, systems)
    out: dict[str, Any] = {}
    for kind in ("coverage", "digest"):
        keys = sorted({k for per in labels.values() for k in per if k[0] == kind}, key=str)
        cols = {j: [labels[j].get(k) for k in keys] for j in judges}
        entry: dict[str, Any] = {"n_units": len(keys), "pairs": {}}
        for a, b in itertools.combinations(judges, 2):
            pairs = [(x, y) for x, y in zip(cols[a], cols[b]) if x is not None and y is not None]
            pair = {"n": len(pairs), "exact": round(mean(x == y for x, y in pairs), 4) if pairs else None,
                    "kappa": cohen_kappa(cols[a], cols[b])}
            if kind == "coverage":
                score = lambda v: None if v is None else COVERAGE_SCORE[v]  # noqa: E731
                pair["kappa_scored"] = cohen_kappa([score(v) for v in cols[a]], [score(v) for v in cols[b]])
            out_pair = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in pair.items()}
            entry["pairs"][f"{a} | {b}"] = out_pair
        if len(judges) >= 3:
            rows = [[cols[j][i] for j in judges] for i in range(len(keys))]
            entry["fleiss_kappa"] = round(k, 4) if (k := fleiss_kappa(rows)) is not None else None
        entry["label_counts"] = {j: dict(Counter(v for v in cols[j] if v is not None)) for j in judges}
        out[kind] = entry

    units = [(rid, s) for rid in reviews for s in systems if all(s in results[j][rid]["systems"] for j in judges)]
    direction = {j: [official(results, j, rid, s, "direction") for rid, s in units] for j in judges}
    consistency = {j: [official(results, j, rid, s, "insights_consistency") for rid, s in units] for j in judges}
    out["direction"] = {"n_units": len(units), "pairs": {}}
    out["insights_consistency"] = {"n_units": len(units), "pairs": {}}
    for a, b in itertools.combinations(judges, 2):
        pairs = [(x, y) for x, y in zip(direction[a], direction[b]) if x and y]
        out["direction"]["pairs"][f"{a} | {b}"] = {
            "n": len(pairs), "exact": round(mean(x == y for x, y in pairs), 4) if pairs else None,
            "kappa": round(k, 4) if (k := cohen_kappa(direction[a], direction[b])) is not None else None}
        rho = spearman(consistency[a], consistency[b])
        diffs = [abs(x - y) for x, y in zip(consistency[a], consistency[b]) if x is not None and y is not None]
        out["insights_consistency"]["pairs"][f"{a} | {b}"] = {
            "n": len(diffs), "spearman": round(rho, 4) if rho is not None else None,
            "mean_abs_diff": round(mean(diffs), 4) if diffs else None}
    if len(judges) >= 3:
        out["direction"]["fleiss_kappa"] = round(k, 4) if (k := fleiss_kappa([list(r) for r in zip(*direction.values())])) is not None else None
    return out


def convergent(results, judges, reviews, systems) -> dict[str, Any]:
    out = {}
    for judge in [*judges, *(["mean of judges"] if len(judges) > 1 else [])]:
        def value(rid, system, key, source="coverage"):
            js = judges if judge == "mean of judges" else [judge]
            if source == "official":
                vals = [official(results, j, rid, system, "insights_consistency") for j in js]
            else:
                vals = [results[j][rid]["systems"].get(system, {}).get(key) for j in js]
            vals = [v for v in vals if v is not None]
            return mean(vals) if vals else None

        entry = {}
        for key in ("coverage_all", "coverage_answerable"):
            for scope, keep in (("all systems", lambda s: True), *[(s, (lambda t, s=s: t == s)) for s in systems]):
                units = [(rid, value(rid, s, key), value(rid, s, None, "official")) for rid in reviews for s in systems if keep(s)]
                units = [u for u in units if u[1] is not None and u[2] is not None]
                rho, ci = spearman_ci(units)
                entry[f"{key} / {scope}"] = {"n": len(units), "spearman": round(rho, 4) if rho is not None else None,
                                             "ci95": [round(c, 4) for c in ci] if ci else None}
        means = {}
        for s in systems:
            row = {}
            for key, source in (("coverage_all", "coverage"), ("coverage_answerable", "coverage"), ("insights_consistency", "official")):
                vals = [v for rid in reviews if (v := value(rid, s, key, source)) is not None]
                row[key] = round(mean(vals), 4) if vals else None
            means[s] = row
        out[judge] = {"correlations": entry, "system_means": means}
    return out


def render(report: dict[str, Any]) -> str:
    fmt = lambda v: "–" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))  # noqa: E731
    lines = ["# MetaSyn judging: judge agreement and convergent validity", "",
             f"Batch `{report['batch']}`, {report['n_reviews']} reviews, judges: {', '.join(f'`{j}`' for j in report['judges'])}.",
             f"Systems: {', '.join(report['systems'])} (control forms excluded).", ""]
    agr = report.get("agreement")
    if agr:
        lines += ["## Agreement between judges", "",
                  "κ: <0.2 slight, 0.2–0.4 fair, 0.4–0.6 moderate, 0.6–0.8 substantial, >0.8 almost perfect (Landis & Koch).", ""]
        for kind, title in (("coverage", "Insight coverage verdict (4 labels; κ scored = on 1 / 0.5 / 0)"),
                            ("digest", "Digest verdict (answerable)"), ("direction", "Direction (MetaSyn official)")):
            e = agr[kind]
            lines += [f"### {title}", "", f"units: {e['n_units']}" + (f"; Fleiss' κ over all judges: {fmt(e.get('fleiss_kappa'))}"
                                                                      if "fleiss_kappa" in e else ""), "",
                      "| judge pair | n | exact | κ |" + (" κ scored |" if kind == "coverage" else ""),
                      "|---|---|---|---|" + ("---|" if kind == "coverage" else "")]
            for pair, p in e["pairs"].items():
                lines.append(f"| {pair} | {p['n']} | {fmt(p['exact'])} | {fmt(p['kappa'])} |"
                             + (f" {fmt(p.get('kappa_scored'))} |" if kind == "coverage" else ""))
            lines.append("")
        lines += ["### insights_consistency (MetaSyn official, 0–1)", "", "| judge pair | n | Spearman ρ | mean |diff| |",
                  "|---|---|---|---|"]
        lines += [f"| {pair} | {p['n']} | {fmt(p['spearman'])} | {fmt(p['mean_abs_diff'])} |"
                  for pair, p in agr["insights_consistency"]["pairs"].items()]
        lines.append("")
    lines += ["## Convergent validity: insight coverage vs insights_consistency", "",
              "Spearman ρ over (review, system) units; 95% CI by bootstrap over reviews.", ""]
    for judge, e in report["convergent"].items():
        lines += [f"### {judge}", "", "| measure / scope | n | ρ [95% CI] |", "|---|---|---|"]
        for name, c in e["correlations"].items():
            ci = f" [{c['ci95'][0]:+.2f}, {c['ci95'][1]:+.2f}]" if c["ci95"] else ""
            lines.append(f"| {name} | {c['n']} | {fmt(c['spearman'])}{ci} |")
        lines += ["", "| system | coverage_all | coverage_answerable | insights_consistency |", "|---|---|---|---|"]
        lines += [f"| {s} | {fmt(m['coverage_all'])} | {fmt(m['coverage_answerable'])} | {fmt(m['insights_consistency'])} |"
                  for s, m in e["system_means"].items()]
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch", type=Path, required=True)
    ap.add_argument("--judges", nargs="+", required=True, help="as given to metasyn_eval.py --judge")
    ap.add_argument("--systems", nargs="+", help="default: every system except the damaged control forms")
    ap.add_argument("--reviews", nargs="*", type=int, help="default: reviews scored by every judge")
    args = ap.parse_args()

    results = load(args.batch, args.judges)
    reviews = sorted(set.intersection(*(set(per) for per in results.values())))
    if args.reviews:
        reviews = [r for r in reviews if r in args.reviews]
    systems = args.systems or default_systems(results)
    report = {"batch": args.batch.name, "judges": args.judges, "systems": systems, "n_reviews": len(reviews),
              "reviews": reviews, "convergent": convergent(results, args.judges, reviews, systems)}
    if len(args.judges) >= 2:
        report["agreement"] = agreement(results, args.judges, reviews, systems)
    out = args.batch / "eval" / "judge_agreement"
    (out.with_suffix(".json")).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    md = render(report)
    out.with_suffix(".md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
