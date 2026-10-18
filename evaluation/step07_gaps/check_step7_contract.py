#!/usr/bin/env python3
"""Deterministic Step 7 (research-gaps) checks: raw LLM output, step7_gaps.json and step7_gap_analysis.md.

    python evaluation/step07_gaps/check_step7_contract.py --session <session_dir> [--output step7_contract.json]
    python evaluation/step07_gaps/check_step7_contract.py --batch evaluation/runs/<batch>   # → eval/{id}/step07/contract.json

Failures (exit 1) are contract violations; warnings are reported, not gated.

Raw output (newest s7_gaps response in {session}/.cache/llm, i.e. before parsing):
    every property of the tool schema that was sent must be present in the emitted object — a field with a default
    is optional in the schema, and an omitted field is invisible after parsing (it becomes the default; this is how
    counter_evidence went missing for every gap). Fields listed in --may-omit (default: secondary_type, year) are
    exempt. Optional (non-required) schema fields are listed as warnings even when emitted.
step7_gaps.json:
    1..max_gaps gaps, GAP_001.. ids and ranks in order, integer 1-5 scores, composite = Σ score × weight
    (half-up, 2 dp) and sort order (composite ↓, severity ↓, title), legal gap types, ≥2 supporting items,
    every evidence key in the key set Step 7 was given (step6_sota.json paper_map) and in step4_references.bib,
    no empty text fields; counts of evidence items dropped by Step 7's own key filter (raw → json).
step7_gap_analysis.md:
    frontmatter gaps_identified, one "## GAP_xxx: title" per gap, evidence bullets, composite and ranking table
    all agree with step7_gaps.json.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

GAP_TYPES = {"methodological", "population", "measurement", "temporal", "integration"}
SCORES = ("severity", "novelty", "feasibility")
GAP_TEXT = ("title_en", "description_en", "why_it_matters_en",
            "severity_rationale_en", "novelty_rationale_en", "feasibility_rationale_en")
SUMMARY_TEXT = ("executive_en", "coverage_en", "methodology_en", "patterns_en")  # step7_gaps.json "summary"
EVIDENCE = ("supporting_evidence", "counter_evidence")
BIB_ENTRY_RE = re.compile(r"@[A-Za-z]+\s*\{\s*([^,\s]+)\s*,(.*?)(?=\n@|\Z)", re.S)
OLD_EMPTY_COUNTER = "This suggests a highly novel direction"  # renderer text before the counter_evidence fix


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def round2(x: Decimal) -> float:
    return float(x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class Report:
    def __init__(self):
        self.failures: list[dict] = []
        self.warnings: list[dict] = []

    def fail(self, code: str, where: str | None, detail: str) -> None:
        self.failures.append({"code": code, "where": where, "detail": detail})

    def warn(self, code: str, where: str | None, detail: str) -> None:
        self.warnings.append({"code": code, "where": where, "detail": detail})


# --------------------------------------------------------------------------- #
# raw LLM output vs the schema that was sent
# --------------------------------------------------------------------------- #
def newest_raw(session: Path) -> dict | None:
    best = None
    for f in (session / ".cache" / "llm").glob("*.json"):
        try:
            d = read_json(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if d.get("_descriptor", {}).get("prompt") != "s7_gaps":
            continue
        if best is None or f.stat().st_mtime > best[0]:
            best = (f.stat().st_mtime, d)
    return best[1] if best else None


def walk_schema(schema: dict, value, path: str, may_omit: set[str], rep: Report, optional: dict[str, str]) -> None:
    """Compare an emitted value with its (inlined) JSON schema node, recursing into objects and arrays."""
    if "anyOf" in schema:  # e.g. secondary_type: GapType | None
        branches = [b for b in schema["anyOf"] if b.get("type") != "null"]
        if value is None or len(branches) != 1:
            return
        schema = branches[0]
    if schema.get("type") == "object" or "properties" in schema:
        if not isinstance(value, dict):
            rep.fail("raw_type", path, f"expected an object, got {type(value).__name__}")
            return
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        generic = re.sub(r"\[\d+\]", "[]", path)
        for name, sub in props.items():
            if name not in required:
                optional.setdefault(f"{generic}.{name}".lstrip("."), "has a default → optional in the tool schema")
            if name not in value:
                if name in may_omit:
                    continue
                rep.fail("raw_field_omitted", f"{path}.{name}".lstrip("."),
                         "field was in the tool schema but the model did not emit it"
                         + (" (schema: optional, so parsing silently used the default)" if name not in required else ""))
                continue
            walk_schema(sub, value[name], f"{path}.{name}".lstrip("."), may_omit, rep, optional)
        for name in sorted(set(value) - set(props)):
            rep.warn("raw_field_unknown", f"{path}.{name}".lstrip("."), "emitted field not in the tool schema (dropped by parsing)")
    elif schema.get("type") == "array" and isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            walk_schema(schema["items"], item, f"{path}[{i}]", may_omit, rep, optional)


def check_raw(raw: dict, may_omit: set[str], rep: Report) -> dict:
    desc = raw["_descriptor"]
    response = raw.get("response") or {}
    optional: dict[str, str] = {}
    walk_schema(desc["schema"], response, "", may_omit, rep, optional)
    for field, why in sorted(optional.items()):
        if field.split(".")[-1] not in may_omit:
            rep.warn("schema_optional_field", field, why + "; the model may omit it without any error")
    if raw.get("attempts", 1) > 1:
        rep.warn("validation_retries", None, f"schema validation needed {raw['attempts']} attempts")
    if raw.get("stop_reason") not in (None, "tool_use", "stop", "end_turn"):
        rep.warn("stop_reason", None, f"stop_reason {raw.get('stop_reason')!r}")
    return {
        "prompt_version": desc.get("prompt_version"),
        "model": raw.get("model") or desc.get("model"),
        "attempts": raw.get("attempts", 1),
        "gaps": len(response.get("gaps", [])),
        "schema_optional_fields": sorted(optional),
    }


# --------------------------------------------------------------------------- #
# step7_gaps.json
# --------------------------------------------------------------------------- #
def given_keys(session: Path) -> tuple[set[str], str]:
    """The key list s7_gaps.run passes to the model (paper_map, else Step 6 table keys)."""
    if (session / "step6_sota.json").exists():
        keys = {m["citation_key"] for m in read_json(session / "step6_sota.json").get("paper_map", [])}
        if keys:
            return keys, "step6_sota.json paper_map"
    md = (session / "step6_sota_review.md").read_text(encoding="utf-8") if (session / "step6_sota_review.md").exists() else ""
    return set(re.findall(r"\| `([A-Za-z][A-Za-z0-9\-]+\d{4}[a-z]?)` \|", md)), "step6_sota_review.md tables"


def bib_years(session: Path) -> dict[str, int | None]:
    path = session / "step4_references.bib"
    if not path.exists():
        return {}
    out = {}
    for key, body in BIB_ENTRY_RE.findall(path.read_text(encoding="utf-8")):
        m = re.search(r"\byear\s*=\s*[{\"]?(\d{4})", body)
        out[key] = int(m.group(1)) if m else None
    return out


def check_json(s7: dict, raw: dict | None, keys: set[str], bib: dict[str, int | None], max_gaps: int, rep: Report) -> dict:
    ranked = s7.get("gaps", [])
    weights = s7.get("weights") or {}
    if set(weights) != set(SCORES):
        rep.fail("weights", None, f"weights {weights}")
    elif abs(sum(weights.values()) - 1) > 1e-9:
        rep.warn("weights", None, f"weights sum to {sum(weights.values())}")
    if not 1 <= len(ranked) <= max_gaps:
        rep.fail("gap_count", None, f"{len(ranked)} gaps (allowed 1..{max_gaps})")
    lo, hi = (1, 2) if len(keys) < 10 else (2, 3)
    if not lo <= len(ranked) <= hi:
        rep.warn("gap_count_prompt", None, f"{len(ranked)} gaps; prompt asks for {lo}-{hi} with {len(keys)} papers")

    for name in SUMMARY_TEXT:
        if not str((s7.get("summary") or {}).get(name, "")).strip():
            rep.fail("empty_text", f"summary.{name}", "empty")

    order = []
    for i, r in enumerate(ranked, 1):
        g, where = r.get("gap", {}), r.get("id", f"#{i}")
        if r.get("id") != f"GAP_{i:03d}" or r.get("rank") != i:
            rep.fail("id_rank", where, f"position {i}: id {r.get('id')!r}, rank {r.get('rank')!r}")
        scores_ok = True
        for name in SCORES:
            v = g.get(name)
            if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 5:
                rep.fail("score_range", where, f"{name}={v!r}")
                scores_ok = False
        if scores_ok and set(weights) == set(SCORES):
            expected = round2(sum(Decimal(str(g[n])) * Decimal(str(weights[n])) for n in SCORES))
            if r.get("composite") != expected:
                rep.fail("composite", where, f"composite {r.get('composite')} != {expected}")
            order.append((-expected, -g["severity"], g.get("title_en", ""), where))
        if g.get("gap_type") not in GAP_TYPES:
            rep.fail("gap_type", where, f"gap_type {g.get('gap_type')!r}")
        if g.get("secondary_type") is not None:
            if g["secondary_type"] not in GAP_TYPES:
                rep.fail("gap_type", where, f"secondary_type {g['secondary_type']!r}")
            elif g["secondary_type"] == g.get("gap_type"):
                rep.warn("secondary_same", where, "secondary_type equals gap_type")
        for name in GAP_TEXT:
            if not str(g.get(name) or "").strip():
                rep.fail("empty_text", f"{where}.{name}", "empty")

        sup = g.get("supporting_evidence") or []
        if len(sup) < 2:
            rep.fail("supporting_min", where, f"{len(sup)} supporting items (need >= 2)")
        for kind in EVIDENCE:
            items = g.get(kind) or []
            seen = Counter(e.get("citation_key") for e in items)
            for key, n in seen.items():
                if n > 1:
                    rep.warn("duplicate_evidence", f"{where}.{kind}", f"{key} listed {n} times")
            for j, e in enumerate(items):
                key, loc = e.get("citation_key"), f"{where}.{kind}[{j}]"
                if key not in keys:
                    rep.fail("evidence_key_not_given", loc, f"{key!r} is not in the Step 6 key set given to Step 7")
                if bib and key not in bib:
                    rep.fail("evidence_key_not_in_bib", loc, f"{key!r} has no step4_references.bib entry")
                if not str(e.get("explanation_en") or "").strip():
                    rep.fail("empty_text", f"{loc}.explanation_en", "empty")
                year = e.get("year")
                if year is not None and bib.get(key) and year != bib[key]:
                    rep.warn("evidence_year", loc, f"{key}: year {year} vs bib {bib[key]}")
        both = {e.get("citation_key") for e in sup} & {e.get("citation_key") for e in g.get("counter_evidence") or []}
        if both:
            rep.warn("counter_also_supporting", where, f"in both supporting and counter: {', '.join(sorted(both))}")

    if order and [o[3] for o in sorted(order)] != [o[3] for o in order]:
        rep.fail("sort_order", None, f"ranked {[o[3] for o in order]}, expected {[o[3] for o in sorted(order)]}")

    gaps = [r.get("gap", {}) for r in ranked]
    counter = [len(g.get("counter_evidence") or []) for g in gaps]
    if gaps and not any(counter):
        rep.warn("counter_all_empty", None, "counter_evidence is empty for every gap")

    dropped = None
    if raw:
        raw_gaps = (raw.get("response") or {}).get("gaps", [])
        by_title = {g.get("title_en"): g for g in raw_gaps}
        dropped = {kind: 0 for kind in EVIDENCE}
        for g in gaps:
            rg = by_title.get(g.get("title_en"))
            if rg is None:
                rep.fail("raw_mismatch", g.get("title_en", "")[:60], "gap in step7_gaps.json not in the raw response (stale json or cache?)")
                continue
            for kind in EVIDENCE:
                dropped[kind] += max(0, len(rg.get(kind) or []) - len(g.get(kind) or []))
        if len(raw_gaps) > len(gaps) and len(gaps) < max_gaps:
            rep.fail("raw_mismatch", None, f"raw response has {len(raw_gaps)} gaps, json {len(gaps)} (max_gaps {max_gaps})")
        if len(raw_gaps) > max_gaps:
            rep.warn("gaps_truncated", None, f"model emitted {len(raw_gaps)} gaps; Step 7 kept the first {max_gaps}")
        if any(dropped.values()):
            rep.warn("evidence_filtered", None, f"Step 7 dropped evidence items with keys outside the key set: {dropped}")

    return {
        "gaps": len(ranked),
        "gap_types": dict(Counter(g.get("gap_type") for g in gaps)),
        "supporting_per_gap": [len(g.get("supporting_evidence") or []) for g in gaps],
        "counter_per_gap": counter,
        "evidence_dropped_by_step7_filter": dropped,
    }


# --------------------------------------------------------------------------- #
# step7_gap_analysis.md
# --------------------------------------------------------------------------- #
def check_md(md: str, s7: dict, rep: Report) -> None:
    ranked = s7.get("gaps", [])
    m = re.search(r"^gaps_identified:\s*(\d+)\s*$", md, re.M)
    if not m or int(m.group(1)) != len(ranked):
        rep.fail("md_frontmatter", None, f"gaps_identified {m.group(1) if m else 'missing'} vs {len(ranked)} gaps")
    heads = list(re.finditer(r"^## (GAP_\d{3}): (.*)$", md, re.M))
    if [h.group(1) for h in heads] != [r.get("id") for r in ranked]:
        rep.fail("md_gap_headings", None, f"headings {[h.group(1) for h in heads]} vs json {[r.get('id') for r in ranked]}")
    blocks = {}
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else md.find("## Priority Ranking")
        blocks[h.group(1)] = (h.group(2).strip(), md[h.end():end if end > 0 else len(md)])
    for r in ranked:
        g, gid = r.get("gap", {}), r.get("id")
        if gid not in blocks:
            continue
        title, block = blocks[gid]
        if title != g.get("title_en", "").strip():
            rep.fail("md_title", gid, "heading title differs from json title_en")
        if not re.search(rf"^\*\*Priority Rank:\*\* #{r.get('rank')}\s*$", block, re.M):
            rep.fail("md_rank", gid, "Priority Rank line missing or wrong")
        comp = re.search(r"= \*\*([\d.]+)\*\*\s*$", block, re.M)
        if not comp or float(comp.group(1)) != r.get("composite"):
            rep.fail("md_composite", gid, f"composite in md {comp.group(1) if comp else 'missing'} vs json {r.get('composite')}")
        for kind, title_re in (("supporting_evidence", r"### Supporting Evidence"), ("counter_evidence", r"### Counter-Evidence")):
            sec = re.search(rf"{title_re}\s*\n(.*?)(?=\n### |\Z)", block, re.S)
            if not sec:
                rep.fail("md_section_missing", gid, f"{title_re.lstrip('# ')} section missing")
                continue
            md_keys = re.findall(r"^- \*\*([^\s*(]+)", sec.group(1), re.M)
            json_keys = [e.get("citation_key") for e in g.get(kind) or []]
            if md_keys != json_keys:
                rep.fail("md_evidence", f"{gid}.{kind}", f"md {md_keys} vs json {json_keys}")
            if kind == "counter_evidence" and OLD_EMPTY_COUNTER in sec.group(1):
                rep.warn("md_old_empty_counter_text", gid, "empty counter-evidence rendered as 'highly novel direction' (pre-fix renderer)")
    table = re.search(r"## Priority Ranking\s*\n(.*?)(?=\n---|\n## |\Z)", md, re.S)
    rows = re.findall(r"^\|\s*(\d+)\s*\|\s*(GAP_\d{3})\s*\|.*\*\*([\d.]+)\*\*\s*\|\s*$", table.group(1), re.M) if table else []
    expected = [(str(r.get("rank")), r.get("id"), r.get("composite")) for r in ranked]
    if [(a, b, float(c)) for a, b, c in rows] != expected:
        rep.fail("md_ranking_table", None, f"ranking table {rows} vs json {expected}")


# --------------------------------------------------------------------------- #
def check_session(session: Path, max_gaps: int, may_omit: set[str]) -> dict:
    rep = Report()
    json_path, md_path = session / "step7_gaps.json", session / "step7_gap_analysis.md"
    for path in (json_path, md_path):
        if not path.exists():
            rep.fail("missing_output", None, f"{path.name} not found")
    if rep.failures:
        return finish(session, rep, {})

    raw = newest_raw(session)
    raw_info = check_raw(raw, may_omit, rep) if raw else None
    if raw is None:
        rep.warn("raw_missing", None, "no s7_gaps response in .cache/llm: omitted-field check not possible")
    keys, key_source = given_keys(session)
    if not keys:
        rep.fail("no_key_set", None, "could not read the key set Step 7 was given")
    s7 = read_json(json_path)
    stats = check_json(s7, raw, keys, bib_years(session), max_gaps, rep)
    check_md(md_path.read_text(encoding="utf-8"), s7, rep)
    return finish(session, rep, {"raw": raw_info, "key_set": {"source": key_source, "size": len(keys)}, **stats})


def finish(session: Path, rep: Report, stats: dict) -> dict:
    return {
        "session": str(session),
        "pass": not rep.failures,
        "n_failures": len(rep.failures),
        "n_warnings": len(rep.warnings),
        "failure_codes": dict(Counter(f["code"] for f in rep.failures)),
        "warning_codes": dict(Counter(w["code"] for w in rep.warnings)),
        "stats": stats,
        "failures": rep.failures,
        "warnings": rep.warnings,
    }


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--session", type=Path, nargs="+")
    src.add_argument("--batch", type=Path)
    ap.add_argument("--output", type=Path, help="--session only: write the report(s) here")
    ap.add_argument("--max-gaps", type=int, default=3, help="GapsConfig.max_gaps")
    ap.add_argument("--may-omit", nargs="*", default=["secondary_type", "year"],
                    help="schema fields the model may leave out (genuinely optional)")
    args = ap.parse_args()

    if args.batch:
        runs = [json.loads(l) for l in (args.batch / "runs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        targets = [(r["id"], args.batch / r["session_dir"]) for r in runs if (args.batch / r["session_dir"] / "step7_gaps.json").exists()]
    else:
        targets = [(p.name, p) for p in args.session]

    reports = {}
    for name, session in targets:
        report = check_session(session, args.max_gaps, set(args.may_omit))
        reports[name] = report
        if args.batch:
            write(args.batch / "eval" / name / "step07" / "contract.json", report)
        raw = (report["stats"].get("raw") or {})
        print(f"{'PASS' if report['pass'] else 'FAIL'} {name} [s7_gaps {raw.get('prompt_version', '?')}] "
              f"failures={report['n_failures']} warnings={report['n_warnings']} {report['failure_codes'] or ''}")
        for f in report["failures"][:8]:
            print(f"    - {f['code']} {f['where'] or ''}: {f['detail']}")
        if len(report["failures"]) > 8:
            print(f"    ... {len(report['failures']) - 8} more")

    total = lambda field: dict(sum((Counter(r[field]) for r in reports.values()), Counter()))  # noqa: E731
    summary = {
        "sessions": len(reports),
        "passed": sum(r["pass"] for r in reports.values()),
        "failure_codes": total("failure_codes"),
        "warning_codes": total("warning_codes"),
        "per_session": {k: {"pass": r["pass"], "failure_codes": r["failure_codes"]} for k, r in reports.items()},
    }
    if args.batch:
        write(args.batch / "eval" / "step07_contract_summary.json", summary)
    elif args.output:
        write(args.output, reports if len(reports) > 1 else next(iter(reports.values())))
    print(f"\n{summary['passed']}/{summary['sessions']} sessions pass; failure codes: {summary['failure_codes'] or 'none'}"
          f"\nwarning codes: {summary['warning_codes'] or 'none'}")
    return 0 if summary["passed"] == summary["sessions"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
