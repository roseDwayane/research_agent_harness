from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .adapter import import_official, load_tasks
from .client import ModelConfig, OllamaJSONClient
from .jsonio import append_jsonl, read_json, write_json
from .pipeline import run_p1
from .new_pipeline import prepare_research_dir, run_pipeline_p2
from .ranking import p2_ranking_text, rank_protocol, summarize


def _usage(path: Path) -> dict:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []
    ok = [row for row in rows if row.get("status") == "ok"]
    return {"calls": len(rows), "successful_calls": len(ok),
            "input_tokens": sum((row.get("usage") or {}).get("input_tokens", 0) for row in ok),
            "output_tokens": sum((row.get("usage") or {}).get("output_tokens", 0) for row in ok),
            "wall_seconds": round(sum(float(row.get("wall_seconds") or 0) for row in rows), 3)}


def _usage_by_target(path: Path, task_ids: list[str]) -> dict:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []
    result = {}
    for task_id in task_ids:
        selected = [row for row in rows if str(row.get("tag") or "").startswith(task_id + ":")]
        result[task_id] = {
            "calls": len(selected),
            "input_tokens": sum((row.get("usage") or {}).get("input_tokens", 0) for row in selected),
            "output_tokens": sum((row.get("usage") or {}).get("output_tokens", 0) for row in selected),
            "wall_seconds": round(sum(float(row.get("wall_seconds") or 0) for row in selected), 3),
        }
    return result


def run(dataset: Path, out: Path, generator, judge, *, generator_config: ModelConfig,
        judge_config: ModelConfig, limit: int | None = None, max_questions: int = 3,
        phase: str = "all", seed: int = 0, say=print, p2_runner=run_pipeline_p2) -> dict:
    if phase == "evaluate":
        phase = "rank"
    if phase not in ("all", "prepare", "generate", "rank"):
        raise ValueError("phase must be all, prepare, generate, rank, or evaluate")
    if (generator_config.url.rstrip("/"), generator_config.model.casefold()) == \
            (judge_config.url.rstrip("/"), judge_config.model.casefold()):
        raise ValueError("generator and independent judge must not be the same endpoint/model pair")
    tasks = load_tasks(dataset, limit)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "ideabench-offline-experiment/1", "dataset": str(Path(dataset).resolve()),
        "requested": len(tasks), "fixed_references": 5,
        "order": ["P2 Stage A", "P2 Stage B P1-P5 per adopted question", "n_i = valid P2 idea.json count",
                  "P1 n_i independent generations", "independent novelty/feasibility judge"],
        "gold_source": "target_papers.csv abstract_summary",
        "generation_blinding": "target paper and abstract_summary are not loaded until ranking",
        "generator": generator_config.__dict__, "judge": judge_config.__dict__, "max_questions": max_questions,
        "seed": seed,
    }
    manifest_path = out / "experiment_manifest.json"
    if manifest_path.is_file() and read_json(manifest_path) != manifest:
        raise ValueError("experiment contract changed; use a new output directory")
    write_json(manifest_path, manifest)
    errors, records = [], []
    for index, task in enumerate(tasks, 1):
        pid, refs = task["paperId"], task["references"]
        folder = out / "tasks" / task["taskKey"]
        folder.mkdir(parents=True, exist_ok=True)
        write_json(folder / "references.json", {"count": 5, "references": refs})
        say(f"[{index}/{len(tasks)}] {pid}")
        started = time.time()
        if phase in ("all", "prepare", "generate"):
            prepare_research_dir(folder / "P2" / "research", refs, max_questions=max_questions)
        if phase == "prepare":
            append_jsonl(out / "timing.jsonl", {"paperId": pid, "phase": phase,
                         "wall_seconds": round(time.time() - started, 3)})
            continue
        if phase in ("all", "generate"):
            try:
                if (folder / "P2_ideas.json").is_file():
                    p2 = read_json(folder / "P2_ideas.json")["ideas"]
                    say(f"    P2 resumed: {len(p2)} valid idea.json files")
                else:
                    p2 = p2_runner(folder, refs, generator_config,
                                   max_questions=max_questions, say=say)
                n = len(p2)
                if n < 1:
                    raise ValueError("P2 produced no P5-valid idea.json; n_i is zero")
                if (folder / "P1_ideas.json").is_file():
                    p1 = read_json(folder / "P1_ideas.json")["ideas"]
                    if len(p1) != n:
                        raise ValueError(f"saved P1 count {len(p1)} does not match P2 n_i={n}")
                else:
                    p1 = run_p1(folder, refs, generator, n, say=say)
                complete = {"paperId": pid, "n_i": n, "P1_count": len(p1), "P2_count": len(p2), "status": "ok"}
                write_json(folder / "generation_summary.json", complete)
                write_json(folder / "generation.complete.json", complete)
            except Exception as exc:
                error = {"paperId": pid, "phase": "generate", "error": f"{type(exc).__name__}: {exc}"}
                errors.append(error)
                write_json(folder / "generation_error.json", error)
                say(f"    generation FAILED: {exc}")
        append_jsonl(out / "timing.jsonl", {"paperId": pid, "phase": phase,
                     "wall_seconds": round(time.time() - started, 3)})
    if phase == "prepare":
        result = {"status": "complete", "m_requested": len(tasks), "prepared": len(tasks)}
        write_json(out / "prepare_summary.json", result)
        return result
    if phase == "generate":
        result = {"status": "complete" if not errors else "incomplete", "m_requested": len(tasks), "errors": errors}
        write_json(out / "generation_summary.json", result)
        return result

    for index, task in enumerate(tasks, 1):
        pid, refs, folder = task["paperId"], task["references"], out / "tasks" / task["taskKey"]
        say(f"[{index}/{len(tasks)}] rank {pid}")
        try:
            p1_payload, p2_payload = read_json(folder / "P1_ideas.json"), read_json(folder / "P2_ideas.json")
            if p1_payload["n"] != p2_payload["n"] or p1_payload["n"] < 1:
                raise ValueError("P1/P2 n_i mismatch")
            gold = Path(task["gold_path"]).read_text(encoding="utf-8-sig").strip()
            for protocol, ideas in (
                ("P1", list(p1_payload["ideas"])),
                ("P2", [p2_ranking_text(row["idea"]) for row in p2_payload["ideas"]]),
            ):
                score_path = folder / f"{protocol}_scores.json"
                record = read_json(score_path) if score_path.is_file() else rank_protocol(
                    pid, protocol, ideas, gold, refs, judge, folder, seed=seed, say=say)
                records.append(record)
        except Exception as exc:
            error = {"paperId": pid, "phase": "rank", "error": f"{type(exc).__name__}: {exc}"}
            errors.append(error)
            write_json(folder / "ranking_error.json", error)
            say(f"    ranking FAILED: {exc}")
        write_json(out / "summary.json", summarize(records, [t["paperId"] for t in tasks]))
    summary = summarize(records, [t["paperId"] for t in tasks])
    summary["errors"] = errors
    write_json(out / "summary.json", summary)
    ids = [task["paperId"] for task in tasks]
    keys = [task["taskKey"] for task in tasks]
    generator_by_key = _usage_by_target(out / "generator_ledger.jsonl", keys)
    judge_by_key = _usage_by_target(out / "judge_ledger.jsonl", ids)
    write_json(out / "usage_summary.json", {
        "generator": _usage(out / "generator_ledger.jsonl"), "judge": _usage(out / "judge_ledger.jsonl"),
        "by_target": {task["paperId"]: {
            "generator": generator_by_key[task["taskKey"]], "judge": judge_by_key[task["paperId"]],
        } for task in tasks},
    })
    return summary


