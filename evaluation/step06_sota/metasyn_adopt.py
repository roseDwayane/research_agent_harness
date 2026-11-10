#!/usr/bin/env python3
"""MetaSyn fixed-input research folder for the fusion-block harness: the papers a review included, F1 onwards.

MetaSyn gives a system the question and PI/ECO and lets it search a corpus. Here the search is not part of the test: the
papers the source review included (matched_corpus_ids minus the review itself) are the input, and the harness runs from
F1 (A7.D) to F4 (B2). The harness refuses to start there on a folder it did not search (IDEATE.UPSTREAM.NOT_DONE: A7.D
requires A4.b and A6.c, which require the search units), so this script builds the folder the search would have left and
puts it on the ledger. Nothing in `harness/` or `scripts/` is changed; it only calls what is there.

    python evaluation/step06_sota/metasyn_adopt.py --list [--split test] [--min-refs 10 --max-refs 30]
    python evaluation/step06_sota/metasyn_adopt.py <review_id> <batch_dir> [--split test] [--offline]

What it writes, for review N, under <batch_dir>:
    topics/review_N.md                  the topic file (Topic and Research_Question)
    sessions/review_N/                  the research folder, the harness's --research-dir
        step0_session_config.json       topic and a protocol built from MetaSyn's PI/ECO, criteria and search period
        step3_shortlist.json            the included papers, all `included` (title, authors, year, abstract, ...)
        step4_*                         citation keys (A4.k's mint_keys) and the bibliography (A4.b, offline)
        step5_full_text/<key>.md        the abstract and the PMC sections the corpus has; none for an abstract-only paper
        _state/ledger.jsonl             A1.p-A5 and A6.d recorded as adopted (`why: metasyn-import`); A4.k, A4.b and A6.c
                                        are the real units, run on these files
    eval/review_N/ground_truth.json     the answers (Key_Insights, Effect_Direction, ...) - only here, never in sessions/
    eval/review_N/input_report.json     what was dropped and why, which criteria were used
    batch.json, runs.jsonl              so naive_baseline.py (B0, B2) and metasyn_eval.py find the review

Then:  PYTHONUTF8=1 ideate-harness run topics/review_N.md --research-dir sessions/review_N --from F1 --to F4 --worker ollama
(PYTHONUTF8=1: the harness reads its files with the platform's default encoding.) The baselines B0 and B2 are generated
from the same folder (naive_baseline.py --batch <batch_dir> [--variant fulltext]), so every arm reads the same papers.

The source review's Title, Abstract and Introduction, its findings and any free-text criteria field that reads as a
finding are not written into the research folder (metasyn_data.ANSWER_FIELDS, clean_criteria).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
HARNESS = REPO / "ai-scientist-ideate-harness"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))                                    # evaluation/: eval_common

from eval_common import append_run, batch_paths, read_runs, write_json  # noqa: E402
from metasyn_data import (  # noqa: E402
    ANSWER_FIELDS, GROUND_TRUTH_FIELDS, _str, _year, article_text, clean_criteria, has_value, load_articles, load_review,
    pubmed_authors, reference_ids)

DEFAULT_DATA = REPO.parent / "data" / "metasyn"
SEARCH_UNITS = ["A1.p", "A1.q", "A1.v", "A1.e", "A2.s", "A2.m", "A2.c", "A3.b", "A3.g", "A3", "A5"]   # adopted
OPERATORS = re.compile(r"(^|\s)(AND|OR|NOT)(\s|$)|[()\[\]]")
CHEAP_SPLIT = re.compile(r"[;,:/()]| and | or | with | versus | vs\.? | among | in | of | for | by | to ", re.IGNORECASE)
COMPLETION = ("fixed input: the papers a MetaSyn source review included; no search was run (metasyn_adopt.py)")


# ------------------------------------------------------------------------------------------------ harness modules
def load_harness(harness_dir: Path):
    scripts = harness_dir / "scripts"
    for p in (str(scripts), str(harness_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import it_export, it_frame, it_ledger  # noqa: PLC0415 - the harness's own modules, found through sys.path
    return it_export, it_frame, it_ledger


# ------------------------------------------------------------------------------------------------ the protocol
def terms_of(text: str, need: int) -> list[str]:
    """1-4 word terms from a slot's text (no operators, no brackets), at least `need` of them."""
    out: list[str] = []

    def add(t: str) -> None:
        t = re.sub(r"\s+", " ", t).strip(" .-'\"")
        if t and len(t.split()) <= 4 and not OPERATORS.search(t) and t.lower() not in {x.lower() for x in out}:
            out.append(t)

    for part in CHEAP_SPLIT.split(text):
        words = part.split()
        if len(words) <= 4:
            add(part)
        else:
            for i in range(0, len(words) - 2, 2):
                add(" ".join(words[i:i + 3]))
    words = text.split()
    i = 0
    while len(out) < need and i < len(words) - 1:
        add(" ".join(words[i:i + 2]))
        i += 1
    return out[:8]


