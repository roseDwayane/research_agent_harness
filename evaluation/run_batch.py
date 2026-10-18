#!/usr/bin/env python3
"""Phase A — run Steps 1–N (default 6) for every topic in a fresh session; produces a batch, evaluates nothing.

Per topic, in order:
  1. create a brand-new session under runs/{batch_id}/sessions/ (refuses to reuse a folder);
  2. run the harness pipeline with the batch's single Config and auto checkpoints
     (CP1 approve, CP2 no borderline rescue) — nobody edits anything in between;
  3. record the outcome in runs.jsonl, failures included (failed step, error, timing, tokens).

Each step's evaluation runs afterwards from that step's folder, e.g.
step06_sota/run_checks.py (deterministic) or step05_fulltext/check_step5_contract.py;
LLM-judge scoring stays separate so the judge and the pipeline model never compete for the GPU.

    python evaluation/run_batch.py --topics evaluation/topics.toml
    python evaluation/run_batch.py --topics evaluation/topics.toml --batch-id smoke1 --resume
"""
from __future__ import annotations

import argparse
import datetime as dt
import platform
import sys
import time
import traceback
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scholar_research without pip install

from scholar_research import ENGINE_VERSION  # noqa: E402
from scholar_research.config import Config, tomllib  # noqa: E402
from scholar_research.llm.prompts import list_prompts, load_prompt  # noqa: E402
from scholar_research.pipeline import run_range  # noqa: E402
from scholar_research.session import STEP_NAMES, Session  # noqa: E402
from scholar_research.steps.base import Context  # noqa: E402
from scholar_research.utils import slugify  # noqa: E402

