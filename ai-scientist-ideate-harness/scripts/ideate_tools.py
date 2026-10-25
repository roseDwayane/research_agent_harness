#!/usr/bin/env python3
"""Command-line entry of the ai-scientist-ideate tools: the deterministic bookkeeping of the pipeline, never left to
free-form generation. The literature-search commands are registered by their Unit modules (it_*.py); the rest live here.

Literature search (references/search/; the network runs are mcp_bridge.py probe / search / merge / bibliometrics /
snowball / bibliography):
  python ideate_tools.py frame {set-protocol|set-strategy|query-revise|add-terms|set-context|eval-brief|set-evaluation|check|render} <RD> [...]
                                                                     # A1 frame        (it_frame.py)
  python ideate_tools.py search-check | relevance-set | a2-check <RD> [...]
                                                                     # A2 search       (it_search.py)
  python ideate_tools.py screen-gate | screen-plan | screen-merge | screen-amend | screen-rescue | screen-build | a3-check <RD> [...]
                                                                     # A3 screen       (it_screen.py)
  python ideate_tools.py a5-check <RD>                               # A5 snowball     (it_snowball.py)
  python ideate_tools.py export <RD> [--no-snowball REASON] | a4-check <RD>
                                                                     # A4 export       (it_export.py)
  python ideate_tools.py units {render|check}                        # Unit registry -> references/units.md (it_units.py)
  python ideate_tools.py next <RD> | status <RD> [--json]            # the ledger: next Unit, every Unit's state (it_ledger.py)
  python ideate_tools.py trace <RD> <paper_id|citation_key|query_id> # every Unit's decision about one item (it_trace.py)

Reading the collection (every later step):
  python ideate_tools.py paths         --topic ai_scientist/ideas/my_topic.md
  python ideate_tools.py list-papers   <RD> [--file raw|shortlist|snowball|excluded] [--slice 0:30] [--abstract-chars 400]
                                            [--ids a,b] [--grep "words"]

Full text and knowledge base:
  python ideate_tools.py tier1         <RD> [--depth {quick,standard,deep}] [--top-up | --targets]   # A6.d (depth: step0's)
  python ideate_tools.py arxiv-pdfs    <RD>                                # A6.d; `mcp_bridge.py download` is the other route
  python ideate_tools.py a6-check      <RD> [--unit A6.d|A6.c|all] [--json]
  python ideate_tools.py figures       <RD> [--dpi 130] [--all-pages]      # caption pages -> step5_full_text/figure/
  python ideate_tools.py fulltext-status <RD>
  python ideate_tools.py build-cards   <RD> cards.json                     # compact JSON -> Point / Plane cards
  python ideate_tools.py build-methods <RD> input.json [...]               # Pass M: method / experiment-design matrix
  python ideate_tools.py list-methods  <RD> [--family a,b] [--theme T2] [--dataset x] [--evidence full-text]
  python ideate_tools.py concept-index <RD>

Research cycle and hand-off:
  python ideate_tools.py consume       <RD> --gap GAP_001 --angle "..." --idea idea_name
  python ideate_tools.py consumed      <RD>
  python ideate_tools.py validate      <topic>.json
  python ideate_tools.py append-idea   <topic>.json <idea.json>
  python ideate_tools.py link-run      <run_dir> <topic>.json        # -> <run>/ideation_source.json
  python ideate_tools.py argument-check  <gen_dir> [--idea idea.json | --no-idea] [--json]   # coherence gate C1-C24; exit 1 on any ERROR, 2 on bad input
  python ideate_tools.py argument-render <gen_dir>                   # argument.json -> argument.md
  python ideate_tools.py env-probe     <RD> [--packages mne,specparam] [--roots ~/mne_data,/data/x] [--write] [--json]
                                                                     # what is cached and installed NOW -> local_environment.probe
  python ideate_tools.py power --mode corr|two-group|paired|estimate|equivalence [--n N] [--n1 N --n2 N] [--sd S]
                               [--sided 1|2] [--effect X] [--alpha 0.05] [--power 0.80] [--conf 0.95] [--json]
                                                                     # smallest detectable effect / equivalence margin at a fixed n

<RD> = <research_dir> = <topic>_research/ next to the topic markdown; <gen_dir> is one <research_dir>/gen_k/.
The argument-file rules (schema ai-scientist-argument/1, checks C1-C24) are in references/question-craft.md.
argument-check also reads, each only when it exists: <gen_dir>/argument_r1.json (the round-1 copy), step7b_problem.md
(its `study:` line), restatement_1.json / restatement_2.json, and <research_dir>/step0_session_config.json (the probe).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

from it_common import split_name
from it_common import write_json as atomic_json, write_text as atomic_text   # interruptible (armour condition 8)
from it_fulltext import STANDARD_FULLTEXT_CAP, depth_picks, pdf_is_complete, ranked, record_attempts

IDEA_KEYS = [
    "Name",
    "Title",
    "Short Hypothesis",
    "Related Work",
    "Abstract",
    "Experiments",
    "Risk Factors and Limitations",
]


# --------------------------------------------------------------------------- io
def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    """Write-to-temp-then-rename so a crash never leaves a truncated file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def die(msg: str, code: int = 1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def load_shortlist(rd: Path) -> dict:
    p = rd / "step3_shortlist.json"
    if not p.exists():
        die(f"{p} not found - run the screen step first")
    data = read_json(p)
    if not isinstance(data, dict) or not isinstance(data.get("papers"), list):
        die(f"{p} must be an object with a 'papers' list")
    return data


# ------------------------------------------------------------------------ paths
def cmd_paths(a):
    topic = Path(a.topic).expanduser().resolve()
    rd = topic.with_name(topic.stem + "_research")
    print(json.dumps({"topic_md": str(topic), "ideas_json": str(topic.with_suffix(".json")),
                      "research_dir": str(rd), "exists": rd.exists()}, indent=2))


# ------------------------------------------------------------------------ tier1
def arxiv_id_of(p: dict) -> str | None:
    """An arXiv paper may carry its id only inside the DataCite DOI (10.48550/arXiv.2401.01234)."""
    if p.get("arxiv_id"):
        return re.sub(r"^arxiv:", "", str(p["arxiv_id"]), flags=re.I)
    for doi in [p.get("doi")] + list(p.get("alt_dois") or []):
        m = re.search(r"10\.48550/arxiv\.(\d{4}\.\d{4,5}(?:v\d+)?)", str(doi or ""), re.I)
        if m:
            return m.group(1)
    return None


def cmd_tier1(a):
    from it_fulltext import check_fetch
    from it_ledger import degraded_codes, run_unit
    rd = Path(a.research_dir)
    with run_unit(rd, "A6.d", check=lambda: check_fetch(rd), degraded=lambda: degraded_codes(rd, "A6.d")):
        _cmd_tier1(a)


def _cmd_tier1(a):
    rd = Path(a.research_dir)
    data = load_shortlist(rd)
    papers = ranked(data)
    if not papers:
        die("no citation_key on any paper - run `export` first")
    cfg = read_json(rd / "step0_session_config.json") if (rd / "step0_session_config.json").exists() else {}
    depth = a.depth or cfg.get("depth") or "standard"
    cf = rd / "step3_tier1_candidates.json"
    prev_file = read_json(cf) if cf.exists() else None
    prev = {c["citation_key"]: c for c in (prev_file or {}).get("candidates") or []}
    top_ups = int((prev_file or {}).get("top_ups") or 0)
    added = {}                                   # key -> added_by, for the papers this run adds
    have = lambda p: pdf_is_complete(rd / "pdfs" / f"{p['citation_key']}.pdf")
    if a.top_up:
        # Second pass, after a download: keep everything already targeted, then walk further down the ranking until
        # the number of PDFs in hand plus new candidates reaches the budget. Capped so a paywalled field cannot run away.
        if depth != "standard":
            die(f"--top-up replaces paywalled papers at the standard depth; this topic's depth is {depth}")
        if prev_file is None:
            die("no step3_tier1_candidates.json yet: run `tier1 <RD>`, then download, before a top-up")
        if top_ups >= 1:
            die("one top-up pass per candidate list (A6.d, F04): run `tier1 <RD>` again to start over")
        chosen = [p for p in papers if p["citation_key"] in prev]
        need = STANDARD_FULLTEXT_CAP - sum(1 for p in chosen if have(p))
        extra = [p for p in papers if p["citation_key"] not in prev][: max(0, min(need, STANDARD_FULLTEXT_CAP))]
        chosen += extra
        top_ups += 1
        added = {p["citation_key"]: "top-up" for p in extra}
        print(f"top-up: {sum(1 for p in chosen if have(p))} PDFs in hand, adding {len(extra)} next-ranked candidate(s)")
    elif a.targets:
        # F-M4 (PLAN_ideate_planning §5): the attack targets of the questions' section 9 that rest on an abstract only,
        # added to the candidates already targeted (capped per topic); then download / arxiv-pdfs / pdf2md as usual
        import it_recon
        want = it_recon.abstract_targets(rd)[: it_recon.TARGET_FULLTEXT_CAP]
        by_key = {p["citation_key"]: p for p in papers}
        chosen = [p for p in papers if p["citation_key"] in prev]
        extra = [by_key[e["key"]] for e in want if e["key"] in by_key and e["key"] not in prev and not have(by_key[e["key"]])]
        chosen += extra
        added = {p["citation_key"]: "targets" for p in extra}
        print(f"targets: {len(want)} abstract-only attack target(s) (cap {it_recon.TARGET_FULLTEXT_CAP}); adding "
              f"{len(extra)} candidate(s): {', '.join(p['citation_key'] for p in extra) or 'none'}")
        for e in want:
            print(f"  {e['key']}{' (a first target)' if e['first'] else ''}: {', '.join(e['questions'])}")
    else:                                        # quick: none; standard: the 20 best; deep: every Tier 1 paper (>= 20)
        chosen = depth_picks(papers, depth)
        prev, top_ups = {}, 0
    # the population (or sample) slot of A1.p's protocol; `pico.population` where step0 has no protocol
    slots = {s.get("slot"): s.get("value") for s in ((cfg.get("protocol") or {}).get("framework") or {}).get("slots") or []}
    domain = slots.get("population") or slots.get("sample") or (cfg.get("pico") or {}).get("population")
    cands = [{
        "citation_key": p["citation_key"], "title": p.get("title"), "doi": p.get("doi"), "year": p.get("year"),
        "arxiv_id": arxiv_id_of(p), "domain": domain,
        # paper_pdf renders track_lvl as f"{track}/{level}"
        "track": f"T{p.get('screening', {}).get('tier', '?')}", "level": p.get("screening", {}).get("composite"),
        "group": None,
        "added_by": added.get(p["citation_key"]) or (prev.get(p["citation_key"]) or {}).get("added_by") or "depth",
    } for p in chosen]
    atomic_json(cf, {"depth": depth, "count": len(cands), "top_ups": top_ups, "candidates": cands})
    no_doi = [c["citation_key"] for c in cands if not c["doi"]]
    print(f"depth={depth}: {len(cands)} full-text candidates ({len(cands) - len(no_doi)} with DOI, "
          f"{sum(1 for c in cands if c['arxiv_id'])} with arXiv id)")
    if no_doi:
        print("  no DOI (paper_pdf cannot resolve these; `arxiv-pdfs` covers the ones with an arXiv id): " + ", ".join(no_doi))


# ------------------------------------------------------------------- arxiv-pdfs
def fetch_pdf(url: str, target: Path, before_rename=None) -> int:
    """Download to {key}.part, check it is a complete PDF, then rename. `before_rename()` runs between the two - the
    attempt is recorded before the PDF appears, so an interruption leaves neither (the rerun fetches it again)."""
    tmp = target.with_suffix(".part")
    _download_to(url, tmp)
    if not pdf_is_complete(tmp):
        tmp.unlink(missing_ok=True)
        raise ValueError("download is not a complete PDF (missing %PDF- header or %%EOF trailer)")
    size = tmp.stat().st_size
    if before_rename:
        before_rename()
    os.replace(tmp, target)
    return size


def _download_to(url: str, tmp: Path) -> None:
    """Download via curl: urllib was observed to stop silently at exactly 1 MiB on arXiv, yielding a corrupt PDF."""
    import shutil
    import subprocess
    if shutil.which("curl"):
        subprocess.run(["curl", "-sSL", "--fail", "--retry", "3", "--retry-delay", "5", "--max-time", "300",
                        "-A", "ai-scientist-ideate/1.0", "-o", str(tmp), url], check=True)
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "ai-scientist-ideate/1.0"})
        with urllib.request.urlopen(req, timeout=300) as resp, open(tmp, "wb") as out:
            while chunk := resp.read(1 << 16):
                out.write(chunk)


def cmd_arxiv_pdfs(a):
    from it_fulltext import check_fetch
    from it_ledger import degraded_codes, run_unit
    rd = Path(a.research_dir)
    with run_unit(rd, "A6.d", check=lambda: check_fetch(rd), degraded=lambda: degraded_codes(rd, "A6.d")):
        _cmd_arxiv_pdfs(a)


def _cmd_arxiv_pdfs(a):
    """paper_pdf resolves by DOI only, so arXiv-only preprints all end up in its no_doi bucket. Fetch them directly."""
    rd = Path(a.research_dir)
    cf = rd / "step3_tier1_candidates.json"
    if not cf.exists():
        die("step3_tier1_candidates.json not found - run `tier1` first")
    out = rd / "pdfs"
    out.mkdir(exist_ok=True)
    got = skipped = failed = 0
    for c in read_json(cf)["candidates"]:
        target = out / f"{c['citation_key']}.pdf"
        if target.exists() and not pdf_is_complete(target):
            print(f"  {target.name} is truncated/corrupt - refetching")
            target.unlink()
        if target.exists() or not c.get("arxiv_id"):
            skipped += 1
            continue
        aid = re.sub(r"^arxiv:", "", str(c["arxiv_id"]), flags=re.I)
        ok = {"key": c["citation_key"], "status": "ok", "reason": f"arXiv:{aid}"}
        try:                                     # every attempt, with its reason -> step5_fetch_log.json
            size = fetch_pdf(f"https://arxiv.org/pdf/{aid}", target, before_rename=lambda: record_attempts(rd, "arxiv", [ok]))
            got += 1
            print(f"  downloaded {target.name} ({size // 1024} KB)")
        except Exception as e:  # keep going: one failure must not stop the batch
            failed += 1
            record_attempts(rd, "arxiv", [{"key": c["citation_key"], "status": "failed",
                                           "reason": f"arXiv:{aid}: {type(e).__name__}: {e}"}])
            print(f"  FAILED {c['citation_key']} (arXiv:{aid}): {e}", file=sys.stderr)
        time.sleep(ARXIV_PAUSE)  # arXiv asks for ~1 request / 3 s
    print(f"arxiv-pdfs: {got} downloaded, {skipped} skipped, {failed} failed")


ARXIV_PAUSE = 3


# -------------------------------------------------------------- fulltext-status
def normalise_fulltexts(rd: Path) -> list:
    """Every full text must be UTF-8 with LF line ends and no NUL bytes. A Latin-1 / cp1252 file (some pdftotext builds, files converted
    elsewhere) makes grep print nothing without an error, so the reading-note and Pass M lookups silently miss it."""
    fixed = []
    for f in sorted((rd / "step5_full_text").glob("*.md")) if (rd / "step5_full_text").exists() else []:
        raw = f.read_bytes()
        try:
            text, changed = raw.decode("utf-8"), False
        except UnicodeDecodeError:
            try:
                text = raw.decode("cp1252")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
            changed = True
        if "\r\n" in text:
            text, changed = text.replace("\r\n", "\n"), True
        if "\x00" in text:  # NUL bytes make grep treat the file as binary ("Binary file matches") - same silent miss
            text, changed = text.replace("\x00", ""), True
        if changed:
            atomic_text(f, text)
            fixed.append(f.name)
    return fixed


# A caption starts a line: "Fig. 3", "Figure 3:", "FIG. 3", "TABLE IV", "Table 2". In-text references ("as shown in
# Fig. 3") sit mid-line and are ignored; a reference that happens to wrap to a line start only costs one extra page.
CAPTION = re.compile(r"^\s*((?:Fig\.?|Figure|FIG\.?|FIGURE|Table|TABLE)\s*(?:[0-9]+|[IVXLC]+)"
                     r"(?:\s*$|\s*[.:|\u2014\u2013-]|\s+[A-Z(]).*)$")  # "Figure 1 shows ..." (a sentence) does not match
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def _figure_index(fd: Path) -> list:
    f = fd / "index.json"
    return read_json(f) if f.exists() else []


def cmd_figures(a):
    from it_fulltext import check_convert
    from it_ledger import degraded_codes, run_unit
    rd = Path(a.research_dir)
    with run_unit(rd, "A6.c", check=lambda: check_convert(rd), degraded=lambda: degraded_codes(rd, "A6.c")):
        _cmd_figures(a)


def _cmd_figures(a):
    """Render every PDF page that carries a figure or table caption to step5_full_text/figure/{key}_p{NN}.png and
    record it in figure/index.json. Whole pages, not crops: vector plots are not embedded images (pdfimages returns
    1x1 stencils for them), and a whole page is always complete - it is what numbers are checked against. Local
    (poppler), no network; pages already rendered are skipped. Crops that pdf2md delivers land in the same folder
    as {key}_{name} and are indexed with source "pdf2md"."""
    import shutil
    import subprocess
    import tempfile
    rd = Path(a.research_dir)
    fd = rd / "step5_full_text" / "figure"
    fd.mkdir(parents=True, exist_ok=True)
    if not (shutil.which("pdftoppm") and shutil.which("pdftotext") and shutil.which("pdfinfo")):
        die("pdftoppm / pdftotext / pdfinfo not found - install poppler (brew install poppler)")
    index = {(e["key"], e["file"]): e for e in _figure_index(fd)}
    from it_common import sha256_file
    from it_fulltext import PROCESSED
    processed = read_json(rd / PROCESSED) if (rd / PROCESSED).exists() else {}   # which PDF, as it was, went through
    new = pages_seen = 0
    for pdf in sorted((rd / "pdfs").glob("*.pdf")):
        key = pdf.stem
        info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
        m = re.search(r"^Pages:\s+(\d+)", info, re.M)
        if not m:
            print(f"  figures: {key} - unreadable PDF, skipped", file=sys.stderr)
            processed[key] = {"pdf_sha": sha256_file(pdf), "pages": None, "caption_pages": 0, "unreadable": True}
            continue
        n = int(m.group(1))
        caption_pages = 0
        width = max(2, len(str(n)))
        for i in range(1, n + 1):
            text = subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), "-enc", "UTF-8", str(pdf), "-"],
                                  capture_output=True, text=True, errors="replace").stdout
            caps = [c.group(1).strip()[:140] for c in map(CAPTION.match, text.splitlines()) if c]
            caption_pages += bool(caps)
            if not caps and not a.all_pages:
                continue
            pages_seen += 1
            name = f"{key}_p{i:0{width}d}.png"
            if not (fd / name).exists():
                with tempfile.TemporaryDirectory() as tmp:
                    subprocess.run(["pdftoppm", "-f", str(i), "-l", str(i), "-r", str(a.dpi), "-png", "-singlefile",
                                    str(pdf), str(Path(tmp) / "page")], check=False)
                    out = Path(tmp) / "page.png"
                    if out.exists():
                        shutil.move(str(out), fd / name)
                        new += 1
            if (fd / name).exists():
                index[(key, name)] = {"key": key, "file": name, "page": i, "source": "page", "dpi": a.dpi,
                                      "captions": caps}
        processed[key] = {"pdf_sha": sha256_file(pdf), "pages": n, "caption_pages": caption_pages}
    # pdf2md crops: {key}_{original image name}, linked from step5_full_text/{key}.md as figure/{file}
    for img in sorted(fd.iterdir()):
        if img.suffix.lower() not in IMAGE_EXT or re.search(r"_p\d+\.png$", img.name):
            continue
        key = next((k for k in (p.stem for p in (rd / "pdfs").glob("*.pdf")) if img.name.startswith(k + "_")), None)
        if key:  # recomputed every run, so a later .md (or a fixed rule) updates the entry
            md = rd / "step5_full_text" / f"{key}.md"
            cap = ""
            if md.exists():
                lines = md.read_text(encoding="utf-8", errors="replace").splitlines()
                for j, ln in enumerate(lines):
                    if f"figure/{img.name}" in ln:
                        cap = next((l.strip()[:140] for l in lines[j + 1:j + 4] if CAPTION.match(l)), "")
                        break
            pg = re.search(r"_page_(\d+)_", img.name)  # marker counts pages from 0
            index[(key, img.name)] = {"key": key, "file": img.name, "page": int(pg.group(1)) + 1 if pg else None, "source": "pdf2md",
                                      "captions": [cap] if cap else []}
    entries = sorted(index.values(), key=lambda e: (e["key"], e["page"] or 0, e["file"]))
    entries = [e for e in entries if (fd / e["file"]).exists()]
    atomic_json(fd / "index.json", entries)
    atomic_json(rd / PROCESSED, dict(sorted(processed.items())))
    mb = sum(f.stat().st_size for f in fd.iterdir() if f.is_file()) / 1e6
    print(f"figures: {new} page image(s) rendered, {pages_seen} caption page(s) across {len({e['key'] for e in entries})} "
          f"paper(s); {len(entries)} indexed -> step5_full_text/figure/ ({mb:.0f} MB)")


def cmd_fulltext_status(a):
    from it_fulltext import check_convert
    from it_ledger import degraded_codes, run_unit
    rd = Path(a.research_dir)
    with run_unit(rd, "A6.c", check=lambda: check_convert(rd), degraded=lambda: degraded_codes(rd, "A6.c")):
        _cmd_fulltext_status(a)


