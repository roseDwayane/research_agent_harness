#!/usr/bin/env python3
"""Deterministic Step 6 checks for the fusion-block architecture (B2 `step6_sota_review.md`).

    python evaluation/step06_sota/check_step6_contract.py --session <research folder> [--output contract.json]

Replaces the checks written for the archived engine, which assumed `(AuthorYear)` keys, themes chosen by the model and a
step5 full text for every paper. In the new architecture the review cites ids (collisions X0019, experiments
galt2019#E1, Points, Lines) and one Theme per Plane, so this file checks against the harness's own records
(step6_world.py), not against a bibliography alone.

1  integrity      every id cited exists (collisions.jsonl, decon units, Points, Lines, Planes, .bib keys); an id a
                  duplicate_of marks as superseded is reported
2  structure      frontmatter (scope topic, counts agree with the Planes and the decon records); one Theme per Plane,
                  titled as the Plane; each Theme has Consensus / Debates / Dominant methods / Key results; Key results
                  header, Study = a legal exp_id of that Plane's papers; Executive summary, Cross-theme analysis (four
                  subsections), Experiments (A, B), the abstract-only warning when no full text was read
3  type fit       Consensus rests on an agree/boundary collision or findings Point, Debates on a conflict/boundary
                  collision or a debate Line - else the section says (TBD)   (the harness's J08, re-run here so the
                  eval does not depend on the harness gate; `--harness-gate` also runs it)
4  coverage       share of the Planes' papers named in a Theme (key, unit id or exp id), and of the full-text subset
5  mapping        Methodology legend and Paper–theme mapping are filled, agree with each other, with the Planes and with
                  knowledge_cards.json["methodology"]
6  disclosure     (reported, not gated) share of Consensus / Debates sentences that rest only on abstract-level
                  collisions and say so; share of (TBD) cells in the Key results tables

Exit 1 when `overall_pass` is false (a failed check is a result, not an error).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from step6_common import (
    content_lines,
    is_table_row,
    sections,
    split_frontmatter,
    tables,
)
from step6_world import DEBATE_RESULTS, FINDING_RESULTS, TBD, World, ids_in, load_world

THEME_TITLE_RE = re.compile(r"^Theme\s+(\d+)\s*:\s*(.*)$", re.IGNORECASE)
DIMENSIONS = {
    "consensus": re.compile(r"^Consensus\b", re.IGNORECASE),
    "debates": re.compile(r"^Debates?\b", re.IGNORECASE),
    "methods": re.compile(r"^Dominant\s+Methods?\b", re.IGNORECASE),
    "key_results": re.compile(r"^Key\s+Results?\b", re.IGNORECASE),
}
CROSS_THEME_SUBSECTIONS = {
    "methodological_trends_over_time": re.compile(r"^Methodological\s+Trends\s+Over\s+Time\b", re.IGNORECASE),
    "converging_findings": re.compile(r"^Converging\s+Findings\b", re.IGNORECASE),
    "diverging_findings": re.compile(r"^Diverging\s+Findings\b", re.IGNORECASE),
    "theme_interactions": re.compile(r"^Theme\s+Interactions\b", re.IGNORECASE),
}
EXPERIMENT_SUBSECTIONS = {
    "designs": re.compile(r"^A\.\s*Experimental\s+Designs\b", re.IGNORECASE),
    "numbers": re.compile(r"^B\.\s*Reported\s+Numbers\b", re.IGNORECASE),
}
H2 = {
    "summary": re.compile(r"^Executive\s+Summary\b", re.IGNORECASE),
    "legend": re.compile(r"^Methodology\s+Legend\b", re.IGNORECASE),
    "cross": re.compile(r"^Cross[-\s]Theme\s+Analysis\b", re.IGNORECASE),
    "experiments": re.compile(r"^Experiments\s+in\s+this\s+Literature\b", re.IGNORECASE),
    "mapping": re.compile(r"^Paper[–-]Theme\s+Mapping\b", re.IGNORECASE),
}
KEY_RESULTS_HEADER = ["Study", "N", "Data", "Method", "Primary Outcome", "Metric", "Result"]
METHODOLOGY_CLASSES = ("experimental", "computational", "review", "observational", "engineering", "theoretical")
COVERAGE_THRESHOLD = 0.8
SENTENCE_RE = re.compile(r"(?<=[.!?;])\s+(?=[A-Z(\[])")


KEY_AT = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*):(?=\s|$)")


def parse_frontmatter(lines: list[str]) -> dict[str, str]:
    """Key: value pairs, one or several per line (`total_papers: 16   themes: 4`: the harness's template allows both)."""
    out: dict[str, str] = {}
    for line in lines:
        marks = list(KEY_AT.finditer(line))
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(line)
            out.setdefault(m.group(1), line[m.end():end].strip().strip('"').strip("'"))
    return out


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().rstrip(".")).casefold()


