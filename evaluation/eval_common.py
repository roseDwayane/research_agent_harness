"""Shared helpers for the Step 6 evaluation batch (run_batch / autosurvey_eval / metasyn_eval / aggregate).

Batch layout (everything a batch produces lives under one folder)::

    evaluation/runs/{batch_id}/
    ├── batch.json            protocol: engine, git, config, prompt versions, model digests
    ├── runs.jsonl            one line per topic, appended as soon as the topic finishes (incl. failures)
    ├── sessions/             fresh harness sessions, one per topic (never edited by hand)
    ├── logs/{topic_id}.log   pipeline console output
    └── eval/{topic_id}/      step6_manifest.json, contract_results.json, numeric_results.json,
                              autosurvey/, metasyn/, controls/
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import requests

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
RUNS_ROOT = HERE / "runs"
# MetaSyn reviews used to tune the judge prompts and the full-text retrieval (2026-10-09 / 10-14); the rest is held out
METASYN_DEV = {255, 356, 225, 243, 324, 70}


def batch_paths(batch_dir: Path) -> dict[str, Path]:
    batch_dir = Path(batch_dir)
    return {
        "batch": batch_dir / "batch.json",
        "runs": batch_dir / "runs.jsonl",
        "sessions": batch_dir / "sessions",
        "logs": batch_dir / "logs",
        "eval": batch_dir / "eval",
    }


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_runs(batch_dir: Path) -> list[dict[str, Any]]:
    path = batch_paths(batch_dir)["runs"]
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_run(batch_dir: Path, record: dict[str, Any]) -> None:
    path = batch_paths(batch_dir)["runs"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def sha256_file(path: Path) -> str | None:
    path = Path(path)
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_script(script: str, args: list[str], log_path: Path | None = None) -> subprocess.CompletedProcess:
    """Run one of the evaluation scripts in this folder with the current interpreter (UTF-8 forced)."""
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(
        [sys.executable, str(HERE / script), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=str(HERE),
    )
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"\n$ {script} {' '.join(args)}\n[exit {proc.returncode}]\n{proc.stdout}{proc.stderr}")
    return proc


def git_info() -> dict[str, Any]:
    def git(*args: str) -> str | None:
        try:
            out = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=10)
            return out.stdout.strip() if out.returncode == 0 else None
        except Exception:  # noqa: BLE001
            return None

    porcelain = git("status", "--porcelain")
    return {
        "sha": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty_files": porcelain.splitlines() if porcelain else [],
    }


def ollama_digest(model: str, base_url: str = "http://127.0.0.1:11434") -> str | None:
    """The exact weights behind an Ollama tag; None when the server or model is unavailable."""
    try:
        tags = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=10).json().get("models", [])
    except Exception:  # noqa: BLE001
        return None
    wanted = {model, model if ":" in model else f"{model}:latest"}
    return next((m.get("digest") for m in tags if m.get("name") in wanted), None)


def tail(text: str, lines: int = 15) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])
