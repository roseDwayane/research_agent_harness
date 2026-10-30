"""Filesystem trust boundary: which research folders v2 may read, and the only places it may write.

Allowed roots come from IDEATE_ALLOWED_ROOTS (os.pathsep-separated). When unset, the process's working directory is
the only root. A path is accepted only when it resolves - symlinks followed - inside a root. Writes are confined to
<RD>/_state/errors/** and <RD>/ERRORS.md (decision D-07: the legacy ledger ignores exactly these).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import IdeateError, valid_run_id

RUN_DIR_MARKERS = ("step0_session_config.json", "_state/ledger.jsonl", "questions/index.json")
OBS_DIR = "_state/errors"


@dataclass(frozen=True)
class PathPolicy:
    roots: tuple[Path, ...]

    @classmethod
    def from_env(cls, env: dict | None = None, cwd: Path | None = None) -> "PathPolicy":
        env = os.environ if env is None else env
        raw = (env.get("IDEATE_ALLOWED_ROOTS") or "").strip()
        roots = [Path(r) for r in raw.split(os.pathsep) if r.strip()] if raw else [Path(cwd or os.getcwd())]
        return cls(tuple(r.expanduser().resolve() for r in roots))

    def _inside(self, p: Path) -> bool:
        return any(p == r or r in p.parents for r in self.roots)

    def resolve_run_dir(self, raw: str, require_markers: bool = True) -> Path:
        """Resolve a research folder given as an absolute path or relative to the first root."""
        if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
            raise IdeateError("IDEATE.INPUT.INVALID", "run_dir must be a non-empty path string")
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = self.roots[0] / p
        p = p.resolve()
        if not self._inside(p):
            raise IdeateError("IDEATE.PATH.DENIED", "run_dir resolves outside the allowed roots",
                              context={"allowed_roots": [str(r) for r in self.roots]})
        if not p.is_dir():
            raise IdeateError("IDEATE.PATH.NOT_A_RUN_DIR", "run_dir is not a directory", context={"run_dir": str(p)})
        if require_markers and not any((p / m).exists() for m in RUN_DIR_MARKERS):
            raise IdeateError("IDEATE.PATH.NOT_A_RUN_DIR", "not a research folder (no step0_session_config.json, "
                              "_state/ledger.jsonl or questions/index.json)", context={"run_dir": str(p)})
        return p


def observability_dir(run_dir: Path, run_id: str) -> Path:
    """<RD>/_state/errors/<run_id> - the only directory v2 writes into (besides <RD>/ERRORS.md)."""
    if not valid_run_id(run_id):
        raise IdeateError("IDEATE.INPUT.INVALID", f"run_id {run_id!r} does not match r_YYYYMMDD_HHMMSS_xxxx")
    d = (Path(run_dir) / OBS_DIR / run_id).resolve()
    if Path(run_dir).resolve() not in d.parents:
        raise IdeateError("IDEATE.PATH.DENIED", "observability path escapes the research folder")
    return d


def safe_component(name: str) -> str:
    """A file-name component built from a Unit id and an instance (e.g. 'A7.D@leeetal2021', 'B5@gen_2')."""
    cleaned = "".join(ch if ch.isalnum() or ch in "._@-" else "_" for ch in name)
    if not cleaned or cleaned in (".", "..") or cleaned.startswith("."):
        raise IdeateError("IDEATE.INPUT.INVALID", f"unsafe file name component {name!r}")
    return cleaned[:120]