def _sub(body, parent, pattern):
    return next((s for s in sections(body, 3, parent.start + 1, parent.end) if pattern.match(s.title)), None)


# ------------------------------------------------------------------------------------------------ 1 integrity
def check_integrity(body: list[str], offset: int, w: World) -> dict:
    invalid, stale, cited = [], set(), set()
    for index, line in enumerate(body):
        if is_table_row(line) and re.match(r"^\|\s*:?-{3,}", line.strip()):
            continue
        for ident, form in ids_in(line, w):
            cited.add(ident)
            if w.kind(ident) is None:
                invalid.append({"id": ident, "form": form, "line": index + offset + 1})
            elif ident in w.collisions and w.collisions[ident].get("duplicate_of"):
                stale.add(ident)
    return {
        "integrity_fail": bool(invalid),
        "invalid_ids": sorted({i["id"] for i in invalid}),
        "invalid_occurrences": invalid,
        "superseded_collisions_cited": sorted(stale),
        "cited_id_count": len(cited),
        "cited_by_kind": {k: sum(1 for i in cited if w.kind(i) == k)
                          for k in ("collision", "exp", "unit", "point", "line", "plane", "paper")},
    }


# ------------------------------------------------------------------------------------------------ 2 structure
def check_theme(body, offset, theme, plane: dict | None, w: World) -> dict:
    m = THEME_TITLE_RE.match(theme.title)
    number = int(m.group(1))
    subs = sections(body, 3, theme.start + 1, theme.end)
    dims = {}
    for name, pattern in DIMENSIONS.items():
        sec = next((s for s in subs if pattern.match(s.title)), None)
        lines = sec.lines(body) if sec else []
        dims[name] = {"present": sec is not None, "non_empty": bool(content_lines(lines)), "_lines": lines}

    members = set((plane or {}).get("member_papers") or [])
    header_checks, row_problems, rows_outside, rows_n, tbd_cells, cells_n = [], [], [], 0, 0, 0
    exp_ids_in_table: set[str] = set()
    for table in tables(dims["key_results"]["_lines"]):
        header_checks.append({"header": table["header"],
                              "pass": [c.casefold() for c in table["header"]] == [c.casefold() for c in KEY_RESULTS_HEADER]})
        for row in table["rows"]:
            rows_n += 1
            study = row[0].strip("` ") if row else ""
            exp_ids_in_table.add(study)
            if study not in w.exps:
                row_problems.append({"study": study, "problem": "Study is not a legal exp_id"})
            elif members and w.units[study] not in members:
                rows_outside.append({"study": study, "paper": w.units[study]})
            tbd_cells += sum(1 for c in row[1:] if TBD in c)
            cells_n += max(len(row) - 1, 0)
    expected_exps = {e for e, rec in w.exps.items() if w.units[e] in members}
    dims_ok = all(d["present"] and d["non_empty"] for d in dims.values())
    for d in dims.values():
        d.pop("_lines")
    kr_ok = bool(header_checks) and all(c["pass"] for c in header_checks) and not row_problems
    title_ok = plane is not None and _norm(m.group(2)) == _norm(plane.get("name", ""))
    return {
        "theme": number,
        "title": theme.title,
        "plane": None if plane is None else f"T{plane['n']} {plane.get('slug')}",
        "title_matches_plane": title_ok,
        "dimensions": dims,
        "dimensions_pass": dims_ok,
        "key_results_header_checks": header_checks,
        "key_results_rows": rows_n,
        "key_results_row_problems": row_problems,
        "key_results_rows_of_other_planes": rows_outside,      # reported, not gated: the harness contract does not ask for it
        "key_results_pass": kr_ok,
        "experiments_missing_from_table": sorted(expected_exps - exp_ids_in_table),
        "tbd_cells": f"{tbd_cells}/{cells_n}",
        "pass": plane is not None and dims_ok and kr_ok,
    }