def _cmd_fulltext_status(a):
    from it_fulltext import ACCESS_LEVELS, access_level
    rd = Path(a.research_dir)
    data = load_shortlist(rd)
    fixed = normalise_fulltexts(rd)
    figs = {}
    for e in _figure_index(rd / "step5_full_text" / "figure"):
        figs[e["key"]] = figs.get(e["key"], 0) + 1
    if fixed:
        print(f"fulltext-status: re-encoded {len(fixed)} full text(s) to UTF-8 / LF: {fixed[:8]}{' …' if len(fixed) > 8 else ''}")
    cf = rd / "step3_tier1_candidates.json"
    targeted = {c["citation_key"] for c in read_json(cf)["candidates"]} if cf.exists() else set()
    rows, counts = [], dict.fromkeys(ACCESS_LEVELS, 0)
    for p in data["papers"]:
        k = p.get("citation_key")
        if not k:
            continue
        md, pdf = (rd / "step5_full_text" / f"{k}.md").exists(), (rd / "pdfs" / f"{k}.pdf").exists()
        # pdf2md (marker) leaves a {key}_meta.json beside its output; a markdown file without one came from pdftotext,
        # where equations and tables are degraded - numbers read from it deserve a second look.
        level = access_level(rd, k)
        counts[level] = counts.get(level, 0) + 1
        p["access_level"] = level
        nfig = figs.get(k, 0)
        rows.append(f"| `{k}` | {'yes' if k in targeted else 'no'} | {'yes' if pdf else '-'} | {'yes' if md else '-'} | {level} | {nfig or '-'} |")
    atomic_json(rd / "step3_shortlist.json", data)
    # Some open-access publishers (MDPI among them) answer 403 to every automated client, and paywalls block the rest.
    # The pipeline does not fight that - but it says exactly which missing papers matter and where to put them.
    want = [p for p in data["papers"] if p.get("citation_key") and p.get("access_level") == "abstract-only"
            and (p.get("screening") or {}).get("tier") in (1, 2)]
    want.sort(key=lambda p: -float((p.get("screening") or {}).get("composite") or 0))
    by_hand = ""
    if want:
        by_hand = ("\n## Worth fetching by hand\n\nThese Tier 1-2 papers have no full text. Download the PDF in a browser, save it "
                   "under the name shown, then re-run `pdf2md.sh` and `fulltext-status` - every step skips what already exists, "
                   "so only the new files are processed.\n\n| Save as | Composite | Link | Title |\n|---|---|---|---|\n" +
                   "\n".join(f"| `pdfs/{p['citation_key']}.pdf` | {p['screening']['composite']} | "
                             f"{('https://doi.org/' + p['doi']) if p.get('doi') else (p.get('url') or '-')} | {str(p.get('title'))[:80]} |"
                             for p in want[:15]) + "\n")
    note = ("\n`full-text` = converted by pdf2md; `full-text-plain` = pdftotext fallback (tables/equations degraded). "
            "`pdf-only` = PDF fetched but not converted (pdf2md failed or PDF2MD_API_KEY unset). "
            "`abstract-only` papers still feed the knowledge cards, but mark fields they cannot support as `(TBD)`.\n")
    (rd / "step5_full_text").mkdir(exist_ok=True)
    atomic_text(rd / "step5_full_text" / "_access_log.md",
        "# Full-text access log\n\n" + ", ".join(f"{k}: {v}" for k, v in counts.items()) + "\n\n"
        "| Citation key | Targeted | PDF | Markdown | access_level | Figure pages |\n|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n" + note + by_hand)
    print(f"fulltext-status: {counts} -> step5_full_text/_access_log.md (access_level written back to shortlist)")
    no_fig = [p["citation_key"] for p in data["papers"] if p.get("citation_key") and
              (rd / "pdfs" / f"{p['citation_key']}.pdf").exists() and not figs.get(p["citation_key"])]
    if no_fig:
        print(f"  {len(no_fig)} paper(s) with a PDF but no figure pages - run `figures` (or they have no captions): {no_fig[:8]}")
    if want:
        print(f"  {len(want)} Tier 1-2 paper(s) have no full text - listed under 'Worth fetching by hand' in the access log")


# ---------------------------------------------------------------- concept-index
def frontmatter(text: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}
    try:
        import yaml  # type: ignore
        d = yaml.safe_load(m.group(1))
        return d if isinstance(d, dict) else {}
    except Exception:
        out = {}
        for line in m.group(1).splitlines():
            mm = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
            if mm:
                v = mm.group(2).strip()
                out[mm.group(1)] = [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()] \
                    if v.startswith("[") and v.endswith("]") else v.strip("\"'")
        return out


def cmd_concept_index(a):
    rd = Path(a.research_dir)
    kd = rd / "knowledge"
    if not kd.exists():
        die(f"{kd} not found - run to-knowledge first")
    nodes, edges, planes, bodies, dangling, chain_ends = [], [], [], [], [], []
    for f in sorted(kd.rglob("*.md")):
        text = f.read_text(encoding="utf-8")
        fm = frontmatter(text)
        t = fm.get("type")
        rel = str(f.relative_to(rd))
        if t == "point":
            nodes.append({"id": fm.get("id"), "name": fm.get("name"), "claim_type": fm.get("claim_type"),
                          "source": fm.get("source"), "year": fm.get("year"), "planes": fm.get("related_planes") or [],
                          "tags": fm.get("tags") or [], "file": rel})
            for field in ("parent", "depends_on", "caused_by", "causes", "parts"):
                v = fm.get(field)
                for tgt in ([v] if isinstance(v, str) and v else (v or [])):
                    edges.append({"from": fm.get("id"), "to": tgt, "relation": field, "card": None})
            # The Inspiration section names other Points as [[P_draft_X]]; those links are relations in their own
            # right and are the only edges a quick run (no Pass 2) can have.
            body = text.split("\n---", 2)[-1]
            m = re.search(r"^##\s*Inspiration.*?$(.*?)(?=^##\s|\Z)", body, re.S | re.M)
            rel = "inspired"
            for line in (m.group(1).splitlines() if m else []):
                # The direction is set by the nearest "Inspired by" / "Inspired" label at or above the link, so links
                # written on the label's own line and links listed on the lines beneath it both resolve correctly.
                if re.search(r"\*\*\s*inspired by", line, re.I):
                    rel = "inspired_by"
                elif re.search(r"\*\*\s*inspired\b", line, re.I):
                    rel = "inspired"
                for tgt in re.findall(r"\[\[(P_draft_[A-Za-z0-9_\-]+)\]\]", line):
                    if tgt != fm.get("id"):
                        edges.append({"from": fm.get("id"), "to": tgt, "relation": rel, "card": None})
        elif t == "line":
            ends = fm.get("endpoints") or []
            # An evolution Line is an ordered chain, so only neighbours are linked. A debate or an analogy relates every
            # endpoint to every other - linking neighbours only made the result depend on the order they were listed in.
            pairs = list(zip(ends, ends[1:])) if fm.get("relation_type") == "evolution" else \
                [(x, y) for i, x in enumerate(ends) for y in ends[i + 1:]]
            for x, y in pairs:
                edges.append({"from": x, "to": y, "relation": fm.get("relation_type"), "card": fm.get("id"), "file": rel})
            if fm.get("relation_type") == "evolution" and ends:
                chain_ends.append({"line": fm.get("id"), "last_point": ends[-1], "file": rel})
        elif t == "plane":
            planes.append({"id": fm.get("id"), "member_points": fm.get("member_points") or [],
                           "adjacent_planes": fm.get("adjacent_planes") or [], "file": rel})
        elif t == "body":
            bodies.append({"id": fm.get("id"), "body_role": fm.get("body_role"), "modules": fm.get("modules") or [], "file": rel})
    not_done = []
    for f in sorted((kd / "_notes").glob("*.md")) if (kd / "_notes").exists() else []:
        for line in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\W*(not done|future work)\s*\**\s*[:：]\s*\**\s*(.+)$", line.strip(), re.I)
            if m and m.group(2).strip() and m.group(2).strip().upper() != "(TBD)":
                not_done.append({"paper": f.stem, "kind": m.group(1).lower(), "text": m.group(2).strip()[:400]})
    assumptions, disagreements, n_notes, n_claim = _claim_lines(kd)
    ids = {n["id"] for n in nodes}
    for e in edges:
        for end in (e["from"], e["to"]):
            if end not in ids:
                dangling.append(f"{e.get('card') or e['relation']}: {end}")
    degree = {i: 0 for i in ids}
    for e in edges:
        for end in (e["from"], e["to"]):
            if end in degree:
                degree[end] += 1
    plane_of = {pt: pl["id"] for pl in planes for pt in pl["member_points"]}
    linked = {tuple(sorted((plane_of.get(e["from"]), plane_of.get(e["to"])))) for e in edges
              if plane_of.get(e["from"]) and plane_of.get(e["to"]) and plane_of.get(e["from"]) != plane_of.get(e["to"])}
    pids = sorted(p["id"] for p in planes if p["id"])
    unlinked = [[x, y] for i, x in enumerate(pids) for y in pids[i + 1:] if (x, y) not in linked]
    n_lines = sum(1 for e in edges if e.get("card"))
    reliable = n_lines > 0
    index = {
        "nodes": nodes, "edges": edges, "planes": planes, "bodies": bodies,
        # Without Line cards (a quick run) almost every Point is "isolated" and every Plane pair "unlinked" simply
        # because nothing was linked - those signals then say nothing about the field. Consumers must check this.
        "structure_reliable": reliable,
        "structure_note": ("Line cards present - structural signals are meaningful." if reliable else
                           "No Line cards (quick depth or Pass 2 skipped): isolated_points and "
                           "plane_pairs_without_any_line reflect missing analysis, NOT gaps in the field. Ignore them."),
        # The structural signals the gap step reads instead of re-reading every card:
        "signals": {
            "isolated_points": sorted(i for i, d in degree.items() if d == 0),
            "plane_pairs_without_any_line": unlinked,
            "open_debates": sorted({e["card"] for e in edges if e["relation"] == "debate" and e.get("card")}),
            # Where each evolution chain currently stops - "what is the next step, and has anyone taken it?" was the
            # most productive gap question in practice, more so than the purely structural signals above.
            "evolution_chain_ends": chain_ends,
            # What each paper read in full visibly did not test, vary or compare, and the future work it asks for -
            # read ACROSS papers: several papers not doing the same thing is a gap.
            "not_done_and_future_work": not_done,
            "claim_type_counts": {k: sum(1 for n in nodes if n["claim_type"] == k) for k in
                                  sorted({n["claim_type"] for n in nodes if n["claim_type"]})},
            "dangling_references": sorted(set(dangling)),
            # Pass M, projected: how the field runs its experiments. B2 filters the matrix itself by angle; these are
            # the cross-paper facts B3 weighs (holes are combinations nobody reported, not yet gaps).
            "methods": _methods_signals(kd),
            # The reading notes' "Assumes:" / "Disagrees with:" lines, harvested like the two above. A premise several
            # papers take for granted, or two papers that contradict each other, is a stronger gap source than an
            # absence. Notes written before these lines existed contribute nothing here - see notes_with_claim_fields.
            "assumptions": assumptions,
            "disagreements": disagreements,
            **_fusion_signals(rd),
        },
        # "n/N": notes that carry a "Claim scope:" line out of all notes. Low on a knowledge base that predates the
        # three claim lines; B3 then falls back to its earlier source order instead of trusting two near-empty lists.
        "notes_with_claim_fields": f"{n_claim}/{n_notes}",
    }
    write_json(kd / "concept_index.json", index)
    s = index["signals"]
    print(f"concept-index: {len(nodes)} points, {len(edges)} edges, {len(planes)} planes, {len(bodies)} bodies | "
          f"isolated={len(s['isolated_points'])} unlinked_plane_pairs={len(unlinked)} dangling={len(s['dangling_references'])}")
    print(f"  notes_with_claim_fields={n_claim}/{n_notes} assumptions={len(assumptions)} disagreements={len(disagreements)}")


NOTE_EMPTY = re.compile(r"\(?\s*(none|n/?a|tbd)\s*\)?\.?", re.I)
# A claim line that only says there is nothing to report, with or without trailing words ("none found in text").
def _fusion_signals(rd: Path) -> dict:
    """Fusion block (knowledge/collisions.jsonl exists): what the collisions found, by result and axis. Keys appear only
    then - an older knowledge base's index is unchanged."""
    if not (rd / "knowledge" / "collisions.jsonl").exists():
        return {}
    import it_collide
    from collections import Counter
    cur = it_collide.current(it_collide.log(rd))
    cands = read_json(rd / it_collide.CANDS) if (rd / it_collide.CANDS).exists() else {}
    pick = lambda res: [{"collision": r["collision_id"], "papers": sorted({s.get("paper") for s in r["sides"] if s.get("paper")}),
                         "axes": r.get("axes_differ") or [], "reason": r.get("reason")} for r in cur if r["result"] in res]
    judged = {r["candidate"] for r in cur}
    listed = cands.get("candidates") or []
    I = it_collide.inputs(rd)
    same = [{"collision": r["collision_id"], "datasets": it_collide.same_data(I, r)} for r in cur
            if r["result"] in ("agree", "extends") and it_collide.same_data(I, r)]
    return {"consensus": pick({"agree"}), "boundary_conditions": pick({"boundary"}),
            "same_data_relations": same,
            "premises": pick({"untested-shared", "assumption-challenged", "assumption-at-stake", "criterion-unmet"}),
            "incommensurable": pick({"incommensurable"}),
            "conflicts_by_axis": dict(Counter(a for r in cur if r["result"] == "conflict" for a in r.get("axes_differ") or [])),
            "collision_coverage": {"candidates": len(listed), "judged": sum(1 for c in listed if c["id"] in judged),
                                   "truncated": len(cands.get("truncated") or []),
                                   "by_evidence_level": dict(Counter(r.get("evidence_level") for r in cur)),
                                   "by_result": dict(Counter(r["result"] for r in cur))}}


NOTE_PLACEHOLDER = re.compile(r"\(?\s*(none|n/?a|tbd|no (conflict|disagreement|assumption)s?)\b", re.I)


def _claim_lines(kd: Path) -> tuple[list, list, int, int]:
    """(assumptions, disagreements, notes, notes with a "Claim scope:" line) from knowledge/_notes/*.md. Same line
    shape as "Not done:" (plain, bulleted or bold label). A note without the lines is skipped silently: existing
    knowledge bases are never backfilled."""
    label = lambda names: re.compile(r"^\W*(" + names + r")\s*\**\s*[:：]\s*\**\s*(.*)$", re.I)
    rx, scope = label("assumes|disagrees with"), label("claim scope")
    out = {"assumes": [], "disagrees with": []}
    n_notes = n_claim = 0
    for f in sorted((kd / "_notes").glob("*.md")) if (kd / "_notes").exists() else []:
        n_notes += 1
        has_scope = False
        for line in f.read_text(encoding="utf-8").splitlines():
            has_scope = has_scope or bool(scope.match(line.strip()))
            m = rx.match(line.strip())
            if m and m.group(2).strip() and not NOTE_PLACEHOLDER.match(m.group(2).strip()):
                out[" ".join(m.group(1).lower().split())].append({"paper": f.stem, "text": m.group(2).strip()[:400]})
        n_claim += has_scope
    return out["assumes"], out["disagrees with"], n_notes, n_claim


def _methods_signals(kd: Path) -> dict:
    f = kd / "methods_matrix.json"
    if not f.exists():
        return {"available": False, "note": "no knowledge/methods_matrix.json - Pass M not run"}
    agg = read_json(f).get("aggregates", {})
    slim = lambda xs: [{k: i[k] for k in ("item", "share", "status") if k in i} for i in xs]
    return {"available": True, "file": "knowledge/methods_matrix.md", "counts": agg.get("counts", {}),
            "conventions_full_text": {d: slim(v) for d, v in agg.get("conventions_full_text", {}).items()},
            "nr_rates_full_text": agg.get("nr_rates_full_text", {}),
            "dataset_family_empty_cells": agg.get("dataset_family_empty_cells", []),
            "affordable_here": agg.get("affordable_here", {})}


# -------------------------------------------------------------- consume / ledger
def cmd_consume(a):
    rd = Path(a.research_dir)
    p = rd / "step0_session_config.json"
    cfg = read_json(p) if p.exists() else {}
    ledger = cfg.setdefault("consumed", [])
    if a.question:
        # fusion block: the consumed unit is the question; gap and angle are read off it (keys kept for older readers)
        import it_recon
        q = it_recon.question_meta(rd, a.question)
        # the generation is the gen_k folder question-take wrote (its question.json names the question), not the ledger's
        # length: a topic copied onto the fusion block inherits entries of older generations
        took = sorted(int(f.parent.name.split("_")[1]) for f in rd.glob("gen_*/question.json")
                      if f.parent.name.split("_")[1].isdigit() and read_json(f).get("question") == a.question)
        gen_no = took[-1] if took else len(ledger) + 1
        if a.gap and a.gap != q["gap"]:
            die(f"{a.question} belongs to {q['gap']}, not {a.gap}")
        if any(e.get("question") == a.question for e in ledger):
            e0 = next(e for e in ledger if e.get("question") == a.question)
            die(f"{a.question} is already in the ledger ({'abandoned: ' + str(e0.get('reason')) if e0.get('status') == 'abandoned' else 'consumed by idea ' + repr(e0.get('idea'))})")
        if a.abandoned is not None:
            # planning P3 (PLAN_ideate_planning P-D5): the generation gives the question up - nothing is consumed, the
            # ledger records why, and question-next passes over it
            if not a.abandoned.strip():
                die("--abandoned needs the reason (the gate, the node, what no design on this machine can change)")
            ledger.append({"gap": q["gap"], "angle": q["angle"], "question": a.question, "idea": None,
                           "status": "abandoned", "reason": a.abandoned.strip(), "generation": gen_no,
                           "also_uses": []})
            write_json(p, cfg)
            print(f"abandoned += {a.question} ({q['gap']}): {a.abandoned.strip()}")
            return
        if not a.idea:
            die("consume needs --idea (or --abandoned \"<reason>\" when the generation gives the question up)")
        also = [g.strip() for g in (a.also_uses or "").split(",") if g.strip()]
        ledger.append({"gap": q["gap"], "angle": a.angle or q["angle"], "question": a.question, "idea": a.idea,
                       "generation": gen_no, "also_uses": also})
        write_json(p, cfg)
        print(f"consumed += {a.question} ({q['gap']}, {q['angle']!r}) -> {a.idea}")
        return
    if not a.idea:
        die("consume needs --idea")
    if not a.gap or not a.angle:
        die("consume needs --question (a topic on the fusion block) or both --gap and --angle")
    if (rd / "questions" / "index.json").exists():
        die("this topic is on the fusion block: consume the question the idea took (--question Q_NNN); its gap ids are "
            "the fusion block's, not a generation's")
    words = lambda s: {w for w in re.findall(r"[a-z]{4,}", s.lower())}
    for e in ledger:
        if e["gap"] != a.gap:
            continue
        x, y = words(e["angle"]), words(a.angle)
        overlap = len(x & y) / max(1, len(x | y))
        if e["angle"].strip().lower() == a.angle.strip().lower() or overlap >= 0.6:
            die(f"({a.gap}, {a.angle!r}) is too close to ({e['gap']}, {e['angle']!r}) already consumed by idea "
                f"{e.get('idea')!r} (word overlap {overlap:.0%}) - pick a genuinely different angle")
    also = [g.strip() for g in (a.also_uses or "").split(",") if g.strip()]
    ledger.append({"gap": a.gap, "angle": a.angle.strip(), "idea": a.idea, "generation": len(ledger) + 1,
                   "also_uses": also})
    write_json(p, cfg)
    print(f"consumed += ({a.gap}, {a.angle!r}) -> {a.idea}")


def cmd_consumed(a):
    p = Path(a.research_dir) / "step0_session_config.json"
    ledger = (read_json(p) if p.exists() else {}).get("consumed", [])
    print(json.dumps(ledger, indent=2, ensure_ascii=False))


# ----------------------------------------------------------- validate / append
def idea_problems(idea, where="idea") -> list[str]:
    if not isinstance(idea, dict):
        return [f"{where}: not an object"]
    out = []
    keys = [k for k in idea.keys() if k != "Code"]  # new_run.py may add "Code" later
    if keys != IDEA_KEYS:
        out.append(f"{where}: keys must be exactly {IDEA_KEYS} in this order, got {keys}")
    name = idea.get("Name", "")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)*", name):
        out.append(f"{where}: Name {name!r} must be lowercase_with_underscores (it becomes a directory name)")
    for k in ("Title", "Short Hypothesis", "Related Work", "Abstract"):
        if not isinstance(idea.get(k), str) or not idea.get(k, "").strip():
            out.append(f"{where}: {k} must be a non-empty string")
    n = len(str(idea.get("Abstract", "")).split())
    if not 150 <= n <= 350:
        out.append(f"{where}: Abstract is {n} words, expected about 250")
    for k in ("Experiments", "Risk Factors and Limitations"):
        v = idea.get(k)
        if not (isinstance(v, list) and v and all(isinstance(x, str) and x.strip() for x in v)):
            out.append(f"{where}: {k} must be a non-empty list of strings")
    return out


def cmd_validate(a):
    p = Path(a.ideas_json)
    try:
        data = read_json(p)
    except Exception as e:
        die(f"{p} does not parse ({e}); a truncated archive means an earlier crash - do not overwrite it silently")
    if not isinstance(data, list):
        die("archive must be a JSON list of idea objects")
    problems = [m for i, idea in enumerate(data) for m in idea_problems(idea, f"[{i}] {idea.get('Name', '?') if isinstance(idea, dict) else '?'}")]
    names = [i.get("Name") for i in data if isinstance(i, dict)]
    problems += [f"duplicate Name: {n}" for n in sorted({n for n in names if names.count(n) > 1})]
    print(f"{p.name}: {len(data)} idea(s)")
    for m in problems:
        print("  - " + m)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    sys.exit(0 if not problems else 2)


def cmd_append_idea(a):
    archive = Path(a.ideas_json)
    idea = read_json(Path(a.idea_json))
    idea = idea.get("idea", idea) if isinstance(idea, dict) else idea  # accept the FinalizeIdea {"idea": {...}} wrapper
    problems = idea_problems(idea, idea.get("Name", "idea") if isinstance(idea, dict) else "idea")
    data = []
    if archive.exists():
        try:
            data = read_json(archive)
        except Exception as e:
            die(f"{archive} does not parse ({e}); refusing to overwrite a possibly truncated archive")
    if any(isinstance(x, dict) and x.get("Name") == idea.get("Name") for x in data):
        problems.append(f"an idea named {idea.get('Name')!r} is already in the archive")
    if problems:
        for m in problems:
            print("  - " + m)
        die("idea rejected; fix the problems above and retry", 2)
    data.append({k: idea[k] for k in IDEA_KEYS})
    write_json(archive, data)
    print(f"appended {idea['Name']!r} -> {archive} ({len(data)} idea(s) total)")


# ------------------------------------------------------------------ list-papers
def all_candidates(rd: Path) -> list[dict]:
    """Every candidate: the search collection plus, once A5 has run, the snowball additions."""
    papers = list(read_json(rd / "step2_raw_papers.json")["papers"])
    sb = rd / "step2b_snowball_papers.json"
    if sb.exists():
        papers += read_json(sb)["papers"]
    return papers


def _authors_short(p: dict) -> str:
    au = p.get("authors") or []
    if not au:
        return "(no authors on record)"
    fam = [split_name(x)[0] for x in au[:3]]
    return ", ".join(fam) + (" et al." if len(au) > 3 else "")