from eval_common import (  # noqa: E402
    RUNS_ROOT, append_run, batch_paths, git_info, ollama_digest, read_json, read_runs, sha256_file, write_json,
)


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #
def load_topics(path: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    topics = data.get("topics", [])
    ids = [t["id"] for t in topics]
    if not topics or len(ids) != len(set(ids)):
        raise SystemExit(f"{path}: need a non-empty [[topics]] list with unique ids")
    slugs = [slugify(t["topic"]) for t in topics]
    if len(slugs) != len(set(slugs)):
        raise SystemExit(f"{path}: two topics map to the same session folder slug")
    return topics, data.get("pipeline", {})


def build_config(config_path: str | None, pipeline: dict[str, Any], sessions_root: Path) -> Config:
    """One Config for the whole batch: research.toml/env, then the [pipeline] section of topics.toml."""
    cfg = Config.load(config_path)
    for key, value in pipeline.items():
        if key in ("until",):
            continue
        if not hasattr(cfg.llm, key):
            raise SystemExit(f"[pipeline] {key!r} is not an [llm] setting")
        setattr(cfg.llm, key, value)
    cfg.llm = type(cfg.llm).model_validate(cfg.llm.model_dump())
    cfg.paths.research_root = str(sessions_root)
    return cfg


def protocol(cfg: Config, until: int) -> dict[str, Any]:
    llm = cfg.llm
    return {
        "engine_version": ENGINE_VERSION,
        "git": git_info(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "steps": [1, until],
        "checkpoint_mode": "auto",
        "config": cfg.public_dict(),
        "prompt_versions": {name: load_prompt(name).version for name in list_prompts()},
        "pipeline_model": {
            "provider": llm.provider,
            "model": llm.model,
            "ollama_digest": ollama_digest(llm.model, llm.base_url) if llm.provider == "ollama" else None,
        },
    }


# --------------------------------------------------------------------------- #
# one topic
# --------------------------------------------------------------------------- #
def run_topic(topic: dict[str, str], cfg: Config, batch_dir: Path, session_id: str, until: int,
              backend: Any = None, echo: bool = True) -> dict[str, Any]:
    paths = batch_paths(batch_dir)
    log_path = paths["logs"] / f"{topic['id']}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {"id": topic["id"], "topic": topic["topic"], "started_at": _now()}

    session_dir = paths["sessions"] / f"{session_id}_{slugify(topic['topic'])}"
    if session_dir.exists():
        record.update(pipeline_status="setup_error", error=f"session folder already exists: {session_dir}")
        return _finish(record)
    record["session_dir"] = str(session_dir.relative_to(batch_dir))

    with open(log_path, "a", encoding="utf-8") as log:
        def say(message: str) -> None:
            log.write(message + "\n")
            log.flush()
            if echo:
                print(message, flush=True)

        session = Session.create(paths["sessions"], topic["topic"], cfg, session_id=session_id)
        ctx = Context(session, cfg, llm_backend=backend)
        ctx.checkpoint_mode = "auto"
        ctx.ui_print = say
        t0 = time.time()
        try:
            run_range(ctx, 1, until)
        except Exception as exc:  # noqa: BLE001 — every failure is data
            record["error"] = f"{type(exc).__name__}: {exc}"
            say(traceback.format_exc())
        record["wall_seconds"] = round(time.time() - t0, 1)

    manifest_path = session_dir / "run_manifest.json"
    steps = read_json(manifest_path)["steps"] if manifest_path.exists() else []
    record["steps"] = [
        {"step": s["step"], "name": s["name"], "status": s["status"], "wall_seconds": s.get("wall_seconds"),
         "error": s.get("error"), "llm": {k: v for k, v in (s.get("llm") or {}).items() if k != "by_prompt"}}
        for s in steps
    ]
    done = [s["step"] for s in steps if s["status"] == "ok"]
    failed = next((s for s in steps if s["status"] != "ok"), None)
    if done == list(range(1, until + 1)):
        record["pipeline_status"] = "ok"
    else:
        record["pipeline_status"] = "failed"
        record["failed_step"] = failed["step"] if failed else (max(done, default=0) + 1)
        record["failed_step_name"] = STEP_NAMES.get(record["failed_step"])
        record.setdefault("error", failed.get("error") if failed else "pipeline stopped early")

    review = session_dir / "step6_sota_review.md"
    record["step6_present"] = review.exists()
    record["step6_sha256_at_run_end"] = sha256_file(review)
    return _finish(record)


def _now() -> str:
    return dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _finish(record: dict[str, Any]) -> dict[str, Any]:
    record["finished_at"] = _now()
    return record


# --------------------------------------------------------------------------- #
def run_batch(topics: list[dict[str, str]], cfg: Config, batch_dir: Path, until: int,
              resume: bool = False, backend: Any = None, echo: bool = True) -> list[dict[str, Any]]:
    paths = batch_paths(batch_dir)
    if paths["batch"].exists() and not resume:
        raise SystemExit(f"{batch_dir} already exists; pass --resume to continue it or pick a new --batch-id")
    if paths["batch"].exists():
        batch = read_json(paths["batch"])
        if batch["protocol"]["config"] != cfg.public_dict():
            raise SystemExit("--resume: config differs from the one recorded in batch.json; start a new batch")
    else:
        batch = {"batch_id": batch_dir.name, "created_at": _now(), "protocol": protocol(cfg, until),
                 "topics": topics}
        write_json(paths["batch"], batch)
    session_id = batch["created_at"][:10].replace("-", "")

    finished = {r["id"] for r in read_runs(batch_dir)}
    records = []
    for i, topic in enumerate(topics, 1):
        if topic["id"] in finished:
            print(f"[{i}/{len(topics)}] {topic['id']}: already recorded, skipping")
            continue
        # An unreachable model server is an infrastructure fault, not a pipeline result: stop the batch
        # without writing a record, so --resume reruns this topic once the server is back.
        if backend is None and cfg.llm.provider == "ollama" and ollama_digest(cfg.llm.model, cfg.llm.base_url) is None:
            raise SystemExit(f"Ollama at {cfg.llm.base_url} is not reachable or has no model {cfg.llm.model!r}; "
                             f"start it, then rerun with --resume (topic {topic['id']} not recorded)")
        print(f"\n===== [{i}/{len(topics)}] {topic['id']}: {topic['topic']} =====", flush=True)
        record = run_topic(topic, cfg, batch_dir, session_id, until, backend=backend, echo=echo)
        append_run(batch_dir, record)
        records.append(record)
        print(f"→ {record['pipeline_status']}"
              + (f" at step {record.get('failed_step')}: {record.get('error')}" if record["pipeline_status"] != "ok" else ""),
              flush=True)
    return records


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--topics", default=str(Path(__file__).with_name("topics.toml")))
    parser.add_argument("--config", default=None, help="research.toml (default: ./research.toml if present)")
    parser.add_argument("--batch-id", default=None, help="default: timestamp")
    parser.add_argument("--resume", action="store_true", help="continue a batch; topics already in runs.jsonl are skipped")
    parser.add_argument("--only", nargs="+", help="topic ids to run (default: all)")
    args = parser.parse_args()

    topics, pipeline = load_topics(Path(args.topics))
    if args.only:
        topics = [t for t in topics if t["id"] in args.only]
    until = int(pipeline.get("until", 6))
    batch_dir = RUNS_ROOT / (args.batch_id or dt.datetime.now().strftime("%Y%m%dT%H%M%S"))
    cfg = build_config(args.config, pipeline, batch_paths(batch_dir)["sessions"])
    run_batch(topics, cfg, batch_dir, until, resume=args.resume)

    runs = read_runs(batch_dir)
    ok = sum(r["pipeline_status"] == "ok" for r in runs)
    print(f"\nbatch {batch_dir}: {ok}/{len(runs)} topics completed Steps 1–{until}")
    print(f"next: python evaluation/step06_sota/run_checks.py --batch {batch_dir}\n"
          f"      then the LLM-judge evaluations, e.g. python evaluation/step06_sota/autosurvey_eval.py --batch {batch_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
