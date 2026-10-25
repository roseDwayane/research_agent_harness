"""A6 full text - the two Units between the literature search and the fusion block (rules: references/scholar-pipeline.md §2).

  A6.d  fetch     which papers are read in full (tier1, by depth; one top-up; the questions' attack targets) and their
                  PDFs (download: paper_pdf by DOI; arxiv-pdfs: arXiv directly), every attempt recorded with its reason
                                        -> step3_tier1_candidates.json, pdfs/<key>.pdf, step5_fetch_log.json,
                                           step3_missing_pdfs.md (paper_pdf's report)
  A6.c  convert   markdown (pdf2md.sh; pdftotext when the service is down), the figure pages (figures), and the access
                  level of every shortlisted paper (fulltext-status, the command that closes the Unit)
                                        -> step5_full_text/<key>.md, step5_full_text/figure/index.json + _processed.json,
                                           step5_full_text/_access_log.md, step3_shortlist.json access_level

The two Units are a ledger block of their own (`fulltext`, between `search` and `fusion`): a topic whose full texts were
fetched before these Units existed has no fulltext events, so its fusion Units do not go stale for want of them.

  ideate_tools.py a6-check <RD> [--unit A6.d|A6.c|all] [--json]
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

from it_common import now_iso, read_json, read_jsonl, sha256_file, write_json

STANDARD_FULLTEXT_CAP = 20
CANDIDATES = "step3_tier1_candidates.json"
FETCH_LOG = "step5_fetch_log.json"
FIGURES = "step5_full_text/figure"
PROCESSED = FIGURES + "/_processed.json"
ACCESS_LEVELS = ("full-text", "full-text-plain", "pdf-only", "abstract-only")
ROUTES = ("paper_pdf", "arxiv")
# a credential in a URL or a header line (the same shapes mcp_bridge.scrub_log redacts), unless already redacted
SECRET = re.compile(r"""(?i)(?:api_?key|apikey|x-els-apikey|x-apikey|insttoken|token)=(?!REDACTED)[^&\s"']{6,}""")
SECRET_ENV = re.compile(r"KEY|TOKEN|SECRET", re.I)


def F(level, code, unit, msg):
    return {"level": level, "code": code, "unit": unit, "msg": msg}


def errors(fs):
    return [f for f in fs if f["level"] == "ERROR"]


def _j(rd: Path, name: str):
    p = Path(rd) / name
    return read_json(p) if p.exists() else None


# ===================================================================================================== shared rules
def pdf_is_complete(path: Path) -> bool:
    """A PDF starts with %PDF- and ends with an %%EOF trailer; a transfer cut short has the header but no trailer."""
    path = Path(path)
    if not path.exists() or path.stat().st_size < 1024:
        return False
    with open(path, "rb") as f:
        head = f.read(5)
        f.seek(-min(2048, path.stat().st_size), os.SEEK_END)
        return head == b"%PDF-" and b"%%EOF" in f.read()


def ranked(shortlist: dict) -> list[dict]:
    """The shortlisted papers that carry a key, best composite first (the order tier1 picks in)."""
    papers = [p for p in shortlist.get("papers") or [] if p.get("citation_key")]
    return sorted(papers, key=lambda p: -float((p.get("screening") or {}).get("composite") or 0))


def depth_picks(papers: list[dict], depth: str) -> list[dict]:
    """The candidates a depth asks for before any top-up: quick none; standard the 20 best by composite; deep every
    Tier 1 paper, and never fewer than the standard 20. `papers` is ranked()."""
    if depth == "quick":
        return []
    if depth == "standard":
        return papers[:STANDARD_FULLTEXT_CAP]
    tier1 = [p for p in papers if (p.get("screening") or {}).get("tier") == 1]
    return tier1 if len(tier1) >= STANDARD_FULLTEXT_CAP else papers[:max(len(tier1), STANDARD_FULLTEXT_CAP)]


def depth_of(rd: Path) -> str:
    return ((_j(rd, "step0_session_config.json") or {}).get("depth")) or "standard"


def fetch_log(rd: Path) -> dict:
    return _j(rd, FETCH_LOG) or {"schema": "ideate-fetch-log/1", "attempts": {}}


def record_attempts(rd: Path, route: str, results: list[dict]) -> None:
    """Append one attempt per paper - {key, status: ok | failed | skipped, reason} - to step5_fetch_log.json. The file is
    rewritten whole (temporary file, rename), never appended to."""
    if route not in ROUTES or not results:
        return
    log = fetch_log(rd)
    at = now_iso()
    for r in results:
        log["attempts"].setdefault(r["key"], []).append(
            {"route": route, "status": r["status"], "reason": str(r.get("reason") or "")[:300], "at": at})
    log["at"] = at
    write_json(Path(rd) / FETCH_LOG, log)


