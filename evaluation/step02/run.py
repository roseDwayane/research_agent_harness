"""Run live Step 2 and automatically evaluate each saved question."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from scholar_research.config import Config
from scholar_research.llm.prompts import load_prompt
from scholar_research.utils import dump_json, load_json, sha256_obj
from .data import dump_subset, load_frozen_subset
from .ids import build_gold_id_map, dump_map, load_map, unique_corpusids
from .rescore import run as evaluate
from .runner import (
    _load_done, _write_results, eval_config, run_mode_a, run_mode_b,
    score_question, summarise,
)


def run(out: Path, *, subset: Path | None = None, mode: str = "A",
        limit: int | None = None, config: Config | None = None,
        mapping: Path | None = None, say=print) -> bool:
    out = Path(out)
    questions = load_frozen_subset(subset)
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit must be positive")
        questions = questions[:limit]
    if not questions:
        raise ValueError("No benchmark questions selected")
    cfg = config or eval_config(out / "sessions")
    out.mkdir(parents=True, exist_ok=True)
    if mode not in ("A", "B"):
        raise ValueError("Step 2 mode must be A or B")
    contract = {"questions": questions, "mode": mode,
                "config": cfg.public_dict(),
                "initialization_prompt": sha256_obj(load_prompt("s1_init").__dict__) if mode == "B" else None}
    contract_path = out / "run_contract.json"
    if contract_path.exists() and load_json(contract_path) != contract:
        raise ValueError("Run settings changed; use a new --out directory")
    dump_json(contract_path, contract)
    dump_subset(out / "subset_v1.json", questions)
    map_path = out / "gold_id_map.json"
    id_map = load_map(mapping or map_path)
    if mapping is None:
        id_map = build_gold_id_map(unique_corpusids(questions), out / ".cache",
                                   cfg.api.semantic_scholar_key, id_map)
    dump_map(map_path, id_map)
    rows = []
    for question in questions:
        try:
            fn = run_mode_b if mode == "B" else run_mode_a
            row = fn([question], id_map, out, cfg,
                     shared_cache=out / ".cache", say=say)[0]
        except Exception as exc:
            row = score_question(question, [], id_map, 0, 9999)
            row.update(mode=mode, error=f"{type(exc).__name__}: {exc}")
            done = _load_done(out / "results.jsonl")
            done[question["qid"]] = row
            _write_results(out / "results.jsonl", done)
            say(f"{question['qid']}: failed: {row['error']}")
        rows.append(row)
        dump_json(out / "summary.json", summarise(rows, mode=mode))
        with redirect_stdout(StringIO()):
            evaluate(out, out / "subset_v1.json", map_path, out / "evaluation")
        say(f"{question['qid']}: Step 2 evaluation saved to {out / 'evaluation'}")
    return not any(row.get("error") for row in rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("eval_runs/litsearch/step02"))
    parser.add_argument("--subset", type=Path)
    parser.add_argument("--mapping", type=Path, help="Reuse a saved gold map without API lookups")
    parser.add_argument("--mode", choices=["A", "B"], default="A")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--then-step3", action="store_true")
    parser.add_argument("--step3-out", type=Path, default=Path("eval_runs/litsearch/step03"))
    args = parser.parse_args(argv)
    try:
        ok = run(args.out, subset=args.subset, mapping=args.mapping,
                 mode=args.mode, limit=args.limit)
        if args.then_step3:
            from evaluation.step03.run import run_from_step2
            ok = run_from_step2(args.out, args.step3_out) and ok
        return 0 if ok else 1
    except (ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