def build_protocol(review: dict, topic: str, topic_sha: str, depth: str, answers: dict) -> tuple[dict, dict]:
    """A protocol that passes it_frame.check_protocol, from MetaSyn's PI/ECO, criteria and search period.
    The terms of the search axes are cut from the slot texts: nothing is searched, they only have to be well formed."""
    pico = has_value(review.get("Intervention"))
    anchor_slot, comp_slot = ("intervention", "comparison") if pico else ("exposure", "comparator")
    population = _str(review.get("Population")) if has_value(review.get("Population")) else topic
    anchor = _str(review.get("Intervention" if pico else "Exposure"))
    anchor = anchor if has_value(anchor) else topic
    comparison = _str(review.get("Comparison")) if has_value(review.get("Comparison")) else "no comparator stated by the source review"
    outcome = _str(review.get("Outcome")) if has_value(review.get("Outcome")) else topic
    need = 3 if depth != "quick" else 2
    slot = lambda name, value, role: {  # noqa: E731
        "slot": name, "value": value, "operational_role": role,
        "reason": "copied from the MetaSyn source review's PI/ECO fields (fixed input, nothing is searched)"}
    framework = {"name": "PICO" if pico else "PECO",
                 "rationale": "fixed MetaSyn input: the slots are the source review's own " + ("PICO" if pico else "PECO") + " fields",
                 "slots": [slot("population", population, "search-and-eligibility"),
                           slot(anchor_slot, anchor, "search-and-eligibility"),
                           slot(comp_slot, comparison, "eligibility-only"),
                           slot("outcome", outcome, "eligibility-only")]}
    axes = [{"id": "C1", "kind": "search", "slot": "population", "name": "population", "terms": terms_of(population, need)},
            {"id": "C2", "kind": "search", "slot": anchor_slot, "name": anchor_slot, "terms": terms_of(anchor, need)},
            {"id": "C3", "kind": "anchor", "name": "topic", "terms": terms_of(topic, 2)[:3] or [topic[:30]]},
            {"id": "C4", "kind": "contrast", "name": "comparator", "terms": terms_of(comparison, 1)[:3] or ["comparator"]}]

    inc_text, inc_why = clean_criteria(review.get("inclusion_criteria"), answers)
    exc_text, exc_why = clean_criteria(review.get("exclusion_criteria"), answers)
    split_items = lambda t: [x.strip(" .") for x in re.split(r";|\n", t) if len(x.strip(" .")) > 8]  # noqa: E731
    inclusion = [{"id": "IN1", "text": f"concerns {population}", "refs": ["population"]},
                 {"id": "IN2", "text": f"concerns {anchor}, possibly against {comparison}", "refs": [anchor_slot, comp_slot]},
                 {"id": "IN3", "text": f"reports {outcome}", "refs": ["O1"]}]
    exclusion = [{"id": "EX1", "text": "concerns neither the population nor the intervention / exposure above",
                  "refs": ["population", anchor_slot]}]
    for t in split_items(inc_text or ""):
        inclusion.append({"id": f"IN{len(inclusion) + 1}", "text": t, "refs": []})
    for t in split_items(exc_text or ""):
        exclusion.append({"id": f"EX{len(exclusion) + 1}", "text": t, "refs": []})

    y0, y1 = _year(review.get("search_start_date")), _year(review.get("search_end_date"))
    this = dt.date.today().year
    ok = y0 and y1 and y0 <= y1 <= this + 1
    timeframe = f"{y0}-{y1}" if ok else f"2000-{this}"
    protocol = {
        "schema": "ideate-protocol/1", "review_type": "scoping", "reporting_standard": "PRISMA-ScR",
        "purpose": "gap-identification", "framework": framework, "axes": axes,
        "outcomes": [{"id": "O1", "text": outcome}], "timeframe": timeframe,
        "timeframe_reason": ("the source review's own search period" if ok else
                             "the source review gives no usable search period; a wide default (nothing is searched)"),
        "setting": "MetaSyn fixed input (medical literature); no search was run",
        "criteria": {"inclusion": inclusion, "exclusion": exclusion}, "completion_criterion": COMPLETION,
        "topic_sha256": topic_sha, "written_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "history": []}
    sources = {"inclusion_criteria": inc_why, "exclusion_criteria": exc_why, "framework": protocol["framework"]["name"],
               "timeframe": "source review" if ok else "default"}
    return protocol, sources


# ------------------------------------------------------------------------------------------------ the papers
def build_papers(articles: list[dict], pubmed: bool, cache: Path | None) -> tuple[list[dict], dict[str, dict], list[dict]]:
    """The same inclusion rule as metasyn_prepare.build_papers: a paper with no abstract and no sections, or with no
    authors (even after a PubMed lookup), is dropped and listed - so the harness and the baselines see the same papers."""
    known = json.loads(cache.read_text(encoding="utf-8")) if cache and cache.exists() else {}
    papers, texts, dropped = [], {}, []
    for a in articles:
        cid, title = int(a["ID"]), _str(a.get("title"))
        level, body = article_text(a)
        if not _str(a.get("abstract")) and level == "abstract-only":
            dropped.append({"corpus_id": cid, "title": title, "reason": "no abstract and no sections"})
            continue
        authors = [x for x in (a.get("authors") or []) if _str(x)]
        source = "metasyn"
        pmid = _str(a.get("pmid"))
        if not authors and pmid and pubmed:
            try:
                if pmid not in known:
                    known[pmid] = pubmed_authors(pmid)
                authors, source = known[pmid], "pubmed"
            except Exception as e:  # noqa: BLE001 - recorded; the paper is dropped below
                source = f"pubmed failed: {type(e).__name__}"
        elif not authors and pmid:
            source = "offline: no PubMed lookup"
        if not authors:
            dropped.append({"corpus_id": cid, "title": title, "reason": f"no authors ({source})"})
            continue
        pid = f"paper_{len(papers) + 1:03d}"
        pmc = _str(a.get("pmc_id"))
        papers.append({
            "id": pid, "title": title, "authors": authors, "year": _year(a.get("year")), "journal": _str(a.get("journal")) or None,
            "doi": _str(a.get("doi")) or None, "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
            "abstract": _str(a.get("abstract")) or None, "has_abstract": bool(_str(a.get("abstract"))),
            "pubmed_id": pmid or None, "pmc_id": pmc or None, "sources_found_in": ["metasyn"], "found_via": "metasyn",
            "venue_type": "journal", "language": "en", "manually_included": False,
            "screening": {"relevance": 5, "quality": 5, "recency_impact": 5, "composite": 5.0, "tier": 1,
                          "category": "included", "rationale": "MetaSyn reference article (fixed input)"}})
        texts[pid] = {"corpus_id": cid, "access_level": level, "body": body, "author_source": source,
                      "n_sections": sum(1 for s in (a.get("sections") or []) if _str(s.get("text")))}
    if cache and known:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(known, ensure_ascii=False), encoding="utf-8")
    return papers, texts, dropped


