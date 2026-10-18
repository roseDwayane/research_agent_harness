#!/usr/bin/env python3
"""MetaSyn fixed-input Step 6 runs: build a harness session from one MetaSyn review, run Steps 4 and 6.

Step 6 is given the papers the source review included (MetaSyn ``matched_corpus_ids`` minus
``source_review_corpus_ids``), so retrieval and screening play no part in the score:

  step0_session_config.json   Topic + PI/ECO from MetaSyn (Intervention, or Exposure when there is none)
  step3_shortlist.json        the included papers, all "included" with a flat screening score
  step4_*                     real Step 4 (deterministic, no network)
  step5_full_text/{key}.md    MetaSyn corpus text: abstract + PMC sections when available
  step6_*                     real Step 6 (pipeline model from --pipeline-toml)

The ground truth (Key_Insights, Effect_Direction, Conclusion_Summary, …) is written to
``eval/{review}/ground_truth.json`` only — never into the session folder Step 6 reads.

Papers that cannot enter Step 6 are dropped and listed in ``eval/{review}/input_report.json``:
no abstract and no sections (title only), or no authors even after a PubMed lookup
(Step 4 skips author-less papers). PubMed is queried only for papers missing authors.

MetaSyn has 336 train and 86 test reviews (disjoint source reviews, shared corpus). Develop on train
(--split train) and keep test for the final evaluation.

    python evaluation/step06_sota/metasyn_prepare.py --data-dir <dir with {split}.parquet and corpus/> --split train --review-id 12 --batch-id metasyn_dev
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.dataset as ds
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # scholar_research without pip install
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # evaluation/: eval_common, run_batch

from scholar_research import ENGINE_VERSION  # noqa: E402
from scholar_research.config import tomllib  # noqa: E402
from scholar_research.pipeline import run_range  # noqa: E402
from scholar_research.schemas.paper import Screening, ScreenedPaper, Shortlist, ShortlistSummary, ScreeningConfigOut  # noqa: E402
from scholar_research.schemas.session_config import PICO, EngineInfo, SessionConfig  # noqa: E402
from scholar_research.session import Session  # noqa: E402
from scholar_research.steps.base import Context  # noqa: E402
from scholar_research.utils import dump_json, frontmatter, load_json, write_text  # noqa: E402

from eval_common import RUNS_ROOT, append_run, batch_paths, read_runs, write_json  # noqa: E402
from run_batch import build_config, protocol  # noqa: E402

GROUND_TRUTH_FIELDS = (
    "Title", "Topic", "Research_Question", "Population", "Intervention", "Exposure", "Comparison", "Outcome",
    "Effect_Direction", "Statistical_Significance", "Effect_Size_Category", "Conclusion_Summary", "Key_Insights",
    "inclusion_criteria", "exclusion_criteria", "search_start_date", "search_end_date", "study_count",
    "matched_ref_count", "source",
)
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def _str(v: Any) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def _year(v: Any) -> int | None:
    s = _str(v)[:4]
    return int(s) if s.isdigit() else None


def load_review(data_dir: Path, review_id: int, split: str = "test") -> dict[str, Any]:
    df = pd.read_parquet(data_dir / f"{split}.parquet")
    rows = df[df["ID"] == review_id]
    if rows.empty:
        raise SystemExit(f"review {review_id} is not in the {split} split")
    return rows.iloc[0].to_dict()


def load_articles(data_dir: Path, ids: list[int]) -> list[dict[str, Any]]:
    table = ds.dataset(data_dir / "corpus", format="parquet").to_table(filter=ds.field("ID").isin(ids))
    by_id = {int(r["ID"]): r for r in table.to_pylist()}
    return [by_id[i] for i in ids if i in by_id]


def pubmed_authors(pmid: str) -> list[str]:
    r = requests.get(EFETCH, params={"db": "pubmed", "id": pmid, "retmode": "xml"}, timeout=30)
    r.raise_for_status()
    out = []
    for a in ET.fromstring(r.content).iter("Author"):
        fn, ln = a.findtext("ForeName") or "", a.findtext("LastName") or ""
        if ln:
            out.append(f"{fn} {ln}".strip())
        elif a.findtext("CollectiveName"):
            out.append(a.findtext("CollectiveName"))
    return out


def article_text(a: dict[str, Any]) -> tuple[str, str]:
    """→ (access_level, markdown body) in the step5_full_text layout."""
    abstract = _str(a.get("abstract"))
    sections = [s for s in (a.get("sections") or []) if _str(s.get("text"))]
    parts = ["## Abstract", "", abstract or "(no abstract available)", ""]
    for s in sections:
        parts += [f"## {_str(s.get('heading')).title() or 'Section'}", "", _str(s["text"]), ""]
    return ("full-text-html" if sections else "abstract-only"), "\n".join(parts).rstrip() + "\n"


def build_papers(articles: list[dict[str, Any]]) -> tuple[list[ScreenedPaper], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    papers, texts, dropped = [], {}, []
    screening = Screening(relevance=5, quality=5, recency_impact=5, composite=5.0, tier=1, category="included",
                          rationale="MetaSyn reference article (fixed Step 6 input)")
    for a in articles:
        cid, title = int(a["ID"]), _str(a.get("title"))
        level, body = article_text(a)
        if not _str(a.get("abstract")) and level == "abstract-only":
            dropped.append({"corpus_id": cid, "title": title, "reason": "no abstract and no sections"})
            continue
        authors = [x for x in (a.get("authors") or []) if _str(x)]
        author_source = "metasyn"
        if not authors and _str(a.get("pmid")):
            try:
                authors, author_source = pubmed_authors(_str(a["pmid"])), "pubmed"
            except Exception as e:  # noqa: BLE001 — recorded, the paper is dropped below
                author_source = f"pubmed failed: {type(e).__name__}"
        if not authors:
            dropped.append({"corpus_id": cid, "title": title, "reason": f"no authors ({author_source})"})
            continue
        pid = f"paper_{len(papers) + 1:03d}"
        pmid, pmc = _str(a.get("pmid")), _str(a.get("pmc_id"))
        papers.append(ScreenedPaper(
            id=pid, title=title, authors=authors, year=_year(a.get("year")), journal=_str(a.get("journal")) or None,
            doi=_str(a.get("doi")) or None, url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
            abstract=_str(a.get("abstract")) or None, pubmed_id=pmid or None, pmc_id=pmc or None,
            sources_found_in=["metasyn"], found_via="metasyn", venue_type="journal", screening=screening,
        ))
        texts[pid] = {"corpus_id": cid, "access_level": level, "body": body, "author_source": author_source}
    return papers, texts, dropped


def write_inputs(s: Session, review: dict[str, Any], papers: list[ScreenedPaper], model: str) -> None:
    ts = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).replace(microsecond=0).isoformat()
    y0, y1 = _year(review.get("search_start_date")), _year(review.get("search_end_date"))
    pico = PICO(
        population=_str(review.get("Population")),
        intervention=_str(review.get("Intervention")) or _str(review.get("Exposure")),
        comparison=_str(review.get("Comparison")),
        outcome=_str(review.get("Outcome")),
        timeframe=f"{y0 or ''}-{y1 or ''}".strip("-"),
    )
    sid = s.state["session_id"]
    cfg = SessionConfig(session_id=sid, topic=_str(review["Topic"]), topic_original=_str(review["Topic"]),
                        topic_slug=s.state["topic_slug"], timestamp=ts, current_step=5, pico=pico,
                        field_type="biomedical", engine=EngineInfo(version=ENGINE_VERSION, llm_model=model))
    s.save_config(cfg)
    n = len(papers)
    sl = Shortlist(session_id=sid, topic=cfg.topic, screening_timestamp=ts,
                   screening_config=ScreeningConfigOut(threshold=0.0, borderline_threshold=0.0, weights={}),
                   summary=ShortlistSummary(total_screened=n, included=n, borderline=0, excluded=0, inclusion_rate="100%"),
                   papers=papers)
    dump_json(s.path("step3_shortlist.json"), sl.model_dump(mode="json"))


def write_fulltext(s: Session, papers: list[ScreenedPaper], texts: dict[str, dict[str, Any]], date: str) -> None:
    keys = load_json(s.path("step4_citation_keys.json"))
    ft = s.path("step5_full_text")
    ft.mkdir(exist_ok=True)
    rows = []
    for p in papers:
        if p.id not in keys:
            continue
        k, t = keys[p.id]["key"], texts[p.id]
        fm = {"citation_key": k, "title": p.title, "authors": ", ".join(p.authors), "year": p.year or "",
              "doi": p.doi or "", "source": f"MetaSyn corpus ({t['corpus_id']})", "access_level": t["access_level"],
              "retrieved_date": date, "extraction_method": "metasyn-corpus", "char_count": len(t["body"])}
        write_text(ft / f"{k}.md", "\n".join([frontmatter(fm), "", f"# {p.title}", "", t["body"]]))
        rows.append(f"| `{k}` | {t['access_level']} | MetaSyn corpus {t['corpus_id']} |")
    write_text(ft / "_access_log.md", "\n".join(["# Access log", "", "Fixed input from the MetaSyn corpus (no fetching).", "",
                                                  "| Key | Access level | Source |", "|---|---|---|"] + rows) + "\n")


def register(batch_dir: Path, cfg: Any) -> int:
    """batch.json + one runs.jsonl line per review, so naive_baseline.py and autosurvey_eval.py run on this batch."""
    paths = batch_paths(batch_dir)
    if not paths["batch"].exists():
        write_json(paths["batch"], {"batch_id": batch_dir.name, "source": "metasyn fixed input (Steps 4 and 6 only)",
                                    "protocol": protocol(cfg, 6)})
    known = {r["id"] for r in read_runs(batch_dir)}
    added = 0
    for review_dir in sorted(paths["eval"].glob("review_*")):
        report = review_dir / "input_report.json"
        if review_dir.name in known or not report.exists():
            continue
        session = batch_dir / load_json(report)["session_dir"]
        if not (session / "step6_sota_review.md").exists():
            continue
        append_run(batch_dir, {"id": review_dir.name, "topic": load_json(session / "step0_session_config.json")["topic"],
                               "session_dir": load_json(report)["session_dir"], "pipeline_status": "ok", "steps_done": [4, 6],
                               "step6_present": True})
        added += 1
    return added


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, help="folder with {train,test}.parquet and corpus/*.parquet")
    ap.add_argument("--split", choices=["train", "test"], default="test",
                    help="MetaSyn split of --review-id (develop on train, keep test for the final evaluation)")
    ap.add_argument("--review-id", type=int)
    ap.add_argument("--register-only", action="store_true", help="only (re)write batch.json / runs.jsonl for finished reviews")
    ap.add_argument("--batch-id", required=True)
    ap.add_argument("--pipeline-toml", type=Path, default=Path(__file__).with_name("metasyn.toml"),
                    help="TOML whose [pipeline] section sets the pipeline model (default: metasyn.toml)")
    ap.add_argument("--config", default=None, help="research.toml (optional)")
    ap.add_argument("--prepare-only", action="store_true", help="build the session and Step 4, do not run Step 6")
    args = ap.parse_args()

    with open(args.pipeline_toml, "rb") as fh:
        pipeline = tomllib.load(fh).get("pipeline", {})
    batch_dir = RUNS_ROOT / args.batch_id
    paths = batch_paths(batch_dir)
    cfg = build_config(args.config, pipeline, paths["sessions"])
    if args.register_only:
        print(f"registered {register(batch_dir, cfg)} reviews")
        return 0
    if args.data_dir is None or args.review_id is None:
        raise SystemExit("--data-dir and --review-id are required unless --register-only")

    review = load_review(args.data_dir, args.review_id, args.split)
    source_ids = {int(x) for x in (review.get("source_review_corpus_ids") if review.get("source_review_corpus_ids") is not None else [])}
    ref_ids = [int(x) for x in review["matched_corpus_ids"] if int(x) not in source_ids]
    articles = load_articles(args.data_dir, ref_ids)
    papers, texts, dropped = build_papers(articles)
    if not papers:
        raise SystemExit("no usable input papers")

    rid = f"review_{args.review_id}"
    eval_dir = paths["eval"] / rid
    write_json(eval_dir / "ground_truth.json", {"review_id": args.review_id, "split": args.split,
                                                **{f: _str(review.get(f)) for f in GROUND_TRUTH_FIELDS},
                                                "extracted_titles": [str(x) for x in review["extracted_titles"]]})
    session = Session.create(paths["sessions"], _str(review["Topic"]), cfg, session_id=dt.date.today().strftime("%Y%m%d"))
    if session.has("step3_shortlist.json"):
        raise SystemExit(f"session already exists: {session.dir}")
    write_inputs(session, review, papers, cfg.llm.model)
    # Checkpoint 2 (borderline rescue) has nothing to decide: every input paper is included.
    session.record_checkpoint(2, "fixed-input", {"include": []}, note="MetaSyn fixed input — no borderline papers")

    ctx = Context(session, cfg)
    ctx.checkpoint_mode = "auto"
    run_range(ctx, 4, 4)
    write_fulltext(session, papers, texts, dt.date.today().isoformat())
    keys = load_json(session.path("step4_citation_keys.json"))
    write_json(eval_dir / "input_report.json", {
        "review_id": args.review_id, "session_dir": str(session.dir.relative_to(batch_dir)),
        "matched_corpus_ids": len(review["matched_corpus_ids"]), "source_review_ids_excluded": sorted(source_ids),
        "found_in_corpus": len(articles), "papers_in": len(papers), "with_keys": len(keys),
        "full_text": sum(1 for p in papers if p.id in keys and texts[p.id]["access_level"] != "abstract-only"),
        "authors_from_pubmed": [texts[p.id]["corpus_id"] for p in papers if texts[p.id]["author_source"] == "pubmed"],
        "dropped": dropped, "study_count": review.get("study_count"),
    })
    if not args.prepare_only:
        ctx = Context(session, cfg)
        ctx.checkpoint_mode = "auto"
        run_range(ctx, 6, 6)
    print(f"session: {session.dir}\neval: {eval_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
