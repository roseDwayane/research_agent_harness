"""HarnessConfig: everything a run can be tuned by, from `harness.toml` ([harness] table) and the command line.

    [harness]
    python = "/path/to/python"          # interpreter for scripts/ (needs the mcp package); default: this one
    worker = "claude"                   # "claude": claude -p workers | "ollama": an Ollama server, no Claude Code
    claude = "claude"                   # the Claude Code CLI used for the model Units
    # worker = "ollama": ollama_url = "http://127.0.0.1:11434", model = "qwen3.8", num_ctx = 131072, think = false
    model = "claude-opus-5-5"           # optional; default: the CLI's own
    max_parallel = 4                    # fan-out workers at once
    default_budget_usd = 5.0            # per worker (claude -p --max-budget-usd); unset: no cap
    worker_timeout_s = 3600
    command_timeout_s = 3600
    depth = "standard"                  # quick | standard | deep
    max_num_generations = 3
    num_reflections = 3

    [harness.unit_budget_usd]           # per Unit, overrides default_budget_usd
    A3 = 20.0

    [harness.loop_bounds]               # the loops the contracts leave unbounded (OQ-07); others come from the contracts
    "LOOP-03" = 2
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:                      # Python 3.10
    tomllib = None  # type: ignore[assignment]

MODULE_ROOT = Path(__file__).resolve().parent.parent
DEPTHS = ("quick", "standard", "deep")
WORKERS = ("claude", "ollama")

# Conservative bounds for the loops the contracts state no number for (OQ-07). LOOP-11 is bounded by the ready
# questions that remain and LOOP-12 by max_num_generations; they are not listed here.
DEFAULT_LOOP_BOUNDS = {"LOOP-03": 2, "LOOP-05": 1, "LOOP-06": 1}


@dataclass
class HarnessConfig:
    python: str = sys.executable
    worker: str = "claude"                       # who does the model Units: "claude" (claude -p) | "ollama" (HTTP API)
    claude: str = "claude"
    model: str | None = None
    ollama_url: str = "http://127.0.0.1:11434"   # worker = "ollama": the server (OLLAMA_API_KEY -> Bearer header)
    ollama_api_key_env: str = "OLLAMA_API_KEY"
    num_ctx: int = 65536                         # the context the model is run with - Ollama cuts longer prompts silently
    num_predict: int = 16384                     # the longest answer
    think: bool | None = None                    # a thinking model's reasoning on/off (None: the model's default)
    temperature: float | None = None             # None: the model's (Modelfile) default
    max_file_chars: int = 60000                  # a file put into an Ollama prompt is cut beyond this
    max_parallel: int = 4
    default_budget_usd: float | None = None
    unit_budget_usd: dict[str, float] = field(default_factory=dict)
    worker_timeout_s: float = 3600.0
    command_timeout_s: float = 3600.0
    depth: str = "standard"
    max_num_generations: int = 3
    num_reflections: int = 3
    loop_bounds: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_LOOP_BOUNDS))
    replay: bool = False                         # IDEATE_REPLAY=1: network answers from the recordings
    smoke_cap: int | None = None                 # IDEATE_SMOKE_CAP: every per-source / snowball limit (a smoke test)
    dry_run: bool = False                        # FakeSkill + FakeExecutor
    fixtures: Path | None = None                 # dry run: the research folder copied from (default: evals/datasets)
    inject: dict[str, list[str]] = field(default_factory=dict)   # dry run: faults to inject, see fake.py
    resume: bool = True                          # skip a Unit that is already done (and not stale)
    module_root: Path = MODULE_ROOT

    def __post_init__(self) -> None:
        if self.depth not in DEPTHS:
            raise ValueError(f"depth must be one of {DEPTHS}, not {self.depth!r}")
        if self.max_parallel < 1:
            raise ValueError("max_parallel must be >= 1")
        if self.worker not in WORKERS:
            raise ValueError(f"worker must be one of {WORKERS}, not {self.worker!r}")
        if self.worker == "ollama" and not self.model:
            raise ValueError('worker = "ollama" needs a model (e.g. model = "qwen3.8")')
        self.module_root = Path(self.module_root)

    def budget(self, unit_id: str) -> float | None:
        return self.unit_budget_usd.get(unit_id, self.default_budget_usd)

    def env(self) -> dict[str, str]:
        """The environment of every command the conductor runs."""
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "IDEATE_PYTHON": self.python}
        if self.replay:
            env["IDEATE_REPLAY"] = "1"
        if self.smoke_cap:
            env["IDEATE_SMOKE_CAP"] = str(int(self.smoke_cap))
        if self.model:                           # recorded as step0 engine.llm_model (scripts/it_legacy.py)
            env.setdefault("IDEATE_LLM_MODEL", self.model)
        return env

    @classmethod
    def load(cls, path: Path | None = None, **overrides) -> "HarnessConfig":
        data: dict = {}
        if path is not None:
            if tomllib is None:
                raise RuntimeError("reading harness.toml needs Python >= 3.11 (tomllib)")
            with open(path, "rb") as f:
                data = dict((tomllib.load(f) or {}).get("harness") or {})
        if "loop_bounds" in data:
            data["loop_bounds"] = {**DEFAULT_LOOP_BOUNDS, **data["loop_bounds"]}
        if data.get("fixtures"):
            data["fixtures"] = Path(data["fixtures"]).expanduser()
        known = set(cls.__dataclass_fields__)
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"unknown [harness] key(s) in {path}: {', '.join(unknown)}")
        data.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**data)
