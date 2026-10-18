#!/usr/bin/env python3
"""Deterministic Step 5 (research-fulltext) checks: does step5_full_text/ match what s5_fulltext.py promises?

    python evaluation/step05_fulltext/check_step5_contract.py --session <session_dir> [--output step5_contract.json]
    python evaluation/step05_fulltext/check_step5_contract.py --batch evaluation/runs/<batch>   # → eval/{id}/step05/contract.json

Failures (exit 1) are contract violations; warnings are reported, not gated.

Inputs → outputs:   every shortlisted paper with a Step 4 key has exactly one {key}.md, and nothing else is there
Frontmatter:        required fields present, citation_key == file name, title/doi == shortlist, access_level legal
Access level rules: full text >= 1500 chars; full-text-html below min_chars/min_sections must have been downgraded
                    to partial-text-html (and partial only when below); long_paper iff char_count > 120000;
                    pdf_sha256 iff full-text-pdf; final attempt "ok" iff not abstract-only
Integrity:          file body not shorter than recorded char_count; no two papers with the same body / PDF / DOI
Access log:         _access_log.json has one row per file and agrees with each frontmatter; _access_log.md counts

Sessions without _access_log.json (e.g. MetaSyn fixed-input batches written by metasyn_prepare.py, not by
Step 5) are checked in "fixed-input" mode: files, frontmatter and integrity only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ACCESS_LEVELS = ("full-text-pdf", "full-text-html", "partial-text-html", "abstract-only")
REQUIRED_FM = ("citation_key", "title", "authors", "year", "doi", "source", "access_level", "retrieved_date")
FULLTEXT_FM = ("extraction_method", "char_count", "section_count")
MIN_EXTRACT_CHARS = 1500  # sources.py: shorter extractions are rejected as "too-short"
LONG_PAPER_CHARS = 120000  # s5_fulltext.render_paper_md
ABSTRACT_NOTE = "Full text not available through open access"
LOG_FIELDS = ("access_level", "source", "extraction_method", "char_count", "section_count")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """utils.frontmatter writes JSON-encoded scalars; return (fields, body after the closing ---)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for end in range(1, len(lines)):
        if lines[end].strip() == "---":
            break
    else:
        return {}, text
    meta = {}
    for raw in lines[1:end]:
        if ":" not in raw:
            continue
        name, value = raw.split(":", 1)
        value = value.strip()
        try:
            meta[name.strip()] = json.loads(value)
        except json.JSONDecodeError:
            meta[name.strip()] = value
    return meta, "\n".join(lines[end + 1:])


class Report:
    def __init__(self):
        self.failures: list[dict] = []
        self.warnings: list[dict] = []

    def fail(self, code: str, key: str | None, detail: str) -> None:
        self.failures.append({"code": code, "key": key, "detail": detail})

    def warn(self, code: str, key: str | None, detail: str) -> None:
        self.warnings.append({"code": code, "key": key, "detail": detail})