def check_structure(body, offset, fm, level2, themes, w: World) -> dict:
    planes = {pl["n"]: pl for pl in w.planes}
    reports = [check_theme(body, offset, t, planes.get(int(THEME_TITLE_RE.match(t.title).group(1))), w) for t in themes]
    numbers = [r["theme"] for r in reports]

    def h2(name):
        return next((s for s in level2 if H2[name].match(s.title)), None)

    cross = h2("cross")
    cross_present = {}
    if cross:
        for name, pattern in CROSS_THEME_SUBSECTIONS.items():
            sec = _sub(body, cross, pattern)
            cross_present[name] = bool(sec and content_lines(sec.lines(body)))
    exp = h2("experiments")
    exp_present = {}
    if exp:
        for name, pattern in EXPERIMENT_SUBSECTIONS.items():
            sec = _sub(body, exp, pattern)
            exp_present[name] = bool(sec and content_lines(sec.lines(body)))
    summary = h2("summary")

    # frontmatter agrees with the records
    evidence = w.evidence_papers()
    ft = sum(1 for k in evidence if w.paper_basis(k) == "full-text")
    fm_problems = []
    if fm.get("scope") != "topic":
        fm_problems.append("frontmatter scope is not `topic`")
    if fm.get("step") != "6":
        fm_problems.append("frontmatter step is not 6")
    expected_fm = {"themes": len(w.planes), "total_papers": len(evidence), "full_text_papers": ft,
                   "abstract_only_papers": len(evidence) - ft}
    for name, want in expected_fm.items():
        if str(fm.get(name)) != str(want):
            fm_problems.append(f"frontmatter {name}={fm.get(name)} but the records say {want}")
    warning_ok = ft > 0 or any("abstract" in l.lower() and l.lstrip().startswith(">") for l in body[:6])

    result = {
        "plane_count": len(w.planes),
        "found_themes": len(themes),
        "theme_numbers": numbers,
        "theme_count_pass": numbers == sorted(planes) and len(themes) == len(w.planes),
        "themes": reports,
        "executive_summary_present": bool(summary and content_lines(summary.lines(body))),
        "legend_present": h2("legend") is not None,
        "mapping_present": h2("mapping") is not None,
        "cross_theme_subsections": cross_present,
        "cross_theme_pass": bool(cross) and len(cross_present) == 4 and all(cross_present.values()),
        "experiments_subsections": exp_present,
        "experiments_pass": bool(exp) and len(exp_present) == 2 and all(exp_present.values()),
        "frontmatter_problems": fm_problems,
        "abstract_only_warning_ok": warning_ok,
    }
    result["pass"] = (result["theme_count_pass"] and all(r["pass"] for r in reports) and result["executive_summary_present"]
                      and result["legend_present"] and result["mapping_present"] and result["cross_theme_pass"]
                      and result["experiments_pass"] and not fm_problems and warning_ok)
    return result


# ------------------------------------------------------------------------------------------------ 3 type fit
def counts_for(w: World, heading: str, ident: str) -> bool:
    """Whether `ident` is what a Consensus (agree/boundary collision, findings Point) or Debates (conflict/boundary
    collision, debate Line) section may rest on - the harness's J08 rule."""
    if ident in w.collisions:
        return w.collisions[ident]["result"] in (FINDING_RESULTS if heading == "Consensus" else DEBATE_RESULTS)
    if heading == "Consensus":
        return ident in w.points and w.points[ident].get("origin") == "collide"
    return ident.startswith("D_draft_") and ident in w.lines


def check_type_fit(body, themes, w: World) -> dict:
    sections_checked, failures = 0, []
    for theme in themes:
        for sec in sections(body, 3, theme.start + 1, theme.end):
            heading = next((h for h in ("Consensus", "Debates") if re.match(h, sec.title, re.I)), None)
            if not heading:
                continue
            sections_checked += 1
            text = "\n".join(sec.lines(body))
            ids = [i for i, _ in ids_in(text, w)]
            if TBD in text or any(counts_for(w, heading, i) for i in ids):
                continue
            failures.append({"theme": theme.title, "section": heading,
                             "cited": [f"{i} ({w.collisions[i]['result']})" if i in w.collisions else i
                                       for i in dict.fromkeys(ids)]})
    return {"sections_checked": sections_checked, "failures": failures, "pass": not failures}