def cmd_list_papers(a):
    """Print papers in slices small enough for one tool result (full abstracts of 20 papers overflow it)."""
    rd = Path(a.research_dir)
    need = {"raw": ["step2_raw_papers.json"], "shortlist": ["step3_shortlist.json"],
            "snowball": ["step2b_snowball_papers.json"],
            "excluded": ["step2_raw_papers.json", "step3_shortlist.json"]}[a.file]
    gone = [f for f in need if not (rd / f).exists()]
    if gone:
        die(f"no {', '.join(gone)} in {rd}: the search has not got that far (`ideate_tools.py next {rd}`)", 2)
    def excluded():
        inc = {p["id"] for p in load_shortlist(rd)["papers"]}
        return [p for p in all_candidates(rd) if p["id"] not in inc]
    papers = {"raw": lambda: all_candidates(rd), "shortlist": lambda: load_shortlist(rd)["papers"],
              "snowball": lambda: read_json(rd / "step2b_snowball_papers.json")["papers"], "excluded": excluded}[a.file]()
    if a.grep:  # local lookup used by ConsultKnowledge: every term must appear in title+abstract
        # Match at the start of a word, so "hot pixel" does not hit "photo ... pixel" yet "compress" still finds
        # "compression". Every term must occur somewhere in title + abstract.
        import shlex
        # --grep 'bit error "fixed huffman"'  ->  words bit, error (word-start) AND the exact phrase "fixed huffman"
        terms = [re.compile(r"\b" + re.escape(x).replace(r"\ ", r"\s+"), re.I) for x in shlex.split(a.grep)]
        papers = [p for p in papers if all(rx.search(f"{p.get('title') or ''} {p.get('abstract') or ''}") for rx in terms)]
    if a.ids:
        want = {x.strip() for x in a.ids.split(",")}
        chosen = [p for p in papers if p.get("id") in want or p.get("citation_key") in want]
        limit = a.abstract_chars if a.abstract_chars != 400 else 10 ** 6  # full abstracts unless a cap was asked for
    else:
        lo, _, hi = a.slice.partition(":")
        chosen, limit = papers[int(lo or 0): int(hi) if hi else None], a.abstract_chars
    print(f"# {len(chosen)} of {len(papers)} papers ({a.file})")
    if a.abstract_chars == 0 and not a.ids:  # titles-only triage: one line per paper, hundreds fit in one result
        for p in chosen:
            f_ = "".join(c for c, on in (("S", p.get("found_via") == "snowball"), ("!", p.get("anchor_match") is False),
                                         ("-", not str(p.get("abstract") or "").strip())) if on)
            print(f"{p.get('citation_key') or p.get('id')}\t{p.get('year')}\t{f_ or '.'}\t{str(p.get('title'))[:120]}")
        print("# flags: S = snowball addition, ! = no anchor term, - = no abstract")
        return
    for p in chosen:
        snow = "SNOWBALL" + (":" + "+".join(p["snowball_direction"]) if p.get("snowball_direction") else "")
        flags = [f for f, on in ((snow, p.get("found_via") == "snowball"),
                                 ("NO-ANCHOR", p.get("anchor_match") is False),
                                 ("NO-ABSTRACT", not str(p.get("abstract") or "").strip())) if on]
        ab = str(p.get("abstract") or "").strip().replace("\n", " ")
        ab = ab if len(ab) <= limit else ab[:limit].rsplit(" ", 1)[0] + " ..."
        sc = p.get("screening") or {}
        score = f" | composite={sc.get('composite')} tier={sc.get('tier')}" if sc else ""
        ident = f"{p.get('citation_key')} / {p.get('id')}" if p.get("citation_key") else p.get("id")
        print(f"\n[{ident}] ({p.get('year')}) {p.get('title')}{score}"
              f"\n   {_authors_short(p)} | {p.get('journal') or '-'} | cites={p.get('citation_count')} | via={p.get('found_via')}"
              f" | src={','.join(p.get('sources_found_in') or [])}" + (f" | {' '.join(flags)}" if flags else "")
              + (f"\n   {ab}" if ab else ""))


# ------------------------------------------------------------------ build-cards
TBD = "(TBD)"


def _v(d: dict, k: str) -> str:
    v = d.get(k)
    return str(v).strip() if v not in (None, "", []) else TBD


def _q(s) -> str:
    """A double-quoted YAML scalar: escape backslashes and quotes, flatten newlines."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").strip() + '"'


def _yaml_list(xs) -> str:
    """A flow list; an item holding a comma, colon, hash or bracket is quoted, or it would split or break the list."""
    q = lambda s: json.dumps(s, ensure_ascii=False) if re.search(r"[,:#\[\]{}]", s) else s
    return "[" + ", ".join(q(str(x)) for x in (xs or [])) + "]"


def _fusion_fields(c: dict) -> str:
    """Fusion-block Point fields, written only when given (a card from the old flow renders exactly as before):
    origin (align | collide), concept (the alignment concept id), unit_refs (decon unit ids), collisions."""
    out = ""
    for k in ("origin", "concept"):
        if c.get(k):
            out += f"{k}: {c[k]}\n"
    for k in ("unit_refs", "collisions"):
        if c.get(k):
            out += f"{k}: {_yaml_list(c[k])}\n"
    return out


def cmd_build_cards(a):
    """Render Point and Plane cards from a compact JSON so the frontmatter stays consistent and the six Point fields /
    five Plane questions are always present. Content the agent leaves out becomes (TBD) - never invented text.

    {"points": [{"slug","name","description","claim_type","source","year","plane","also_in":[keys],"tags":[],
                 "domain":[],"field":[],"purpose","core_claim","expanded","method","findings",
                 "parent","parts":[],"depends_on":[],"caused_by":[],"causes":[],"related_lines":[],   <- Pass 2 patches go here
                 "inspired_by":[{"id","how"}],"inspired":[{"id","how"}],"source_files":[]}],
     "methodology": {"<citation_key>": "experimental|computational|review|observational|engineering|theoretical"},
     "bridges": {"<citation_key>": "T3"},
     "planes": [{"n","slug","name","member_points":[],"member_papers":[],"adjacent_planes":[],
                 "q1","q2","q3","q4","q5","judgement","relations","source_files":[]}]}
    """
    import datetime
    rd = Path(a.research_dir)
    spec = read_json(Path(a.cards_json))
    today = datetime.date.today().isoformat()
    kd = rd / "knowledge"
    for sub in ("points", "lines", "planes", "body"):
        (kd / sub).mkdir(parents=True, exist_ok=True)
    n_pt = n_pl = n_tbd = 0
    for c in spec.get("points", []):
        pid = "P_draft_" + re.sub(r"[^A-Za-z0-9_]+", "_", c["slug"]).strip("_")
        links = lambda xs: "\n".join(f"  - [[{x['id']}]] — {x.get('how') or TBD}" for x in xs) if xs else f"  - {TBD}"
        body = f"""---
id: {pid}
type: point
name: {_q(c.get('name', c['slug']))}
description: {_q(_v(c, 'description'))}
tags: {_yaml_list(c.get('tags'))}
domain: {_yaml_list(c.get('domain'))}
field: {_yaml_list(c.get('field'))}
status: draft
created: {today}
parent: {c.get('parent') or ''}
parts: {_yaml_list(c.get('parts'))}
depends_on: {_yaml_list(c.get('depends_on'))}
caused_by: {_yaml_list(c.get('caused_by'))}
causes: {_yaml_list(c.get('causes'))}
related_lines: {_yaml_list(c.get('related_lines'))}
related_planes: {_yaml_list([c['plane']] if c.get('plane') else [])}
source: {_q(c.get('source', ''))}
year: {c.get('year') or ''}
claim_type: {c.get('claim_type', 'methodological')}
{_fusion_fields(c)}provenance:
  source_files: {_yaml_list(c.get('source_files'))}
  generated_at: {today}
---

# {c.get('name', c['slug'])}

> **Core claim (核心主張)**: {_v(c, 'core_claim')}

## Source (來源)
- citation key: `{c.get('source', '')}` ({c.get('year') or 'n.d.'})
- Also appears in: {', '.join(f'`{k}`' for k in c.get('also_in', [])) or TBD}

## Purpose (目的)
{_v(c, 'purpose')}

## Core claim, expanded (核心主張・展開)
{_v(c, 'expanded')}

## Method (方法)
{_v(c, 'method')}

## Findings (發現)
{_v(c, 'findings')}

## Inspiration (啟發)
- **Inspired by**:
{links(c.get('inspired_by'))}
- **Inspired**:
{links(c.get('inspired'))}
"""
        (kd / "points" / f"{pid}.md").write_text(body, encoding="utf-8")
        n_pt, n_tbd = n_pt + 1, n_tbd + body.count(TBD)
    for c in spec.get("planes", []):
        fid = f"F_draft_T{c['n']}_" + re.sub(r"[^A-Za-z0-9_]+", "_", c["slug"]).strip("_")
        body = f"""---
id: {fid}
type: plane
name: {_q(c.get('name', c['slug']))}
member_points: {_yaml_list(c.get('member_points'))}
member_papers: {_yaml_list(c.get('member_papers'))}
adjacent_planes: {_yaml_list(c.get('adjacent_planes'))}
status: draft
provenance:
  source_files: {_yaml_list(c.get('source_files'))}
  generated_at: {today}
---

# Theme {c['n']}: {c.get('name', c['slug'])}

## Q1 What problem does it solve? (解決什麼問題)
{_v(c, 'q1')}

## Q2 Core concepts (核心概念有哪些)
{_v(c, 'q2')}

## Q3 Relations among the concepts (概念之間關係)
{_v(c, 'q3')}

## Q4 Dominant methods (常用方法)
{_v(c, 'q4')}

## Q5 Common errors / open problems (常見錯誤)
{_v(c, 'q5')}

## Promote / demote judgement (升格／降格判斷)
{_v(c, 'judgement')}

