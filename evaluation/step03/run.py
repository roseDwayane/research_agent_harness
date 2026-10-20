"""Run Step 3 on saved Step 2 or prepared BM25 candidates, then evaluate."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
from io import StringIO
from pathlib import Path
import shutil

from scholar_research.config import Config
from scholar_research.llm.prompts import load_prompt
from scholar_research.pipeline import run_range
from scholar_research.session import Session
from scholar_research.steps.base import Context
from scholar_research.utils import dump_json, load_json, sha256_obj
from .rank import score_ranking, summarise_rank
from .rescore import run as evaluate
from .runner import _load_done, _write_results, eval_config


def run_from_step2(source: Path, out: Path, *, limit: int | None = None,
                   config: Config | None = None, llm_backend=None, say=print) -> bool:
    source, out = Path(source).resolve(), Path(out).resolve()
    if source == out or source in out.parents or out in source.parents:
        raise ValueError("Step 2 input and Step 3 output must be separate directories")
    questions = load_json(source / "subset_v1.json")["questions"]
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit must be positive")
        questions = questions[:limit]
    if not questions:
        raise ValueError("No benchmark questions selected")
    id_map = load_json(source / "gold_id_map.json")
    prior = _load_done(source / "results.jsonl")
    cfg = config or eval_config(out / "sessions")
    inputs = {}
    for q in questions:
        record = prior.get(q["qid"], {})
        name = record.get("session")
        if name and (Path(name).name != name or name in (".", "..")):
            raise ValueError("Invalid source session name")
        folder = source / "sessions" / name if name else source / "__missing__"
        inputs[q["qid"]] = {"row": record, "files": {
            filename: hashlib.sha256((folder / filename).read_bytes()).hexdigest()
            for filename in ("step0_session_config.json", "step2_raw_papers.json", "step2_gold_trace.json")
            if (folder / filename).is_file()}}
    contract = {"source": str(source), "questions": questions, "inputs": inputs,
                "mapping": id_map, "config": cfg.public_dict(), "gold_hit_gating": False,
                "prompts": {name: sha256_obj(load_prompt(name).__dict__)
                            for name in ("s3_criteria", "s3_score")}}
    out.mkdir(parents=True, exist_ok=True)
    contract_path = out / "run_contract.json"
    if contract_path.exists() and load_json(contract_path) != contract:
        raise ValueError("Frozen inputs or settings changed; use a new --out directory")
    dump_json(contract_path, contract)
    dump_json(out / "subset_v1.json", {"questions": questions})
    dump_json(out / "gold_id_map.json", id_map)
    _write_results(out / "results.jsonl", {q["qid"]: prior[q["qid"]]
                                          for q in questions if q["qid"] in prior})
    done = _load_done(out / "rank.jsonl")
    rows = []
    for q in questions:
        row = done.get(q["qid"])
        if row and not row.get("error"):
            folder = out / "sessions" / row["session"]
            hashes = row.get("outputs_sha256", {})
            if not hashes or any(not (folder / name).is_file()
                                 or hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest
                                 for name, digest in hashes.items()):
                row = None
        if not row or row.get("error"):
            record = prior.get(q["qid"], {})
            row = {"qid": q["qid"], "error": None}
            try:
                if not record or record.get("error") or record.get("skipped"):
                    raise ValueError("Step 2 was not completed for this question")
                name = record.get("session")
                if not name:
                    raise ValueError("Missing Step 2 session")
                folder = out / "sessions" / name
                folder.mkdir(parents=True, exist_ok=True)
                for filename in inputs[q["qid"]]["files"]:
                    shutil.copy2(source / "sessions" / name / filename, folder / filename)
                session = Session(folder, cfg, cache_dir=out / ".cache")
                raw = load_json(folder / "step2_raw_papers.json")
                # Gold is evaluation-only: score every candidate, even on retrieval misses.
                ctx = Context(session, cfg, llm_backend=llm_backend)
                ctx.checkpoint_mode = "auto"
                ctx.ui_print = say
                run_range(ctx, 3, 3)
                screened = load_json(folder / "step3_screening_all.json")["papers"]
                if ({p["id"] for p in screened} != {p["id"] for p in raw["papers"]}
                        or len(screened) != len(raw["papers"])):
                    raise ValueError("Step 3 did not score every frozen candidate exactly once")
                if any(p["screening"]["rationale"].startswith("LLM returned no score") for p in screened):
                    raise ValueError("Fallback scores cannot count as successful evaluation")
                row = score_ranking(q, raw["papers"], id_map, 0, 9999, screened)
                row.update(session=name, error=None)
                row["outputs_sha256"] = {
                    filename: hashlib.sha256((folder / filename).read_bytes()).hexdigest()
                    for filename in ("step3_screening_all.json", "step3_shortlist.json")}
            except Exception as exc:
                row = score_ranking(q, [], id_map, 0, 9999)
                row["error"] = f"{type(exc).__name__}: {exc}"
                say(f"{q['qid']}: failed: {row['error']}")
                # A failed/incomplete screening must not be counted by the evaluator.
                if record.get("session"):
                    marker = out / "sessions" / record["session"] / "step3_shortlist.json"
                    marker.unlink(missing_ok=True)
            done[q["qid"]] = row
            _write_results(out / "rank.jsonl", done)
        rows.append(row)
        dump_json(out / "rank_summary.json", summarise_rank(rows, mode="step03"))
        with redirect_stdout(StringIO()):
            evaluate(out, out / "subset_v1.json", out / "gold_id_map.json", out / "evaluation")
        say(f"{q['qid']}: Step 3 evaluation saved to {out / 'evaluation'}")
    return not any(row.get("error") for row in rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["step02", "bm25"], default="step02")
    parser.add_argument("--input", type=Path, default=Path("eval_runs/litsearch/step02"))
    parser.add_argument("--out", type=Path, default=Path("eval_runs/litsearch/step03"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--bm25-root", type=Path, default=Path("eval_runs/litsearch/official_bm25"))
    args = parser.parse_args(argv)
    try:
        if args.limit is not None and args.limit < 1:
            raise ValueError("--limit must be positive")
        if args.source == "step02":
            ok = run_from_step2(args.input, args.out, limit=args.limit)
        else:
            from .official_bm25 import evaluate as evaluate_bm25, read_jsonl, score
            if not (args.out / "tasks.jsonl").is_file():
                raise ValueError("BM25 requires a prepared --out with tasks.jsonl and sessions; run official_bm25 prepare first")
            score(args.bm25_root, args.out, limit=args.limit)
            tasks = read_jsonl(args.out / "tasks.jsonl")
            if args.limit is not None:
                tasks = tasks[:args.limit]
            summary = evaluate_bm25(args.bm25_root, args.out, tasks=tasks)
            ok = bool(tasks) and summary["completed"] == summary["n"]
        return 0 if ok else 1
    except (ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
