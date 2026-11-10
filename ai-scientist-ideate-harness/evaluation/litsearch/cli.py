"""Prepare and evaluate LitSearch against current STEP-S2/STEP-S3 artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapter import prepare_step3, read_json, scored_papers, verify_frozen, write_json
from .metrics import ranking_metrics


def read_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def write_jsonl(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")


def _pack(rows, key):
    names = ("R@5", "R@20", "R@100", "MRR", "nDCG@10")
    return {name: sum(r[key][name] for r in rows) / len(rows) if rows else None for name in names}


def run_pipeline(tasks_path: Path, sessions: Path, *, step: int, model: str, url: str,
                 num_ctx: int, max_tokens: int) -> dict:
    """Run the production conductor; benchmark gold is never written into its research directory."""
    from harness.config import HarnessConfig
    from harness.context import RunContext
    from harness.executors import RecipeExecutor
    from harness.pipeline import PipelineAgent
    from harness.recipes import load as load_recipes
    from harness.skill import Skill
    from ideate_v2.registry import Registry

    tasks, completed, failures = read_jsonl(tasks_path), [], []
    for task in tasks:
        rd = sessions / task.get("session", task["qid"])
        try:
            if step == 2:
                topic = sessions / "_topics" / f"{task['qid']}.md"
                topic.parent.mkdir(parents=True, exist_ok=True)
                topic.write_text("# LitSearch benchmark query\n\n" + task["query"] + "\n", encoding="utf-8")
                frm, to = "S1", "S2"       # S1 creates the frame needed by S2; only S2 is scored.
            else:
                verify_frozen(rd)
                topic, frm, to = rd / "litsearch_topic.md", "S3", "S3"
            cfg = HarnessConfig(worker="ollama", model=model, ollama_url=url, num_ctx=num_ctx,
                                num_predict=max_tokens, max_num_generations=1, resume=True)
            reg, recipes, default = Registry.load(), load_recipes(), RecipeExecutor()
            ctx = RunContext(reg, cfg, Skill(cfg), rd, topic,
                             say=lambda message, q=task["qid"]: print(f"{q}: {message}", flush=True))
            summary = PipelineAgent(reg, recipes, lambda _unit: default).run(ctx, frm, to)
            if summary["failed"]:
                raise RuntimeError(f"pipeline stopped: {summary['status']}")
            completed.append(task["qid"])
        except Exception as exc:  # one question must not erase the rest of a long benchmark run
            failures.append({"qid": task["qid"], "error": f"{type(exc).__name__}: {exc}"})
        write_json(sessions / f"step{step}_progress.json", {
            "status": "running", "completed": completed, "failures": failures, "total": len(tasks)})
    result = {"status": "complete" if len(completed) == len(tasks) else "incomplete",
              "completed": len(completed), "total": len(tasks), "failures": failures}
    write_json(sessions / f"step{step}_progress.json", result)
    return result


def _canonical_ids(papers: list[dict], mapping: dict) -> list[str]:
    aliases = {}
    for cid, rec in mapping.items():
        if not rec or not rec.get("ok"):
            continue
        for value in (rec.get("paperId"), rec.get("doi"), rec.get("arxiv_id")):
            if value:
                aliases[str(value).casefold()] = str(cid)
    result = []
    for paper in papers:
        values = [paper.get("id"), paper.get("paperId"), paper.get("doi"), paper.get("arxiv_id"),
                  paper.get("openalex_id")]
        result.append(next((aliases[str(v).casefold()] for v in values if v and str(v).casefold() in aliases),
                           str(paper["id"])))
    return result


def evaluate(tasks_path: Path, sessions: Path, out: Path, step: int, mapping_path: Path | None = None) -> dict:
    mapping = read_json(mapping_path) if mapping_path else {}
    rows = []
    for task in read_jsonl(tasks_path):
        rd = sessions / task.get("session", task["qid"])
        raw = read_json(rd / "step2_raw_papers.json").get("papers") or []
        ids = _canonical_ids(raw, mapping)
        gold = [str(x) for x in task["corpusids"]]
        gold_set = set(gold)
        row = {**task, "set_size": len(ids),
               "step2_set_recall": len(gold_set & set(ids)) / len(gold_set) if gold_set else 0.0,
               "completed": True}
        if step == 3:
            verify_frozen(rd)
            papers = scored_papers(rd)
            for name in ("relevance", "composite"):
                ordered = sorted(papers, key=lambda p: (-p["screening"][name], str(p["id"])))
                ranked = _canonical_ids(ordered, mapping)
                row[name] = ranking_metrics(gold, ranked)
            row["bm25"] = ranking_metrics(gold, ids)
            kept = read_json(rd / "step3_shortlist.json").get("papers") or []
            row["shortlist_size"] = len(kept)
        rows.append(row)
    summary = {"schema": f"litsearch-current-step{step}/1", "n": len(rows),
               "step2": {"set_recall": sum(r["step2_set_recall"] for r in rows) / len(rows) if rows else None,
                         "mean_set_size": sum(r["set_size"] for r in rows) / len(rows) if rows else None},
               "gold_exposed_to_pipeline": False}
    if step == 3:
        summary.update(bm25=_pack(rows, "bm25"), relevance=_pack(rows, "relevance"),
                       composite=_pack(rows, "composite"))
    write_jsonl(out / "results.jsonl", rows)
    write_json(out / "summary.json", summary)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare-step3")
    prep.add_argument("--tasks", type=Path, required=True)
    prep.add_argument("--corpus", type=Path, required=True)
    prep.add_argument("--sessions", type=Path, required=True)
    prep.add_argument("--top-k", type=int, default=100)
    for name in ("evaluate-step2", "evaluate-step3"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--tasks", type=Path, required=True)
        cmd.add_argument("--sessions", type=Path, required=True)
        cmd.add_argument("--out", type=Path, required=True)
        cmd.add_argument("--mapping", type=Path,
                         help="gold_id_map.json for live Step 2 provider IDs; not needed for corpus-ID BM25")
    for name in ("run-step2", "run-step3"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--tasks", type=Path, required=True)
        cmd.add_argument("--sessions", type=Path, required=True)
        cmd.add_argument("--model", required=True)
        cmd.add_argument("--url", default="http://127.0.0.1:11434")
        cmd.add_argument("--num-ctx", type=int, default=32768)
        cmd.add_argument("--max-tokens", type=int, default=8192)
    a = ap.parse_args(argv)
    if a.command == "prepare-step3":
        corpus = {str(p["corpusid"]): p for p in read_jsonl(a.corpus)}
        for task in read_jsonl(a.tasks):
            ids = [str(x) for x in task["bm25_top100"][:a.top_k]]
            candidates = [{"id": cid, "title": corpus[cid]["title"], "abstract": corpus[cid]["abstract"]}
                          for cid in ids]
            prepare_step3(a.sessions / task.get("session", task["qid"]), task, candidates)
        result = {"status": "complete", "prepared": len(read_jsonl(a.tasks)), "top_k": a.top_k}
    elif a.command.startswith("run-"):
        result = run_pipeline(a.tasks, a.sessions, step=2 if a.command.endswith("step2") else 3,
                              model=a.model, url=a.url, num_ctx=a.num_ctx, max_tokens=a.max_tokens)
    else:
        result = evaluate(a.tasks, a.sessions, a.out, 2 if a.command.endswith("step2") else 3, a.mapping)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