def write_text_lf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def write_json_lf(path: Path, data: Any) -> None:
    write_text_lf(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------------------------------------ the ledger
def adopt(L, rd: Path, units: list[str]) -> None:
    """Record units nobody ran as done, through the ledger's own begin / done (they record the hashes of the files
    that exist now, so the units are not stale), each with `why: metasyn-import`."""
    for u in units:
        L.note(rd, u, "adopt", why="metasyn-import")
        L.begin(rd, u)
        L.done(rd, u, render_views=False)


def unit_problems(L, rd: Path) -> list[str]:
    """Search and full-text units that are not `done` (stale, running, ...) - none is allowed after the import."""
    sys.path.insert(0, str(HARNESS))
    from ideate_v2.ledger import ledger_block, load_events, unit_states  # noqa: PLC0415
    from ideate_v2.registry import Registry  # noqa: PLC0415
    reg = Registry.load()
    events, _ = load_events(rd)
    st = unit_states(reg, rd, events)
    return [f"{u} {s['state']}: {s['why'][:80]}" for u, s in st.items()
            if ledger_block(reg, u) in ("search", "fulltext") and s["state"] != "done"]


def run_tool(harness_dir: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, str(harness_dir / "scripts" / "ideate_tools.py"), *args], env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def llm_config(toml_path: Path) -> dict:
    with open(toml_path, "rb") as fh:
        p = tomllib.load(fh).get("pipeline", {})
    return {"provider": p.get("provider", "ollama"), "model": p.get("model", "qwen3.8"),
            "base_url": p.get("base_url", "http://127.0.0.1:11434"), "num_ctx": p.get("num_ctx", 49152),
            "think": p.get("think", False), "request_timeout": 1800.0, "temperature": p.get("temperature", 0.0),
            "max_tokens": p.get("max_tokens", 16384)}


# ------------------------------------------------------------------------------------------------ one review
def adopt_review(review_id: int, batch_dir: Path, data_dir: Path, split: str, offline: bool, depth: str,
                 llm_toml: Path, harness_dir: Path, force: bool) -> dict:
    export, frame, L = load_harness(harness_dir)
    paths = batch_paths(batch_dir)
    rid = f"review_{review_id}"
    rd = batch_dir / "sessions" / rid
    topic_md = batch_dir / "topics" / f"{rid}.md"
    eval_dir = paths["eval"] / rid
    if rd.exists():
        if not force:
            raise SystemExit(f"{rd} exists (use --force to rebuild it)")
        shutil.rmtree(rd)

    review = load_review(data_dir, review_id, split)
    ref_ids, source_ids = reference_ids(review)
    articles = load_articles(data_dir, ref_ids)
    papers, texts, dropped = build_papers(articles, pubmed=not offline, cache=data_dir / ".cache" / "pubmed_authors.json")
    if not papers:
        raise SystemExit("no usable input papers")
    answers = {k: review.get(k) for k in ANSWER_FIELDS}

    # the answers, outside everything the harness reads
    write_json(eval_dir / "ground_truth.json", {
        "review_id": review_id, "split": split, **{f: _str(review.get(f)) for f in GROUND_TRUTH_FIELDS},
        "extracted_titles": [str(x) for x in review["extracted_titles"]]})

    topic = _str(review["Topic"])
    question = _str(review.get("Research_Question"))
    protocol, crit_sources = build_protocol(review, topic, "", depth, answers)
    keywords = ", ".join(dict.fromkeys(t for ax in protocol["axes"] for t in ax["terms"]))
    write_text_lf(topic_md, f"# {topic}\n\n## Research Question\n{question or topic}\n\n## Keywords\n{keywords}\n")
    protocol["topic_sha256"] = hashlib.sha256(topic_md.read_bytes()).hexdigest()
    now = dt.datetime.now().astimezone()
    cfg = {"topic": topic, "topic_file": str(topic_md), "depth": depth, "timestamp": now.isoformat(timespec="seconds"),
           "session_id": now.strftime("%Y%m%d"), "topic_original": topic, "topic_slug": rid, "current_step": 5,
           "field_type": "biomedical", "protocol": protocol}
    write_json_lf(rd / "step0_session_config.json", cfg)
    errs = [f for f in frame.check_protocol(cfg, rd) if f["level"] == "ERROR"]
    if errs:
        raise SystemExit("the protocol built from MetaSyn does not pass check_protocol: "
                         + "; ".join(f"{f['code']} {f['msg']}" for f in errs[:5]))

    write_json_lf(rd / "step3_shortlist.json", {
        "schema": "ideate-shortlist/2", "topic": topic, "session_id": cfg["session_id"],
        "screening_timestamp": cfg["timestamp"], "screening_config": {},
        "summary": {"total_screened": len(papers), "included": len(papers), "borderline": 0, "excluded": 0},
        "papers": papers})

    def key_unit() -> dict:
        with L.run_unit(rd, "A4.k", check=lambda: export.check_keys(cfg_now, rd), degraded=lambda: L.degraded_codes(rd, "A4.k")):
            return export.mint_keys(cfg_now, rd, no_snowball="metasyn-import: fixed input, no search and no snowball")

    def fulltext_unit() -> None:
        r = run_tool(harness_dir, "fulltext-status", str(rd))                # A6.c, the real unit
        if r.returncode:
            raise SystemExit("fulltext-status failed: " + (r.stdout + r.stderr)[-1500:])

    cfg_now = json.loads((rd / "step0_session_config.json").read_text(encoding="utf-8"))
    adopt(L, rd, SEARCH_UNITS)                                           # A1.p ... A5: nobody ran them
    minted = key_unit()                                                  # A4.k: the real unit (its gates are the search's)
    sl = json.loads((rd / "step3_shortlist.json").read_text(encoding="utf-8"))
    key_of = {p["id"]: p.get("citation_key") for p in sl["papers"]}

    for pid, t in texts.items():                                         # step5: only a paper with sections has a full text
        key = key_of.get(pid)
        if key and t["n_sections"]:
            title = next(p["title"] for p in papers if p["id"] == pid)
            write_text_lf(rd / "step5_full_text" / f"{key}.md", "# " + title + "\n\n" + t["body"])
            write_json_lf(rd / "step5_full_text" / f"{key}_meta.json", {
                "converter": "metasyn-corpus", "source": f"MetaSyn corpus {t['corpus_id']} (PMC sections)",
                "chars": len(t["body"]), "at": now.isoformat(timespec="seconds")})

    export.build_bibliography(cfg_now, rd, "", offline=True)             # A4.b, from the records only
    adopt(L, rd, ["A6.d"])                                               # nothing was fetched
    fulltext_unit()

    # The commands above add fields to the shortlist (defaults the search would have written), which changes what an
    # earlier unit recorded about it. Once the files have settled, record every unit again on the final files:
    # the ledger then holds a done event per unit that matches what is on disk (later events win).
    adopt(L, rd, SEARCH_UNITS)
    key_unit()
    export.build_bibliography(cfg_now, rd, "", offline=True)
    adopt(L, rd, ["A6.d"])
    fulltext_unit()
    open_units = unit_problems(L, rd)
    if open_units:
        raise SystemExit("units not done on the final files: " + "; ".join(open_units))

    # the leak check: no answer text in anything the harness can read
    leaks = leaked(rd, answers)
    if leaks:
        raise SystemExit(f"answer text found in the research folder: {leaks}")

    full = sum(1 for t in texts.values() if t["n_sections"])
    write_json(eval_dir / "input_report.json", {
        "review_id": review_id, "split": split, "session_dir": f"sessions/{rid}", "topic_file": f"topics/{rid}.md",
        "matched_corpus_ids": len(review["matched_corpus_ids"]), "source_review_ids_excluded": sorted(source_ids),
        "found_in_corpus": len(articles), "papers_in": len(papers), "with_keys": len([k for k in key_of.values() if k]),
        "full_text": full, "authors_from_pubmed": [t["corpus_id"] for t in texts.values() if t["author_source"] == "pubmed"],
        "dropped": dropped, "study_count": review.get("study_count"), "protocol_sources": crit_sources,
        "minted": minted})
    if not paths["batch"].exists():
        write_json(paths["batch"], {"batch_id": batch_dir.name, "source": "metasyn adopted fixed input (fusion block)",
                                    "protocol": {"config": {"llm": llm_config(llm_toml)}}})
    if rid not in {x["id"] for x in read_runs(batch_dir)}:
        append_run(batch_dir, {"id": rid, "topic": topic, "session_dir": f"sessions/{rid}", "pipeline_status": "adopted",
                               "steps_done": ["adopt"], "step6_present": False})
    return {"research_dir": str(rd), "topic_file": str(topic_md), "papers": len(papers), "full_text": full,
            "dropped": len(dropped), "criteria": crit_sources}


def leaked(rd: Path, answers: dict, n: int = 8) -> list[str]:
    """Files under the research folder that share a run of `n` words with a text the source review gives as an answer."""
    from metasyn_data import ngrams  # noqa: PLC0415
    secrets = {k: ngrams(v, n) for k, v in answers.items() if _str(v) and len(_str(v).split()) >= n}
    found = []
    for f in sorted(rd.rglob("*")):
        if not f.is_file() or f.suffix not in {".json", ".md", ".jsonl", ".bib", ".txt"} or "_state" in f.parts:
            continue
        grams = ngrams(f.read_text(encoding="utf-8", errors="replace"), n)
        for name, sg in secrets.items():
            # a paper's own abstract may legitimately share text with the source review's abstract (it is cited by it);
            # what matters is the review's findings, so Abstract / Title / Introduction are not matched
            if name in ("Abstract", "Title", "Introduction"):
                continue
            if grams & sg:
                found.append(f"{f.relative_to(rd).as_posix()} ~ {name}")
    return found


# ------------------------------------------------------------------------------------------------ --list
def list_reviews(data_dir: Path, split: str, lo: int, hi: int) -> None:
    import pandas as pd  # noqa: PLC0415
    df = pd.read_parquet(data_dir / f"{split}.parquet")
    print(f"{'id':>5} {'refs':>5} {'full text':>9}  topic")
    for _, r in df.iterrows():
        n = int(r["matched_ref_count"]) if str(r["matched_ref_count"]).isdigit() else 0
        if not lo <= n <= hi:
            continue
        ids, _ = reference_ids(r.to_dict())
        arts = load_articles(data_dir, ids)
        full = sum(1 for a in arts if any(_str(s.get("text")) for s in (a.get("sections") or [])))
        print(f"{int(r['ID']):>5} {n:>5} {full:>9}  {_str(r['Topic'])[:90]}")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("review_id", nargs="?", type=int)
    ap.add_argument("batch_dir", nargs="?", type=Path)
    ap.add_argument("--list", action="store_true", help="list the reviews of --split with --min-refs..--max-refs references")
    ap.add_argument("--data-dir", type=Path, default=Path(os.environ.get("METASYN_DATA_DIR", DEFAULT_DATA)))
    ap.add_argument("--split", choices=["train", "test"], default="test")
    ap.add_argument("--min-refs", type=int, default=10)
    ap.add_argument("--max-refs", type=int, default=30)
    ap.add_argument("--offline", action="store_true", help="no PubMed lookup for papers without authors (they are dropped)")
    ap.add_argument("--depth", choices=["quick", "standard", "deep"], default="standard")
    ap.add_argument("--llm-toml", type=Path, default=HERE / "metasyn.toml", help="[pipeline] model the baselines use")
    ap.add_argument("--harness-dir", type=Path, default=HARNESS)
    ap.add_argument("--force", action="store_true", help="rebuild an existing research folder")
    args = ap.parse_args()
    if args.list:
        list_reviews(args.data_dir, args.split, args.min_refs, args.max_refs)
        return 0
    if args.review_id is None or args.batch_dir is None:
        ap.error("review_id and batch_dir are required (or --list)")
    out = adopt_review(args.review_id, args.batch_dir.resolve(), args.data_dir, args.split, args.offline, args.depth,
                       args.llm_toml, args.harness_dir, args.force)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("\nnext:  PYTHONUTF8=1 ideate-harness run", out["topic_file"], "--research-dir", out["research_dir"],
          "--from F1 --to F4 --worker ollama")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
