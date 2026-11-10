"""Step 3-only commands, backed by the current production STEP-S3."""
import argparse
import json
from pathlib import Path

from evaluation.litsearch.adapter import prepare_step3
from evaluation.litsearch.cli import evaluate, read_jsonl, run_pipeline, selected_tasks


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("download", help="download official LitSearch corpus and build BM25 top-100")
    fetch.add_argument("--out", type=Path, required=True)
    fetch.add_argument("--revision", default=None)
    fetch.add_argument("--limit", type=int)
    fetch.add_argument("--sample", choices=("all", "table7-80"), default="all")
    fetch.add_argument("--seed", type=int, default=20261110)
    prep = sub.add_parser("prepare")
    prep.add_argument("--tasks", type=Path, required=True); prep.add_argument("--corpus", type=Path, required=True)
    prep.add_argument("--sessions", type=Path, required=True); prep.add_argument("--top-k", type=int, default=100)
    prep.add_argument("--limit", type=int)
    run = sub.add_parser("run")
    run.add_argument("--tasks", type=Path, required=True); run.add_argument("--sessions", type=Path, required=True)
    run.add_argument("--model", required=True); run.add_argument("--url", default="http://127.0.0.1:11434")
    run.add_argument("--num-ctx", type=int, default=32768); run.add_argument("--max-tokens", type=int, default=8192)
    run.add_argument("--limit", type=int)
    score = sub.add_parser("evaluate")
    score.add_argument("--tasks", type=Path, required=True); score.add_argument("--sessions", type=Path, required=True)
    score.add_argument("--out", type=Path, required=True); score.add_argument("--mapping", type=Path)
    score.add_argument("--limit", type=int)
    a = ap.parse_args(argv)
    if a.command == "download":
        from evaluation.litsearch.download import DEFAULT_REVISION, download
        result = download(a.out, kind="step03", revision=a.revision or DEFAULT_REVISION,
                          limit=a.limit, sample=a.sample, seed=a.seed)
    elif a.command == "prepare":
        corpus = {str(p["corpusid"]): p for p in read_jsonl(a.corpus)}
        tasks = selected_tasks(a.tasks, a.limit)
        for task in tasks:
            ids = [str(x) for x in task["bm25_top100"][:a.top_k]]
            prepare_step3(a.sessions / task.get("session", task["qid"]), task,
                          [{"id": cid, "title": corpus[cid]["title"], "abstract": corpus[cid]["abstract"]}
                           for cid in ids])
        result = {"status": "complete", "prepared": len(tasks), "top_k": a.top_k}
    elif a.command == "run":
        result = run_pipeline(a.tasks, a.sessions, step=3, model=a.model, url=a.url,
                              num_ctx=a.num_ctx, max_tokens=a.max_tokens, limit=a.limit)
    else:
        result = evaluate(a.tasks, a.sessions, a.out, 3, a.mapping, limit=a.limit)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