## Relation to other Planes (與其他 Plane 的關係)
{_v(c, 'relations')}
"""
        (kd / "planes" / f"{fid}.md").write_text(body, encoding="utf-8")
        n_pl, n_tbd = n_pl + 1, n_tbd + body.count(TBD)
    # Theme table for the manifest - the paper -> theme mapping is already in the planes' member_papers.
    theme_of = {k: f"T{c['n']} {c.get('name', c['slug'])}" for c in spec.get("planes", []) for k in c.get("member_papers", [])}
    meth = spec.get("methodology") or {}
    bridge = spec.get("bridges") or {}
    keys = [p_.get("citation_key") for p_ in load_shortlist(rd)["papers"] if p_.get("citation_key")] \
        if (rd / "step3_shortlist.json").exists() else sorted(theme_of)
    rows = [f"| `{k}` | {theme_of.get(k, '**UNASSIGNED**')} | {meth.get(k, TBD)} | {bridge.get(k, '-')} |" for k in keys]
    block = ("<!-- theme-table:start (generated by build-cards; edit knowledge_cards.json, not this block) -->\n"
             "| citation_key | theme | methodology | bridge to |\n|---|---|---|---|\n" + "\n".join(rows) +
             "\n<!-- theme-table:end -->")
    mf = kd / "_MANIFEST.md"
    text = mf.read_text(encoding="utf-8") if mf.exists() else "# Knowledge manifest\n\n## Paper - theme mapping\n\n"
    text = re.sub(r"<!-- theme-table:start.*?theme-table:end -->", lambda _: block, text, flags=re.S) \
        if "theme-table:start" in text else text.rstrip() + "\n\n" + block + "\n"
    if spec.get("planes"):    # fusion block: concept Points come before any theme exists - no all-UNASSIGNED table then
        mf.write_text(text, encoding="utf-8")
    unassigned = [k for k in keys if k not in theme_of] if spec.get("planes") else []
    print(f"build-cards: {n_pt} Points, {n_pl} Planes written; {n_tbd} occurrences of {TBD} (omitted fields and inline)")
    if spec.get("planes"):
        print(f"  theme table -> knowledge/_MANIFEST.md ({len(keys)} papers" +
              (f", {len(unassigned)} UNASSIGNED: {unassigned[:8]}" if unassigned else ", every shortlisted paper has a theme") + ")")
    else:
        print("  no Planes yet: the theme table is written when the Planes exist")
    print("  next: write Line cards and the Body by hand from the templates, then run `concept-index`")


# ---------------------------------------------------------------- build-methods
NR = "(NR)"
NA = "(NA)"   # read in full, does not apply to this design (no split in a non-predictive ANOVA) - not a reporting gap
METHOD_ROLES = ("proposes-method", "comparison-study", "benchmark", "dataset", "analysis", "review", "resource")
# Content fields of one experiment row, in rendering order. Lists are rendered joined; `data` is a list of objects.
M_TEXT = ("where", "role", "problem", "core_idea", "pipeline", "novel_vs_prior", "design_choices", "claim_tested",
          "split", "leakage_control", "metric_notes", "stats", "headline", "compute", "code_data", "affordable_here")
M_LIST = ("method_family", "factors", "baselines", "ablations", "metrics", "not_done")
# Fields whose (NR) share is reported - "the paper does not say" is itself evidence about a field's habits.
M_NR_FIELDS = ("design_choices", "split", "leakage_control", "baselines", "ablations", "stats", "compute", "code_data")
M_ALIAS_KINDS = ("dataset", "baseline", "metric", "split")


def _tag(v):
    """(NR) / (TBD) / (NA) when a value is, or starts with, that tag - '(NR) - no CI or test' keeps its reason and still
    counts."""
    v = v[0] if isinstance(v, list) and len(v) == 1 else v
    for t in (NR, TBD, NA):
        if isinstance(v, str) and v.strip().upper().startswith(t):
            return t
    return None


def _cell(v, n: int = 90) -> str:
    s = ("; ".join(str(x) for x in v) if isinstance(v, list) else str(v if v not in (None, "") else TBD))
    s = s.replace("|", "/").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def cmd_build_methods(a):
    """Pass M: validate + normalise the per-experiment method/design rows and render the cross-paper matrix.

    Input (one or more files - batches are concatenated, so Pass M can be written and resumed in parts):
    {"vocab": {"method_family": {"<tag>": "one-line definition"}},
     "aliases": {"dataset"|"baseline"|"metric"|"split": {"<canonical>": ["<variant>", ...]}},
     "experiments": [{"exp_id": "<key>#E1", "citation_key", "evidence": "full-text"|"abstract", "where",
                      "role", "problem", "method_family": [], "core_idea", "pipeline", "novel_vs_prior", "design_choices",
                      "claim_tested", "factors": [], "data": [{"name","n","modality","preproc"}], "split",
                      "leakage_control", "baselines": [], "ablations": [], "metrics": [primary first], "metric_notes",
                      "stats", "headline", "compute", "code_data", "affordable_here", "not_done": []}]}
    Omitted fields become (TBD). (NR) = read in full, the paper does not report it - only valid on full-text rows; a
    short reason may follow the tag ("(NR) - point estimates only"). "not_shared_datasets": [canonical names] marks
    placeholders such as "own recordings" so they are not counted as a benchmark the field shares.
    """
    import datetime
    from collections import Counter, defaultdict
    rd = Path(a.research_dir)
    kd = rd / "knowledge"
    vocab, aliases, rows, not_shared, affordable = {}, {k: {} for k in M_ALIAS_KINDS}, [], set(), {}
    for f in a.input_json:
        spec = read_json(Path(f))
        vocab.update((spec.get("vocab") or {}).get("method_family") or {})
        for kind, amap in (spec.get("aliases") or {}).items():
            aliases.setdefault(kind, {}).update(amap or {})
        rows += spec.get("experiments") or []
        not_shared |= set(spec.get("not_shared_datasets") or [])
        affordable.update(spec.get("affordable") or {})   # fusion block: the lens's verdict per method family
    shortlist = load_shortlist(rd)["papers"]
    paper = {p["citation_key"]: p for p in shortlist if p.get("citation_key")}
    cards = read_json(rd / "knowledge_cards.json") if (rd / "knowledge_cards.json").exists() else {}
    theme_of = {k: f"T{pl['n']}" for pl in cards.get("planes", []) for k in pl.get("member_papers", [])}
    theme_name = {f"T{pl['n']}": pl.get("name", pl.get("slug")) for pl in cards.get("planes", [])}
    lookup = {kind: {v.strip().lower(): canon for canon, vs in amap.items() for v in [canon, *vs]}
              for kind, amap in aliases.items()}
    canon = lambda kind, s: lookup.get(kind, {}).get(str(s).strip().lower(), str(s).strip())

    errors, warns, seen, per_paper = [], [], set(), Counter()
    out = []
    for r in rows:
        eid, key = r.get("exp_id", ""), r.get("citation_key", "")
        m = re.fullmatch(r"(.+)#E(\d+)", eid)
        if not m or m.group(1) != key:
            errors.append(f"{eid or '?'}: exp_id must be '<citation_key>#E<n>' matching citation_key '{key}'")
            continue
        if eid in seen:
            errors.append(f"{eid}: duplicate exp_id")
            continue
        seen.add(eid)
        if key not in paper:
            errors.append(f"{eid}: '{key}' is not in step3_shortlist.json")
            continue
        per_paper[key] += 1
        has_ft = (rd / "step5_full_text" / f"{key}.md").exists()
        ev = r.get("evidence") or ("full-text" if has_ft else "abstract")
        if ev == "full-text" and not has_ft:
            errors.append(f"{eid}: evidence full-text but step5_full_text/{key}.md does not exist")
        if ev == "abstract" and has_ft:
            warns.append(f"{eid}: a full text exists but the row is abstract-based - read it")
        row = {"exp_id": eid, "citation_key": key, "evidence": ev, "year": paper[key].get("year"),
               "theme": r.get("theme") or theme_of.get(key, TBD)}
        for k in M_TEXT:
            row[k] = str(r[k]).strip() if r.get(k) not in (None, "") and str(r[k]).strip() else TBD
        for k in M_LIST:
            v = r.get(k)
            row[k] = ([str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else
                      ([str(v).strip()] if isinstance(v, str) and v.strip() else [])) or [TBD]
        row["data"] = [{"name": canon("dataset", d.get("name", TBD)), **{f: d.get(f) or TBD for f in ("n", "modality", "preproc")}}
                       for d in (r.get("data") or []) if isinstance(d, dict)] or [{"name": TBD, "n": TBD, "modality": TBD, "preproc": TBD}]
        row["method_family"] = list(dict.fromkeys(canon("method_family", x) if not _tag(x) else x for x in row["method_family"]))
        row["baselines"] = [canon("baseline", x) if not _tag(x) else x for x in row["baselines"]]
        if _tag(row["affordable_here"]) == TBD and affordable:
            # the weakest verdict among the row's families (fusion block: projected from lens.json, never per row)
            got = [affordable[f] for f in row["method_family"] if f in affordable]
            order = {"no": 0, "partial": 1, "yes": 2}
            if got:
                row["affordable_here"] = min(got, key=lambda v: order.get(v.split()[0].lower(), 3)) + " (lens)"
        row["metrics"] = [canon("metric", x) if not _tag(x) else x for x in row["metrics"]]
        if not _tag(row["split"]):
            row["split"] = canon("split", row["split"])
        if ev != "full-text":  # "not reported" needs the full text; from an abstract it only means "not verified"
            for k, v in list(row.items()):
                if k != "data" and _tag(v) in (NR, NA):
                    row[k] = [TBD] if isinstance(v, list) else TBD
                    warns.append(f"{eid}: {k} = {_tag(v)} on an abstract row -> (TBD)")
        if row["role"] not in METHOD_ROLES + (TBD,):
            warns.append(f"{eid}: role '{row['role']}' not in {METHOD_ROLES}")
        for t in row["method_family"]:
            if vocab and t not in vocab and t != TBD:
                warns.append(f"{eid}: method_family '{t}' is not in vocab")
        if not _tag(row["affordable_here"]) and not re.match(r"(yes|partial|no)\b", row["affordable_here"], re.I):
            warns.append(f"{eid}: affordable_here must start with yes / partial / no")
        out.append(row)
    for key, n in per_paper.items():
        ev = {r["evidence"] for r in out if r["citation_key"] == key}
        if n > 4:
            errors.append(f"{key}: {n} rows - at most 4 main experiments per paper")
        if ev == {"abstract"} and n > 1:
            errors.append(f"{key}: abstract-only papers get exactly one row, found {n}")
    if errors:
        print("build-methods: NOT written -", len(errors), "error(s):", file=sys.stderr)
        for e in errors:
            print("  -", e, file=sys.stderr)
        sys.exit(1)
    missing = [k for k in paper if k not in per_paper]

    # ---- aggregates (computed, never judged)
    ft = [r for r in out if r["evidence"] == "full-text"]
    n_ft = len(ft)
    real = lambda xs: [x for x in xs if not _tag(x)]

    def freq(rs, get):
        c, papers = Counter(), defaultdict(set)
        for r in rs:
            for x in set(real(get(r))):
                c[x] += 1
                papers[x].add(r["citation_key"])
        return [{"item": x, "experiments": n, "papers": sorted(papers[x])} for x, n in c.most_common()]

    dims = {"dataset": lambda r: [d["name"] for d in r["data"]], "split": lambda r: [r["split"]],
            "baseline": lambda r: r["baselines"], "metric": lambda r: r["metrics"],
            "primary_metric": lambda r: r["metrics"][:1], "method_family": lambda r: r["method_family"]}
    aggregates = {"counts": {"experiments": len(out), "papers": len(per_paper), "full_text_experiments": n_ft,
                             "abstract_experiments": len(out) - n_ft, "papers_without_rows": missing,
                             "role": dict(Counter(r["role"] for r in out))},
                  "frequency": {d: freq(out, g) for d, g in dims.items()}}
    # Conventions are read off the full-text rows only: abstracts under-report designs, so they would dilute the shares.
    conv = {}
    for d in ("dataset", "split", "baseline", "primary_metric"):
        # A "convention" one paper follows is that paper's habit, not the field's.
        items = [i for i in freq(ft, dims[d]) if len(i["papers"]) >= 2
                 and not (d == "dataset" and i["item"] in not_shared)][:3]
        conv[d] = [{**i, "share": round(i["experiments"] / n_ft, 2),
                    "status": "convention" if n_ft and i["experiments"] / n_ft >= 0.5 else
                    "common" if n_ft and i["experiments"] / n_ft >= 0.25 else "minority"} for i in items]
    aggregates["conventions_full_text"] = conv
    aggregates["nr_rates_full_text"] = {f: {"NR": sum(1 for r in ft if _tag(r[f]) == NR),
                                            "TBD": sum(1 for r in ft if _tag(r[f]) == TBD),
                                            "NA": sum(1 for r in ft if _tag(r[f]) == NA), "of": n_ft}
                                        for f in M_NR_FIELDS}
    aggregates["affordable_here"] = dict(Counter((r["affordable_here"].split()[0].strip(",;:—-").lower()
                                                  if not _tag(r["affordable_here"]) else TBD) for r in out))
    # Dataset x method-family grid, restricted to datasets used by >= 2 papers: an empty cell there is a combination the
    # retrieved literature did not report. That is a structural fact for B3 to weigh, not a gap by itself.
    shared_ds = [i["item"] for i in aggregates["frequency"]["dataset"] if len(i["papers"]) >= 2 and i["item"] not in not_shared]
    fams = [i["item"] for i in aggregates["frequency"]["method_family"]]
    grid = {ds: {fm: sorted({r["citation_key"] for r in out if fm in r["method_family"]
                             and ds in [d["name"] for d in r["data"]]}) for fm in fams} for ds in shared_ds}
    aggregates["dataset_family_grid"] = grid
    aggregates["dataset_family_empty_cells"] = [[ds, fm] for ds in shared_ds for fm in fams if not grid[ds][fm]]
    aggregates["not_shared_datasets"] = sorted(not_shared)

    today = datetime.date.today().isoformat()
    write_json(kd / "methods_matrix.json", {"generated_at": today, "vocab": {"method_family": vocab}, "aliases": aliases,
                                            "not_shared_datasets": sorted(not_shared),
                                            "experiments": out, "aggregates": aggregates})

    # ---- markdown view
    L = [f"---\ntype: methods_matrix\nstatus: draft\ngenerated_at: {today}\nexperiments: {len(out)}\n"
         f"papers: {len(per_paper)}\nfull_text_experiments: {n_ft}\n---\n",
         "# Method & experiment-design matrix (方法與實驗設計矩陣)\n",
         "Generated by `ideate_tools.py build-methods` from `methods_matrix_input.json` - edit the input, not this file. "
         "`(TBD)` = not verified (abstract only / not read); `(NR)` = read in full and the paper does not report it.\n"]
    if not n_ft:
        L.append("> **WARNING: no full-text rows.** Everything below rests on abstracts; designs are under-reported, so "
                 "conventions and structural holes are not computed.\n")
    c = aggregates["counts"]
    L.append(f"{c['experiments']} experiments from {c['papers']} papers ({c['full_text_experiments']} full-text, "
             f"{c['abstract_experiments']} abstract). Roles: " + ", ".join(f"{k} {v}" for k, v in sorted(c["role"].items())) + ".")
    if missing:
        L.append(f" **{len(missing)} shortlisted paper(s) have no row:** " + ", ".join(f"`{k}`" for k in missing[:20]) +
                 (" …" if len(missing) > 20 else ""))
    L.append("\n\n## 1. Overview (總表)\n\n| exp_id | ev | T | role | family | data | split | baselines | metrics | stats | headline |\n"
             "|---|---|---|---|---|---|---|---|---|---|---|")
    order = sorted(out, key=lambda r: (r["theme"], r["evidence"] != "full-text", str(r["year"]), r["exp_id"]))
    for r in order:
        L.append(f"| `{r['exp_id']}` | {'FT' if r['evidence'] == 'full-text' else 'abs'} | {r['theme']} | {r['role']} | "
                 f"{_cell(r['method_family'], 40)} | {_cell([d['name'] for d in r['data']], 50)} | {_cell(r['split'], 30)} | "
                 f"{_cell(r['baselines'], 50)} | {_cell(r['metrics'], 40)} | {_cell(r['stats'], 40)} | {_cell(r['headline'], 80)} |")
    L.append("\n## 2. Method Development (方法發展)\n\n### Method family x theme\n")
    themes = sorted({r["theme"] for r in out})
    L.append("| method_family | definition | " + " | ".join(themes) + " | total |\n|---|---|" + "---|" * (len(themes) + 1))
    for i in aggregates["frequency"]["method_family"]:
        per = [sum(1 for r in out if r["theme"] == t and i["item"] in r["method_family"]) for t in themes]
        L.append(f"| {i['item']} | {_cell(vocab.get(i['item'], '(not in vocab)'), 60)} | " +
                 " | ".join(str(n or "") for n in per) + f" | {i['experiments']} |")
    L.append("\n" + "; ".join(f"{t} = {theme_name.get(t, t)}" for t in themes) + "\n\n### Evolution by family (by year)\n")
    for i in aggregates["frequency"]["method_family"]:
        L.append(f"**{i['item']}**\n")
        for r in sorted((r for r in out if i["item"] in r["method_family"]), key=lambda r: (str(r["year"]), r["exp_id"])):
            L.append(f"- {r['year']} `{r['exp_id']}` ({r['role']}) {_cell(r['core_idea'], 160)}"
                     + (f" — vs prior: {_cell(r['novel_vs_prior'], 120)}" if not _tag(r["novel_vs_prior"]) else ""))
        L.append("")
    L.append("## 3. Experiment Design (實驗設計)\n\n### Datasets\n\n| dataset | experiments | papers | splits used | keys |\n|---|---|---|---|---|")
    for i in aggregates["frequency"]["dataset"]:
        splits = sorted({r["split"] for r in out if i["item"] in [d["name"] for d in r["data"]] and not _tag(r["split"])})
        L.append(f"| {i['item']}{' *(not shared)*' if i['item'] in not_shared else ''} | {i['experiments']} | "
                 f"{len(i['papers'])} | {_cell(splits, 60)} | {_cell(i['papers'], 120)} |")
    for d, title in (("split", "Validation splits"), ("baseline", "Baselines"), ("metric", "Metrics (any position)"),
                     ("primary_metric", "Primary metrics")):
        items = aggregates["frequency"][d]
        many, once = [i for i in items if len(i["papers"]) >= 2], [i for i in items if len(i["papers"]) < 2]
        L.append(f"\n### {title}\n\n| item | experiments | papers |\n|---|---|---|")
        L += [f"| {i['item']} | {i['experiments']} | {_cell(i['papers'], 120)} |" for i in many]
        if once:  # the long tail is one paper's own comparison each - listed, not tabulated
            L.append(f"\nUsed by one paper only ({len(once)}): " + "; ".join(f"{i['item']} [{i['papers'][0]}]" for i in once))
    L.append("\n### Reporting habits (full-text rows only)\n\n| field | (NR) | (TBD) | (NA) | of |\n|---|---|---|---|---|")
    L += [f"| {f} | {v['NR']} | {v['TBD']} | {v.get('NA', 0)} | {v['of']} |" for f, v in aggregates["nr_rates_full_text"].items()]
    L.append("\n### Stats, compute and affordability (full-text rows)\n\n| exp_id | stats | compute | code_data | affordable_here |\n|---|---|---|---|---|")
    L += [f"| `{r['exp_id']}` | {_cell(r['stats'], 70)} | {_cell(r['compute'], 50)} | {_cell(r['code_data'], 40)} | "
          f"{_cell(r['affordable_here'], 70)} |" for r in sorted(ft, key=lambda r: r["exp_id"])]
    L.append("\naffordable_here (all rows): " + ", ".join(f"{k} {v}" for k, v in sorted(aggregates["affordable_here"].items())))
    if n_ft:
        L.append("\n## 4. Conventions (de facto protocol, full-text rows)\n\n`convention` >= 50% of full-text experiments, "
                 "`common` >= 25%.\n\n| dimension | item | share | status | papers |\n|---|---|---|---|---|")
        for d, items in conv.items():
            L += [f"| {d} | {i['item']} | {i['share']:.0%} | {i['status']} | {_cell(i['papers'], 100)} |" for i in items]
        L.append("\n## 5. Structural holes (事實，不是 gap — B3 decides)\n\n### Method family x shared dataset "
                 "(datasets used by >= 2 papers, placeholders excluded; cell = papers, · = none reported)\n")
        if shared_ds:
            L.append("| method_family | " + " | ".join(shared_ds) + " |\n|---|" + "---|" * len(shared_ds))
            L += [f"| {fm} | " + " | ".join(str(len(grid[ds][fm])) if grid[ds][fm] else "·" for ds in shared_ds) + " |" for fm in fams]
        else:
            L.append("No dataset is shared by two or more papers - the literature does not share a benchmark.")
        L.append(f"\nOnly {len(shared_ds)} of {len(aggregates['frequency']['dataset'])} named datasets are used by two or more papers.")
        L.append("\n### Not reported (full-text rows)\n")
        L += [f"- `{f}`: {v['NR']}/{v['of']} experiments do not report it" for f, v in aggregates["nr_rates_full_text"].items() if v["NR"]]
    L.append("\n## 6. Row details\n")
    for r in order:
        L.append(f"### `{r['exp_id']}` — {r['theme']} · {r['evidence']} · {r['year']}\n")
        for k in ("where", "role", "problem", "method_family", "core_idea", "pipeline", "novel_vs_prior", "design_choices",
                  "claim_tested", "factors"):
            L.append(f"- **{k}**: {_cell(r[k], 10_000)}")
        L += [f"- **data**: " + " · ".join(f"{d['name']} ({d['n']}; {d['modality']}; {d['preproc']})" for d in r["data"])]
        for k in ("split", "leakage_control", "baselines", "ablations", "metrics", "metric_notes", "stats", "headline",
                  "compute", "code_data", "affordable_here", "not_done"):
            L.append(f"- **{k}**: {_cell(r[k], 10_000)}")
        L.append("")
    (kd / "methods_matrix.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    n_tbd = sum(1 for r in out for k in M_TEXT + M_LIST if _tag(r[k]) == TBD)
    print(f"build-methods: {len(out)} experiments / {len(per_paper)} papers ({n_ft} full-text rows) -> "
          f"knowledge/methods_matrix.{{json,md}}; {n_tbd} (TBD) fields")
    if missing:
        print(f"  {len(missing)} shortlisted paper(s) without a row: {missing[:10]}{' …' if len(missing) > 10 else ''}")
    for w in warns[:40]:
        print("  warn:", w)
    if len(warns) > 40:
        print(f"  … {len(warns) - 40} more warnings")
    print("  next: fold the matrix into Plane Q4 (knowledge_cards.json) and run `concept-index`")


def cmd_list_methods(a):
    """B2's view of the matrix: the rows relevant to an angle, compact, so the SOTA review cites exp_ids instead of
    re-reading notes. Filters are ANDed; each takes comma-separated values (any of them matches)."""
    f = Path(a.research_dir) / "knowledge" / "methods_matrix.json"
    if not f.exists():
        die(f"{f} not found - run Pass M (knowledge-passes.md) first")
    rows = read_json(f)["experiments"]
    want = lambda arg: [x.strip().lower() for x in arg.split(",") if x.strip()]
    fam, th, ds, key = want(a.family), want(a.theme), want(a.dataset), want(a.ids)
    sel = [r for r in rows
           if (not fam or any(x in [m.lower() for m in r["method_family"]] for x in fam))
           and (not th or r["theme"].lower() in th)
           and (not ds or any(x in d["name"].lower() for d in r["data"] for x in ds))
           and (not key or r["citation_key"].lower() in key or r["exp_id"].lower() in key)
           and (a.evidence == "any" or r["evidence"] == a.evidence)]
    print(f"# {len(sel)} of {len(rows)} experiments")
    fields = [x.strip() for x in a.fields.split(",") if x.strip()]
    for r in sel:
        print(f"\n{r['exp_id']} [{r['evidence']} · {r['theme']} · {r['year']}] {', '.join(r['method_family'])}")
        print(f"  data: {_cell([d['name'] for d in r['data']], 160)}")
        for k in fields:
            if k in r:
                print(f"  {k}: {_cell(r[k], a.width)}")


# --------------------------------------------------------------------- link-run
def cmd_link_run(a):
    """Drop <run>/ideation_source.json so later stages can find the evidence base. new_run.py is deliberately not
    modified; this is the one line that connects a run to the literature behind its idea."""
    run = Path(a.run_dir).expanduser().resolve()
    if not (run / "idea.json").exists():
        die(f"{run}/idea.json not found - is this a run directory created by new_run.py?")
    name = (read_json(run / "idea.json") or {}).get("Name")
    topic_json = Path(a.ideas_json).expanduser().resolve()
    rd = topic_json.with_name(topic_json.stem + "_research")
    if not rd.exists():
        die(f"{rd} not found - this archive was not produced by the literature-grounded ideation")
    ledger = (read_json(rd / "step0_session_config.json") or {}).get("consumed", []) if (rd / "step0_session_config.json").exists() else []
    entry = next((e for e in ledger if e.get("idea") == name), {})
    gen = entry.get("generation")
    gen_dir = next((g for g in sorted(rd.glob("gen_*")) if (g / "idea.json").exists()
                    and ((read_json(g / "idea.json") or {}).get("idea", read_json(g / "idea.json")) or {}).get("Name") == name), None)
    pointer = {
        "idea": name, "topic_json": str(topic_json), "research_dir": str(rd),
        "generation_dir": str(gen_dir) if gen_dir else None, "generation": gen,
        "gap": entry.get("gap"), "angle": entry.get("angle"),
        "references_bib": str(rd / "step4_references.bib") if (rd / "step4_references.bib").exists() else None,
        "citation_keys": str(rd / "step4_citation_keys.md") if (rd / "step4_citation_keys.md").exists() else None,
        # a generation's own synthesis (older topics), else the topic's (fusion block: one synthesis per topic)
        "sota_review": str(gen_dir / "step6_sota_review.md") if gen_dir and (gen_dir / "step6_sota_review.md").exists()
        else (str(rd / "step6_sota_review.md") if (rd / "step6_sota_review.md").exists() else None),
        "journal_recommendations": str(gen_dir / "step8_journal_recommendations.md")
        if gen_dir and (gen_dir / "step8_journal_recommendations.md").exists() else None,
        # null for a generation made before the problem / argument files existed: downstream then takes its old path.
        "problem": str(gen_dir / "step7b_problem.md") if gen_dir and (gen_dir / "step7b_problem.md").exists() else None,
        "argument": str(gen_dir / "argument.json") if gen_dir and (gen_dir / "argument.json").exists() else None,
    }
    if entry.get("question") or (rd / "step7_gaps.json").exists():
        # fusion block only, appended so an older topic's pointer stays exactly as it was
        pointer.update(question=entry.get("question"),
                       question_file=str(rd / "questions" / f"{entry['question']}.md") if entry.get("question") else None,
                       gap_list=str(rd / "step7_gaps.json") if (rd / "step7_gaps.json").exists() else None)
    write_json(run / "ideation_source.json", pointer)
    print(f"linked {run.name} -> {rd}" + (f" ({gen_dir.name})" if gen_dir else " (generation folder not identified)"))
    for k in ("references_bib", "sota_review", "journal_recommendations"):
        print(f"  {k}: {'ok' if pointer[k] else 'missing'}")
    for k in ("problem", "argument"):
        print(f"  {k}: {'ok' if pointer[k] else 'not present (generation without it - nothing to backfill)'}")


# ------------------------------------------------- argument-check / argument-render
# gen_k/argument.json (schema ai-scientist-argument/1) is the idea's argument in checkable form: claims, the evidence
# and warrant behind each, rival explanations, and which experiment plays which role. These checks look at STRUCTURE
# only - "every claim has an experiment", never "this warrant is sound". Judgement stays with the reflection rounds.
ARG_SCHEMA = "ai-scientist-argument/1"
ARG_KINDS = ("fact", "definition", "cause", "evaluation", "action")
ARG_MODES = ("test", "estimate", "equivalence")
ARG_ROLES = ("instrument", "tests", "control", "descriptive", "release")
ARG_SUPPORT_ROLES = ("tests", "control", "descriptive")  # an instrument or a release step tests nothing
ARG_RIVALS = ("chance", "bias", "reverse-cause", "confounding", "selection", "incorporation", "leakage", "other")
ARG_BASIC_RIVALS = ("chance", "bias", "reverse-cause", "confounding")
ARG_NEGATION = ("contestable", "direction-settled", "obviously-false", "trivial")
ARG_NEGATION_PASS = ("contestable", "direction-settled")
ARG_VARIANTS = ("none", "biomarker", "cause", "equivalence", "estimate", "invariance")
ARG_GATES = ("compute", "coherence", "restatement", "none")
ARG_DOUBT_SOURCES = ("restatement-1", "restatement-2")
ARG_DOUBT_LEVELS = ("design", "wording")
ARG_DOUBT_RESPONSES = ("fixed", "not-fixed")
ARG_COVERAGE = ("whole", "part")
ARG_POWER = ("adequate", "marginal", "underpowered")
ARG_VALIDITY = ("face", "content", "construct", "predictive", "criterion")
ARG_TOP_KEYS = ("schema", "variant", "study_sentence", "question", "key_terms", "claims", "experiments")
ARG_CLAIM_KEYS = ("id", "primary", "kind", "mode", "statement", "evidence", "warrant", "outcomes", "negation",
                  "rivals", "scope")
ARG_ORDER = ["SCHEMA"] + [f"C{i}" for i in range(1, 29)]     # C25-C27: the planning block's P1; C28: its files current
# C7: a falsifier that compares with zero ("CI includes 0", "> 0", "≤ 0", "overlaps zero", "= 0", "is not positive");
# "below 0.5" and "p > 0.05" are not such comparisons.
ZERO_COMPARISON = re.compile(
    r"(?:\b(?:includes?|excludes?|contains?|above|below|under|over|exceeds?|than|from|overlaps?|cross(?:es)?|spans?|"
    r"covers?|at most|at least|equals?|reach(?:es)?)\s+|[<>≤≥=]=?\s*)(?:zero\b|0\b(?!\.\d))"
    r"|\bnot\s+(?:positive|negative)\b|\bnon-?(?:zero|positive|negative)\b", re.I)
ARG_ESTIMATE_BECAUSE = ("descriptive", "size-open", "by-construction")
ARG_DIRECTION_BASIS = ("unknown", "contested", "settled")
QUESTION_CHANGED = re.compile(r"\s*(data|budget|coherence|restatement|wording only):\s*\S", re.I)
NOT_FIXED_HOW = re.compile(r"\s*(data|budget|conflict):\s*\S", re.I)
NOT_A_REASON = re.compile(r"\bno gate\b|\bnot forced\b|\bout of scope\b|\bfuture work\b", re.I)
READER_SAYS_ALL = re.compile(r"\ball of it\b|\bthe whole (?:question|of it)\b|\bthe entire question\b", re.I)
SYNTHETIC_WORDS = re.compile(r"\b(?:inject\w*|simulat\w*|synthetic\w*|planted)\b", re.I)
# C18: a subscripted symbol (RMS_r, x_i, sigma_bg) is a formula symbol; an all-capitals token (RMS, R01) may be one.
SYMBOL_SUBSCRIPTED = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+(?![A-Za-z0-9_])")
SYMBOL_CAPITALS = re.compile(r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9]+(?![A-Za-z0-9_])")
SYMBOL_STOP = {"AUC", "ROC", "CI", "SD", "SE", "EEG", "MEG", "CV", "BCI", "ANOVA", "IQR", "MIN", "MAX", "LOG", "ICC"}
# C17: what a statistic does to a planted value, by family -> what positive_expected must then mention
STATISTIC_FAMILIES = (
    ("an absolute value", re.compile(r"\|[^|\n]{1,120}\||\babs\(|\babsolute\b|\bunsigned\b|\bmagnitude of\b", re.I),
     re.compile(r"\||\babs|absolute|unsigned|magnitude|\bsign", re.I)),
    ("a rank", re.compile(r"\brank(?:s|ed|ing)?\b(?!-)", re.I), re.compile(r"rank", re.I)),
    ("clipping or a ceiling", re.compile(r"\bclip\w*|\bceiling\w*|\bsaturat\w*", re.I),
     re.compile(r"clip|ceiling|saturat|bound", re.I)),
)
EXP_ID_IN_TEXT = re.compile(r"\bE(\d+)\b")
_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"), "-")
_QUOTES = {0x2018: "'", 0x2019: "'", 0x201A: "'", 0x201B: "'", 0x201C: '"', 0x201D: '"', 0x201E: '"', 0x201F: '"'}
CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿]")
TERM_STOP = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "vs", "with"}
WORD_STOP = TERM_STOP | {"under", "over", "into", "between", "across", "through", "using", "based", "that", "this", "their",
                         "than", "when", "where", "which", "each", "both", "does", "what"}


def exp_id_of(entry) -> str | None:
    """The experiment id an Experiments entry (or an argument.json id) starts with, normalised to "E<n>". Shapes in
    use: "E3 [tests C1] ..." (id, then role tag - the convention), "**E0 Data ...**" and "E3: ..." (older archives),
    and the bracketed "[E3 · tests C1]" (read, but not to be written: exp_plan.py of the experiment stage does not
    see an id behind a bracket). Markdown markers and brackets are dropped; the token must sit within the first 15
    characters."""
    head = re.sub(r"[*_`#>\[\](){}]", "", str(entry)[:60]).lstrip()[:15]
    m = re.search(r"(?<![A-Za-z0-9])E(\d+)(?![A-Za-z0-9])", head)
    return f"E{int(m.group(1))}" if m else None


def _filled(v) -> bool:
    """A value that says something: not missing, not blank, not the (TBD) placeholder."""
    if isinstance(v, str):
        return bool(v.strip()) and not v.strip().upper().startswith(TBD)
    return v not in (None, [], {})


def _word_in(word: str, text: str) -> bool:
    """`word` occurs in `text`. Up to 4 characters (MI, ICA, ERP, AUC): as a whole token, plural allowed - never as a
    prefix, or "MI" is found in "minimum". Longer: at the start of a word, and a long word matches on its stem so
    "reliability" finds "reliable"."""
    if len(word) <= 4:
        return re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?:s|es)?(?![a-z0-9])", text) is not None
    stem = word[:max(5, len(word) // 2)] if len(word) > 5 else word
    return re.search(r"(?<![a-z0-9])" + re.escape(stem), text) is not None


def term_in(term, text) -> bool:
    """Case-insensitive: the term on word boundaries (plural allowed), else every content word of it (stemmed).
    CJK terms: plain substring, since CJK text has no word boundaries."""
    t, x = " ".join(str(term).lower().split()), " ".join(str(text).lower().split())
    if not t:
        return False
    if CJK.search(t):
        return t in x
    if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?:s|es)?(?![a-z0-9])", x):
        return True
    words = re.findall(r"[a-z0-9]+", t)
    words = [w for w in words if len(w) >= 3 and w not in TERM_STOP] or words
    return bool(words) and all(_word_in(w, x) for w in words)


def _names(name, text) -> bool:
    """`text` names the predictor `name` (C15): EVERY content word of it, acronyms included, or a parenthesised alias
    such as "(M_cal)" as a whole token. One shared word is not enough - "calibration accuracy" is not named by a text
    that only says "calibration block"."""
    t, x = " ".join(str(name).lower().split()), " ".join(str(text).lower().split())
    for alias in (al.strip() for al in re.findall(r"\(([^)]+)\)", t)):
        if alias and re.search(r"(?<![a-z0-9_])" + re.escape(alias) + r"(?![a-z0-9_])", x):
            return True
    main = re.sub(r"\([^)]*\)", " ", t)
    cjk = re.findall(CJK.pattern + "+", main)
    words = [w for w in re.findall(r"[a-z0-9_]+", main) if w not in TERM_STOP]
    return bool(cjk or words) and all(run in x for run in cjk) and all(_word_in(w, x) for w in words)


def _yes_no(v) -> str | None:
    """"yes: reason" / "no: reason" -> "yes" / "no"; anything else -> None."""
    m = re.match(r"\s*(yes|no)\b", v, re.I) if isinstance(v, str) else None
    return m.group(1).lower() if m else None


def _not_addressed(v) -> bool:
    return not _filled(v) or re.match(r"\(?\s*not addressed\b", str(v).strip(), re.I) is not None


def _nullish(v) -> bool:
    return v is None or (isinstance(v, str) and (not v.strip() or NOTE_EMPTY.fullmatch(v.strip()) is not None
                                                 or v.strip().lower() in ("null", "not applicable", "(not applicable)")))


def _norm_text(s) -> str:
    """Text as compared across files: lower case, every dash character -> "-", curly quotes -> straight, whitespace
    collapsed. The seven fields are typed with ASCII dashes where argument.json has an em dash; that is not a rewording."""
    return " ".join(str(s or "").translate(_DASHES).translate(_QUOTES).lower().split())


def _content_words(text) -> list:
    """The words of `text` that carry content: lower case, 4 letters or more, no stop word, each once, in order.
    (Latin script only - a CJK phrase has no word boundaries to split on, so it yields nothing and is not checked.)"""
    out = []
    for w in re.findall(r"[a-z0-9]+", _norm_text(text)):
        if len(w) >= 4 and w not in WORD_STOP and w not in out:
            out.append(w)
    return out


def _numbered_items(text) -> int:
    """How many numbered items ("1. ... 2. ..." / "(1) ... (2) ...") a reader's biggest_doubt holds; a list counts its
    entries. 0 = not numbered."""
    if isinstance(text, list):
        return len([x for x in text if _filled(x)])
    found = [int(m) for m in re.findall(r"(?:^|[\s(])(\d{1,2})[.)](?=\s)", str(text or ""))]
    k = 0
    for x in found:
        if x == k + 1:
            k = x
    return k


def _exp_ids_in(text) -> set:
    """Experiment ids named in free text ("E3: ...", "see E4 and E06") -> {"E3", "E4", "E6"}."""
    return {f"E{int(n)}" for n in EXP_ID_IN_TEXT.findall(str(text or ""))}


def _primary_of(arg) -> dict:
    claims = arg.get("claims") if isinstance(arg, dict) and isinstance(arg.get("claims"), list) else []
    return next((c for c in claims if isinstance(c, dict) and c.get("primary") is True), {})


def _primary_changed(arg: dict, r1: dict) -> list[str]:
    """What differs between the primary claim now and in the round-1 copy: any of id, statement, mode, falsifier,
    comparator, baseline_predictor (whitespace collapsed; None counts as ""). [] = the reader of round 1 saw this claim."""
    a, b = _primary_of(arg), _primary_of(r1)
    flat = lambda v: " ".join(str("" if v is None else v).split())
    return [k for k in ("id", "statement", "mode", "falsifier", "comparator", "baseline_predictor")
            if flat(a.get(k)) != flat(b.get(k))]


def load_idea(path: Path) -> dict:
    """One 7-key idea file as a dict, its Experiments as a list of strings. Raises ValueError when the file is not
    usable as one, so the caller can exit 2 (bad input) instead of reporting a C3 ERROR per experiment (which would
    force a revision)."""
    idea = read_json(path)
    if isinstance(idea, dict) and isinstance(idea.get("idea"), dict):  # the FinalizeIdea {"idea": {...}} wrapper
        idea = idea["idea"]
    if not isinstance(idea, dict):
        raise ValueError("it must hold one 7-key idea object, not a list (an ideas archive) or a scalar")
    exps = idea.get("Experiments")
    if isinstance(exps, str):
        exps = [ln for ln in exps.splitlines() if ln.strip()]
    if not isinstance(exps, list) or not exps:
        raise ValueError("it has no 'Experiments' list")
    return dict(idea, Experiments=[str(e) for e in exps])


def idea_experiments(path: Path) -> list[str]:
    """The Experiments entries of one 7-key idea file (ValueError as for load_idea)."""
    return load_idea(path)["Experiments"]


def check_argument(arg: dict, idea_exps: list[str] | None, ctx: dict | None = None) -> list[dict]:
    """Findings as {"level": ERROR|WARN|NOTE, "check": "C7"|"SCHEMA", "claim": "C2"|None, "text": ...}.
    `idea_exps` is the idea's Experiments list, or None when no idea file is read (--no-idea, or none exists).
    `ctx` carries what the other files of the generation say, each None / empty when its file does not exist:
      r1            argument_r1.json, the round-1 copy (C16, C17, C19, C21, C22; C23 reads only whether it exists)
      study         the `study:` word of step7b_problem.md; None when that file is absent (C21)
      study_r1      the same word of step7b_problem_r1.md, the round-1 copy; None when absent (C21)
      restatements  {1, 2} for the restatement_<n>.json files present (C22)
      restatement_docs  {n: the reader's object} for those files (C22 reads tested_part and biggest_doubt)
      idea          the 7-key idea dict (C20 reads Title, Short Hypothesis and the Experiments entries)
      probe         True / False: step0_session_config.json has / lacks local_environment.probe; None without a config (C23)
      datasets_files  the documents in <research_dir>/datasets/ (C23: each must be named in the inventory)
      data_roots    the non-empty data roots of local_environment.probe (C23, likewise)
      planning      it_plan.context(gen_dir): gen_k/question.json, its gap, its collisions - a generation that took a
                    question from the fusion block (C25-C27, PLAN_ideate_planning §4.1); None otherwise
      planning_stale  it_plan.stale(gen_dir): decision tree / attack plan / packaging built on another argument (C28)
    ctx=None behaves as "none of these files exist"."""
    ctx = ctx or {}
    r1 = ctx.get("r1") if isinstance(ctx.get("r1"), dict) else None
    study, idea, probe = ctx.get("study"), ctx.get("idea"), ctx.get("probe")
    study_r1 = ctx.get("study_r1")
    restatements = set(ctx.get("restatements") or ())
    restatement_docs = {k: v for k, v in (ctx.get("restatement_docs") or {}).items() if isinstance(v, dict)}
    datasets_files = [str(x) for x in (ctx.get("datasets_files") or ())]
    data_roots = [str(x) for x in (ctx.get("data_roots") or ())]
    out: list[dict] = []

    def add(level, check, text, claim=None):
        f = {"level": level, "check": check, "claim": claim, "text": text}
        if f not in out:
            out.append(f)

    err = lambda check, text, claim=None: add("ERROR", check, text, claim)
    warn = lambda check, text, claim=None: add("WARN", check, text, claim)

    def enum(value, allowed, what, claim=None) -> bool:
        if value in allowed:
            return True
        err("SCHEMA", f"{what} is {value!r}; allowed: {' | '.join(allowed)}", claim)
        return False

    # ---- structure
    if arg.get("schema") != ARG_SCHEMA:
        err("SCHEMA", f"schema is {arg.get('schema')!r}, expected {ARG_SCHEMA!r}")
    for k in ARG_TOP_KEYS:
        if k not in arg:
            err("SCHEMA", f"missing required key '{k}'")
    for k in ("study_sentence", "question"):
        if k in arg and not _filled(arg[k]):
            err("SCHEMA", f"'{k}' must be a non-empty string")
    claims = arg.get("claims") if isinstance(arg.get("claims"), list) else []
    if "claims" in arg and not claims:
        err("SCHEMA", "'claims' must be a non-empty list")
    exps = arg.get("experiments") if isinstance(arg.get("experiments"), list) else []
    if "experiments" in arg and not exps:
        err("SCHEMA", "'experiments' must be a non-empty list")
    terms = arg.get("key_terms") if isinstance(arg.get("key_terms"), list) else []
    if "key_terms" in arg and not isinstance(arg["key_terms"], list):
        err("SCHEMA", "'key_terms' must be a list of strings")
    if "variant" in arg:
        enum(arg["variant"], ARG_VARIANTS, "variant")
    cov = arg.get("coverage") if isinstance(arg.get("coverage"), dict) else None
    if cov is not None:
        enum(cov.get("question"), ARG_COVERAGE, "coverage.question")
        enum(cov.get("angle"), ARG_COVERAGE, "coverage.angle")
    ext = arg.get("external_check") if isinstance(arg.get("external_check"), dict) else None
    if ext is not None:
        if not isinstance(ext.get("synthetic"), bool):
            err("SCHEMA", "external_check.synthetic must be true or false: does the primary claim's evidence come from "
                          "simulated, injected or planted signals or effects?")
        if not (isinstance(ext.get("datasets"), list) and ext["datasets"]):
            err("SCHEMA", "external_check.datasets must be a non-empty list: the independent datasets that carry the primary claim")

    good_claims, seen = [], set()
    for i, c in enumerate(claims):
        cid = c.get("id") if isinstance(c, dict) else None
        if not isinstance(c, dict) or not isinstance(cid, str) or not cid.strip():
            err("SCHEMA", f"claims[{i}] must be an object with a string 'id'")
            continue
        if cid in seen:
            err("SCHEMA", "duplicate claim id", cid)
            continue
        seen.add(cid)
        good_claims.append(c)
        for k in ARG_CLAIM_KEYS:
            if k not in c:
                err("SCHEMA", f"missing required key '{k}'", cid)
        for k, typ, name in (("primary", bool, "true or false"), ("evidence", list, "a list"), ("rivals", list, "a list"),
                             ("outcomes", dict, "an object"), ("negation", dict, "an object"), ("scope", dict, "an object")):
            if k == "negation" and c.get(k) is None and c.get("mode") == "estimate":
                continue  # an estimate asserts no direction: there is nothing to reverse
            if k in c and not isinstance(c[k], typ):
                err("SCHEMA", f"'{k}' must be {name}", cid)
        for k in ("statement", "warrant"):
            if k in c and not _filled(c[k]):
                err("SCHEMA", f"'{k}' must be a non-empty string", cid)
        if "kind" in c:
            enum(c["kind"], ARG_KINDS, "kind", cid)
        if "mode" in c:
            enum(c["mode"], ARG_MODES, "mode", cid)
        if isinstance(c.get("construction"), dict) and not isinstance(c["construction"].get("shared_terms"), list):
            err("SCHEMA", "construction.shared_terms must be a list ([] only after comparing the two formulas)", cid)
    claim_ids = {c["id"] for c in good_claims}
    evidence = lambda c: [e for e in (c.get("evidence") if isinstance(c.get("evidence"), list) else []) if isinstance(e, dict)]
    rivals = lambda c: [r for r in (c.get("rivals") if isinstance(c.get("rivals"), list) else []) if isinstance(r, dict)]

    good_exps, seen = [], set()
    for i, e in enumerate(exps):
        eid = exp_id_of(e.get("id", "")) if isinstance(e, dict) else None
        if not eid:
            err("SCHEMA", f"experiments[{i}] must be an object whose 'id' looks like E<n>")
            continue
        if eid in seen:
            err("SCHEMA", f"duplicate experiment id {eid}")
            continue
        seen.add(eid)
        cl = e.get("claims", [])
        if not isinstance(cl, list):
            err("SCHEMA", f"experiments {eid}: 'claims' must be a list of claim ids")
            cl = []
        good_exps.append({"id": eid, "role": e.get("role"), "claims": [str(x) for x in cl]})
    arg_exp_ids = {e["id"] for e in good_exps}
    idea_ids = None if idea_exps is None else {i for i in map(exp_id_of, idea_exps) if i}

    # ---- C1
    n_primary = sum(1 for c in good_claims if c.get("primary") is True)
    if good_claims and n_primary != 1:
        err("C1", f"exactly one claim must have primary: true, found {n_primary}")

    for c in good_claims:
        cid, mode = c["id"], c.get("mode")
        # ---- C2
        if mode == "test":
            if not _filled(c.get("falsifier")):
                err("C2", "mode test needs a falsifier: which result of which experiment, with its threshold, refutes the claim", cid)
            if not evidence(c):
                err("C2", "mode test needs at least one evidence entry", cid)
        elif mode == "estimate" and not _filled(c.get("precision_target")):
            err("C2", "mode estimate needs precision_target (the confidence-interval width aimed for)", cid)
        if mode in ("test", "equivalence"):  # every experiment that "tests" the claim has a result that counts against it
            testing = [e["id"] for e in good_exps if e["role"] == "tests" and cid in e["claims"]]
            named = [f"E{int(x)}" for x in EXP_ID_IN_TEXT.findall(str(c.get("falsifier") or ""))]
            deciding = next((x for x in named if x in testing), None)  # the first one the falsifier names decides
            own_rule = {exp_id_of(ev.get("experiment", "")) for ev in evidence(c) if _filled(ev.get("refuted_if"))}
            for eid in testing:
                if eid == deciding or eid in own_rule:
                    continue
                if eid in named:  # mentioned after the deciding experiment: a mention is not a rule
                    err("C2", f"{eid} has role tests for this claim and is only mentioned in the falsifier after {deciding}, "
                              f"which decides: give the evidence row of {eid} its own refuted_if (the result of {eid} that "
                              "counts against the claim, with its threshold), or change its role to descriptive", cid)
                else:
                    err("C2", f"{eid} has role tests for this claim but no decision rule: name it in the falsifier with "
                              "its threshold, give its evidence row refuted_if, or change its role to descriptive", cid)
        # ---- C3 (evidence side)
        for ev in evidence(c):
            eid = exp_id_of(ev.get("experiment", ""))
            if not eid:
                err("C3", f"evidence.experiment {ev.get('experiment')!r} is not an experiment id (E<n>)", cid)
                continue
            if eid not in arg_exp_ids:
                err("C3", f"evidence cites {eid}, which is not listed in experiments[]", cid)
            if idea_ids is not None and eid not in idea_ids:
                err("C3", f"evidence cites {eid}, which is not an entry of the idea's Experiments", cid)
        # ---- C5
        if not any(cid in e["claims"] and e["role"] in ARG_SUPPORT_ROLES for e in good_exps):
            err("C5", "orphan claim: no experiments[] entry with role tests / control / descriptive lists it", cid)
        # ---- C6 (a planning-block generation before its decision tree: the outcomes are P3's to write - a NOTE)
        o = c.get("outcomes")
        if ctx.get("planning") and not ctx.get("planning_tree"):
            if isinstance(o, dict) and not (_filled(o.get("if_supported")) and _filled(o.get("if_not"))):
                add("NOTE", "C6", "outcomes are written by the decision tree (P3, tree-render --project)", cid)
        elif isinstance(o, dict):
            a_, b_ = o.get("if_supported"), o.get("if_not")
            if not (_filled(a_) and _filled(b_)):
                err("C6", "outcomes.if_supported and outcomes.if_not must both say what is learned", cid)
            elif " ".join(str(a_).lower().split()) == " ".join(str(b_).lower().split()):
                err("C6", "outcomes.if_supported and outcomes.if_not are the same text: one of the two results teaches nothing", cid)
        # ---- C7
        ng = c.get("negation")
        if mode == "test":  # what is expected before any data, and on what ground
            ed = c.get("expected_direction") if isinstance(c.get("expected_direction"), dict) else {}
            basis = re.match(r"\s*(" + "|".join(ARG_DIRECTION_BASIS) + r")\s*:\s*\S", str(ed.get("basis") or ""), re.I)
            if not (_filled(ed.get("direction")) and basis):
                err("C7", "expected_direction is missing: before any data, which direction do you expect (direction) and "
                          "from what (basis) - 'settled: <citation, textbook physiology or physics, or the algebra of "
                          "construction>', 'contested: <who holds each side>' or 'unknown: <why nothing predicts it>'", cid)
            elif basis.group(1).lower() == "settled" and isinstance(ng, dict) and ng.get("verdict") == "contestable":
                err("C7", "expected_direction.basis is settled but negation.verdict is contestable: a direction you can "
                          "name with its basis before any data is direction-settled - set the verdict, fill "
                          "smallest_effect_of_interest and state the falsifier against it", cid)
        if mode != "estimate" and isinstance(ng, dict):  # an estimate claim asserts no direction: C7 does not read it
            if not _filled(ng.get("text")):
                err("C7", "negation.text is empty: write the opposite of the claim before judging it", cid)
            if not enum(ng.get("verdict"), ARG_NEGATION, "negation.verdict", cid):
                pass
            elif ng["verdict"] not in ARG_NEGATION_PASS:
                err("C7", f"negation.verdict is {ng['verdict']}: the opposite of the claim is not worth arguing against, "
                          "so the claim is true by definition or of no interest", cid)
            elif ng["verdict"] == "direction-settled" and mode in ("test", "equivalence"):
                if not _filled(c.get("smallest_effect_of_interest")):
                    err("C7", "negation.verdict is direction-settled: the direction is known in advance, so the falsifier "
                              "must be a magnitude - fill smallest_effect_of_interest and state the falsifier against it", cid)
                zero = ZERO_COMPARISON.search(str(c.get("falsifier") or ""))
                if zero:
                    err("C7", f"the falsifier compares with zero ({zero.group(0)!r}) although the direction is settled: "
                              "use smallest_effect_of_interest as the threshold", cid)
        # ---- C8 / C13 / rival enums
        types = set()
        how_of = lambda r: " ".join(str(r.get("how") or "").split())[:60]
        core = c.get("primary") is True or c.get("kind") == "cause"
        for r in rivals(c):
            if "type" not in r:
                err("SCHEMA", "a rivals entry has no 'type'", cid)
            elif enum(r["type"], ARG_RIVALS, "rivals.type", cid):
                types.add(r["type"])
                if _not_addressed(r.get("ruled_out_by")):
                    warn("C13", f"rival '{r['type']}'" + (f" ({how_of(r)})" if how_of(r) else "")
                                + " is (not addressed) - goes into Risk Factors and Limitations at finalize", cid)
                    # ---- C18
                    if r["type"] == "incorporation" and core:
                        err("C18", "rival 'incorporation' is (not addressed) on a primary or cause claim: the two sides "
                                   "of the contrast share a component, so part of the result is built in - add the "
                                   "experiment or control that separates them, or redefine one of the two", cid)
                elif r["type"] == "incorporation" and core:
                    by = str(r.get("ruled_out_by"))
                    if not (_exp_ids_in(by) & arg_exp_ids) and not by.strip().lower().startswith("design:"):
                        err("C18", "incorporation rival: ruled_out_by must name the experiment (E<n>) that separates the "
                                   "shared component, or start with 'design:' and say which part of the endpoint was removed", cid)
        # ---- C18 (formulas): what the two sides of the contrast share
        con = c.get("construction") if isinstance(c.get("construction"), dict) else None
        if con is not None and isinstance(con.get("shared_terms"), list):
            shared = [str(t) for t in con["shared_terms"] if str(t).strip()]
            pf, of = _norm_text(con.get("predictor_formula")), _norm_text(con.get("outcome_formula"))
            for t in shared:
                if _norm_text(t) not in pf or _norm_text(t) not in of:
                    err("C18", f"shared term {t!r} does not occur in both formulas: write the formulas with the symbols you list", cid)
            if shared and "incorporation" not in types:
                err("C18", f"the two formulas share {', '.join(shared)} but the claim lists no incorporation rival", cid)
            # the reverse direction: a symbol that is in both formulas and was left out of the list
            raw_p, raw_o = str(con.get("predictor_formula") or ""), str(con.get("outcome_formula") or "")
            listed = lambda sym: any(sym.lower() in _norm_text(t) or _norm_text(t) in sym.lower() for t in shared)
            both = lambda rx: [x for x in dict.fromkeys(rx.findall(raw_p)) if x in set(rx.findall(raw_o))]
            for sym in both(SYMBOL_SUBSCRIPTED):
                if not listed(sym):
                    err("C18", f"{sym!r} occurs in both formulas but is not in shared_terms: list it, add the incorporation "
                               "rival, and redo computable_without_experiment with it substituted", cid)
            for sym in both(SYMBOL_CAPITALS):
                if sym not in SYMBOL_STOP and not listed(sym):
                    warn("C18", f"{sym!r} occurs in both formulas and is not in shared_terms: if it is a quantity the two "
                                "sides share, list it; if it is only a label, say so in the round-2 answer to question 8", cid)
        # ---- C24: the rival a skeptical reader reaches for first
        if c.get("primary") is True and mode in ("test", "equivalence"):
            mains = [r for r in rivals(c) if r.get("main") is True]
            if len(mains) != 1:
                err("C24", "mark exactly one rival main: true - the explanation a skeptical reader would reach for first "
                           f"(found {len(mains)})", cid)
            elif _not_addressed(mains[0].get("ruled_out_by")):
                err("C24", f"the main rival ({str(mains[0].get('type'))!r}: {how_of(mains[0])}) is (not addressed): aim the "
                           "negative control or an experiment at it", cid)
        if c.get("kind") == "cause":
            missing = [t for t in ARG_BASIC_RIVALS if t not in types]
            if missing:
                err("C8", f"kind cause must list the four basic rival explanations; missing: {', '.join(missing)}", cid)
            if not any(e["role"] == "control" and cid in e["claims"] for e in good_exps):
                err("C8", "kind cause needs an experiments[] entry with role control (ablation, injection or negative "
                          "control) that lists this claim", cid)
        # ---- C9
        if mode == "equivalence":
            ctl = c.get("controls") if isinstance(c.get("controls"), dict) else {}
            if not _filled(ctl.get("positive")):
                err("C9", "mode equivalence needs controls.positive: show the pipeline detects an effect that is known to exist", cid)
            if not _filled(c.get("falsifier")):
                err("C9", "mode equivalence needs a falsifier that states the margin fixed in advance", cid)
        # ---- C17: could the evidence have come out otherwise?
        ctl = c.get("controls") if isinstance(c.get("controls"), dict) else {}
        in_scope = mode != "estimate" and core
        if in_scope and evidence(c):
            verdicts = [(exp_id_of(ev.get("experiment", "")) or "?", _yes_no(ev.get("can_fail"))) for ev in evidence(c)]
            missing = [e for e, v in verdicts if v is None]
            if missing:
                err("C17", f"evidence row(s) {', '.join(missing)}: can_fail is missing - write 'yes: ...' or 'no: ...' after "
                           "comparing where the manipulation or contrast acts with where the measure is computed", cid)
            elif all(v == "no" for _, v in verdicts):
                err("C17", "every evidence row has can_fail: no - the result is fixed by construction, so no experiment "
                           "tests this claim", cid)
        if in_scope:
            if con is None or not (_filled(con.get("predictor_formula")) and _filled(con.get("outcome_formula"))):
                err("C17", "construction is missing: write the formula (or the support: channels, band, window, labels) of "
                           "the manipulated dose or predictor and of the outcome measure, list the terms they share, and "
                           "answer whether the result could be computed from existing data without running the experiment", cid)
            else:
                cwe = " ".join(str(con.get("computable_without_experiment") or "").split())
                m = re.match(r"(no|partly|yes)\b", cwe, re.I)
                if not m:
                    err("C17", "computable_without_experiment must start with no, partly or yes: substitute the predictor "
                               "formula into the outcome formula and say what is left for the experiment to decide", cid)
                elif m.group(1).lower() == "yes":
                    err("C17", "computable_without_experiment is yes: the result follows from existing data or algebra, so "
                               "no experiment tests this claim", cid)
                elif m.group(1).lower() == "partly":
                    warn("C17", f"part of the result is computable without the experiment ({cwe[:80]}): exclude it from the "
                                "falsifier and name it in Short Hypothesis sentence 4", cid)
                if not _filled(con.get("free_quantity")):
                    err("C17", "free_quantity is empty: name the quantity the design does not fix on which the result depends", cid)
                shared_now = [str(t) for t in con.get("shared_terms") if str(t).strip()] \
                    if isinstance(con.get("shared_terms"), list) else []
                unshown = [t for t in shared_now if _norm_text(t) not in _norm_text(cwe)
                           and all(_norm_text(t) in _norm_text(con.get(k)) for k in ("predictor_formula", "outcome_formula"))]
                if unshown and m and m.group(1).lower() == "no":
                    warn("C17", f"the two formulas share {', '.join(unshown)}, yet computable_without_experiment says 'no' "
                                "without mentioning it: show the substitution - say in that field what happens to "
                                f"{', '.join(unshown)} when one formula is put into the other, and what is left for the "
                                "experiment to decide", cid)
        if in_scope and c.get("primary") is True and r1 is not None:  # a new primary claim needs its own derivation
            was = _primary_of(r1)
            what = [k for k in _primary_changed(arg, r1) if k in ("id", "statement", "mode")]
            same = lambda a_, b_: _filled(a_) and _norm_text(json.dumps(a_, sort_keys=True, ensure_ascii=False)) \
                == _norm_text(json.dumps(b_, sort_keys=True, ensure_ascii=False))
            stale = [k for k, a_, b_ in (("construction", con, was.get("construction")),
                                         ("controls.positive_expected", ctl.get("positive_expected"),
                                          (was.get("controls") or {}).get("positive_expected")
                                          if isinstance(was.get("controls"), dict) else None)) if same(a_, b_)]
            if what and stale:
                warn("C17", f"the primary claim changed since round 1 ({', '.join(what)}) but {' and '.join(stale)} did "
                            "not: redo the by-construction steps 1-6 of research-cycle section 4 for the claim as it "
                            "stands now", cid)
        if c.get("primary") is True and mode == "test" and not _filled(ctl.get("positive")):
            warn("C17", "no positive control: nothing shows the pipeline would find the effect if it were there - goes "
                        "into Risk Factors and Limitations", cid)
        if (in_scope or mode == "equivalence") and _filled(ctl.get("positive")) and _filled(ctl.get("positive_expected")):
            reads = " ".join([str(c.get("falsifier") or ""), str((con or {}).get("outcome_formula") or "")]
                             + [str(ev.get("measure") or "") for ev in evidence(c)])
            for family, in_statistic, in_expected in STATISTIC_FAMILIES:
                if in_statistic.search(reads) and not in_expected.search(str(ctl["positive_expected"])):
                    warn("C17", f"the statistic the falsifier reads takes {family}, and controls.positive_expected does not "
                                "say what that does to the planted value: derive it through the statistic (|d+k| - |d| is "
                                "k only when d >= 0) and state the condition under which the control can pass", cid)
        if in_scope and c.get("primary") is True and STATISTIC_FAMILIES[0][1].search(
                " ".join([str(c.get("falsifier") or "")] + [str(ev.get("measure") or "") for ev in evidence(c)])):
            limits = (c.get("scope") or {}).get("limits") if isinstance(c.get("scope"), dict) else None
            if not re.search(r"absolute|unsigned|\bsign", " ".join(map(str, limits if isinstance(limits, list) else [])), re.I):
                warn("C17", "the primary claim's statistic takes an absolute value: say in scope.limits why the claim is "
                            "unsigned, or keep the sign the mechanism predicts (an unsigned statistic cannot tell the "
                            "predicted direction from its opposite)", cid)
        if (in_scope or mode == "equivalence") and _filled(ctl.get("positive")) and not _filled(ctl.get("positive_expected")):
            err("C17", "controls.positive_expected is missing: push the planted effect through the statistic the falsifier "
                       "reads and write the value that comes out, with the derivation", cid)
        if (c.get("kind") == "cause" or in_scope) and _filled(ctl.get("negative")):
            v = _yes_no(ctl.get("negative_can_move"))
            if v is None:
                err("C17", "controls.negative_can_move is missing - write 'yes: ...' or 'no: ...': does the negative control "
                           "act on the data the measure is computed from?", cid)
            elif v == "no":
                err("C17", "controls.negative_can_move is no: the negative control cannot change the measure whether the "
                           "claim is right or wrong, so its null result shows nothing", cid)
        # ---- C12 / power enum
        pw = c.get("power")
        if isinstance(pw, dict) and pw.get("verdict") is not None:
            enum(pw["verdict"], ARG_POWER, "power.verdict", cid)
        if c.get("primary") is True:
            if isinstance(pw, dict) and pw.get("verdict") == "underpowered":
                warn("C12", "the primary claim is underpowered at this sample size", cid)
            elif mode == "test" and not (isinstance(pw, dict) and _filled(pw.get("min_detectable")) and pw.get("verdict")):
                warn("C12", "the primary claim has no power estimate (power.min_detectable and power.verdict) - run `power`", cid)
        # ---- C14
        if not _filled(c.get("warrant_basis")):
            warn("C14", "warrant_basis is (TBD): nothing cited says this measurement counts as evidence for this claim", cid)
        elif c.get("primary") is True and _norm_text(c["warrant_basis"]) == "(field convention)":
            warn("C14", "warrant_basis of the primary claim is (field convention): question 7 must name who in the field "
                        "accepts this inference", cid)

    # ---- C3 (experiment side) / C4
    for e in good_exps:
        if idea_ids is not None and e["id"] not in idea_ids:
            err("C3", f"experiments[] lists {e['id']}, which is not an entry of the idea's Experiments")
        if e["role"] in (None, ""):
            err("C4", f"experiment {e['id']} has no role")
            continue
        if not enum(e["role"], ARG_ROLES, f"experiments {e['id']} role"):
            continue
        if e["role"] in ("tests", "control") and not e["claims"]:
            err("C4", f"experiment {e['id']} has role {e['role']} but lists no claim")
        for x in e["claims"]:
            if x not in claim_ids:
                err("C4", f"experiment {e['id']} lists claim {x!r}, which is not in claims[]")
    if idea_exps is None:
        add("NOTE", "C3", "no idea file read (--no-idea, or none exists) - experiment ids were not checked against the "
                          "idea's Experiments")
    else:
        unlisted = sorted(idea_ids - arg_exp_ids, key=lambda s: int(s[1:]))
        if unlisted:
            add("NOTE", "C4", f"the idea's Experiments {', '.join(unlisted)} have no entry (hence no role) in experiments[]")

    # ---- C10
    if "key_terms" in arg and not 4 <= len(terms) <= 5:
        warn("C10", f"key_terms has {len(terms)} item(s), expected 4-5 (fewer usually means the question is too broad)")
    statements = [str(c.get("statement", "")) for c in good_claims]
    for t in terms:
        where = []
        if not term_in(t, arg.get("question", "")):
            where.append("the question")
        if not any(term_in(t, s) for s in statements):
            where.append("any claim statement")
        if idea_exps is not None and not term_in(t, " ".join(idea_exps)):  # the field as a whole, not one entry
            where.append("any Experiments entry")
        if where:
            warn("C10", f"key term {t!r} does not appear in " + ", ".join(where))
    if idea_exps is None and terms:
        add("NOTE", "C10", "no idea file read (--no-idea, or none exists) - key terms were not looked up in the "
                           "Experiments entries")

    # ---- C11
    rep = arg.get("representation")
    if not isinstance(rep, dict):
        warn("C11", "representation is missing: sample, predictor and outcome each need their target and their stand-in")
    else:
        need = {"sample": ("target", "accessible", "concern"),
                "predictor": ("phenomenon", "variable", "precision", "accuracy", "validity"),
                "outcome": ("phenomenon", "variable", "precision", "accuracy", "validity")}
        for block, keys in need.items():
            b = rep.get(block) if isinstance(rep.get(block), dict) else {}
            empty = [k for k in keys if not _filled(b.get(k))]
            if empty:
                warn("C11", f"representation.{block}: not filled: {', '.join(empty)}")
            v = str(b.get("validity") or "")
            if _filled(v):
                basis = re.sub("|".join(ARG_VALIDITY) + r"|validity|valid|type|basis", "", v.lower())
                if not any(k in v.lower() for k in ARG_VALIDITY) or len(re.sub(r"[\W_]+", "", basis)) < 3:
                    warn("C11", f"representation.{block}.validity must name a type ({' | '.join(ARG_VALIDITY)}) and its basis")

    # ---- C15: the baseline predictor is measured for this claim, and it is what the decisive contrast is against.
    # Looked up in this claim's own evidence[].measure only: an Experiments entry is long enough to contain any word.
    for c in good_claims:
        bp, cmp_ = c.get("baseline_predictor"), c.get("comparator")
        if _nullish(bp):
            continue
        if not any(_names(bp, ev.get("measure", "")) for ev in evidence(c)):
            err("C15", f"baseline_predictor {bp!r} is named in no evidence[].measure of this claim: add the evidence row "
                       "that measures it, or the new measure cannot be shown to add to it", c["id"])
        if _nullish(cmp_) or not _filled(cmp_):
            err("C15", "baseline_predictor is set but comparator is empty: state what the contrast in the falsifier is "
                       "against", c["id"])
        # Only the first thing the comparator lists counts: "generic quality G; M_cal as a secondary comparison"
        # names the baseline, but the decisive contrast is still against the weaker comparator.
        elif not _names(bp, re.split(r"[,;/]|\b(?:and|or|vs|versus|then|plus)\b", str(cmp_), flags=re.I)[0]):
            err("C15", f"comparator {cmp_!r} does not start with the baseline predictor {bp!r}: the falsifier must be the increment over "
                       "the baseline; a contrast against a weaker comparator belongs in a secondary claim", c["id"])

    # ---- C16
    tr = arg.get("tradeoffs", [])
    if tr is not None and not isinstance(tr, list):
        err("SCHEMA", "'tradeoffs' must be a list")
        tr = []
    tr = tr or []
    oq = arg.get("original_question")
    # Counts only in its full shape: the earlier wording AND a reason that says which kind of cause it was.
    has_oq = isinstance(oq, dict) and _filled(oq.get("text")) and bool(QUESTION_CHANGED.match(str(oq.get("changed_because") or "")))
    if oq is not None and not has_oq:
        err("C16", "original_question must be null or {text, changed_because}: text is the earlier wording, and "
                   "changed_because must start with data: | budget: | coherence: | restatement: | wording only: and give "
                   "the reason")
    rows = []  # (index, row) of the rows that are objects
    for i, t in enumerate(tr):
        if not isinstance(t, dict):
            err("SCHEMA", f"tradeoffs[{i}] needs still_answers_question: true or false")
            continue
        rows.append((i, t))
        if not isinstance(t.get("still_answers_question"), bool):
            err("SCHEMA", f"tradeoffs[{i}] needs still_answers_question: true or false")
        elif t["still_answers_question"] is False and not has_oq:
            err("C16", f"tradeoff {str(t.get('change', i))[:80]!r} no longer answers the question, yet original_question is "
                       "null: rewrite the question to the one the reduced study answers and record the original")
        enum(t.get("gate"), ARG_GATES, f"tradeoffs[{i}].gate")
        if not (isinstance(t.get("ids"), list) and all(isinstance(x, str) for x in t["ids"])):
            err("SCHEMA", f"tradeoffs[{i}] needs ids: the claim and experiment ids of argument_r1.json this row accounts "
                          "for, as a list of strings ([] for a dataset, condition class or analysis with no id)")
        for k, about in (("covers_gap", "the gap as B3 described it"), ("covers_angle", "the angle")):
            if not isinstance(t.get(k), bool):
                err("SCHEMA", f"tradeoffs[{i}] needs {k}: true or false - does the study still address {about}?")
    if r1 is not None and _filled(arg.get("question")) and not has_oq \
            and _norm_text(arg.get("question")) != _norm_text(r1.get("question")):
        err("C16", "the question differs from argument_r1.json but original_question is null: record the earlier wording "
                   "and why it changed (data | budget | coherence | restatement | wording only)")

    # ---- C19: every removal or demotion since round 1 has a row that says what was lost
    for i, t in rows:
        if not _filled(t.get("lost")):
            err("C19", f"tradeoffs[{i}]: lost is empty: say what a reader can no longer learn, or 'nothing: <why>'")
        if t.get("covers_gap") is False:
            err("C19", f"tradeoffs[{i}] says the study no longer addresses the gap: restore what was cut or abandon the "
                       "pair (research-cycle §5)")
        if t.get("covers_angle") is False and (cov or {}).get("angle") != "part":
            err("C19", f"tradeoffs[{i}] has covers_angle false but coverage.angle is not 'part'")
    if r1 is not None:
        accounted = set()
        for _, t in rows:
            for x in (t.get("ids") if isinstance(t.get("ids"), list) else []):
                accounted |= {str(x).strip(), exp_id_of(str(x)) or str(x).strip()}
        now = {c["id"]: c for c in good_claims}
        for c in (c for c in (r1.get("claims") if isinstance(r1.get("claims"), list) else [])
                  if isinstance(c, dict) and isinstance(c.get("id"), str)):
            cid = c["id"]
            if cid in accounted:
                continue
            if cid not in now:
                err("C19", f"claim {cid} of argument_r1.json is gone and no tradeoffs row lists it in ids: record what "
                           "was lost and why")
                continue
            if now[cid].get("mode") != c.get("mode"):
                err("C19", f"claim {cid}: mode changed {c.get('mode')} -> {now[cid].get('mode')} since argument_r1.json "
                           f"and no tradeoffs row lists {cid}", cid)
            if (now[cid].get("primary") is True) != (c.get("primary") is True):
                flag = lambda x: "true" if x.get("primary") is True else "false"
                err("C19", f"claim {cid}: primary changed {flag(c)} -> {flag(now[cid])} since argument_r1.json and no "
                           f"tradeoffs row lists {cid}", cid)
            # an id that now names another claim hides a removal: ids are retired, never reused
            if now[cid].get("kind") != c.get("kind"):
                err("C19", f"claim {cid}: kind changed {c.get('kind')} -> {now[cid].get('kind')} since argument_r1.json and "
                           f"no tradeoffs row lists {cid} (an id is retired, never reused for another claim)", cid)
            else:
                s0, s1 = _norm_text(c.get("statement")), _norm_text(now[cid].get("statement"))
                w0, w1 = set(_content_words(s0)), set(_content_words(s1))
                all_terms = terms + (r1.get("key_terms") if isinstance(r1.get("key_terms"), list) else [])
                if s0 != s1 and w0 and w1 and len(w0 & w1) < 0.2 * min(len(w0), len(w1)) \
                        and not any(term_in(t, s0) and term_in(t, s1) for t in all_terms):
                    err("C19", f"claim {cid} no longer reads as the claim of argument_r1.json (no key term and almost no "
                               f"word in common) and no tradeoffs row lists {cid}: an id is retired, never reused - give "
                               "the new claim a new id and record what happened to the old one", cid)
        role_now = {e["id"]: e["role"] for e in good_exps}
        claims_now = {e["id"]: set(e["claims"]) for e in good_exps}
        r1_claim_ids = {c["id"] for c in (r1.get("claims") if isinstance(r1.get("claims"), list) else [])
                        if isinstance(c, dict) and isinstance(c.get("id"), str)}
        for e in (e for e in (r1.get("experiments") if isinstance(r1.get("experiments"), list) else []) if isinstance(e, dict)):
            eid = exp_id_of(e.get("id", ""))
            if not eid or eid in accounted:
                continue
            if eid not in role_now:
                err("C19", f"experiment {eid} of argument_r1.json is gone and no tradeoffs row lists it")
            elif role_now[eid] != e.get("role"):
                err("C19", f"experiment {eid}: role changed {e.get('role')} -> {role_now[eid]} since argument_r1.json and "
                           f"no tradeoffs row lists {eid}")
            else:  # the same role for another claim (claims that exist in only one of the two files do not count)
                kept = r1_claim_ids & claim_ids
                was = {str(x) for x in (e.get("claims") if isinstance(e.get("claims"), list) else [])} & kept
                if was != claims_now[eid] & kept:
                    err("C19", f"experiment {eid}: claims changed {', '.join(sorted(was)) or '-'} -> "
                               f"{', '.join(sorted(claims_now[eid] & kept)) or '-'} since argument_r1.json and no tradeoffs "
                               f"row lists {eid}")

    # ---- C20: does the tested claim answer the whole question, and do Title / Short Hypothesis promise only that?
    primary_ids = {c["id"] for c in good_claims if c.get("primary") is True}
    claim_text = lambda c: " ".join(
        [str(c.get(k) or "") for k in ("statement", "falsifier", "precision_target")] + [str(r) for r in (c.get("reasons") or [])
                                                                                        if isinstance(c.get("reasons"), list)]
        + [str(ev.get(k) or "") for ev in evidence(c) for k in ("measure", "would_show", "refuted_if")])
    title = idea.get("Title", "") if idea is not None else ""
    if cov is None:
        err("C20", "coverage is missing: say whether the primary claim answers the whole question or a named part, and "
                   "whether the angle is still covered")
    else:
        untested = [u for u in (cov.get("untested") if isinstance(cov.get("untested"), list) else []) if isinstance(u, dict)]
        if cov.get("question") == "part" and not (_filled(cov.get("tested_part")) and untested):
            err("C20", "coverage.question is 'part' but tested_part or untested is empty: name the part the primary claim "
                       "tests and list every other part of the question with the claim that covers it")
        for i, u in enumerate(untested):
            by = u.get("by")
            if by is not None and not (isinstance(by, str) or (isinstance(by, list) and all(isinstance(x, str) for x in by))):
                err("SCHEMA", f"coverage.untested[{i}].by must be a claim id, or a list of claim ids")
                continue
            ids = [by] if isinstance(by, str) else (by or [])
            if not ids or any(x not in claim_ids or x in primary_ids for x in ids):
                err("C20", f"the question includes {str(u.get('part'))[:80]!r}, which no claim covers: narrow the question "
                           "(fill original_question) or add the claim that estimates it")
            elif idea is not None:
                for t in (u.get("terms") if isinstance(u.get("terms"), list) else []):
                    if term_in(t, title):
                        err("C20", f"Title names {str(t)!r}, a part of the question that is estimated, not tested "
                                   f"({', '.join(ids)}): the title may promise only what the primary claim tests - reword "
                                   "the Title in the draft and run the check again (a wording repair, no revision)")
        if cov.get("question") == "whole" and primary_ids:  # the self-assessment, asked again of the claim's own text
            tested = claim_text(next(c for c in good_claims if c["id"] in primary_ids))
            for t in terms:
                if term_in(t, arg.get("question", "")) and not term_in(t, tested):
                    warn("C20", f"key term {str(t)!r} is in the question but not in the primary claim's statement, "
                                "falsifier or evidence" + ("; the Title names it too" if idea is not None and term_in(t, title) else "")
                                + ": coverage.question says 'whole' - declare it 'part' with this term under untested, or "
                                  "narrow the question")
        if cov.get("angle") == "part" and not _filled(cov.get("angle_dropped")):
            err("C20", "coverage.angle is 'part' but angle_dropped is empty: say which part of the angle no claim or "
                       "experiment covers, and why")
        # the angle, phrase by phrase: what covers each part of it
        parts = cov.get("angle_parts")
        if not (isinstance(parts, list) and parts and all(isinstance(p, dict) and _filled(p.get("part"))
                                                          and isinstance(p.get("by"), str) and p["by"].strip() for p in parts)):
            err("C20", "coverage.angle_parts is missing or incomplete: split the angle into its phrases and name for each "
                       "what covers it - [{part, by}], by = a claim id, an experiment id, or 'none'")
        else:
            uncovered = []
            for p in parts:
                by, text = p["by"].strip(), None
                if by.lower() == "none":
                    uncovered.append(str(p["part"]))
                    continue
                if by in claim_ids:
                    text = claim_text(next(c for c in good_claims if c["id"] == by))
                elif exp_id_of(by) in arg_exp_ids:
                    eid = exp_id_of(by)
                    if idea_exps is not None:  # an experiment is described in its Experiments entry; without it, not checked
                        text = " ".join([e for e in idea_exps if exp_id_of(e) == eid]
                                        + [str(ev.get(k) or "") for c in good_claims for ev in evidence(c)
                                           if exp_id_of(ev.get("experiment", "")) == eid for k in ("measure", "would_show")])
                else:
                    err("C20", f"angle part {str(p['part'])[:60]!r}: by is {by!r}, which is neither a claim id, an "
                               "experiment id of this argument nor 'none'")
                    continue
                absent = [w for w in _content_words(p["part"]) if text is not None and not _word_in(w, _norm_text(text))]
                if absent:
                    warn("C20", f"angle part {str(p['part'])[:60]!r} is said to be covered by {by}, but "
                                f"{', '.join(repr(w) for w in absent)} occur(s) nowhere in its text: quote in the log what "
                                "covers it, or write by: none and set coverage.angle to part")
            if uncovered and cov.get("angle") != "part":
                err("C20", f"angle part(s) {'; '.join(repr(x[:60]) for x in uncovered)} have by: none but coverage.angle is "
                           "not 'part': set it to part and say in angle_dropped what is not covered and why")
            listed_parts = _norm_text(" ".join(str(p["part"]) for p in parts))
            left_out = [w for w in _content_words(arg.get("angle")) if not _word_in(w, listed_parts)]
            if left_out:
                err("C20", f"the angle names {', '.join(repr(w) for w in left_out)}, which no angle_parts entry mentions: "
                           "go through the angle phrase by phrase - a part dropped before round 1 counts like one dropped "
                           "later")
    if idea is None and idea_exps is None:
        add("NOTE", "C20", "no idea file read (--no-idea, or none exists) - Title and Short Hypothesis were not checked "
                           "against coverage, nor angle parts against the Experiments entries")
    elif idea is not None and _filled(arg.get("question")) \
            and _norm_text(arg["question"]) not in _norm_text(idea.get("Short Hypothesis")):
        warn("C20", "Short Hypothesis does not contain the research question as argument.json words it - a wording "
                    "repair in the draft, no revision")

    # ---- C21: an estimate leaves C7/C17 - only for a stated reason, and as the primary claim only in a study
    # declared descriptive at B3.5
    estimates = [c for c in good_claims if c.get("mode") == "estimate"]
    for c in estimates:
        m = re.match(r"\s*(" + "|".join(ARG_ESTIMATE_BECAUSE) + r")\s*:\s*\S", str(c.get("estimate_because") or ""), re.I)
        if not m:
            err("C21", "mode estimate needs estimate_because, starting with 'descriptive:' (the quantity has no direction "
                       "to test), 'size-open:' (the direction is settled, only the size is unknown) or 'by-construction:' "
                       "(a test was given up - say which, and what a reader loses)", c["id"])
        elif m.group(1).lower() == "by-construction":
            warn("C21", "an estimate because its test was fixed by construction ("
                        + " ".join(str(c["estimate_because"]).split())[:80] + ") - listed at Finish under scope given up; "
                        "question 4 of the round-2 critique asks whether a magnitude test could replace it", c["id"])
    tested = [c for c in good_claims if c.get("mode") in ("test", "equivalence")]
    if study == "analytic" and len(estimates) > len(tested):
        warn("C21", f"{len(estimates)} of {len(good_claims)} claims are estimates in a study declared analytic "
                    f"({len(tested)} tested): say in coverage what the question loses by it, or restore a test")
    for c in good_claims:
        if c.get("primary") is not True or c.get("mode") != "estimate":
            continue
        if study is None:
            add("NOTE", "C21", "step7b_problem.md not found - whether an estimate may be the primary claim (study: "
                               "descriptive) was not checked", c["id"])
        elif study != "descriptive":
            err("C21", "the primary claim is mode estimate but step7b_problem.md does not declare study: descriptive - a "
                       "test claim may not be downgraded to leave C7/C17: restore a testable primary claim, or rewrite the "
                       "question as a descriptive one (study: descriptive, original_question filled)", c["id"])
        elif r1 is not None and _primary_of(r1).get("mode") != "estimate" and not has_oq:
            err("C21", f"the primary claim was mode {_primary_of(r1).get('mode')} in argument_r1.json and is an estimate "
                       "now, yet original_question is null: a test claim may not be downgraded to leave C7/C17 - restore "
                       "it, or record the question it answered in original_question", c["id"])
        if study == "descriptive" and study_r1 == "analytic":
            warn("C21", "step7b_problem_r1.md declared study: analytic and the study is descriptive now, with an estimate "
                        'as its primary claim - goes into Risk Factors and Limitations as "Primary claim downgraded to an '
                        'estimate: ..."', c["id"])

    # ---- C22: the blind reader's doubts are answered, one row each
    doubts = arg.get("reader_doubts", [])
    if not isinstance(doubts, list):
        err("SCHEMA", "'reader_doubts' must be a list ([] when no blind restatement was run)")
        doubts = []
    good_doubts = []
    for i, d in enumerate(doubts):
        if not isinstance(d, dict):
            err("SCHEMA", f"reader_doubts[{i}] needs source, doubt, level, response and how")
            continue
        ok = enum(d.get("source"), ARG_DOUBT_SOURCES, f"reader_doubts[{i}].source")
        enum(d.get("level"), ARG_DOUBT_LEVELS, f"reader_doubts[{i}].level")
        enum(d.get("response"), ARG_DOUBT_RESPONSES, f"reader_doubts[{i}].response")
        for k in ("doubt", "how"):
            if not _filled(d.get(k)) or len(re.findall(r"[^\W\d_]{2,}", str(d.get(k)))) < 2:
                err("SCHEMA", f"reader_doubts[{i}] needs a '{k}' that says something (at least two words)")
        if d.get("response") == "not-fixed" and _filled(d.get("how")):
            if not NOT_FIXED_HOW.match(str(d["how"])):
                err("SCHEMA", f"reader_doubts[{i}]: a not-fixed doubt needs the obstacle in 'how', starting with data: "
                              "(absent on this machine, as env-probe shows) | budget: (which experiment, what cost) | "
                              "conflict: (with which claim)")
            elif NOT_A_REASON.search(str(d["how"])):
                err("C22", f"reader_doubts[{i}]: {NOT_A_REASON.search(str(d['how'])).group(0)!r} is not an obstacle - a "
                           "design doubt is answered by changing the design, or by the data, the cost or the conflict "
                           "that prevents it")
        if d.get("level") == "design" and d.get("response") == "fixed" and _filled(d.get("how")) \
                and not (_exp_ids_in(d["how"]) & arg_exp_ids or any(re.search(r"\b" + re.escape(x) + r"\b", str(d["how"]))
                                                                    for x in claim_ids)):
            err("C22", f"reader_doubts[{i}]: a design doubt marked fixed must name in 'how' the experiment or claim that "
                       "changed (its id) and what changed in it - a sentence added to an entry is a wording fix")
        if ok:
            good_doubts.append(d)
    for k in sorted(restatements):
        mine = [d for d in good_doubts if d["source"] == f"restatement-{k}"]
        if not mine:
            err("C22", f"restatement_{k}.json exists but reader_doubts has no row with source restatement-{k}: split its "
                       "biggest_doubt into separate doubts and answer each")
        elif _numbered_items(restatement_docs.get(k, {}).get("biggest_doubt")) > len(mine):
            err("C22", f"restatement_{k}.json numbers {_numbered_items(restatement_docs[k].get('biggest_doubt'))} doubts "
                       f"and reader_doubts has {len(mine)} row(s) with source restatement-{k}: one row per doubt")
    latest = restatement_docs.get(max(restatement_docs)) if restatement_docs else None
    if latest is not None and (cov or {}).get("question") == "whole" and _filled(latest.get("tested_part")) \
            and not READER_SAYS_ALL.search(str(latest["tested_part"])) \
            and not (has_oq and re.match(r"\s*(restatement|coherence):", str(oq.get("changed_because")), re.I)):
        err("C22", f"the blind reader says only part of the question is tested "
                   f"({' '.join(str(latest['tested_part']).split())[:100]!r}) while coverage.question is 'whole': narrow "
                   "the question (original_question, changed_because 'restatement: ...') or declare coverage.question "
                   "'part' and reword Title and Short Hypothesis")
    for d in good_doubts:
        if d.get("response") == "not-fixed":
            warn("C22", f"reader doubt not fixed ({d['source']}): {' '.join(str(d.get('doubt')).split())[:80]} - goes into "
                        'Risk Factors and Limitations as "Blind restatement unresolved: ..."')
    if 1 in restatements and 2 not in restatements and r1 is not None:
        changed = _primary_changed(arg, r1)
        if changed:
            warn("C22", f"the primary claim changed since round 1 ({', '.join(changed)}): run the second blind restatement "
                        "before FinalizeIdea - unless this run follows a forced revision of the finalize round (then "
                        'no reader follows: record it as "Coherence unresolved: the primary claim was not restated")')

    # ---- C23: a route out of the model, and out of the one dataset, the result was built in
    if ext is None:
        err("C23", "external_check is missing: say whether the primary evidence is synthetic and which experiment ties it "
                   "to real recordings, which datasets carry the primary claim and which experiment repeats it on a "
                   "second, and list what was looked at in external_check.inventory")
    else:
        inventory = [" ".join(str(x).split()) for x in (ext.get("inventory") if isinstance(ext.get("inventory"), list) else [])
                     if _filled(x)]
        has_inventory = bool(inventory)
        support = {e["id"] for e in good_exps if e["role"] in ARG_SUPPORT_ROLES}
        routes = []
        if ext.get("synthetic") is True:
            routes.append(("real_data",
                           "the primary evidence is synthetic and no experiment ties it to real recordings: name the "
                           "experiment in external_check.real_data, or write 'none: <why>' after checking the local "
                           "inventory (env-probe, $RD/datasets/) and list what was checked in external_check.inventory",
                           "no experiment ties the synthetic evidence to real recordings ({why}) - goes into Risk Factors "
                           'and Limitations as "No real-data validation: ..."'))
        if isinstance(ext.get("datasets"), list) and len(ext["datasets"]) == 1:
            routes.append(("second_dataset",
                           "one dataset carries the primary claim and no experiment repeats it on a second: name the "
                           "experiment in external_check.second_dataset, or write 'none: <why>' after checking the local "
                           "inventory (env-probe, $RD/datasets/) and list what was checked in external_check.inventory",
                           'single dataset ({why}) - goes into Risk Factors and Limitations as "Single dataset: ..."'))
        said_none = False
        for key, missing, recorded in routes:
            v = " ".join(str(ext.get(key) or "").split())
            none = re.match(r"none:\s*(\S.*)", v, re.I)
            if none:  # read before the ids: the reason may well name the experiment that was cut
                said_none = True
                if not has_inventory:
                    err("C23", missing)
                elif key == "real_data" and r1 is None:
                    # No argument_r1.json yet = the round-1 run: "none" is not accepted before the scheduled revision
                    # has tried once. Afterwards it is recorded, not blocked (no gate waits for a person).
                    err("C23", "external_check.real_data is 'none:' in round 1: a synthetic result needs a route to real "
                               "recordings, so the round-2 revision must try once - add the experiment (a direction-only "
                               "or rank check on real artifacts counts when no strength scale exists), or keep 'none:' "
                               "with the concrete obstacle per inventory candidate; once argument_r1.json exists this is a "
                               'WARN and a "No real-data validation: ..." risk entry')
                else:
                    warn("C23", recorded.format(why=none.group(1)[:80]))
            elif _exp_ids_in(v) & support:
                pass
            elif _exp_ids_in(v) - arg_exp_ids:
                err("C23", f"external_check.{key} names {', '.join(sorted(_exp_ids_in(v) - arg_exp_ids))}, which is not "
                           "listed in experiments[]")
            else:
                err("C23", missing)
        if said_none and has_inventory:  # "no data" may be said only after looking at what is on the disk
            low = [x.lower() for x in inventory]
            for x in inventory:
                if not re.match(r"\S[^:]*:\s*\S", x):
                    err("C23", f"inventory entry {x[:60]!r} does not say why: write '<path or dataset>: <why it does or "
                               "does not serve>'")
            for name in datasets_files:
                if not any(name.lower() in x for x in low):
                    err("C23", f"inventory does not mention $RD/datasets/{name}: read it and say why each candidate in it "
                               "does or does not serve")
            spell = lambda r: {r.lower().rstrip("/"), str(Path(r).expanduser()).lower().rstrip("/")}
            named = lambda r: any(sp in x for sp in spell(r) for x in low)
            for root in data_roots:  # named itself or through a path below it; a root inside another listed root is
                # covered by that one
                if any(p != root and any(a.startswith(b + "/") for a in spell(root) for b in spell(p)) for p in data_roots):
                    continue
                if not named(root):
                    err("C23", f"inventory does not mention the data root {root} that env-probe lists: say what is in it "
                               "and why it does or does not serve")
        if ext.get("synthetic") is False:
            primary = _primary_of(arg)
            said = SYNTHETIC_WORDS.search(" ".join(
                [str(arg.get("study_sentence") or ""), str((primary.get("construction") or {}).get("predictor_formula") or "")
                 if isinstance(primary.get("construction"), dict) else ""]
                + [str(ev.get("measure") or "") for ev in evidence(primary)]))
            if said:
                warn("C23", f"external_check.synthetic is false, yet the study sentence, the predictor or a measure of the "
                            f"primary claim says {said.group(0)!r}: if the primary evidence is injected, simulated or "
                            "planted, set synthetic to true and name the route to real recordings")
        if probe is False:
            warn("C23", "the session config has no local_environment.probe: run env-probe before trusting what is cached")

    for s in ctx.get("planning_stale") or []:   # the planning block's later files rest on this argument (C28)
        err("C28", f"{s} - P1 or P2 changed since it was built: redo the steps after the one the revision entered "
                   "(tree, attack plan, packaging), never patch them")
    if ctx.get("planning"):  # P1 Gap2Hypo: derivation (C25), rival accounts (C26), magnitudes (C27)
        import it_plan
        p1 = it_plan.p1_findings(arg, ctx["planning"])
        for f in p1:
            add(f["level"], f["check"], f["text"], f.get("claim"))
        if not p1:
            add("NOTE", "C25", "planning P1 checks C25-C27 ran (gen_k/question.json): no finding")

    out.sort(key=lambda f: ARG_ORDER.index(f["check"]))  # stable: SCHEMA first, then C1..C28
    return out


def _load_argument(gen_dir: Path) -> dict:
    f = gen_dir / "argument.json"
    if not f.exists():
        die(f"{f} not found - write it at the end of B4 (question-craft.md section 4); a generation made before the "
            "argument file existed has nothing to check", 2)
    try:
        arg = read_json(f)
    except Exception as e:
        die(f"{f} does not parse ({e})", 2)
    if not isinstance(arg, dict):
        die(f"{f} must be a JSON object", 2)
    return arg


def _study_of(step7b: Path) -> str | None:
    """The `study:` word of step7b_problem.md's frontmatter (first 40 lines). None: no such file. A file without the
    line (written before the key existed) counts as analytic - the stricter reading."""
    if not step7b.exists():
        return None
    for ln in step7b.read_text(encoding="utf-8", errors="replace").splitlines()[:40]:
        m = re.match(r"\s*study\s*:\s*[\"']?([A-Za-z-]+)", ln)
        if m:
            return m.group(1).lower()
    return "analytic"


def _argument_context(gd: Path, idea: dict | None) -> dict:
    """What the other files of the generation say (see check_argument). Each file is read only when it exists, so a
    folder written before these files were introduced is checked exactly as far as it goes."""
    ctx = {"r1": None, "study": _study_of(gd / "step7b_problem.md"), "study_r1": _study_of(gd / "step7b_problem_r1.md"),
           "restatements": set(), "restatement_docs": {}, "idea": idea, "probe": None, "datasets_files": [], "data_roots": []}
    f = gd / "argument_r1.json"
    if f.exists():
        try:
            ctx["r1"] = read_json(f)
        except Exception as e:
            die(f"{f} does not parse ({e})", 2)
        if not isinstance(ctx["r1"], dict):
            die(f"{f} must be a JSON object", 2)
    for n in (1, 2):
        f = gd / f"restatement_{n}.json"
        if f.exists():
            try:
                doc = read_json(f)
            except Exception as e:
                die(f"{f} does not parse ({e}) - save the reader's JSON object as returned", 2)
            if not (isinstance(doc, dict) and _filled(doc.get("biggest_doubt"))):
                die(f"{f} is not a reader's restatement: it must be the JSON object the brief asks for, with a "
                    "biggest_doubt (question-craft.md section 7.2) - save the object as returned", 2)
            ctx["restatements"].add(n)
            ctx["restatement_docs"][n] = doc
    cfg = gd.parent / "step0_session_config.json"
    if cfg.exists():
        try:
            env = read_json(cfg).get("local_environment")
            ctx["probe"] = isinstance(env, dict) and isinstance(env.get("probe"), dict) and bool(env["probe"])
            roots = env["probe"].get("data_roots") if ctx["probe"] else None
            own = (gd.parent / "datasets").resolve()  # covered file by file below
            ctx["data_roots"] = [r for r, children in (roots.items() if isinstance(roots, dict) else [])
                                 if children and Path(r).expanduser().resolve() != own]
        except Exception:
            pass  # an unreadable config is another command's problem; here it only means "probe unknown"
    ds = gd.parent / "datasets"
    if ds.is_dir():  # the screening notes and tables someone wrote there; scripts, raw dumps and caches are not read
        ctx["datasets_files"] = sorted(p.name for p in ds.iterdir() if p.is_file() and not p.name.startswith((".", "_"))
                                       and p.suffix.lower() in (".md", ".txt", ".csv", ".tsv"))
    import it_plan
    ctx["planning"] = it_plan.context(gd)
    ctx["planning_stale"] = it_plan.stale(gd)
    ctx["planning_tree"] = (gd / "decision_tree.json").exists()
    return ctx


def cmd_argument_check(a):
    """Coherence gate. ERROR -> one forced ReviseHypothesis, then finalize anyway and record the finding under Risk
    Factors and Limitations ("Coherence unresolved: ..."); WARN -> listed for the reflection round to judge. Some WARNs
    name the Risk entry they become at finalize: "Blind restatement unresolved: ..." (C22, a reader doubt not fixed),
    "No real-data validation: ..." and "Single dataset: ..." (C23), "Primary claim downgraded to an estimate: ..."
    (C21), and the missing positive control (C17). An ERROR that reads only the Title is a wording repair in the draft
    (C20) and costs no revision. Any unexpected value in argument.json is exit 2, never exit 1."""
    gd = Path(a.gen_dir)
    arg = _load_argument(gd)
    if a.idea and a.no_idea:
        die("--idea and --no-idea exclude each other", 2)
    if a.no_idea:  # the run after the round-2 revision: the draft in the folder is stale and must not be read
        idea_file = None
    elif a.idea:
        idea_file = Path(a.idea)
        if not idea_file.exists():
            die(f"{idea_file} not found", 2)
    else:
        idea_file = next((gd / n for n in ("idea.json", "idea_draft.json") if (gd / n).exists()), None)
    idea = None
    if idea_file:
        try:
            idea = load_idea(idea_file)
        except Exception as e:  # bad input is exit 2, never exit 1 (= "revise the hypothesis")
            die(f"{idea_file} is not a usable idea file: {e}", 2)
    ctx = _argument_context(gd, idea)
    try:
        findings = check_argument(arg, idea["Experiments"] if idea else None, ctx)
    except Exception as e:  # a value of a shape no check expected: bad input (exit 2), never "revise" (exit 1)
        die(f"{gd / 'argument.json'} holds a value argument-check cannot read ({type(e).__name__}: {e}) - compare the "
            "file with the schema in question-craft.md section 4.1", 2)
    by = lambda level: [{k: f[k] for k in ("check", "claim", "text")} for f in findings if f["level"] == level]
    errors, warnings, notes = by("ERROR"), by("WARN"), by("NOTE")
    if a.json:
        print(json.dumps({"errors": errors, "warnings": warnings, "notes": notes}, indent=2, ensure_ascii=False))
    else:
        for f in findings:
            print(f"{f['level']} {f['check']}" + (f" {f['claim']}" if f["claim"] else "") + f": {f['text']}")
        print(f"argument-check: {len(errors)} error(s), {len(warnings)} warning(s)"
              + (f" [idea: {idea_file.name}]" if idea_file else " [no idea file]")
              + (" - REVISE" if errors else " - OK"))
    sys.exit(1 if errors else 0)


def cmd_argument_render(a):
    """argument.json -> argument.md, the tables a person reads. Generated: edit the JSON, not this file."""
    gd = Path(a.gen_dir)
    arg = _load_argument(gd)
    d = lambda x: x if isinstance(x, dict) else {}
    ls = lambda x: x if isinstance(x, list) else []
    cell = lambda v, n=10_000: _cell(v, n)
    yn = lambda v: "yes" if v is True else ("NO" if v is False else "-")
    NA = "not applicable (estimate)"
    oq = arg.get("original_question")
    cov, ext = d(arg.get("coverage")), d(arg.get("external_check"))
    L = [f"# Argument — {arg.get('idea') or gd.name}\n",
         "Generated by `ideate_tools.py argument-render` from `argument.json` - edit the JSON, not this file.\n",
         f"- **Generation / gap / angle**: {cell(arg.get('generation'))} / {cell(arg.get('gap'))} / {cell(arg.get('angle'))}",
         f"- **Variant**: {cell(arg.get('variant'))}",
         f"- **Study in one sentence**: {cell(arg.get('study_sentence'))}",
         f"- **Question**: {cell(arg.get('question'))}",
         "- **Original question**: " + (f"{cell(d(oq).get('text'))} — changed because: {cell(d(oq).get('changed_because'))}"
                                        if isinstance(oq, dict) else (cell(oq) if oq else "unchanged")),
         f"- **Key terms**: {cell(ls(arg.get('key_terms')))}",
         "\n## Coverage (does the tested claim answer the question, through the lens it was chosen for?)\n"]
    if cov:
        L.append(f"- **Question covered by the primary claim**: {cell(cov.get('question'))}")
        if cov.get("question") == "part" or cov.get("tested_part") or cov.get("untested"):
            L.append(f"- **Tested part**: {cell(cov.get('tested_part'))}")
            L += [f"- **Untested part**: {cell(u.get('part'))} — carried by {cell(u.get('by'))}"
                  + (f"; terms: {cell(ls(u.get('terms')))}" if ls(u.get("terms")) else "")
                  for u in ls(cov.get("untested")) if isinstance(u, dict)]
        L.append(f"- **Angle covered**: {cell(cov.get('angle'))}")
        L += [f"- **Angle part**: {cell(p.get('part'))} — covered by {cell(p.get('by'))}"
              for p in ls(cov.get("angle_parts")) if isinstance(p, dict)]
        if cov.get("angle") == "part" or cov.get("angle_dropped"):
            L.append(f"- **Angle dropped**: {cell(cov.get('angle_dropped'))}")
    else:
        L.append("Not recorded.")
    L.append("\n## External check (does it hold outside the model, or the one dataset, it was built in?)\n")
    if ext:
        L += [f"- **Primary evidence is synthetic**: {yn(ext.get('synthetic')).lower()}",
              f"- **Route to real data**: {cell(ext.get('real_data'))}",
              f"- **Datasets carrying the primary claim**: {cell(ls(ext.get('datasets')))}",
              f"- **Second dataset**: {cell(ext.get('second_dataset'))}",
              "- **Inventory looked at**:" + ("" if ls(ext.get("inventory")) else f" {TBD}")]
        L += [f"  - {cell(x)}" for x in ls(ext.get("inventory"))]
    else:
        L.append("Not recorded.")
    L.append("\n## Claims\n\n| id | hypothesis | primary | kind | mode | statement |\n|---|---|---|---|---|---|")
    claims = [c for c in ls(arg.get("claims")) if isinstance(c, dict)]
    L += [f"| {cell(c.get('id'))} | {cell(c.get('hypothesis') or '-')} | {'yes' if c.get('primary') is True else ''} | "
          f"{cell(c.get('kind'))} | {cell(c.get('mode'))} | {cell(c.get('statement'))} |" for c in claims]
    for c in claims:
        est = c.get("mode") == "estimate"
        opt = lambda v: NA if est and not _filled(v) else cell(v or "-")  # an estimate has no falsifier, controls or power
        L.append(f"\n### {c.get('id')}" + (" (primary)" if c.get("primary") is True else "") + "\n")
        L.append("**Reasons**\n")
        L += [f"- {cell(r)}" for r in ls(c.get("reasons"))] or [f"- {TBD}"]
        L.append("\n**Evidence**\n\n| experiment | measure | would show | can fail? | refuted if |\n|---|---|---|---|---|")
        L += [f"| {cell(e.get('experiment'))} | {cell(e.get('measure'))} | {cell(e.get('would_show'))} | "
              f"{cell(e.get('can_fail') or '-')} | {cell(e.get('refuted_if') or '-')} |"
              for e in ls(c.get("evidence")) if isinstance(e, dict)]
        o, ng, ctl, sc, pw = (d(c.get(k)) for k in ("outcomes", "negation", "controls", "scope", "power"))
        con = d(c.get("construction"))
        if con:
            L += ["\n**Construction** (is the result fixed before the experiment runs?)\n",
                  f"- Predictor formula: {cell(con.get('predictor_formula'))}",
                  f"- Outcome formula: {cell(con.get('outcome_formula'))}",
                  f"- Shared terms: {cell(ls(con.get('shared_terms')) or 'none')}",
                  f"- Computable without the experiment: {cell(con.get('computable_without_experiment'))}",
                  f"- Free quantity: {cell(con.get('free_quantity'))}"]
        L += ["",
              f"- **Warrant**: {cell(c.get('warrant'))}",
              f"- **Warrant basis**: {cell(c.get('warrant_basis'))}",
              f"- **If supported, we learn**: {cell(o.get('if_supported'))}",
              f"- **If not, we learn**: {cell(o.get('if_not'))}",
              f"- **Negation**: {NA}" if est and not ng else f"- **Negation** ({cell(ng.get('verdict'))}): {cell(ng.get('text'))}",
              "- **Expected direction**: " + (NA if est else f"{cell(d(c.get('expected_direction')).get('direction'))} — basis: "
                                              f"{cell(d(c.get('expected_direction')).get('basis'))}"),
              f"- **Smallest effect of interest**: {cell(c.get('smallest_effect_of_interest') or '-')}",
              f"- **Falsifier**: {opt(c.get('falsifier'))}",
              f"- **Precision target**: {cell(c.get('precision_target') or '-')}",
              *([f"- **Estimate because**: {cell(c.get('estimate_because'))}"] if est else []),
              f"- **Negative control**: {opt(ctl.get('negative'))}",
              f"- **Can the negative control move the measure?**: {opt(ctl.get('negative_can_move'))}",
              f"- **Positive control**: {opt(ctl.get('positive'))}",
              f"- **Positive control, expected value**: {opt(ctl.get('positive_expected'))}",
              f"- **Baseline predictor**: {cell(c.get('baseline_predictor') or 'not applicable')}",
              f"- **Comparator of the falsifier**: {cell(c.get('comparator') or '-')}",
              f"- **Scope, internal**: {cell(sc.get('internal'))}",
              f"- **Scope, external**: {cell(sc.get('external'))}",
              f"- **Limits**: {cell(ls(sc.get('limits')) or '-')}"]
        if pw:
            L.append(f"- **Power** ({cell(pw.get('verdict'))}): n = {cell(pw.get('n'))} {cell(pw.get('unit'))}"
                     + (f", clusters: {cell(pw['clusters'])}" if pw.get("clusters") else "")
                     + f"; smallest detectable: {cell(pw.get('min_detectable'))}; literature: {cell(pw.get('literature_effect'))}")
        elif est:
            L.append(f"- **Power**: {NA}")
        rv = [r for r in ls(c.get("rivals")) if isinstance(r, dict)]
        if any(r.get("id") or r.get("account") for r in rv):   # a planning-block claim: ids for the decision tree
            L.append("\n**Rival explanations**\n\n| id | type | main | how it would arise here | ruled out by | field's account |"
                     "\n|---|---|---|---|---|---|")
            L += [f"| {cell(r.get('id'))} | {cell(r.get('type'))} | {'main' if r.get('main') is True else ''} | "
                  f"{cell(r.get('how'))} | {cell(r.get('ruled_out_by'))} | {cell(r.get('account')) if r.get('account') else '—'} |" for r in rv]
        else:
            L.append("\n**Rival explanations**\n\n| type | main | how it would arise here | ruled out by |\n|---|---|---|---|")
            L += [f"| {cell(r.get('type'))} | {'main' if r.get('main') is True else ''} | {cell(r.get('how'))} | "
                  f"{cell(r.get('ruled_out_by'))} |" for r in rv]
        dv = d(c.get("derivation"))
        if dv:
            L.append(f"\n- **Derived from**: {cell(dv.get('gap'))} ({cell(dv.get('move'))}), primary collision "
                     f"{cell(dv.get('primary_collision'))} → form **{cell(dv.get('form'))}**"
                     + (f"; deviation: {cell(dv.get('deviation'))}" if dv.get("deviation") else "")
                     + (f"; note: {cell(dv.get('note'))}" if dv.get("note") else ""))
            L += [f"- **Account set aside**: {cell(x.get('account'))} — {cell(x.get('why'))}"
                  for x in ls(dv.get("set_aside")) if isinstance(x, dict)]
    rep = d(arg.get("representation"))
    s_, p_, o_ = d(rep.get("sample")), d(rep.get("predictor")), d(rep.get("outcome"))
    L += ["\n## Representation (does the stand-in represent the target?)\n",
          "| | target | stand-in in this study | concern / precision | accuracy | validity |\n|---|---|---|---|---|---|",
          f"| sample | {cell(s_.get('target'))} | {cell(s_.get('accessible'))} | {cell(s_.get('concern'))} | - | - |"]
    L += [f"| {name} | {cell(b.get('phenomenon'))} | {cell(b.get('variable'))} | {cell(b.get('precision'))} | "
          f"{cell(b.get('accuracy'))} | {cell(b.get('validity'))} |" for name, b in (("predictor", p_), ("outcome", o_))]
    L.append("\n## Experiments\n\n| id | role | claims |\n|---|---|---|")
    L += [f"| {cell(e.get('id'))} | {cell(e.get('role'))} | {cell(ls(e.get('claims')) or '-')} |"
          for e in ls(arg.get("experiments")) if isinstance(e, dict)]
    tr = [t for t in ls(arg.get("tradeoffs")) if isinstance(t, dict)]
    L.append("\n## Trade-offs\n")
    if tr:
        L.append("| gate | ids | change | because | lost | answers question | covers gap | covers angle | why |\n"
                 "|---|---|---|---|---|---|---|---|---|")
        L += [f"| {cell(t.get('gate') or '-')} | {cell(ls(t.get('ids')) or '-')} | {cell(t.get('change'))} | "
              f"{cell(t.get('because'))} | {cell(t.get('lost'))} | {yn(t.get('still_answers_question'))} | "
              f"{yn(t.get('covers_gap'))} | {yn(t.get('covers_angle'))} | {cell(t.get('why'))} |" for t in tr]
    else:
        L.append("None recorded.")
    doubts = [x for x in ls(arg.get("reader_doubts")) if isinstance(x, dict)]
    L.append("\n## Reader doubts\n")
    if doubts:
        L.append("| source | level | doubt | response | how |\n|---|---|---|---|---|")
        L += [f"| {cell(x.get('source'))} | {cell(x.get('level'))} | {cell(x.get('doubt'))} | {cell(x.get('response'))} | "
              f"{cell(x.get('how'))} |" for x in doubts]
    else:
        L.append("None recorded.")
    (gd / "argument.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"argument-render: {len(claims)} claim(s), {len(ls(arg.get('experiments')))} experiment(s) -> {gd / 'argument.md'}")


# -------------------------------------------------------------------- env-probe
PROBE_ROOTS = ("~/mne_data", "~/.cache/huggingface/hub", "~/.cache/torch", "~/scikit_learn_data")
PROBE_MAX_CHILDREN = 200


def _package_version(name: str):
    """(present, version or None) in the running interpreter. Importable by find_spec; "scikit-learn" is not an import
    name, so an installed distribution of that name counts as present too."""
    import importlib.metadata as md
    import importlib.util
    version = None
    for dist in dict.fromkeys((name, name.replace("_", "-"), name.replace("-", "_"))):
        try:
            version = md.version(dist)
            break
        except Exception:
            continue
    try:
        found = importlib.util.find_spec(name.replace("-", "_")) is not None
    except Exception:  # a name that is no module path at all
        found = False
    return found or version is not None, version


def cmd_env_probe(a):
    """What is on this machine NOW: the children of each data root and the listed packages. local_environment in
    step0_session_config.json is prose written once at A1 and goes stale (a dataset downloaded since, a package
    installed since); the screens, the Scope table, external_check.inventory and the compute gate read this probe
    instead. No network."""
    rd = Path(a.research_dir)
    cfg_path = rd / "step0_session_config.json"
    if not cfg_path.exists():
        die(f"{cfg_path} not found", 2)
    try:
        cfg = read_json(cfg_path)
    except Exception as e:
        die(f"{cfg_path} does not parse ({e})", 2)
    if not isinstance(cfg, dict):
        die(f"{cfg_path} must be a JSON object", 2)
    env = cfg.get("local_environment") if isinstance(cfg.get("local_environment"), dict) else {}
    listed = lambda k: [str(x) for x in (env.get(k) if isinstance(env.get(k), list) else [])]
    split = lambda text: [x.strip() for x in str(text or "").split(",") if x.strip()]

    if split(a.roots):
        roots = split(a.roots)
    else:
        roots = list(PROBE_ROOTS) + [str(rd / "datasets")]
        # "~/mne_data/MNE-eegbci-data: 109 subjects" / "/tmp, scratch only": the path stops before the punctuation
        roots += [e.split()[0].rstrip(":,;)") for e in listed("cached_data") if e.strip()[:1] in ("~", "/")]
    data_roots, missing_roots = {}, []
    for root in dict.fromkeys(roots):
        path = Path(root).expanduser()
        if path.is_dir():
            data_roots[root] = sorted(c.name for c in path.iterdir())[:PROBE_MAX_CHILDREN]
        else:
            missing_roots.append(root)

    # "mne 1.13", "scikit-learn>=1.3", "torch==2.2", "pyriemann,", "braindecode: not installed", "name/alias"
    first = lambda entry: re.split(r"[\s/<>=!~(\[:,;]", entry.strip(), maxsplit=1)[0]
    said_present = [first(e) for e in listed("packages_present") if first(e)]
    said_missing = [first(e) for e in listed("packages_missing") if first(e)]
    packages, stale = {}, []
    for name in dict.fromkeys(split(a.packages) + said_present + said_missing):
        present, version = _package_version(name)
        packages[name] = (version or "present, version unknown") if present else None
        if present and name in said_missing:
            stale.append(f"{name} is listed under packages_missing but is importable here ({packages[name]})")
        elif not present and name in said_present:
            stale.append(f"{name} is listed under packages_present but is not importable here")
    from datetime import datetime
    probe = {"date": datetime.now().astimezone().isoformat(timespec="seconds"), "interpreter": sys.executable,
             "data_roots": data_roots, "packages": packages}
    if a.write:
        cfg["local_environment"] = dict(env, probe=probe)  # the A1 prose keys stay as context
        write_json(cfg_path, cfg)
    if a.json:
        print(json.dumps(dict(probe, roots_not_found=missing_roots, stale=stale), indent=2, ensure_ascii=False))
        return
    print(f"env-probe: {probe['date']}  interpreter {probe['interpreter']}")
    for root, children in data_roots.items():
        print(f"data root {root}: {len(children)} entr{'y' if len(children) == 1 else 'ies'}"
              + (f" (first {PROBE_MAX_CHILDREN} shown)" if len(children) == PROBE_MAX_CHILDREN else ""))
        for c in children:
            print(f"  {c}")
    for root in missing_roots:
        print(f"data root {root}: not found")
    for name, version in packages.items():
        print(f"package {name}: {version if version else 'NOT installed'}")
    for line in stale:
        print(f"stale: {line}")
    print("env-probe: " + (f"written to {cfg_path} (local_environment.probe)" if a.write
                           else "not stored - add --write to record it as local_environment.probe"))


# ------------------------------------------------------------------------ power
POWER_NOTE = ("rough estimate (normal approximation); it understates the sample needed when n < 30. "
              "n must count independent units - subjects, not trials or epochs.")


def power_estimate(mode: str, n=None, n1=None, n2=None, sd=None, alpha=0.05, power=0.80, conf=0.95,
                   sided=2, effect=None) -> dict:
    """With the sample size fixed (public data), the smallest effect the study can detect - or, for a descriptive
    study, how wide the confidence interval will be. Closed forms, solved for the effect instead of for N:
      corr         N = ((Za + Zb) / C)^2 + 3,  C = atanh(r)          -> r = tanh((Za + Zb) / sqrt(N - 3))
      two-group    N = (1/q1 + 1/q2) (Za + Zb)^2 / d^2               -> d = (Za + Zb) sqrt(1/n1 + 1/n2)
      paired       the one-sample form, d in SD of the differences   -> d = (Za + Zb) / sqrt(N)
      estimate     N = 4 Z^2 S^2 / W^2                               -> W = 2 Z S / sqrt(N)
      equivalence  two one-sided tests, true difference 0            -> margin = (Z(1-alpha) + Z(1-beta/2)) * se,
                   se = 1/sqrt(N) (paired / one-sample) or sqrt(1/n1 + 1/n2)
    Za = Z(1 - alpha/sided): alpha is two-sided unless sided = 1. `effect` (raw outcome units) is turned round into
    the largest SD at which that effect is still detectable - the honest figure when the SD is not known yet."""
    import math
    from statistics import NormalDist
    z = NormalDist().inv_cdf
    if not 0 < alpha < 1 or not 0 < power < 1 or not 0 < conf < 1:
        raise ValueError("--alpha, --power and --conf must lie strictly between 0 and 1")
    if sd is not None and sd <= 0:
        raise ValueError("--sd must be positive")
    if sided not in (1, 2):
        raise ValueError("--sided must be 1 or 2")
    if effect is not None and effect <= 0:
        raise ValueError("--effect must be positive (the magnitude, in outcome units)")
    if effect is not None and mode == "corr":
        raise ValueError("--effect does not apply to --mode corr: r has no outcome unit")
    if sided != 2 and mode in ("estimate", "equivalence"):
        raise ValueError(f"--sided does not apply to --mode {mode}")
    zab = z(1 - alpha / sided) + z(power)
    side = "one-sided" if sided == 1 else "two-sided"
    res = {"mode": mode, "alpha": alpha, "sided": sided}
    if mode == "equivalence":
        if n1 is not None:
            n2 = n1 if n2 is None else n2
            if min(n1, n2) < 2:
                raise ValueError("equivalence needs --n1 and --n2, each >= 2")
            se = math.sqrt(1 / n1 + 1 / n2)
            res.update(n1=n1, n2=n2, n=n1 + n2)
        elif n is not None:
            if n < 2:
                raise ValueError(f"--n {n} is too small for mode {mode}")
            se = 1 / math.sqrt(n)
            res["n"] = n
        else:
            raise ValueError("equivalence needs --n (paired / one-sample) or --n1 and --n2")
        margin = (z(1 - alpha) + z(1 - (1 - power) / 2)) * se
        res.update(sided=1, power=power, quantity="smallest equivalence margin (in SD) at which equivalence can be shown "
                                                   "when the true difference is 0",
                   min_detectable=round(margin, 3), margin=round(margin, 3),
                   text=f"equivalence margin >= {margin:.2f} SD @ {power:.0%} power (two one-sided tests, alpha = {alpha:g} each)")
    elif mode == "two-group":
        if n1 is None and n is not None:
            raise ValueError("two-group takes the group sizes: --n1 and --n2 (not --n)")
        n2 = n1 if n2 is None else n2
        if n1 is None or min(n1, n2) < 2:
            raise ValueError("two-group needs --n1 and --n2, each >= 2")
        d = zab * math.sqrt(1 / n1 + 1 / n2)
        res.update(n1=n1, n2=n2, n=n1 + n2, power=power, quantity="standardized difference (d)", min_detectable=round(d, 3),
                   text=f"d >= {d:.2f} @ {power:.0%} power, {side} alpha = {alpha:g}")
    else:
        if n is None:
            raise ValueError(f"{mode} needs --n")
        if n < (4 if mode == "corr" else 2):
            raise ValueError(f"--n {n} is too small for mode {mode}")
        res["n"] = n
        if mode == "corr":
            r = math.tanh(zab / math.sqrt(n - 3))
            res.update(power=power, quantity="|r|", min_detectable=round(r, 3),
                       text=f"|r| >= {r:.2f} @ {power:.0%} power, {side} alpha = {alpha:g}")
        elif mode == "paired":
            d = zab / math.sqrt(n)
            res.update(power=power, quantity="standardized difference (d, in SD of the paired differences)",
                       min_detectable=round(d, 3), text=f"d >= {d:.2f} @ {power:.0%} power, {side} alpha = {alpha:g}")
        else:
            w = 2 * z(1 - (1 - conf) / 2) / math.sqrt(n)
            del res["alpha"], res["sided"]
            res.update(conf=conf, quantity="total width of the confidence interval", unit="SD" if sd is None else "raw",
                       ci_width=round(w * (sd or 1), 4), ci_width_in_sd=round(w, 3),
                       text=f"{conf:.0%} CI total width = {w:.2f} SD" + (f" = {w * sd:.4g}" if sd is not None else ""))
    if "min_detectable" in res and sd is not None and mode != "corr":  # r has no unit to convert to
        res["min_detectable_raw"] = round(res["min_detectable"] * sd, 4)
    if effect is not None:  # unrounded figures: the bound must not be looser than the one printed above
        per_sd = w if mode == "estimate" else (margin if mode == "equivalence" else d)
        res["effect"] = effect
        res["max_sd_for_effect"] = round(effect / per_sd, 4)
        res["effect_text"] = {
            "estimate": f"the interval reaches a total width of {effect:g} only if the SD is at most {effect / per_sd:.4g}",
            "equivalence": f"equivalence within a margin of {effect:g} can be shown only if the SD is at most {effect / per_sd:.4g}",
        }.get(mode, f"an effect of {effect:g} is detectable only if the SD is at most {effect / per_sd:.4g}")
    sizes = (res.get("n1"), res.get("n2")) if res.get("n1") is not None else (res["n"],)
    res["small_n"] = min(sizes) < 30
    res["note"] = POWER_NOTE
    return res


def cmd_power(a):
    try:
        res = power_estimate(a.mode, n=a.n, n1=a.n1, n2=a.n2, sd=a.sd, alpha=a.alpha, power=a.power, conf=a.conf,
                             sided=a.sided, effect=a.effect)
    except ValueError as e:
        die(str(e), 2)
    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return
    size = f"n1={res['n1']} n2={res['n2']}" if res.get("n1") is not None else f"n={res['n']}"
    print(f"power {a.mode}: {size} -> {res['text']}")
    if res.get("min_detectable_raw") is not None:
        print(f"  in outcome units (SD {a.sd:g}): {res['min_detectable_raw']:g}")
    if res.get("effect_text"):
        print(f"  {res['effect_text']}")
    print(f"  {res['note']}")
    if res["small_n"]:
        print("  n < 30 here: the true figure is worse than the one printed - treat the verdict as marginal at best.")


# ------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *args):
        sp = sub.add_parser(name)
        for flags, kw in args:
            sp.add_argument(*flags, **kw)
        sp.set_defaults(fn=fn)

    rd = (("research_dir",), {})
    add("paths", cmd_paths, (("--topic",), {"required": True}))
    add("tier1", cmd_tier1, rd, (("--depth",), {"choices": ["quick", "standard", "deep"], "default": "standard"}),
        (("--top-up",), {"action": "store_true", "help": "after a download: add next-ranked papers to replace paywalled ones"}),
        (("--targets",), {"action": "store_true", "help": "planning F-M4: add the questions' abstract-only attack targets "
                                                           "(section 9) to the candidates, at most 5 per topic"}))
    add("arxiv-pdfs", cmd_arxiv_pdfs, rd)
    add("fulltext-status", cmd_fulltext_status, rd)
    add("figures", cmd_figures, rd, (("--dpi",), {"type": int, "default": 130}),
        (("--all-pages",), {"action": "store_true", "help": "render every page, not only pages with a caption"}))
    add("concept-index", cmd_concept_index, rd)
    add("consume", cmd_consume, rd, (("--gap",), {"default": None}), (("--angle",), {"default": None}),
        (("--question",), {"default": None, "help": "fusion block: the question (Q_NNN) the idea took; gap and angle "
                                                     "are read off it"}),
        (("--idea",), {"default": None}),
        (("--abandoned",), {"default": None, "help": "fusion block: the generation gives the question up (the decision "
                                                      "gate could not be passed) - the reason; nothing is consumed"}),
        (("--also-uses",), {"default": "", "help": "comma-separated gap ids whose "
         "controls/designs this idea borrows; a later generation should avoid re-using them the same way"}))
    add("list-papers", cmd_list_papers, rd,
        (("--file",), {"choices": ["raw", "shortlist", "snowball", "excluded"], "default": "raw"}),
        (("--grep",), {"default": "", "help": "only papers whose title+abstract contain ALL of these words"}),
        (("--slice",), {"default": "0:30"}), (("--abstract-chars",), {"type": int, "default": 400}),
        (("--ids",), {"default": "", "help": "comma-separated paper ids: print these in full instead of a slice"}))
    add("build-cards", cmd_build_cards, rd, (("cards_json",), {}))
    add("build-methods", cmd_build_methods, rd, (("input_json",), {"nargs": "+", "help": "one or more batch files"}))
    add("list-methods", cmd_list_methods, rd, (("--family",), {"default": ""}), (("--theme",), {"default": ""}),
        (("--dataset",), {"default": "", "help": "substring of a dataset name"}), (("--ids",), {"default": ""}),
        (("--evidence",), {"choices": ["any", "full-text", "abstract"], "default": "any"}),
        (("--fields",), {"default": "split,leakage_control,baselines,metrics,stats,headline,affordable_here"}),
        (("--width",), {"type": int, "default": 200}))
    add("consumed", cmd_consumed, rd)
    add("link-run", cmd_link_run, (("run_dir",), {}), (("ideas_json",), {}))
    add("validate", cmd_validate, (("ideas_json",), {}))
    add("append-idea", cmd_append_idea, (("ideas_json",), {}), (("idea_json",), {}))
    gd = (("gen_dir",), {"help": "<research_dir>/gen_k"})
    add("argument-check", cmd_argument_check, gd,
        (("--idea",), {"default": "", "help": "7-key idea JSON; default <gen_dir>/idea.json, then idea_draft.json"}),
        (("--no-idea",), {"action": "store_true", "help": "ignore any idea file in <gen_dir> (the run after the round-2 revision, while the draft is stale)"}),
        (("--json",), {"action": "store_true"}))
    add("argument-render", cmd_argument_render, gd)
    add("env-probe", cmd_env_probe, rd,
        (("--packages",), {"default": "", "help": "comma-separated import or distribution names to look for, besides "
                                                   "those listed in local_environment"}),
        (("--roots",), {"default": "", "help": "comma-separated data roots; replaces the default roots"}),
        (("--write",), {"action": "store_true", "help": "store the result as local_environment.probe in step0_session_config.json"}),
        (("--json",), {"action": "store_true"}))
    add("power", cmd_power,
        (("--mode",), {"required": True, "choices": ["corr", "two-group", "paired", "estimate", "equivalence"]}),
        (("--n",), {"type": int, "help": "independent units (subjects, not trials or epochs)"}),
        (("--n1",), {"type": int}), (("--n2",), {"type": int}),
        (("--sd",), {"type": float, "help": "SD of the outcome; without it results are in SD units"}),
        (("--alpha",), {"type": float, "default": 0.05, "help": "two-sided unless --sided 1; per one-sided test for equivalence"}),
        (("--sided",), {"type": int, "choices": [1, 2], "default": 2, "help": "1 for a one-sided decision rule (corr, two-group, paired)"}),
        (("--effect",), {"type": float, "help": "smallest effect of interest in raw outcome units: prints the largest SD "
                                                "at which it is detectable (use it when the SD is not known; never a placeholder --sd)"}),
        (("--power",), {"type": float, "default": 0.80}),
        (("--conf",), {"type": float, "default": 0.95, "help": "confidence level, --mode estimate"}),
        (("--json",), {"action": "store_true"}))
    import it_frame      # A1 frame (sibling module; scripts are run by path)
    import it_units      # the Unit registry: ideate_units.json -> references/units.md
    import it_search     # A2 search: offline tools (the network runs are mcp_bridge.py search / merge)
    import it_screen     # A3 screen: offline tools (the network run is mcp_bridge.py bibliometrics)
    import it_export     # A4 export: a4-check (keys: `export`; the .bib: mcp_bridge.py bibliography)
    import it_snowball   # A5 snowball: a5-check (the network run is mcp_bridge.py snowball)
    import it_ledger     # the search block's ledger: next, status (STATUS.md, search_caveats.json)
    import it_fulltext   # A6 full text, A6.d fetch + A6.c convert: a6-check (the commands are tier1 … fulltext-status)
    import it_trace      # trace: every Unit's decision about one paper, key or query
    import it_decon      # fusion block, A7.D deconstruct: decon-plan / -check / -merge / -render
    import it_align      # fusion block, A7.A align + B1 lens: align-terms / -set / -coords / -points / -check, lens-set
    import it_collide    # fusion block, A7.X collide + B3.c lens + B3 gaps: collide-candidates / -plan / -merge / -check, gaps-set
    import it_recon      # fusion block, A7.R reconstruct + B2 + B3.5 questions: recon-candidates / -check, fusion-map, questions-*
    import it_plan       # planning block, P1-P5 (Gap2Hypo, design, decision tree, attack, packaging): plan-status, …
    it_frame.add_parsers(sub)
    it_search.add_parsers(sub)
    it_screen.add_parsers(sub)
    it_export.add_parsers(sub)
    it_snowball.add_parsers(sub)
    it_ledger.add_parsers(sub)
    it_decon.add_parsers(sub)
    it_align.add_parsers(sub)
    it_collide.add_parsers(sub)
    it_recon.add_parsers(sub)
    it_plan.add_parsers(sub)
    it_trace.add_parsers(sub)
    it_units.add_parsers(sub)
    it_fulltext.add_parsers(sub)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