# ------------------------------------------------------------------------------------------------ 4 coverage
def check_coverage(body, themes, w: World) -> dict:
    theme_text = "\n".join(line for t in themes for line in t.lines(body))
    named, via_collision = set(), set()
    for ident, _ in ids_in(theme_text, w):
        kind = w.kind(ident)
        if kind in ("exp", "unit", "paper"):
            named |= w.papers_of(ident)
        elif kind == "collision":
            via_collision |= w.papers_of(ident)
    evidence = w.evidence_papers()
    full_text = {k for k in evidence if w.paper_basis(k) == "full-text"}

    def rate(denominator: set[str], covered: set[str]) -> dict:
        got = denominator & covered
        return {"denominator": len(denominator), "numerator": len(got),
                "rate": round(len(got) / len(denominator), 4) if denominator else 1.0,
                "missing": sorted(denominator - got)}

    primary = rate(evidence, named)
    primary["pass"] = primary["rate"] >= COVERAGE_THRESHOLD
    return {
        "threshold": COVERAGE_THRESHOLD,
        "definition": "denominator: papers in the Planes' member_papers; numerator: those named in a Theme section by "
                      "paper key, unit id or exp_id",
        "primary": primary,
        "full_text_subset": rate(full_text, named),
        "if_collision_sides_count": rate(evidence, named | via_collision),
        "papers_in_no_plane": sorted(set(w.decon) - evidence),
        "pass": primary["pass"],
    }


# ------------------------------------------------------------------------------------------------ 5 mapping
def check_mapping(body, level2, w: World) -> dict:
    legend_sec = next((s for s in level2 if H2["legend"].match(s.title)), None)
    map_sec = next((s for s in level2 if H2["mapping"].match(s.title)), None)
    legend, mapping = {}, []
    if legend_sec:
        for t in tables(legend_sec.lines(body)):
            for row in t["rows"]:
                if len(row) >= 3 and row[2].strip().isdigit():
                    legend[row[1].strip().casefold()] = int(row[2])
    if map_sec:
        for t in tables(map_sec.lines(body)):
            mapping += t["rows"]
    problems = []
    plane_of = {p: pl["n"] for pl in w.planes for p in pl.get("member_papers") or []}
    seen = []
    for row in mapping:
        key = row[0].strip("` ")
        seen.append(key)
        if key not in w.bib_keys:
            problems.append(f"{key}: not a bibliography key")
            continue
        if key in plane_of and row[1].strip().lstrip("Tt") != str(plane_of[key]):
            problems.append(f"{key}: Theme {row[1].strip()} but the Plane holding it is T{plane_of[key]}")
        want = w.methodology.get(key)
        if want and len(row) > 2 and row[2].strip().casefold() != want:
            problems.append(f"{key}: methodology {row[2].strip()} but knowledge_cards says {want}")
    dup = sorted({k for k in seen if seen.count(k) > 1})
    if dup:
        problems.append(f"papers listed twice: {dup}")
    # the template: "one row per paper the review cites" - cites by key, exp_id or unit id (not through a collision)
    skip: set[int] = set()
    for sec in level2:
        if H2["mapping"].match(sec.title) or H2["legend"].match(sec.title):
            skip.update(range(sec.start, sec.end))
    cited_text = "\n".join(line for i, line in enumerate(body) if i not in skip)
    cited = set()
    for ident, _ in ids_in(cited_text, w):
        if w.kind(ident) in ("paper", "exp", "unit"):
            cited |= w.papers_of(ident)
    missing, extra = sorted(cited - set(seen)), sorted(set(seen) - cited)
    if missing:
        problems.append(f"{len(missing)} papers the review cites are missing from the mapping, e.g. {missing[:8]}")
    if extra:
        problems.append(f"{len(extra)} papers in the mapping are not cited by the review, e.g. {extra[:8]}")
    counted = {c: sum(1 for r in mapping if len(r) > 2 and r[2].strip().casefold() == c) for c in METHODOLOGY_CLASSES}
    legend_ok = bool(legend) and all(legend.get(c, 0) == n for c, n in counted.items())
    if not legend_ok:
        problems.append(f"legend counts {legend} do not match the mapping rows {counted}")
    return {"mapping_rows": len(mapping), "legend": legend, "mapping_counts": counted,
            "problems": problems, "pass": bool(mapping) and not problems}