def check_session(session: Path, min_chars: int, min_sections: int) -> dict:
    rep = Report()
    ft_dir = session / "step5_full_text"
    shortlist_path, keys_path = session / "step3_shortlist.json", session / "step4_citation_keys.json"
    for path in (shortlist_path, keys_path, ft_dir):
        if not path.exists():
            rep.fail("missing_input", None, f"{path.name} not found")
    if rep.failures:
        return finish(session, "n/a", rep, {})

    papers = {p["id"]: p for p in read_json(shortlist_path)["papers"]}
    keymap = read_json(keys_path)
    expected = {}  # key -> shortlist paper
    for pid, paper in papers.items():
        key = (keymap.get(pid) or {}).get("key")
        if key:
            expected[key] = paper
        else:
            rep.warn("no_citation_key", pid, "shortlisted paper has no Step 4 key, so Step 5 skips it")

    files = {p.stem: p for p in ft_dir.glob("*.md") if not p.name.startswith("_")}
    for key in sorted(expected.keys() - files.keys()):
        rep.fail("missing_md", key, "shortlisted paper has no step5 Markdown file")
    for key in sorted(files.keys() - expected.keys()):
        rep.fail("extra_md", key, "Markdown file does not correspond to any shortlisted paper")

    log_path = ft_dir / "_access_log.json"
    mode = "step5" if log_path.exists() else "fixed-input"
    if mode == "fixed-input":
        rep.warn("fixed_input", None, "no _access_log.json: files were not written by Step 5; access-log and access-level rules skipped")

    metas: dict[str, dict] = {}
    body_hash: dict[str, list[str]] = defaultdict(list)
    doi_owner: dict[str, list[str]] = defaultdict(list)
    for key, path in sorted(files.items()):
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        metas[key] = meta
        missing = [f for f in REQUIRED_FM if f not in meta]
        if missing:
            rep.fail("frontmatter_missing", key, f"missing fields: {', '.join(missing)}")
        if meta.get("citation_key") not in (None, key):
            rep.fail("key_mismatch", key, f"frontmatter citation_key {meta.get('citation_key')!r} != file name")
        level = meta.get("access_level")
        if level not in ACCESS_LEVELS:
            rep.fail("access_level_invalid", key, f"access_level {level!r}")
        paper = expected.get(key)
        if paper:
            if "title" in meta and meta["title"] != paper["title"]:
                rep.fail("title_mismatch", key, f"frontmatter {meta['title'][:60]!r} vs shortlist {paper['title'][:60]!r}")
            if "doi" in meta and (meta["doi"] or "") != (paper.get("doi") or ""):
                rep.fail("doi_mismatch", key, f"frontmatter {meta['doi']!r} vs shortlist {paper.get('doi')!r}")
        if meta.get("doi"):
            doi_owner[str(meta["doi"]).lower()].append(key)

        text = body.strip()
        if level == "abstract-only":
            if mode == "step5" and ABSTRACT_NOTE not in body:
                rep.fail("abstract_note_missing", key, "abstract-only file lacks the 'Full text not available' note")
            if "(no abstract available)" in body or not re.search(r"^##\s+Abstract", body, re.M):
                rep.warn("no_abstract", key, "abstract-only file has no abstract text")
        elif level in ACCESS_LEVELS:
            missing_ft = [f for f in FULLTEXT_FM if f not in meta]
            if mode == "fixed-input":
                missing_ft = [f for f in missing_ft if f != "section_count"]  # metasyn_prepare writes none
            if missing_ft:
                rep.fail("fulltext_fields_missing", key, f"{level} without {', '.join(missing_ft)}")
            chars = meta.get("char_count")
            if isinstance(chars, int):
                if mode == "step5" and chars < MIN_EXTRACT_CHARS:
                    rep.fail("fulltext_too_short", key, f"{level} with {chars} chars (< {MIN_EXTRACT_CHARS} is rejected as too-short)")
                # the file holds the extraction minus at most its own H1 line, plus our title/notes
                if len(text) + 300 < chars:
                    rep.fail("body_truncated", key, f"file body {len(text)} chars, frontmatter char_count {chars}")
                if mode == "step5" and bool(meta.get("long_paper")) != (chars > LONG_PAPER_CHARS):
                    rep.fail("long_paper_flag", key, f"long_paper={meta.get('long_paper')} with char_count {chars}")
            sections = meta.get("section_count")
            if mode == "step5" and isinstance(chars, int) and isinstance(sections, int):
                below = chars < min_chars or sections < min_sections
                if level == "full-text-html" and below:
                    rep.fail("not_downgraded", key, f"full-text-html with {chars} chars / {sections} sections (below {min_chars}/{min_sections}) should be partial-text-html")
                if level == "partial-text-html" and not below:
                    rep.fail("wrongly_partial", key, f"partial-text-html with {chars} chars / {sections} sections (not below {min_chars}/{min_sections})")
                if below and "quality check:" not in body:
                    rep.fail("quality_note_missing", key, "below-threshold extraction without the quality-check warning block")
            if level == "full-text-pdf" and mode == "step5" and not meta.get("pdf_sha256"):
                rep.fail("pdf_sha_missing", key, "full-text-pdf without pdf_sha256")
            if level != "full-text-pdf" and meta.get("pdf_sha256"):
                rep.fail("pdf_sha_unexpected", key, f"{level} with pdf_sha256")
        if text:
            # drop our own title line so two papers sharing a fetched body are detected
            core = re.sub(r"^#\s+[^\n]*\n", "", text, count=1).strip()
            body_hash[hashlib.sha256(core.encode("utf-8")).hexdigest()].append(key)

    for owners in body_hash.values():
        if len(owners) > 1:
            rep.fail("duplicate_body", ",".join(owners), "identical file body for different papers")
    for doi, owners in doi_owner.items():
        if len(owners) > 1:
            rep.fail("duplicate_doi", ",".join(owners), f"same DOI {doi}")
    shas = defaultdict(list)
    for key, meta in metas.items():
        if meta.get("pdf_sha256"):
            shas[meta["pdf_sha256"]].append(key)
    for owners in shas.values():
        if len(owners) > 1:
            rep.fail("duplicate_pdf", ",".join(owners), "same PDF (sha256) for different papers")

    if mode == "step5":
        check_access_log(ft_dir, read_json(log_path), metas, rep)

    bib = session / "step4_references.bib"
    if bib.exists():
        bib_keys = set(re.findall(r"@[A-Za-z]+\s*\{\s*([^,\s]+)\s*,", bib.read_text(encoding="utf-8")))
        for key in sorted(files.keys() - bib_keys):
            rep.fail("md_without_bib_entry", key, "Markdown file has no step4_references.bib entry")

    levels = Counter(m.get("access_level") for m in metas.values())
    n = len(metas)
    full = n - levels.get("abstract-only", 0)
    stats = {
        "papers_expected": len(expected),
        "files": n,
        "access_levels": dict(sorted(levels.items(), key=lambda kv: str(kv[0]))),
        "full_text_rate": round(full / n, 4) if n else 0.0,
        "abstract_only": sorted(k for k, m in metas.items() if m.get("access_level") == "abstract-only"),
    }
    return finish(session, mode, rep, stats)