def access_level(rd: Path, key: str) -> str:
    """full-text (pdf2md, which leaves {key}_meta.json beside its markdown) · full-text-plain (pdftotext: tables and
    equations degraded) · pdf-only (fetched, nothing converted it) · abstract-only."""
    ft = Path(rd) / "step5_full_text"
    if (ft / f"{key}.md").exists():
        return "full-text" if (ft / f"{key}_meta.json").exists() else "full-text-plain"
    return "pdf-only" if (Path(rd) / "pdfs" / f"{key}.pdf").exists() else "abstract-only"


def known_keys(rd: Path) -> set:
    """Every key ever minted (retired ones included): a file may be named after any of them."""
    return {e["key"] for e in read_jsonl(Path(rd) / "step4_citation_keys.jsonl")} if (Path(rd) / "step4_citation_keys.jsonl").exists() else set()


def _in_hand(rd: Path, cands: list[dict]) -> list[str]:
    return [c["citation_key"] for c in cands if pdf_is_complete(Path(rd) / "pdfs" / f"{c['citation_key']}.pdf")]


def _budget(rd: Path, cf: dict) -> int:
    """What the depth asked for: the depth's own picks (a top-up replaces losses; it does not raise the budget)."""
    return sum(1 for c in cf.get("candidates") or [] if c.get("added_by", "depth") == "depth")


# ============================================================================================================ A6.d
def check_fetch(rd: Path) -> list[dict]:
    U = "A6.d"
    rd = Path(rd)
    cf = _j(rd, CANDIDATES)
    if cf is None:
        return [F("ERROR", "F01", U, f"no {CANDIDATES}: run `ideate_tools.py tier1 <RD>`")]
    cands = cf.get("candidates") or []
    sl = _j(rd, "step3_shortlist.json") or {}
    papers = ranked(sl)
    active = {p["citation_key"] for p in papers}
    fs = []
    # F01 every candidate is settled: a complete PDF, or every route that applies to it was tried
    attempts = (fetch_log(rd).get("attempts") or {})
    # what `download` tried before it wrote the fetch log - counted only until the log holds a paper_pdf attempt
    logged = any(a.get("route") == "paper_pdf" for v in attempts.values() for a in v)
    legacy = set() if logged else set(_j(rd, "_download_attempted.json") or [])
    open_ = []
    for c in cands:
        k = c["citation_key"]
        if pdf_is_complete(rd / "pdfs" / f"{k}.pdf"):
            continue
        tried = {a.get("route") for a in attempts.get(k) or []}
        need = [cmd for cmd, ok in (("download", "paper_pdf" in tried or k in legacy),
                                    ("arxiv-pdfs", not c.get("arxiv_id") or "arxiv" in tried)) if not ok]
        if need:
            open_.append(f"{k} ({', '.join(need)})")
    if open_:
        fs.append(F("ERROR", "F01", U, f"{len(open_)} candidate(s) neither fetched nor tried on every route: "
                                       f"{', '.join(open_[:6])}{' …' if len(open_) > 6 else ''}"))
    # F02 every PDF is complete (a transfer cut short reaches pdf2md as garbage)
    broken = sorted(p.name for p in (rd / "pdfs").glob("*.pdf") if not pdf_is_complete(p)) if (rd / "pdfs").is_dir() else []
    if broken:
        fs.append(F("ERROR", "F02", U, f"incomplete PDF(s) (no %PDF- header or %%EOF trailer): {broken[:6]} - "
                                       "`arxiv-pdfs` refetches them, or delete and run `download --retry-failed`"))
    # F03 the candidates follow the depth rule, on the current shortlist
    depth = depth_of(rd)
    if cf.get("depth") != depth:
        fs.append(F("ERROR", "F03", U, f"the candidates were picked for depth {cf.get('depth')!r}, the topic's depth is "
                                       f"{depth!r}: run `tier1 <RD>` again"))
    else:
        unknown = [c["citation_key"] for c in cands if c["citation_key"] not in active]
        want = {p["citation_key"] for p in depth_picks(papers, depth)}
        legacy_file = cands and not any("added_by" in c for c in cands)        # written before `added_by` existed
        have = {c["citation_key"] for c in cands if legacy_file or c.get("added_by", "depth") == "depth"}
        missing, extra = sorted(want - have), ([] if legacy_file else sorted(have - want))
        if unknown or missing or extra:
            fs.append(F("ERROR", "F03", U, "the candidates do not follow the depth rule on the current shortlist: "
                                           f"not shortlisted {unknown[:5]}, missing {missing[:5]}, not the depth's pick "
                                           f"{extra[:5]} - run `tier1 <RD>` again"))
    # F04 one top-up pass at most
    tops = sum(1 for c in cands if c.get("added_by") == "top-up")
    if int(cf.get("top_ups") or 0) > 1 or tops > STANDARD_FULLTEXT_CAP:
        fs.append(F("ERROR", "F04", U, f"{cf.get('top_ups')} top-up passes ({tops} papers): one pass is the rule - "
                                       "run `tier1 <RD>` again and top up once"))
    # F05 no credential in what A6.d writes
    secrets = [v for n, v in os.environ.items() if SECRET_ENV.search(n) and len(v) >= 12]
    leaked = []
    for name in (CANDIDATES, FETCH_LOG, "step3_missing_pdfs.md", "_mcp_paper_pdf.log"):
        p = rd / name
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace")
            if SECRET.search(text) or any(s in text for s in secrets):
                leaked.append(name)
    if leaked:
        fs.append(F("ERROR", "F05", U, f"a credential appears in {leaked}: remove it (mcp_bridge.scrub_log redacts "
                                       "credential-shaped values) and keep keys in mcp/scholar_mcp/.env only"))
    # F06 the PDFs in hand fall short of what the depth asked for (WARN; caveat fulltext-short)
    got, budget = len(_in_hand(rd, cands)), _budget(rd, cf)
    if got < budget:
        fs.append(F("WARN", "F06", U, f"{got} of the {budget} full texts the depth asks for are in hand"
                                      + ("; one `tier1 <RD> --top-up` pass is still allowed" if not cf.get("top_ups") else "")))
    return fs