# ------------------------------------------------------------------------------------------------ 6 disclosure
def check_disclosure(body, level2, themes, w: World) -> dict:
    scopes = [t for t in themes] + [s for s in level2 if H2["summary"].match(s.title) or H2["cross"].match(s.title)]
    total = marked = 0
    unmarked = []
    for sec in scopes:
        for line in sec.lines(body):
            if not line.strip() or line.startswith(("#", "|")):
                continue
            for sentence in SENTENCE_RE.split(line.strip()):
                xs = [i for i, f in ids_in(sentence, w) if i in w.collisions]
                if not xs or any(w.collisions[i].get("evidence_level") != "abstract" for i in xs):
                    continue
                total += 1
                if re.search(r"abstract", sentence, re.I):
                    marked += 1
                else:
                    unmarked.append(sentence[:160])
    return {"note": "reported, not gated",
            "abstract_level_sentences": total, "marked": marked,
            "marking_rate": round(marked / total, 4) if total else 1.0,
            "unmarked_examples": unmarked[:5]}


# ------------------------------------------------------------------------------------------------ harness gate
def harness_gate(rd: Path) -> dict:
    script = Path(__file__).resolve().parents[2] / "ai-scientist-ideate-harness" / "scripts" / "ideate_tools.py"
    if not script.exists():
        return {"status": "skipped", "reason": f"missing {script}"}
    proc = subprocess.run([sys.executable, str(script), "recon-check", str(rd), "--unit", "B2"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {"status": "ok" if proc.returncode == 0 else "failed", "exit_code": proc.returncode,
            "output": (proc.stdout + proc.stderr).strip()[-1500:]}


# ------------------------------------------------------------------------------------------------ main
def run_checks(rd: Path, with_harness_gate: bool = False) -> dict:
    rd = Path(rd).resolve()
    w = load_world(rd)
    review = rd / "step6_sota_review.md"
    raw_lines = review.read_text(encoding="utf-8").splitlines()
    _, body, offset = split_frontmatter(review.read_text(encoding="utf-8"))
    fm = parse_frontmatter(raw_lines[1:offset - 1] if offset else [])
    level2 = sections(body, 2)
    themes = [s for s in level2 if THEME_TITLE_RE.match(s.title)]

    integrity = check_integrity(body, offset, w)
    structure = check_structure(body, offset, fm, level2, themes, w)
    type_fit = check_type_fit(body, themes, w)
    coverage = check_coverage(body, themes, w)
    mapping = check_mapping(body, level2, w)
    disclosure = check_disclosure(body, level2, themes, w)

    source_integrity = {
        "bib_keys_without_decon": sorted(w.bib_keys - set(w.decon)),
        "decon_without_bib_entry": sorted(set(w.decon) - w.bib_keys),
        "plane_papers_without_decon": sorted(w.evidence_papers() - set(w.decon)),
        "fulltext_files_for_abstract_only_papers": sorted(k for k in w.fulltext if w.paper_basis(k) != "full-text"),
    }
    source_integrity["pass"] = not any(source_integrity.values())

    result = {
        "review": str(review),
        "citation_integrity": integrity,
        "structure": structure,
        "type_fit": type_fit,
        "coverage": coverage,
        "mapping": mapping,
        "disclosure": disclosure,
        "source_integrity": source_integrity,
        "cite_score_policy": "integrity_fail -> all Cite scores are 0 and the judge model is not run",
    }
    if with_harness_gate:
        result["harness_b2_gate"] = harness_gate(rd)
    result["overall_pass"] = (not integrity["integrity_fail"] and structure["pass"] and type_fit["pass"]
                              and coverage["pass"] and mapping["pass"] and source_integrity["pass"])
    result["summary"] = {
        "integrity_fail": integrity["integrity_fail"],
        "invalid_ids": integrity["invalid_ids"],
        "structure_pass": structure["pass"],
        "theme_count": structure["found_themes"],
        "plane_count": structure["plane_count"],
        "failing_themes": [t["theme"] for t in structure["themes"] if not t["pass"]],
        "type_fit_pass": type_fit["pass"],
        "coverage_rate": coverage["primary"]["rate"],
        "coverage_pass": coverage["pass"],
        "mapping_pass": mapping["pass"],
        "source_integrity_pass": source_integrity["pass"],
        "abstract_marking_rate": disclosure["marking_rate"],
        "overall_pass": result["overall_pass"],
    }
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", type=Path, required=True, help="research folder (holds step6_sota_review.md)")
    ap.add_argument("--output", type=Path, help="write the full result here")
    ap.add_argument("--harness-gate", action="store_true", help="also run the harness's own `recon-check --unit B2`")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    result = run_checks(args.session, args.harness_gate)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
