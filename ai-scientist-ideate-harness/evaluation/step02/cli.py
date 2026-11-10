"""Step 2-only commands, backed by the current production STEP-S2."""
import argparse
import json
from pathlib import Path

from evaluation.litsearch.cli import evaluate, run_pipeline


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
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
    result = run_pipeline(a.tasks, a.sessions, step=2, model=a.model, url=a.url, num_ctx=a.num_ctx,
                          max_tokens=a.max_tokens, limit=a.limit) if a.command == "run" else \
        evaluate(a.tasks, a.sessions, a.out, 2, a.mapping, limit=a.limit)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
