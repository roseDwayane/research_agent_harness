"""Prepare and evaluate LitSearch against current STEP-S2/STEP-S3 artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .adapter import prepare_step3, read_json, scored_papers, verify_frozen, write_json
from .metrics import ranking_metrics


def read_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def write_jsonl(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")


def selected_tasks(path: Path, limit: int | None = None) -> list[dict]:
    if limit is not None and limit < 1:
        raise ValueError("--limit must be a positive integer")
    tasks = read_jsonl(path)
    return tasks[:limit] if limit is not None else tasks


def _pack(rows, key):
    names = ("R@5", "R@20", "R@100", "MRR", "nDCG@10")
    return {name: sum(r[key][name] for r in rows) / len(rows) if rows else None for name in names}


def _completion_path(rd: Path, step: int) -> Path:
    return rd / "_state" / "evaluation" / f"step{step}_complete.json"


def _completion_key(task: dict, step: int, model: str, url: str, num_ctx: int,
                    max_tokens: int, rd: Path) -> dict:
    key = {"qid": task["qid"], "query": task["query"], "step": step,
           "model": model, "url": url, "num_ctx": num_ctx, "max_tokens": max_tokens,
           "think": False}
    if step == 3:
        contract = rd / "_state" / "evaluation" / "input_contract.json"
        if contract.is_file():
            key["input_sha256"] = hashlib.sha256(contract.read_bytes()).hexdigest()
    return key


def _completed(rd: Path, step: int, key: dict) -> bool:
    marker = _completion_path(rd, step)
    if not marker.is_file():
        return False
    try:
        record = read_json(marker)
        if record.get("key") != key or not record.get("summary"):
            return False
        summary = rd / record["summary"]
        if not summary.is_file():
            return False
        report = read_json(summary)
        if report.get("failed") or not any(s.get("step") == f"STEP-S{step}" and
                                           s.get("status") in ("done", "degraded") for s in report.get("steps", [])):
            return False
        if step == 4 and not any(g.get("gate") == "GATE-a5-check" and g.get("passed")
                                 for g in report.get("gates", [])):
            return False
        required = {2: ("step2_raw_papers.json",),
                    3: ("screening_scores.json", "step3_shortlist.json"),
                    4: ("step2_raw_papers.json", "step2b_snowball_papers.json",
                        "screening_scores.json", "step3_shortlist.json",
                        "step3_screening_all.json")}[step]
        return all((rd / name).is_file() and
                   hashlib.sha256((rd / name).read_bytes()).hexdigest() == record.get("outputs", {}).get(name)
                   for name in required)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def run_pipeline(tasks_path: Path, sessions: Path, *, step: int, model: str, url: str,
                 num_ctx: int, max_tokens: int, limit: int | None = None) -> dict:
    """Run the production conductor; benchmark gold is never written into its research directory."""
    from harness.config import HarnessConfig
    from harness.context import RunContext
    from harness.executors import RecipeExecutor
    from harness.pipeline import PipelineAgent
    from harness.recipes import load as load_recipes
    from harness.skill import Skill
    from ideate_v2.registry import Registry

    tasks, completed, skipped, failures = selected_tasks(tasks_path, limit), [], [], []
    for task in tasks:
        rd = sessions / task.get("session", task["qid"])
        try:
            key = _completion_key(task, step, model, url, num_ctx, max_tokens, rd)
            if _completed(rd, step, key):
                if step == 3 and (rd / "_state" / "evaluation" / "input_hashes.json").is_file():
                    verify_frozen(rd)
                print(f"{task['qid']}: STEP-S{step} already complete; skipped", flush=True)
                completed.append(task["qid"])
                skipped.append(task["qid"])
                write_json(sessions / f"step{step}_progress.json", {
                    "status": "running", "completed": completed, "skipped": skipped,
                    "failures": failures, "total": len(tasks)})
                continue
            if step in (2, 4):
                topic = sessions / "_topics" / f"{task['qid']}.md"
                topic.parent.mkdir(parents=True, exist_ok=True)
                topic.write_text("# LitSearch benchmark query\n\n" + task["query"] + "\n", encoding="utf-8")
                frm, to = "S1", "S2" if step == 2 else "S4"
            else:
                if (rd / "_state" / "evaluation" / "input_hashes.json").is_file():
                    verify_frozen(rd)
                topic, frm, to = rd / "litsearch_topic.md", "S3", "S3"
            cfg = HarnessConfig(worker="ollama", model=model, ollama_url=url, num_ctx=num_ctx,
                                num_predict=max_tokens, think=False,
                                max_num_generations=1, resume=True)
            reg, recipes, default = Registry.load(), load_recipes(), RecipeExecutor()
            ctx = RunContext(reg, cfg, Skill(cfg), rd, topic,
                             say=lambda message, q=task["qid"]: print(f"{q}: {message}", flush=True))
            summary = PipelineAgent(reg, recipes, lambda _unit: default).run(ctx, frm, to)
            if summary["failed"]:
                raise RuntimeError(f"pipeline stopped: {summary['status']}")
            if not any(s.get("step") == f"STEP-S{step}" and s.get("status") in ("done", "degraded")
                       for s in summary.get("steps", [])):
                raise RuntimeError(f"STEP-S{step} did not complete")
            if step == 4 and not any(g.get("gate") == "GATE-a5-check" and g.get("passed")
                                     for g in summary.get("gates", [])):
                raise RuntimeError("GATE-a5-check did not pass")
            required = {2: ("step2_raw_papers.json",),
                        3: ("screening_scores.json", "step3_shortlist.json"),
                        4: ("step2_raw_papers.json", "step2b_snowball_papers.json",
                            "screening_scores.json", "step3_shortlist.json",
                            "step3_screening_all.json")}[step]
            if not all((rd / name).is_file() for name in required):
                raise RuntimeError(f"STEP-S{step} missing output artifacts")
            write_json(_completion_path(rd, step), {"key": key,
                       "summary": str((ctx.state_dir / "summary.json").relative_to(rd)),
                       "outputs": {name: hashlib.sha256((rd / name).read_bytes()).hexdigest()
                                   for name in required}})
            completed.append(task["qid"])
        except Exception as exc:  # one question must not erase the rest of a long benchmark run
            failures.append({"qid": task["qid"], "error": f"{type(exc).__name__}: {exc}"})
        write_json(sessions / f"step{step}_progress.json", {
            "status": "running", "completed": completed, "skipped": skipped,
            "failures": failures, "total": len(tasks)})
    result = {"status": "complete" if len(completed) == len(tasks) else "incomplete",
              "completed": len(completed), "skipped": len(skipped), "total": len(tasks), "failures": failures}
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


def evaluate(tasks_path: Path, sessions: Path, out: Path, step: int, mapping_path: Path | None = None,
             limit: int | None = None) -> dict:
    mapping = read_json(mapping_path) if mapping_path else {}
    rows = []
    for task in selected_tasks(tasks_path, limit):
        rd = sessions / task.get("session", task["qid"])
        raw = read_json(rd / "step2_raw_papers.json").get("papers") or []
        ids = _canonical_ids(raw, mapping)
        gold = [str(x) for x in task["corpusids"]]
        gold_set = set(gold)
        row = {**task, "set_size": len(ids),
               "step2_set_recall": len(gold_set & set(ids)) / len(gold_set) if gold_set else 0.0,
               "completed": True}
        if step == 3:
            if (rd / "_state" / "evaluation" / "input_hashes.json").is_file():
                verify_frozen(rd)
            papers = scored_papers(rd)
            from evaluation.step03.scoring import rank_papers
            for name in ("relevance", "composite"):
                ordered = rank_papers(papers, name)
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