# ============================================================================================================ A6.c
def check_convert(rd: Path) -> list[dict]:
    U = "A6.c"
    rd = Path(rd)
    sl = _j(rd, "step3_shortlist.json") or {}
    papers = [p for p in sl.get("papers") or [] if p.get("citation_key")]
    active = {p["citation_key"] for p in papers}
    fs = []
    # F11 every shortlisted paper carries the access level its files give
    wrong = [f"{p['citation_key']} {p.get('access_level')!r} -> {access_level(rd, p['citation_key'])!r}" for p in papers
             if p.get("access_level") != access_level(rd, p["citation_key"])]
    if wrong:
        fs.append(F("ERROR", "F11", U, f"{len(wrong)} access level(s) do not match the files: {wrong[:4]} - run "
                                       "`ideate_tools.py fulltext-status <RD>`"))
    # F12 every full text is UTF-8 with LF line ends and no NUL byte (grep misses the others silently)
    ft = rd / "step5_full_text"
    bad = []
    for f in sorted(ft.glob("*.md")) if ft.is_dir() else []:
        raw = f.read_bytes()
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            bad.append(f"{f.name} (not UTF-8)")
            continue
        crlf = b"\r\n" in raw
        if crlf or b"\x00" in raw:
            bad.append(f"{f.name} ({'CRLF' if crlf else 'NUL'})")
    if bad:
        fs.append(F("ERROR", "F12", U, f"full texts grep cannot read: {bad[:5]} - `fulltext-status` re-encodes them"))
    # F13 the figure pages: every PDF went through `figures` as it is now, and the index points at files that exist
    idx = _j(rd, FIGURES + "/index.json") or []
    done = _j(rd, PROCESSED) or {}
    keys = known_keys(rd) | active
    dangling = [e.get("file") for e in idx if not (rd / FIGURES / str(e.get("file"))).exists() or e.get("key") not in keys]
    unseen = [p.stem for p in sorted((rd / "pdfs").glob("*.pdf")) if p.stem in active and pdf_is_complete(p)
              and (done.get(p.stem) or {}).get("pdf_sha") != sha256_file(p)]
    if dangling or unseen:
        fs.append(F("ERROR", "F13", U, f"figure pages: index entries without a file or a key {dangling[:4]}, PDFs not "
                                       f"(or no longer) processed {unseen[:6]} - run `ideate_tools.py figures <RD>`"))
    # F14 every PDF and full text is named after a citation key (a file saved under another name is never read)
    names = [p for d, ext in (("pdfs", "*.pdf"), ("step5_full_text", "*.md")) if (rd / d).is_dir()
             for p in sorted((rd / d).glob(ext)) if not p.name.startswith("_")]
    misnamed = [f"{p.parent.name}/{p.name}" for p in names if p.stem not in keys]
    if misnamed:
        fs.append(F("ERROR", "F14", U, f"file(s) not named after a citation key: {misnamed[:6]} - rename to "
                                       "pdfs/<key>.pdf (the access log lists the names)"))
    lv = Counter(p.get("access_level") for p in papers)
    # F15 / F16 degraded conversions (WARN; caveats fulltext-plain, pdf-unconverted)
    if lv.get("full-text-plain"):
        fs.append(F("WARN", "F15", U, f"{lv['full-text-plain']} full text(s) came from pdftotext: tables and equations "
                                      "are degraded - re-check any number taken from them against the figure pages"))
    if lv.get("pdf-only"):
        fs.append(F("WARN", "F16", U, f"{lv['pdf-only']} PDF(s) could not be converted: those papers are read from "
                                      "their abstracts"))
    return fs


