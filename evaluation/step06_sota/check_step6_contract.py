#!/usr/bin/env python3
"""Deterministic Step 6 checks (spec L2 §4.1–4.3) plus Step 7 evidence integrity.

§4.1 citation integrity (hard gate)
§4.2 structure: theme count, four non-empty dimensions, citation minimums, Key Results header
§4.3 full-text coverage from actual citations in theme text or Key Results tables
Step 7: every evidence key in step7_gap_analysis.md must be in the legal key set K.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from step6_common import (
    as_level_list,
    cited_keys,
    content_lines,
    extract_citations,
    is_papers_inventory,
    is_table_row,
    load_access_levels,
    load_manifest,
    parse_bib_keys,
    sections,
    split_frontmatter,
    tables,
)


THEME_TITLE_RE = re.compile(r"^Theme\s+(\d+)\s*:", re.IGNORECASE)
DIMENSIONS = {
    "consensus": re.compile(r"^Consensus\b", re.IGNORECASE),
    "debates": re.compile(r"^Debates?\b", re.IGNORECASE),
    "methods": re.compile(r"^(?:Dominant\s+)?Methods?\b", re.IGNORECASE),
    "key_results": re.compile(r"^Key\s+Results?\b", re.IGNORECASE),
}
CROSS_THEME_TITLE_RE = re.compile(r"^Cross[-\s]Theme\s+Analysis\b", re.IGNORECASE)
CROSS_THEME_SUBSECTIONS = {
    "methodological_trends_over_time": re.compile(r"^Methodological\s+Trends\s+Over\s+Time\b", re.IGNORECASE),
    "converging_findings": re.compile(r"^Converging\s+Findings\b", re.IGNORECASE),
    "diverging_findings": re.compile(r"^Diverging\s+Findings\b", re.IGNORECASE),
    "theme_interactions": re.compile(r"^Theme\s+Interactions\b", re.IGNORECASE),
}
PAPER_MAP_TITLE_RE = re.compile(r"^Paper[–-]Theme\s+Mapping\b", re.IGNORECASE)
GAP_TITLE_RE = re.compile(r"^(GAP_\d+)\b")
EVIDENCE_TITLES = {
    "supporting": re.compile(r"^Supporting\s+Evidence\b", re.IGNORECASE),
    "counter": re.compile(r"^Counter[-\s]Evidence\b", re.IGNORECASE),
}
DEFAULT_KEY_RESULTS_HEADER = ["Study", "N", "Method", "Primary Outcome", "Result"]


def theme_count_range(paper_count: int) -> tuple[int, int]:
    """Theme-count rule from the Step 6 prompt: <10 papers 2–3, >30 up to 8, otherwise 4–6."""
    if paper_count < 10:
        return 2, 3
    if paper_count > 30:
        return 4, 8
    return 4, 6


def check_citation_integrity(body: list[str], offset: int, legal: set[str]) -> dict:
    """§4.1: every cited key, after normalization, must be in K."""
    invalid = []
    normalized = []
    for index, line in enumerate(body):
        for citation in extract_citations(line, index + offset + 1):
            if citation.form == "author_year":
                normalized.append({"citation": citation.raw, "key": citation.key, "line": citation.line})
            if citation.key not in legal:
                invalid.append({"key": citation.key, "raw": citation.raw, "form": citation.form, "line": citation.line})
    invalid_keys = sorted({item["key"] for item in invalid})
    return {
        "integrity_fail": bool(invalid_keys),
        "invalid_keys": invalid_keys,
        "invalid_occurrences": invalid,
        "normalized_author_year": normalized,
        "cited_key_count": len(cited_keys(body) & legal),
    }


def check_theme(body: list[str], offset: int, theme, legal: set[str], expected_header: list[str]) -> dict:
    number = int(THEME_TITLE_RE.match(theme.title).group(1))
    theme_lines = [line for line in theme.lines(body) if not is_papers_inventory(line)]
    subsections = sections(body, 3, theme.start + 1, theme.end)
    dims = {}
    for name, pattern in DIMENSIONS.items():
        match = next((s for s in subsections if pattern.match(s.title)), None)
        lines = match.lines(body) if match else []
        dims[name] = {
            "present": match is not None,
            "non_empty": bool(content_lines(lines)),
            "keys": sorted(cited_keys(lines) & legal),
            "_lines": lines,
        }

    kr_tables = tables(dims["key_results"]["_lines"])
    header_checks = []
    for table in kr_tables:
        header_checks.append({
            "header": table["header"],
            "pass": [c.casefold() for c in table["header"]] == [c.casefold() for c in expected_header],
        })
    header_ok = all(check["pass"] for check in header_checks)

    theme_keys = sorted(cited_keys(theme_lines) & legal)
    papers_ok = len(theme_keys) >= 2

    for dim in dims.values():
        dim.pop("_lines")
    dims_ok = all(dim["present"] and dim["non_empty"] for dim in dims.values())
    return {
        "theme": number,
        "title": theme.title,
        "line": theme.start + offset + 1,
        "dimensions": dims,
        "dimensions_pass": dims_ok,
        "key_results_is_table": bool(kr_tables),
        "key_results_headers": header_checks,
        "key_results_header_pass": header_ok,
        "cited_papers": theme_keys,
        "min_2_papers": papers_ok,
        "pass": dims_ok and header_ok and papers_ok,
    }


def check_cross_theme(body: list[str], level2) -> dict:
    section = next((s for s in level2 if CROSS_THEME_TITLE_RE.match(s.title)), None)
    subs = sections(body, 3, section.start + 1, section.end) if section else []
    present = {name: any(p.match(s.title) for s in subs) for name, p in CROSS_THEME_SUBSECTIONS.items()}
    return {
        "note": "Not part of spec §4.2; reported for the Step 6 prompt's required form and not gated.",
        "section_present": section is not None,
        "required_subsections": present,
        "pass": section is not None and all(present.values()),
    }


def paper_map_keys(body: list[str], level2, legal: set[str]) -> set[str]:
    section = next((s for s in level2 if PAPER_MAP_TITLE_RE.match(s.title)), None)
    if not section:
        return set()
    keys: set[str] = set()
    for table in tables(section.lines(body)):
        for row in table["rows"]:
            keys.update(cited_keys(row[:1]) & legal)
    return keys


def check_coverage(body, themes, level2, legal, access, manifest) -> dict:
    """§4.3: denominator = full-text sources; numerator = those cited in >=1 theme (text or table)."""
    denominator_levels = as_level_list(manifest.get("coverage_denominator", "full-text-pdf"))
    threshold = float(manifest.get("coverage_threshold", 0.8))
    theme_cited: set[str] = set()
    inventory: set[str] = set()
    for theme in themes:
        for line in theme.lines(body):
            (inventory if is_papers_inventory(line) else theme_cited).update(cited_keys([line]) & legal)

    def rate(levels: list[str]) -> dict:
        denominator = {key for key, level in access.items() if level in levels and key in legal}
        covered = denominator & theme_cited
        value = len(covered) / len(denominator) if denominator else 0.0
        return {
            "levels": levels,
            "denominator": len(denominator),
            "numerator": len(covered),
            "rate": round(value, 4),
            "pass": value >= threshold,
            "missing": sorted(denominator - covered),
        }

    primary = rate(denominator_levels)
    with_html = rate(sorted(set(denominator_levels) | {"full-text-html"}))
    denominator = {key for key, level in access.items() if level in denominator_levels and key in legal}
    mapped = paper_map_keys(body, level2, legal)

    return {
        "threshold": threshold,
        "primary": primary,
        "if_full_text_html_included": with_html,
        "pass": primary["pass"],
        "definition": "Denominator: step5 frontmatter access_level in `levels`. Numerator: denominator keys cited in any "
                      "Theme section's prose or Key Results table (Papers inventory line excluded; each key counted once).",
        "comparison": {
            "papers_line_rate": round(len(denominator & inventory) / len(denominator), 4) if denominator else 0.0,
            "paper_map_rate": round(len(denominator & mapped) / len(denominator), 4) if denominator else 0.0,
            "in_paper_map_not_cited": sorted((denominator & mapped) - theme_cited),
            "cited_not_in_paper_map": sorted((denominator & theme_cited) - mapped),
            "n_repaired": None,
            "n_repaired_note": "Not available: requires the engine's paper_map repair log.",
        },
    }


def check_step7(path: Path, legal: set[str], step6_keys: set[str]) -> dict:
    if not path.exists():
        return {"status": "skipped", "reason": f"missing {path}", "integrity_fail": False, "pass": True}
    _, body, offset = split_frontmatter(path.read_text(encoding="utf-8"))
    integrity = check_citation_integrity(body, offset, legal)
    gaps = []
    for gap in sections(body, 2):
        match = GAP_TITLE_RE.match(gap.title)
        if not match:
            continue
        report = {"gap": match.group(1), "line": gap.start + offset + 1}
        for kind, pattern in EVIDENCE_TITLES.items():
            sub = next((s for s in sections(body, 3, gap.start + 1, gap.end) if pattern.match(s.title)), None)
            items = []
            for line in (sub.lines(body) if sub else []):
                if not line.startswith("- "):
                    continue
                labels = " ".join(re.findall(r"\*\*(.+?)\*\*", line.split(":", 1)[0] + ":"))
                keys = [c.key for c in extract_citations(labels)]
                items.append({
                    "label": labels or line[:80],
                    "keys": keys,
                    "invalid_keys": sorted(set(keys) - legal),
                    "cited": bool(keys),
                })
            report[kind] = {
                "present": sub is not None,
                "items": items,
                "uncited_items": [item["label"] for item in items if not item["cited"]],
            }
        report["has_cited_supporting_evidence"] = any(i["cited"] for i in report["supporting"]["items"])
        report["pass"] = not any(i["invalid_keys"] for k in EVIDENCE_TITLES for i in report[k]["items"])
        gaps.append(report)
    evidence_keys = {key for gap in gaps for k in EVIDENCE_TITLES for i in gap[k]["items"] for key in i["keys"]}
    return {
        "path": str(path),
        **integrity,
        "gaps": gaps,
        "evidence_keys_not_cited_in_step6": sorted((evidence_keys & legal) - step6_keys),
        "phantom_removed": None,
        "phantom_removed_note": "Not available: _validation.json is not produced for this project.",
        "pass": not integrity["integrity_fail"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    here = Path(__file__).resolve().parent
    parser.add_argument("--manifest", default=str(here / "step6_source_manifest.json"))
    parser.add_argument("--output", default=str(here / "step6_contract_results.json"))
    args = parser.parse_args()

    manifest, project = load_manifest(Path(args.manifest).resolve())
    review_path = project / manifest["review"]
    bib_path = project / manifest["bibliography"]
    full_text_dir = project / manifest["full_text_dir"]
    step7_path = project / manifest.get("gap_analysis", "step7_gap_analysis.md")

    legal = parse_bib_keys(bib_path.read_text(encoding="utf-8"))
    access = load_access_levels(full_text_dir)
    _, body, offset = split_frontmatter(review_path.read_text(encoding="utf-8"))
    level2 = sections(body, 2)
    themes = [s for s in level2 if THEME_TITLE_RE.match(s.title)]

    # §4.1
    integrity = check_citation_integrity(body, offset, legal)

    # §4.2
    lo, hi = theme_count_range(len(legal))
    expected_header = manifest.get("key_results_header", DEFAULT_KEY_RESULTS_HEADER)
    theme_reports = [check_theme(body, offset, t, legal, expected_header) for t in themes]
    structure = {
        "paper_count": len(legal),
        "theme_count_range": [lo, hi],
        "found_themes": len(themes),
        "theme_count_pass": lo <= len(themes) <= hi,
        "expected_key_results_header": expected_header,
        "themes": theme_reports,
    }
    structure["pass"] = structure["theme_count_pass"] and all(t["pass"] for t in theme_reports)

    # §4.3
    coverage = check_coverage(body, themes, level2, legal, access, manifest)

    step7 = check_step7(step7_path, legal, cited_keys(body) & legal)

    manifest_levels = manifest.get("sources", {})
    source_integrity = {
        "bib_keys_without_markdown": sorted(legal - access.keys()),
        "markdown_without_bib_entry": sorted(access.keys() - legal),
        "missing_access_level": sorted(k for k, v in access.items() if not v),
        "manifest_access_level_mismatch": sorted(
            k for k, v in manifest_levels.items() if k in access and access[k] != v
        ),
    }
    source_integrity["pass"] = not any(source_integrity.values())

    result = {
        "paths": {"review": str(review_path), "bibliography": str(bib_path),
                  "full_text_dir": str(full_text_dir), "gap_analysis": str(step7_path)},
        "citation_integrity": integrity,
        "cite_score_policy": "integrity_fail -> all Cite scores are 0 and the judge model is not run",
        "structure": structure,
        "cross_theme_analysis": check_cross_theme(body, level2),
        "coverage": coverage,
        "step7": step7,
        "source_integrity": source_integrity,
    }
    result["overall_pass"] = (
        not integrity["integrity_fail"]
        and structure["pass"]
        and coverage["pass"]
        and step7["pass"]
        and source_integrity["pass"]
    )
    result["summary"] = {
        "step6_integrity_fail": integrity["integrity_fail"],
        "step7_integrity_fail": step7["integrity_fail"],
        "structure_pass": structure["pass"],
        "failing_themes": [t["theme"] for t in theme_reports if not t["pass"]],
        "coverage_rate": coverage["primary"]["rate"],
        "coverage_pass": coverage["pass"],
        "source_integrity_pass": source_integrity["pass"],
        "overall_pass": result["overall_pass"],
    }

    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
