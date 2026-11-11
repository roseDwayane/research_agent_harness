"""Evaluate the production search block after A5 and any A3 rescreening."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.litsearch.adapter import read_json, write_json
from evaluation.litsearch.cli import (_canonical_ids, _completed, _pack, run_pipeline,
                                      selected_tasks, write_jsonl)
from evaluation.litsearch.metrics import ranking_metrics


ZERO = {"R@5": 0.0, "R@20": 0.0, "R@100": 0.0, "MRR": 0.0, "nDCG@10": 0.0}


def _mapping(path):
    return read_json(path) if path else {}


def screening_audit(shortlist: dict, screening_all: dict) -> dict:
    """Report requested fields with production names and explicit derived values."""
    config = shortlist.get("screening_config") or {}
    summary = shortlist.get("summary") or {}
    all_summary = screening_all.get("summary") or {}
    screened = summary.get("screened")
    included = summary.get("included")
    return {
        "threshold": 3.5 if config.get("include_at") == 3.0 else config.get("threshold"),
        "borderline_threshold": config.get("include_at"),
        "weights": {k: (config.get("weights") or {}).get(k)
                    for k in ("relevance", "quality", "recency_impact")},
        "total_screened": screened,
        "included": included,
        "borderline": all_summary.get("borderline"),
        "excluded": summary.get("excluded"),
        "inclusion_rate": included / screened if isinstance(included, int) and
                          isinstance(screened, int) and screened else None,
        "manually_included": sum(bool(p.get("manually_included"))
                                 for p in screening_all.get("papers") or []),
        "source_fields": {"threshold": "production it_legacy.INCLUDED_FLOOR (tiers 1-3 start at 3.5)",
                          "borderline_threshold": "step3_shortlist.screening_config.include_at",
                          "total_screened": "step3_shortlist.summary.screened",
                          "borderline": "step3_screening_all.summary.borderline",
                          "inclusion_rate": "included / screened",
                          "manually_included": "count(step3_screening_all.papers[].manually_included)"}}


def rank_final_papers(papers: list[dict], by: str) -> list[dict]:
    """Production excludes some candidates before scoring; put unscored ones last."""
    def key(p):
        score = p.get("screening") or {}
        rel, comp = score.get("relevance"), score.get("composite")
        if by == "relevance":
            return (rel is None, -(rel or 0), -(comp or 0), str(p["id"]))
        if by == "composite":
            return (comp is None, -(comp or 0), str(p["id"]))
        raise ValueError("ranking must be relevance or composite")
    return sorted(papers, key=key)


def evaluate(tasks_path: Path, sessions: Path, out: Path, mapping_path: Path | None = None,
             limit: int | None = None) -> dict:
    tasks, mapping, rows = selected_tasks(tasks_path, limit), _mapping(mapping_path), []
    for task in tasks:
        rd = sessions / task.get("session", task["qid"])
        raw_path = rd / "step2_raw_papers.json"
        raw = read_json(raw_path).get("papers") or [] if raw_path.is_file() else []
        initial_ids = _canonical_ids(raw, mapping)
        gold = [str(x) for x in task["corpusids"]]
        marker = rd / "_state" / "evaluation" / "step4_complete.json"
        complete = marker.is_file() and _completed(rd, 4, read_json(marker).get("key", {}))
        screen_path = rd / "step3_screening_all.json"
        shortlist_path = rd / "step3_shortlist.json"
        if complete and screen_path.is_file() and shortlist_path.is_file():
            screen = read_json(screen_path)
            shortlist = read_json(shortlist_path)
            papers = screen["papers"]
            snowball = read_json(rd / "step2b_snowball_papers.json").get("papers") or []
            final_ids = _canonical_ids(raw + snowball, mapping)
            audit = screening_audit(shortlist, screen)
        else:
            papers, final_ids, audit = [], initial_ids, None
        row = {**task, "step2_hit": bool(set(initial_ids) & set(gold)),
               "final_gold_hit": bool(set(final_ids) & set(gold)) if complete else False,
               "final_status": "completed" if complete else "failed_or_incomplete",
               "initial_set_size": len(initial_ids), "final_set_size": len(final_ids) if complete else None,
               "screening_audit": audit}
        row["relevance"] = ranking_metrics(gold, _canonical_ids(rank_final_papers(papers, "relevance"), mapping)) \
            if complete else dict(ZERO)
        row["composite"] = ranking_metrics(gold, _canonical_ids(rank_final_papers(papers, "composite"), mapping)) \
            if complete else dict(ZERO)
        rows.append(row)

    def status(xs):
        return {"questions": len(xs), "step2_gold_hit": sum(r["step2_hit"] for r in xs),
                "final_gold_hit": sum(r["final_gold_hit"] for r in xs),
                "final_completed": sum(r["final_status"] == "completed" for r in xs),
                "final_failed_or_incomplete": sum(r["final_status"] == "failed_or_incomplete" for r in xs)}
    modes = sorted({str(r.get("mode")) for r in rows if r.get("mode") is not None})
    summary = {"schema": "litsearch-current-step0203/2", "n": len(rows),
               "checkpoint": "STEP-S4 GATE-a5-check after A5 and any A3 rescreen",
               "execution": status(rows),
               "by_mode": {mode: status([r for r in rows if str(r.get("mode")) == mode]) for mode in modes},
               "relevance": _pack(rows, "relevance"), "composite": _pack(rows, "composite"),
               "metric_denominator": "all questions; failed or incomplete final checkpoints score zero",
               "gold_exposed_to_pipeline": False}
    write_jsonl(out / "results.jsonl", rows)
    write_json(out / "summary.json", summary)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("download", help="download official LitSearch queries and gold IDs")
    fetch.add_argument("--out", type=Path, required=True)
    fetch.add_argument("--revision", default=None)
    fetch.add_argument("--limit", type=int)
    fetch.add_argument("--sample", choices=("all", "table7-80"), default="all")
    fetch.add_argument("--seed", type=int, default=20261110)
    mapping = sub.add_parser("map-ids", help="resolve gold CorpusIds before a live Step 2 run")
    mapping.add_argument("--tasks", type=Path, required=True)
    mapping.add_argument("--out", type=Path, required=True)
    mapping.add_argument("--delay", type=float)
    mapping.add_argument("--limit", type=int)
    for name in ("run", "evaluate"):
        p = sub.add_parser(name)
        p.add_argument("--tasks", type=Path, required=True)
        p.add_argument("--sessions", type=Path, required=True)
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("--mapping", type=Path)
        p.add_argument("--limit", type=int, help="run/evaluate only the first N tasks in the frozen task file")
        if name == "run":
            p.add_argument("--model", required=True)
            p.add_argument("--url", default="http://127.0.0.1:11434")
            p.add_argument("--num-ctx", type=int, default=32768)
            p.add_argument("--max-tokens", type=int, default=8192)
    a = ap.parse_args(argv)
    if a.command == "download":
        from evaluation.litsearch.download import DEFAULT_REVISION, download
        result = download(a.out, kind="step0203", revision=a.revision or DEFAULT_REVISION,
                          limit=a.limit, sample=a.sample, seed=a.seed)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if a.command == "map-ids":
        from evaluation.litsearch.mapping import build_mapping
        result = build_mapping(a.tasks, a.out, delay=a.delay, limit=a.limit)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["status"] == "complete" else 1
    if a.command == "run":
        run_pipeline(a.tasks, a.sessions, step=4, model=a.model, url=a.url,
                     num_ctx=a.num_ctx, max_tokens=a.max_tokens, limit=a.limit)
    result = evaluate(a.tasks, a.sessions, a.out, a.mapping, limit=a.limit)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