def run_checks(rd: Path, unit: str = "all") -> list[dict]:
    fs = []
    if unit in ("all", "A6.d"):
        fs += check_fetch(rd)
    if unit in ("all", "A6.c"):
        fs += check_convert(rd)
    return fs


# ========================================================================================= ledger: counts, caveats
def counts(rd: Path, unit: str) -> dict:
    rd = Path(rd)
    if unit == "A6.d":
        cf = _j(rd, CANDIDATES) or {}
        cands = cf.get("candidates") or []
        got = _in_hand(rd, cands)
        return {"candidates": len(cands), "in_hand": len(got), "missing": len(cands) - len(got),
                "budget": _budget(rd, cf), "no_doi": sum(1 for c in cands if not c.get("doi")),
                "top_ups": int(cf.get("top_ups") or 0)}
    if unit == "A6.c":
        lv = Counter(p.get("access_level") for p in (_j(rd, "step3_shortlist.json") or {}).get("papers") or []
                     if p.get("citation_key"))
        return {**{k: lv.get(k, 0) for k in ACCESS_LEVELS}, "figure_pages": len(_j(rd, FIGURES + "/index.json") or [])}
    return {}


def caveats(rd: Path) -> list[tuple[str, str, bool]]:
    """(code, text, must_disclose) for the full-text Units; the ledger names the Unit (FULLTEXT_CAVEAT_UNITS)."""
    rd = Path(rd)
    out = []
    cf = _j(rd, CANDIDATES)
    if cf:
        got, budget = len(_in_hand(rd, cf.get("candidates") or [])), _budget(rd, cf)
        if got < budget:
            out.append(("fulltext-short", f"{got} of the {budget} full texts the depth asks for were obtained "
                                          f"(top-up passes: {int(cf.get('top_ups') or 0)})", False))
    lv = Counter(p.get("access_level") for p in (_j(rd, "step3_shortlist.json") or {}).get("papers") or []
                 if p.get("citation_key"))
    if lv.get("full-text-plain"):
        out.append(("fulltext-plain", f"{lv['full-text-plain']} full text(s) came from pdftotext (tables and equations "
                                      "degraded)", False))
    if lv.get("pdf-only"):
        out.append(("pdf-unconverted", f"{lv['pdf-only']} PDF(s) could not be converted (read from the abstract)", False))
    return out


def trace(rd: Path, key: str) -> list[tuple[str, str, str]]:
    """(unit, text, where) for one paper: whether it was a candidate and why, every fetch attempt, its access level."""
    rd = Path(rd)
    out = []
    cf = _j(rd, CANDIDATES)
    if cf is not None:
        c = next((c for c in cf.get("candidates") or [] if c["citation_key"] == key), None)
        tried = [f"{a['route']} {a['status']}" + (f" ({a['reason'][:80]})" if a.get("reason") else "")
                 for a in (fetch_log(rd).get("attempts") or {}).get(key) or []]
        pdf = pdf_is_complete(rd / "pdfs" / f"{key}.pdf")
        text = (f"candidate (added by {c.get('added_by', 'depth')}) · " if c else "not a full-text candidate · ") \
            + ("PDF in hand" if pdf else "no PDF") + (f" · attempts: {'; '.join(tried)}" if tried else "")
        out.append(("A6.d", text, FETCH_LOG if tried else CANDIDATES))
    sl = {p.get("citation_key"): p for p in (_j(rd, "step3_shortlist.json") or {}).get("papers") or []}
    if sl.get(key, {}).get("access_level"):
        pages = sum(1 for e in _j(rd, FIGURES + "/index.json") or [] if e.get("key") == key)
        out.append(("A6.c", f"access level {sl[key]['access_level']} · {pages} figure page(s)", "step5_full_text/_access_log.md"))
    return out


# ======================================================================================================== commands
def cmd_a6_check(a):
    rd = Path(a.research_dir)
    fs = run_checks(rd, a.unit)
    if a.json:
        print(json.dumps(fs, indent=2, ensure_ascii=False))
    else:
        for f in fs:
            print(f"  {f['level']:<5} {f['code']} [{f['unit']}] {f['msg']}")
        print("OK" if not errors(fs) else f"{len(errors(fs))} error(s)")
    raise SystemExit(1 if errors(fs) else 0)


def add_parsers(sub) -> None:
    sp = sub.add_parser("a6-check", help="A6 full-text checks (A6.d fetch, A6.c convert)")
    sp.add_argument("research_dir")
    sp.add_argument("--unit", default="all", choices=["all", "A6.d", "A6.c"])
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_a6_check)
