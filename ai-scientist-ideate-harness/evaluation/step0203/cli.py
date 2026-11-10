"""Run/evaluate Step 2 followed by Step 3 only for questions with a confirmed gold hit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.litsearch.adapter import read_json, scored_papers, write_json
from evaluation.litsearch.cli import (_canonical_ids, _pack, read_jsonl, run_pipeline, write_jsonl)
from evaluation.litsearch.metrics import ranking_metrics
from evaluation.step03.scoring import rank_papers


ZERO = {"R@5": 0.0, "R@20": 0.0, "R@100": 0.0, "MRR": 0.0, "nDCG@10": 0.0}


def _mapping(path):
    return read_json(path) if path else {}


def hit_tasks(tasks, sessions: Path, mapping: dict):
    hits = []
    for task in tasks:
        rd = sessions / task.get("session", task["qid"])
        raw = read_json(rd / "step2_raw_papers.json").get("papers") or []
        if set(_canonical_ids(raw, mapping)) & {str(x) for x in task["corpusids"]}:
            hits.append(task)
    return hits


def evaluate(tasks_path: Path, sessions: Path, out: Path, mapping_path: Path | None = None) -> dict:
    tasks, mapping, rows = read_jsonl(tasks_path), _mapping(mapping_path), []
    for task in tasks:
        rd = sessions / task.get("session", task["qid"])
        raw = read_json(rd / "step2_raw_papers.json").get("papers") or [] if rd.exists() else []
        ids, gold = _canonical_ids(raw, mapping), [str(x) for x in task["corpusids"]]
        hit = bool(set(ids) & set(gold))
        complete = hit and (rd / "step3_screening_all.json").is_file()
        if hit and not complete and (rd / "screening_scores.json").is_file() and (rd / "step3_shortlist.json").is_file():
            papers = scored_papers(rd)
            complete = True
        elif complete:
            papers = read_json(rd / "step3_screening_all.json")["papers"]
        else:
            papers = []
        row = {**task, "step2_hit": hit, "step3_status": "completed" if complete else
               "skipped_step2_miss" if not hit else "failed_or_incomplete", "set_size": len(ids)}
        row["relevance"] = ranking_metrics(gold, _canonical_ids(rank_papers(papers, "relevance"), mapping)) \
            if complete else dict(ZERO)
        row["composite"] = ranking_metrics(gold, _canonical_ids(rank_papers(papers, "composite"), mapping)) \
            if complete else dict(ZERO)
        rows.append(row)

    def status(xs):
        return {"questions": len(xs), "step2_gold_hit": sum(r["step2_hit"] for r in xs),
                "step3_completed": sum(r["step3_status"] == "completed" for r in xs),
                "step3_skipped_step2_miss": sum(r["step3_status"] == "skipped_step2_miss" for r in xs),
                "step3_failed_or_incomplete": sum(r["step3_status"] == "failed_or_incomplete" for r in xs)}
    modes = sorted({str(r.get("mode")) for r in rows if r.get("mode") is not None})
    summary = {"schema": "litsearch-current-step0203/1", "n": len(rows), "execution": status(rows),
               "by_mode": {mode: status([r for r in rows if str(r.get("mode")) == mode]) for mode in modes},
               "relevance": _pack(rows, "relevance"), "composite": _pack(rows, "composite"),
               "metric_denominator": "all questions; skipped/failed Step 3 questions score zero",
               "gold_exposed_to_pipeline": False}
    write_jsonl(out / "results.jsonl", rows)
    write_json(out / "summary.json", summary)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("run", "evaluate"):
        p = sub.add_parser(name)
        p.add_argument("--tasks", type=Path, required=True)
        p.add_argument("--sessions", type=Path, required=True)
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("--mapping", type=Path)
        if name == "run":
            p.add_argument("--model", required=True)
            p.add_argument("--url", default="http://127.0.0.1:11434")
            p.add_argument("--num-ctx", type=int, default=32768)
            p.add_argument("--max-tokens", type=int, default=8192)
    a = ap.parse_args(argv)
    if a.command == "run":
        run_pipeline(a.tasks, a.sessions, step=2, model=a.model, url=a.url,
                     num_ctx=a.num_ctx, max_tokens=a.max_tokens)
        tasks = read_jsonl(a.tasks)
        selected = hit_tasks(tasks, a.sessions, _mapping(a.mapping))
        selected_path = a.out / "step3_tasks.jsonl"
        write_jsonl(selected_path, selected)
        if selected:
            run_pipeline(selected_path, a.sessions, step=3, model=a.model, url=a.url,
                         num_ctx=a.num_ctx, max_tokens=a.max_tokens)
    result = evaluate(a.tasks, a.sessions, a.out, a.mapping)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