def check_access_log(ft_dir: Path, log: dict, metas: dict[str, dict], rep: Report) -> None:
    rows = log.get("papers", [])
    by_key: dict[str, dict] = {}
    for row in rows:
        key = row.get("citation_key")
        if key in by_key:
            rep.fail("log_duplicate_row", key, "two _access_log.json rows for one key")
        by_key[key] = row
    for key in sorted(metas.keys() - by_key.keys()):
        rep.fail("log_row_missing", key, "file has no _access_log.json row")
    for key in sorted(by_key.keys() - metas.keys()):
        rep.fail("log_row_orphan", key, "_access_log.json row has no file")
    for key in sorted(metas.keys() & by_key.keys()):
        meta, row = metas[key], by_key[key]
        level = row.get("access_level")
        for name in LOG_FIELDS:
            if level == "abstract-only" and name != "access_level" and name != "source":
                continue  # abstract-only frontmatter carries no extraction fields
            if meta.get(name) != row.get(name):
                rep.fail("log_mismatch", key, f"{name}: frontmatter {meta.get(name)!r} vs log {row.get(name)!r}")
        for name in ("title", "doi"):
            if (meta.get(name) or "") != (row.get(name) or ""):
                rep.fail("log_mismatch", key, f"{name}: frontmatter vs log differ")
        if (meta.get("pdf_sha256") or None) != (row.get("pdf_sha256") or None):
            rep.fail("log_mismatch", key, "pdf_sha256: frontmatter vs log differ")
        attempts = row.get("attempts") or []
        if not attempts:
            rep.fail("no_attempts", key, "no fetch attempts recorded")
            continue
        ok = [a for a in attempts if a.get("status") == "ok"]
        if level == "abstract-only" and ok:
            rep.fail("attempt_inconsistent", key, f"abstract-only although attempt {ok[0].get('level')!r} returned ok")
        if level != "abstract-only" and attempts[-1].get("status") != "ok":
            rep.fail("attempt_inconsistent", key, f"{level} but the last attempt is {attempts[-1].get('status')!r}")
        if len(ok) > 1:
            rep.fail("attempt_inconsistent", key, "more than one ok attempt (fetching should stop at the first)")
        if row.get("quality_notes") and level != "abstract-only" and "quality check:" not in json.dumps(row["quality_notes"]):
            rep.warn("quality_note", key, f"extraction notes: {row['quality_notes']}")

    md_log = ft_dir / "_access_log.md"
    if not md_log.exists():
        rep.fail("access_log_md_missing", None, "_access_log.md not found")
        return
    text = md_log.read_text(encoding="utf-8")
    counts = Counter(r.get("access_level") for r in rows)
    for level in ACCESS_LEVELS:
        m = re.search(rf"^\|\s*{re.escape(level)}\s*\|\s*(\d+)\s*\|", text, re.M)
        if not m or int(m.group(1)) != counts.get(level, 0):
            rep.fail("access_log_md_count", level, f"_access_log.md says {m.group(1) if m else 'nothing'}, JSON has {counts.get(level, 0)}")


