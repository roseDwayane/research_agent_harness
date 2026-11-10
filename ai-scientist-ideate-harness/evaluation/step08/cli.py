"""Step 8: download/import IdeaBench, then run the P1/P2 offline evaluation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] != "download":
        from ideabench_eval.runner import main as experiment_main
        return experiment_main(args)
    parser = argparse.ArgumentParser(prog="eval-step08 download", description="Download official IdeaBench data")
    parser.add_argument("download", nargs="?")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--revision", default="main", help="Hugging Face branch, tag, or commit SHA")
    parser.add_argument("--timeout", type=float, default=300)
    parsed = parser.parse_args(args)
    from .download import download
    result = download(parsed.out, revision=parsed.revision, timeout=parsed.timeout)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
