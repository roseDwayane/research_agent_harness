"""Run manifest (plan §4.4): the diffable record of one engine run.

``run_manifest.json`` is overwritten each run and a copy is kept under
``.runs/{run_id}.json`` so two runs can be diffed with ``scholar-research diff``.
"""
from __future__ import annotations

import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import ENGINE_VERSION
from .utils import dump_json, load_json, sha256_file


def _git_sha() -> str | None:
    try:
        here = Path(__file__).resolve().parent
        out = subprocess.run(["git", "-C", str(here), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:  # pragma: no cover
        return None


@dataclass
class StepRecord:
    step: int
    name: str
    status: str = "pending"  # pending | ok | failed | skipped
    started_at: str | None = None
    wall_seconds: float = 0.0
    inputs: dict[str, str] = field(default_factory=dict)  # relpath → sha256
    outputs: dict[str, str] = field(default_factory=dict)
    prompt_versions: dict[str, str] = field(default_factory=dict)
    cache: dict[str, Any] = field(default_factory=dict)
    llm: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    error: str | None = None


class RunManifest:
    def __init__(self, session_dir: Path, run_id: str, started_at: str, config_public: dict[str, Any], cache_mode: str, mode: str):
        self.session_dir = Path(session_dir)
        self.data: dict[str, Any] = {
            "run_id": run_id,
            "started_at": started_at,
            "engine_version": ENGINE_VERSION,
            "engine_git_sha": _git_sha(),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "cache_mode": cache_mode,
            "checkpoint_mode": mode,
            "config": config_public,
            "steps": [],
            "totals": {},
        }
        self._t0 = time.time()

    def add_step(self, rec: StepRecord) -> None:
        self.data["steps"].append(rec.__dict__)

    def hash_outputs(self, files: list[Path]) -> dict[str, str]:
        out: dict[str, str] = {}
        for f in files:
            if f.exists() and f.is_file():
                out[str(f.relative_to(self.session_dir))] = sha256_file(f)
        return dict(sorted(out.items()))

    def finalize(self, cache_stats: dict[str, Any], llm_totals: dict[str, Any]) -> Path:
        self.data["totals"] = {
            "wall_seconds": round(time.time() - self._t0, 3),
            "cache": cache_stats,
            "llm": llm_totals,
        }
        latest = self.session_dir / "run_manifest.json"
        dump_json(latest, self.data)
        dump_json(self.session_dir / ".runs" / f"{self.data['run_id']}.json", self.data)
        return latest


def diff_manifests(a: Path, b: Path) -> dict[str, Any]:
    """Explain *why* two runs differ: model/prompt/config/input/output hashes."""
    ma, mb = load_json(a), load_json(b)
    report: dict[str, Any] = {"a": str(a), "b": str(b), "engine": {}, "config": {}, "steps": {}}
    for k in ("engine_version", "engine_git_sha", "cache_mode", "checkpoint_mode"):
        if ma.get(k) != mb.get(k):
            report["engine"][k] = [ma.get(k), mb.get(k)]
    ca, cb = ma.get("config", {}), mb.get("config", {})
    for section in sorted(set(ca) | set(cb)):
        if ca.get(section) != cb.get(section):
            report["config"][section] = [ca.get(section), cb.get(section)]
    sa = {s["step"]: s for s in ma.get("steps", [])}
    sb = {s["step"]: s for s in mb.get("steps", [])}
    for step in sorted(set(sa) | set(sb)):
        ra, rb = sa.get(step), sb.get(step)
        if ra is None or rb is None:
            report["steps"][step] = {"only_in": "a" if ra else "b"}
            continue
        d: dict[str, Any] = {}
        for k in ("status", "prompt_versions"):
            if ra.get(k) != rb.get(k):
                d[k] = [ra.get(k), rb.get(k)]
        for k in ("inputs", "outputs"):
            fa, fb = ra.get(k, {}), rb.get(k, {})
            changed = {f: [fa.get(f), fb.get(f)] for f in sorted(set(fa) | set(fb)) if fa.get(f) != fb.get(f)}
            if changed:
                d[k] = changed
        if (ra.get("cache") or {}).get("misses") != (rb.get("cache") or {}).get("misses"):
            d["cache_misses"] = [(ra.get("cache") or {}).get("misses"), (rb.get("cache") or {}).get("misses")]
        if d:
            report["steps"][step] = d
    report["identical_outputs"] = all("outputs" not in v for v in report["steps"].values() if isinstance(v, dict))
    return report