def _model(args, prefix: str) -> ModelConfig:
    return ModelConfig(url=getattr(args, f"{prefix}_url"), model=getattr(args, f"{prefix}_model"),
                       num_ctx=getattr(args, f"{prefix}_num_ctx"), num_predict=getattr(args, f"{prefix}_max_tokens"),
                       temperature=getattr(args, f"{prefix}_temperature"), timeout_s=args.timeout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ideabench-offline")
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import", help="adapt the official IdeaBench CSV release")
    imp.add_argument("--source", type=Path, required=True)
    imp.add_argument("--out", type=Path, required=True)
    imp.add_argument("--domain", default="Health & Medicine")
    imp.add_argument("--seed", type=int, default=0)
    imp.add_argument("--limit", type=int)
    go = sub.add_parser("run", help="run offline P2, matched P1, and independent ranking")
    go.add_argument("--dataset", type=Path, required=True)
    go.add_argument("--out", type=Path, required=True)
    go.add_argument("--limit", type=int)
    go.add_argument("--max-questions", type=int, default=3)
    go.add_argument("--phase", choices=("all", "prepare", "generate", "rank", "evaluate"), default="all")
    go.add_argument("--seed", type=int, default=0)
    for prefix in ("generator", "judge"):
        go.add_argument(f"--{prefix}-url", required=True)
        go.add_argument(f"--{prefix}-model", required=True)
        go.add_argument(f"--{prefix}-num-ctx", type=int, default=32768)
        go.add_argument(f"--{prefix}-max-tokens", type=int, default=8192)
        go.add_argument(f"--{prefix}-temperature", type=float, default=0.0)
    go.add_argument("--timeout", type=float, default=3600.0)
    args = parser.parse_args(argv)
    if args.command == "import":
        result = import_official(args.source, args.out, domain=args.domain or None, seed=args.seed, limit=args.limit)
    else:
        generator_cfg, judge_cfg = _model(args, "generator"), _model(args, "judge")
        generator = OllamaJSONClient(generator_cfg, args.out / "generator_ledger.jsonl")
        judge = OllamaJSONClient(judge_cfg, args.out / "judge_ledger.jsonl")
        result = run(args.dataset, args.out, generator, judge, generator_config=generator_cfg,
                     judge_config=judge_cfg, limit=args.limit, max_questions=args.max_questions,
                     phase=args.phase, seed=args.seed)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())