def finish(session: Path, mode: str, rep: Report, stats: dict) -> dict:
    return {
        "session": str(session),
        "mode": mode,
        "pass": not rep.failures,
        "n_failures": len(rep.failures),
        "n_warnings": len(rep.warnings),
        "failure_codes": dict(Counter(f["code"] for f in rep.failures)),
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
    ap.add_argument("--min-chars", type=int, default=8000, help="FulltextConfig.min_chars_full")
    ap.add_argument("--min-sections", type=int, default=4, help="FulltextConfig.min_sections_full")
    args = ap.parse_args()

    if args.batch:
        runs = [json.loads(l) for l in (args.batch / "runs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        targets = [(r["id"], args.batch / r["session_dir"]) for r in runs if (args.batch / r["session_dir"] / "step5_full_text").exists()]
    else:
        targets = [(p.name, p) for p in args.session]

    reports = {}
    for name, session in targets:
        report = check_session(session, args.min_chars, args.min_sections)
        reports[name] = report
        if args.batch:
            write(args.batch / "eval" / name / "step05" / "contract.json", report)
        status = "PASS" if report["pass"] else "FAIL"
        print(f"{status} {name} [{report['mode']}] failures={report['n_failures']} warnings={report['n_warnings']} "
              f"{report['failure_codes'] or ''}")
        for f in report["failures"][:10]:
            print(f"    - {f['code']} {f['key'] or ''}: {f['detail']}")
        if len(report["failures"]) > 10:
            print(f"    ... {len(report['failures']) - 10} more")

    summary = {
        "sessions": len(reports),
        "passed": sum(r["pass"] for r in reports.values()),
        "failure_codes": dict(sum((Counter(r["failure_codes"]) for r in reports.values()), Counter())),
        "per_session": {k: {"pass": r["pass"], "mode": r["mode"], "failure_codes": r["failure_codes"]} for k, r in reports.items()},
    }
    if args.batch:
        write(args.batch / "eval" / "step05_contract_summary.json", summary)
    elif args.output:
        write(args.output, reports if len(reports) > 1 else next(iter(reports.values())))
    print(f"\n{summary['passed']}/{summary['sessions']} sessions pass; failure codes: {summary['failure_codes'] or 'none'}")
    return 0 if summary["passed"] == summary["sessions"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
