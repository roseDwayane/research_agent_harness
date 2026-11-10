#!/usr/bin/env python3
"""RQ-Bench item -> research folder for the fusion-block harness, run from F1 to F4 (and the gaps, B3, and questions, B3.5).

RQ-Bench (declare-lab/rq-bench, arXiv 2606.12071): given the full text of the papers a target paper cites, propose the
research question the target paper went on to investigate. One item = one held-out question + its cited papers; the
annotation says, per cited paper, which limitation the target paper took up (limitation, verbatim evidence quote, how the
target addresses it). This script builds the folder a literature search would have left from an item's cited papers (the
same idea as evaluation/step06_sota/metasyn_adopt.py: the harness refuses to start at F1 on a folder it did not search)
and puts it on the ledger. Nothing under ai-scientist-ideate-harness/ is changed.

    python evaluation/step07_gaps/rqbench_adopt.py --list [--set dev]
    python evaluation/step07_gaps/rqbench_adopt.py <rq_id> <batch_dir>

SPLIT. RQ-Bench has one split (test) and nothing to develop on, so data/rq-bench/split.json fixes, before any run, a
development set (30 items) and a formal set (213 items) out of the 243 items that cite three or more papers (an item with
one or two references has nothing to compare across papers). This script refuses a formal item unless --formal is given.

WHAT THE HARNESS MAY READ. The topic names the research area (the arXiv subfield of the target paper) and the number of
cited papers - nothing of the target paper's title, headline, problem, contributions or question. The held-out question and
the annotated gaps go to eval/<id>/ground_truth.json only; after building, the script fails if a run of 8 words of them
appears in a file the harness reads.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
HARNESS = REPO / "ai-scientist-ideate-harness"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "step06_sota"))

from eval_common import append_run, batch_paths, read_runs, write_json  # noqa: E402
from metasyn_adopt import (  # noqa: E402
    COMPLETION, OPERATORS, SEARCH_UNITS, adopt, leaked, llm_config, load_harness, run_tool, terms_of, unit_problems,
    write_json_lf, write_text_lf)

DATA = REPO.parent / "data" / "rq-bench"
HF = "https://huggingface.co/datasets/declare-lab/rq-bench/resolve/main/"
AREA = {"cs.RO": "robotics", "cs.CV": "computer vision", "cs.CL": "natural language processing", "cs.LG": "machine learning",
        "cs.AI": "artificial intelligence", "cs.SD": "sound and audio processing", "cs.IR": "information retrieval",
        "cs.CR": "cryptography and security", "cs.IT": "information theory", "cs.SE": "software engineering",
        "cs.DC": "distributed computing", "cs.NI": "networking", "cs.HC": "human-computer interaction"}
STOP = set("a an and the of for in on to with via from by using use based towards toward is are as at into over under "
           "do does can how what why when large language models model learning".split())


# ------------------------------------------------------------------------------------------------ data
def data_dir(d: Path | None) -> Path:
    return Path(d) if d else Path(os.environ.get("RQBENCH_DATA_DIR", DATA))


def load_rows(d: Path) -> dict[str, dict]:
    path = d / "rq_dataset.jsonl"
    if not path.exists():
        d.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(HF + "rq_dataset.jsonl", path)
    return {r["rq_id"]: r for r in (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip())}


def as_obj(v: Any) -> Any:
    return v if not isinstance(v, str) else ast.literal_eval(v)


def cited_paper(d: Path, arxiv_id: str) -> dict:
    path = d / "cited_papers" / f"{arxiv_id}.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(HF + f"cited_papers/{arxiv_id}.json", path)
    return json.loads(path.read_text(encoding="utf-8"))


def arxiv_meta(d: Path, ids: list[str], offline: bool) -> dict[str, dict]:
    """{arxiv_id: {authors, year}} from the arXiv API (cached); the cited-paper files carry neither. A record the API
    would not give is not cached: the id stands in for the authors this time and the API is asked again next time."""
    import time  # noqa: PLC0415
    cache_path = d / ".cache" / "arxiv_meta.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    need = [i for i in ids if i not in cache]
    if need and not offline:
        try:                             # one request for all: the arXiv API
            q = urllib.parse.urlencode({"id_list": ",".join(need), "max_results": len(need)})
            req = urllib.request.Request("http://export.arxiv.org/api/query?" + q, headers={"User-Agent": "research-eval/0.1"})
            root = ET.fromstring(urllib.request.urlopen(req, timeout=60).read())
            ns = {"a": "http://www.w3.org/2005/Atom"}
            for e in root.findall("a:entry", ns):
                aid = re.sub(r"v\d+$", "", (e.findtext("a:id", "", ns) or "").rsplit("/abs/", 1)[-1])
                cache[aid] = {"authors": [a.findtext("a:name", "", ns) for a in e.findall("a:author", ns)],
                              "year": int((e.findtext("a:published", "", ns) or "0")[:4]) or None}
        except Exception as exc:  # noqa: BLE001
            print(f"arXiv API failed ({type(exc).__name__}: {exc}); asking OpenAlex", file=sys.stderr)
        for i in [i for i in need if i not in cache]:       # the arXiv DOI in OpenAlex
            try:
                url = "https://api.openalex.org/works/doi:10.48550/arXiv." + i
                w = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research-eval/0.1"}),
                                                     timeout=60).read())
                names = [a["author"]["display_name"] for a in w.get("authorships") or [] if a.get("author", {}).get("display_name")]
                if names:
                    cache[i] = {"authors": names, "year": w.get("publication_year")}
            except Exception as exc:  # noqa: BLE001
                print(f"OpenAlex failed for {i} ({type(exc).__name__}: {exc})", file=sys.stderr)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    out = {}
    for i in ids:
        if i in cache:
            out[i] = cache[i]
        else:                            # no record: the id's own year, and the arXiv id as a stand-in author
            yy = int(i[:2]) if re.match(r"\d{4}\.", i) else 0
            out[i] = {"authors": [f"Arxiv {i}"], "year": 2000 + yy if yy else None, "stand_in": True}
    return out


def split_of(d: Path) -> dict:
    return json.loads((d / "split.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------ the folder
def md_of(cited: dict) -> str:
    parts = [f"# {cited.get('title', '')}", "", "## Abstract", "", str(cited.get("abstract") or "(no abstract available)"), ""]
    for k, v in cited.items():
        if k in ("arxiv_id", "title", "abstract") or not str(v).strip():
            continue
        parts += [f"## {k.strip(': ')}", "", str(v).strip(), ""]
    return "\n".join(parts).rstrip() + "\n"


def title_terms(titles: list[str], need: int = 6) -> list[str]:
    words: dict[str, int] = {}
    for t in titles:
        for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", t):
            if w.lower() not in STOP:
                words[w.lower()] = words.get(w.lower(), 0) + 1
    return [w for w, _ in sorted(words.items(), key=lambda x: (-x[1], x[0]))][:need]


def build_protocol(area: str, n: int, titles: list[str], topic_sha: str, depth: str) -> dict:
    """A PCC protocol that passes it_frame.check_protocol: the cited papers are the population, the research area the
    concept. The terms are cut from the cited papers' titles (inputs, not the target paper); nothing is searched."""
    t = title_terms(titles)
    pad = lambda base, k: (base + ["study", "method", "approach"])[:max(k, 3)]  # noqa: E731
    slot = lambda name, value, role: {"slot": name, "value": value, "operational_role": role,  # noqa: E731
                                      "reason": "fixed input: the papers cited by one target paper (RQ-Bench)"}
    return {
        "schema": "ideate-protocol/1", "review_type": "scoping", "reporting_standard": "PRISMA-ScR",
        "purpose": "gap-identification",
        "framework": {"name": "PCC", "rationale": "fixed input: a set of cited papers read for the gaps they leave open",
                      "slots": [slot("population", f"{n} fixed papers cited by one target paper", "search-and-eligibility"),
                                slot("concept", f"{area} research that the cited papers share", "search-and-eligibility"),
                                slot("context", "open problems the cited papers leave", "eligibility-only")]},
        "axes": [{"id": "C1", "kind": "search", "slot": "population", "name": "cited papers", "terms": pad(t[:3], 3)},
                 {"id": "C2", "kind": "search", "slot": "concept", "name": area, "terms": pad(t[3:6] or [area], 3)},
                 {"id": "C3", "kind": "anchor", "name": "area", "terms": [area[:30]]},
                 {"id": "C4", "kind": "contrast", "name": "alternatives", "terms": ["alternative approach"]}],
        "outcomes": [],
        "timeframe": f"2015-{dt.date.today().year}", "timeframe_reason": "nothing is searched; the cited papers are the input",
        "setting": "RQ-Bench fixed input; no search was run",
        "criteria": {"inclusion": [{"id": "IN1", "text": "is one of the fixed set of cited papers", "refs": ["population"]},
                                   {"id": "IN2", "text": f"concerns {area}", "refs": ["concept", "context"]}],
                     "exclusion": [{"id": "EX1", "text": f"is not about {area}", "refs": ["concept"]}]},
        "completion_criterion": COMPLETION, "topic_sha256": topic_sha,
        "written_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "history": []}


def adopt_item(rq_id: str, batch_dir: Path, d: Path, formal: bool, offline: bool, depth: str, llm_toml: Path,
               harness_dir: Path, force: bool) -> dict:
    sp = split_of(d)
    if rq_id in sp["formal"] and not formal:
        raise SystemExit(f"{rq_id} is in the formal set (data/rq-bench/split.json): it is not run during development. "
                         "Use --formal only for the formal experiment.")
    if rq_id not in sp["dev"] and rq_id not in sp["formal"]:
        raise SystemExit(f"{rq_id} is in neither set: only items citing three or more papers are used")
    export, frame, L = load_harness(harness_dir)
    paths = batch_paths(batch_dir)
    name = "rq_" + rq_id.replace(".", "_")
    rd = batch_dir / "sessions" / name
    topic_md = batch_dir / "topics" / f"{name}.md"
    eval_dir = paths["eval"] / name
    if rd.exists():
        if not force:
            raise SystemExit(f"{rd} exists (use --force)")
        shutil.rmtree(rd)

    item = load_rows(d)[rq_id]
    target = as_obj(item["source_paper"])
    refs = as_obj(item["grounded_in_refs"])
    ids = [r["arxiv_id"] for r in refs]
    cited = {i: cited_paper(d, i) for i in ids}
    meta = arxiv_meta(d, ids, offline)
    area = AREA.get(target.get("subfield"), str(target.get("subfield") or "computer science"))
    topic = f"Open research problems in {area} left by {len(ids)} prior studies"

    write_json(eval_dir / "ground_truth.json", {
        "rq_id": rq_id, "question": item["question"], "subfield": target.get("subfield"),
        "target_title": target.get("title"), "target_arxiv_id": target.get("arxiv_id"),
        "refs": [{"arxiv_id": r["arxiv_id"], "title": cited[r["arxiv_id"]].get("title"), "gaps": r.get("gaps") or []} for r in refs]})

    titles = [str(cited[i].get("title") or "") for i in ids]
    tmp_protocol = build_protocol(area, len(ids), titles, "", depth)
    keywords = ", ".join(dict.fromkeys(t for ax in tmp_protocol["axes"] for t in ax["terms"]))
    write_text_lf(topic_md, f"# {topic}\n\n## Research Question\nWhat do these {len(ids)} papers leave open, and what should be "
                            f"asked next?\n\n## Keywords\n{keywords}\n")
    protocol = build_protocol(area, len(ids), titles, hashlib.sha256(topic_md.read_bytes()).hexdigest(), depth)
    now = dt.datetime.now().astimezone()
    cfg = {"topic": topic, "topic_file": str(topic_md), "depth": depth, "timestamp": now.isoformat(timespec="seconds"),
           "session_id": now.strftime("%Y%m%d"), "topic_original": topic, "topic_slug": name, "current_step": 5,
           "field_type": "computer science", "protocol": protocol}
    write_json_lf(rd / "step0_session_config.json", cfg)
    errs = [f for f in frame.check_protocol(cfg, rd) if f["level"] == "ERROR"]
    if errs:
        raise SystemExit("the protocol does not pass check_protocol: " + "; ".join(f"{f['code']} {f['msg']}" for f in errs[:5]))

    papers = []
    for n, i in enumerate(ids, 1):
        c = cited[i]
        papers.append({"id": f"paper_{n:03d}", "title": str(c.get("title") or ""), "authors": meta[i]["authors"] or [f"Arxiv {i}"],
                       "year": meta[i]["year"], "journal": None, "doi": None, "url": f"https://arxiv.org/abs/{i}",
                       "abstract": str(c.get("abstract") or "") or None, "has_abstract": bool(c.get("abstract")),
                       "arxiv_id": i, "pubmed_id": None, "pmc_id": None, "sources_found_in": ["rq-bench"], "found_via": "rq-bench",
                       "venue_type": "preprint", "language": "en", "manually_included": False,
                       "screening": {"relevance": 5, "quality": 5, "recency_impact": 5, "composite": 5.0, "tier": 1,
                                     "category": "included", "rationale": "cited by the RQ-Bench target paper (fixed input)"}})
    write_json_lf(rd / "step3_shortlist.json", {
        "schema": "ideate-shortlist/2", "topic": topic, "session_id": cfg["session_id"], "screening_timestamp": cfg["timestamp"],
        "screening_config": {}, "summary": {"total_screened": len(papers), "included": len(papers), "borderline": 0, "excluded": 0},
        "papers": papers})

    def key_unit() -> dict:
        with L.run_unit(rd, "A4.k", check=lambda: export.check_keys(cfg_now, rd), degraded=lambda: L.degraded_codes(rd, "A4.k")):
            return export.mint_keys(cfg_now, rd, no_snowball="rq-bench import: fixed input, no search and no snowball")

    def fulltext_unit() -> None:
        r = run_tool(harness_dir, "fulltext-status", str(rd))
        if r.returncode:
            raise SystemExit("fulltext-status failed: " + (r.stdout + r.stderr)[-1500:])

    cfg_now = json.loads((rd / "step0_session_config.json").read_text(encoding="utf-8"))
    adopt(L, rd, SEARCH_UNITS)
    minted = key_unit()
    sl = json.loads((rd / "step3_shortlist.json").read_text(encoding="utf-8"))
    for p in sl["papers"]:
        key = p.get("citation_key")
        if key:
            write_text_lf(rd / "step5_full_text" / f"{key}.md", md_of(cited[p["arxiv_id"]]))
            write_json_lf(rd / "step5_full_text" / f"{key}_meta.json", {
                "converter": "rq-bench", "source": f"RQ-Bench cited_papers/{p['arxiv_id']}.json", "at": now.isoformat(timespec="seconds")})
    export.build_bibliography(cfg_now, rd, "", offline=True)
    adopt(L, rd, ["A6.d"])
    fulltext_unit()
    adopt(L, rd, SEARCH_UNITS)                  # settle: record again on the final files (see metasyn_adopt.py)
    key_unit()
    export.build_bibliography(cfg_now, rd, "", offline=True)
    adopt(L, rd, ["A6.d"])
    fulltext_unit()
    open_units = unit_problems(L, rd)
    if open_units:
        raise SystemExit("units not done on the final files: " + "; ".join(open_units))

    answers = {"Question": item["question"], "Target_headline": ((target.get("main_idea") or {}).get("headline")),
               "Target_problem": target.get("problem") if isinstance(target.get("problem"), str) else json.dumps(target.get("problem")),
               "Target_title": target.get("title")}
    for r in refs:                              # the annotated gaps are answers; the cited papers' own text is not
        for k, g in enumerate(r.get("gaps") or []):
            answers[f"Gap_{r['arxiv_id']}_{k}"] = g.get("target_relation")
    # a gap's limitation is often a sentence of the cited paper's own text, so only the target paper's description is matched
    leaks = leaked(rd, {k: v for k, v in answers.items() if v})
    if leaks:
        raise SystemExit(f"answer text found in the research folder: {leaks}")

    write_json(eval_dir / "input_report.json", {
        "rq_id": rq_id, "set": "formal" if rq_id in sp["formal"] else "dev", "session_dir": f"sessions/{name}",
        "topic_file": f"topics/{name}.md", "cited_papers": ids, "authors_from_arxiv": [i for i in ids if not meta[i].get("stand_in")],
        "chars": {i: len(md_of(cited[i])) for i in ids}, "minted": minted, "annotated_gaps": sum(len(r.get("gaps") or []) for r in refs)})
    if not paths["batch"].exists():
        write_json(paths["batch"], {"batch_id": batch_dir.name, "source": "rq-bench adopted fixed input (fusion block)",
                                    "protocol": {"config": {"llm": llm_config(llm_toml)}}})
    if name not in {x["id"] for x in read_runs(batch_dir)}:
        append_run(batch_dir, {"id": name, "topic": topic, "session_dir": f"sessions/{name}", "pipeline_status": "adopted",
                               "steps_done": ["adopt"], "step6_present": False})
    return {"research_dir": str(rd), "topic_file": str(topic_md), "id": name, "cited_papers": len(ids),
            "chars": sum(len(md_of(cited[i])) for i in ids), "annotated_gaps": sum(len(r.get("gaps") or []) for r in refs)}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rq_id", nargs="?")
    ap.add_argument("batch_dir", nargs="?", type=Path)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--set", choices=["dev", "formal"], default="dev", help="--list: which set")
    ap.add_argument("--data-dir", type=Path)
    ap.add_argument("--formal", action="store_true", help="allow an item of the formal set (the formal experiment only)")
    ap.add_argument("--offline", action="store_true", help="no arXiv API: the id stands in for the authors")
    ap.add_argument("--depth", choices=["quick", "standard", "deep"], default="standard")
    ap.add_argument("--llm-toml", type=Path, default=HERE.parent / "step06_sota" / "metasyn.toml")
    ap.add_argument("--harness-dir", type=Path, default=HARNESS)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    d = data_dir(args.data_dir)
    if args.list:
        rows = load_rows(d)
        for i in split_of(d)[args.set]:
            r = rows[i]
            refs = as_obj(r["grounded_in_refs"])
            print(f"{i:<18} refs {len(refs)}  gaps {sum(len(x.get('gaps') or []) for x in refs)}  {as_obj(r['source_paper']).get('subfield')}")
        return 0
    if not args.rq_id or not args.batch_dir:
        ap.error("rq_id and batch_dir are required (or --list)")
    out = adopt_item(args.rq_id, args.batch_dir.resolve(), d, args.formal, args.offline, args.depth, args.llm_toml,
                     args.harness_dir, args.force)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
