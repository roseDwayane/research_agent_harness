"""Session = one ``10_Research/{session_id}_{topic_slug}/`` folder.

Replaces the skill's "LLM self-reports ``current_step``" with a state machine
driven by *file existence* plus an explicit ``.state.json``:

* ``step_timestamps`` — pinned per step on first execution so replays produce
  byte-identical files (plan §7.1).  ``--refresh`` re-pins.
* ``checkpoints.json`` — human decisions (plan §5).
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cache import Cache
from .config import CacheMode, Config
from .llm.ledger import Ledger
from .schemas.checkpoints import CheckpointDecision, Checkpoints
from .schemas.session_config import SessionConfig
from .utils import dump_json, load_json, slugify

TZ = _dt.timezone(_dt.timedelta(hours=8))  # Asia/Taipei, matches the skills' examples

STEP_NAMES = {
    1: "research-init",
    2: "research-search",
    3: "research-screen",
    4: "research-export",
    5: "research-fulltext",
    6: "research-sota",
    7: "research-gaps",
    8: "research-hypothesis",
    9: "research-write",
}

# Files whose existence proves a step completed (same names as the skills).
STEP_OUTPUTS: dict[int, list[str]] = {
    1: ["step0_session_config.json", "step1_search_queries.md"],
    2: ["step2_raw_papers.json", "step2_search_summary.md"],
    3: ["step3_screening_results.md", "step3_shortlist.json"],
    4: ["step4_references_apa.md", "step4_citation_keys.md", "step4_references.bib"],
    5: ["step5_full_text/_access_log.md"],
    6: ["step6_sota_review.md", "step6_knowledge_graph.canvas"],
    7: ["step7_gap_analysis.md"],
    8: ["step8_hypothesis_specification.md", "step8_journal_recommendations.md"],
    9: ["step9_manuscript/01_intro.tex", "step9_manuscript/02_relatedwork.tex", "step9_manuscript/references.bib"],
}

STEP_INPUTS: dict[int, list[str]] = {
    1: [],
    2: ["step0_session_config.json"],
    3: ["step0_session_config.json", "step2_raw_papers.json"],
    4: ["step3_shortlist.json"],
    5: ["step3_shortlist.json", "step4_citation_keys.md"],
    6: ["step3_shortlist.json", "step4_citation_keys.md", "step4_references_apa.md"],
    7: ["step0_session_config.json", "step6_sota_review.md"],
    8: ["step0_session_config.json", "step6_sota_review.md", "step7_gap_analysis.md"],
    9: ["step4_references.bib", "step6_sota_review.md", "step7_gap_analysis.md", "step8_hypothesis_specification.md", "step8_journal_recommendations.md", "step3_shortlist.json"],
}

# Checkpoint that must be resolved *after* step N before N+1 may run.
CHECKPOINT_AFTER = {1: 1, 3: 2, 7: 3, 8: 4}
CHECKPOINT_NAMES = {1: "初始定向核准", 2: "邊緣打撈", 3: "戰場選擇", 4: "護城河確認"}


def now_iso() -> str:
    return _dt.datetime.now(TZ).replace(microsecond=0).isoformat()


def make_session_id(when: _dt.datetime | None = None) -> str:
    return (when or _dt.datetime.now(TZ)).strftime("%Y%m%d")


@dataclass
class Clock:
    """Returns a pinned ISO timestamp per step (see module docstring)."""

    session: "Session"

    def for_step(self, step: int) -> str:
        st = self.session.state
        key = str(step)
        if self.session.cache.mode == "refresh" or key not in st["step_timestamps"]:
            st["step_timestamps"][key] = now_iso()
            self.session.save_state()
        return st["step_timestamps"][key]

    @staticmethod
    def date_of(iso: str) -> str:
        return iso[:10]


class Session:
    def __init__(self, session_dir: Path, config: Config, cache_mode: CacheMode | None = None):
        self.dir = Path(session_dir)
        self.config = config
        mode = cache_mode or config.cache_mode
        self.cache = Cache(self.dir / ".cache", mode)
        self.ledger = Ledger(self.dir / ".cache" / "llm" / "ledger.jsonl")
        self.state_path = self.dir / ".state.json"
        self.state: dict[str, Any] = {"step_timestamps": {}, "notes": []}
        if self.state_path.exists():
            self.state.update(load_json(self.state_path))
        self.clock = Clock(self)

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #
    @classmethod
    def create(cls, root: Path, topic: str, config: Config, session_id: str | None = None, cache_mode: CacheMode | None = None) -> "Session":
        sid = session_id or make_session_id()
        slug = slugify(topic)
        d = Path(root) / f"{sid}_{slug}"
        d.mkdir(parents=True, exist_ok=True)
        s = cls(d, config, cache_mode)
        s.state.setdefault("topic_original", topic)
        s.state.setdefault("session_id", sid)
        s.state.setdefault("topic_slug", slug)
        s.save_state()
        return s

    @classmethod
    def find(cls, root: Path, needle: str | None, config: Config, cache_mode: CacheMode | None = None) -> "Session":
        root = Path(root)
        if not root.exists():
            raise FileNotFoundError(f"research root {root} does not exist — run `scholar-research new` first")
        candidates = sorted(p for p in root.iterdir() if p.is_dir() and re.match(r"^\d{8}_", p.name))
        if needle:
            direct = root / needle
            if direct.is_dir():
                return cls(direct, config, cache_mode)
            hits = [p for p in candidates if needle in p.name]
            if len(hits) == 1:
                return cls(hits[0], config, cache_mode)
            if not hits:
                raise FileNotFoundError(f"no session matching {needle!r} under {root}")
            raise ValueError(f"ambiguous session {needle!r}: " + ", ".join(p.name for p in hits))
        if not candidates:
            raise FileNotFoundError(f"no sessions under {root}")
        return cls(candidates[-1], config, cache_mode)  # most recent

    # ------------------------------------------------------------------ #
    def save_state(self) -> None:
        dump_json(self.state_path, self.state)

    @property
    def name(self) -> str:
        return self.dir.name

    def path(self, rel: str) -> Path:
        return self.dir / rel

    def has(self, rel: str) -> bool:
        return (self.dir / rel).exists()

    # session config -------------------------------------------------- #
    def load_config(self) -> SessionConfig:
        return SessionConfig.model_validate(load_json(self.path("step0_session_config.json")))

    def save_config(self, cfg: SessionConfig) -> None:
        dump_json(self.path("step0_session_config.json"), cfg.dump())

    def set_current_step(self, step: int) -> None:
        p = self.path("step0_session_config.json")
        if p.exists():
            data = load_json(p)
            data["current_step"] = max(step, int(data.get("current_step", 0))) if step >= int(data.get("current_step", 0)) else step
            data["current_step"] = step
            dump_json(p, data)

    # status ------------------------------------------------------------ #
    def step_done(self, step: int) -> bool:
        return all(self.has(f) for f in STEP_OUTPUTS[step])

    def completed_steps(self) -> list[int]:
        return [s for s in range(1, 10) if self.step_done(s)]

    def last_completed(self) -> int:
        done = 0
        for s in range(1, 10):
            if self.step_done(s):
                done = s
            else:
                break
        return done

    def missing_inputs(self, step: int) -> list[str]:
        return [f for f in STEP_INPUTS[step] if not self.has(f)]

    # checkpoints ---------------------------------------------------------- #
    def load_checkpoints(self) -> Checkpoints:
        p = self.path("checkpoints.json")
        return Checkpoints.model_validate(load_json(p)) if p.exists() else Checkpoints()

    def record_checkpoint(self, n: int, mode: str, decision: dict[str, Any], note: str = "") -> CheckpointDecision:
        cps = self.load_checkpoints()
        d = CheckpointDecision(checkpoint=n, name=CHECKPOINT_NAMES[n], mode=mode, decided_at=now_iso(), decision=decision, note=note)
        cps.decisions[str(n)] = d
        dump_json(self.path("checkpoints.json"), cps.model_dump())
        return d

    def checkpoint_resolved(self, n: int) -> bool:
        return self.load_checkpoints().get(n) is not None

    def pending_checkpoint(self) -> int | None:
        last = self.last_completed()
        cp = CHECKPOINT_AFTER.get(last)
        if cp and not self.checkpoint_resolved(cp):
            return cp
        return None

    def status(self) -> dict[str, Any]:
        rows = []
        for s in range(1, 10):
            files = [f for f in STEP_OUTPUTS[s] if self.has(f)]
            rows.append({"step": s, "name": STEP_NAMES[s], "done": self.step_done(s), "files": files})
        cfg = self.load_config() if self.has("step0_session_config.json") else None
        return {
            "session": self.name,
            "topic": cfg.topic if cfg else self.state.get("topic_original"),
            "current_step": cfg.current_step if cfg else 0,
            "last_completed": self.last_completed(),
            "pending_checkpoint": self.pending_checkpoint(),
            "checkpoints": {k: v.model_dump() for k, v in self.load_checkpoints().decisions.items()},
            "steps": rows,
            "cache_mode": self.cache.mode,
        }
