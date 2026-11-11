"""HarnessConfig: everything a run can be tuned by, from `harness.toml` ([harness] table) and the command line.

    [harness]
    python = "/path/to/python"          # interpreter for scripts/ (needs the mcp package); default: this one
    worker = "claude"                   # "claude": claude -p workers | "ollama": an Ollama server, no Claude Code
                                        # | "openai": any OpenAI-compatible API (GPT, Gemini), no Claude Code
    claude = "claude"                   # the Claude Code CLI used for the model Units
    # worker = "ollama": ollama_url = "http://127.0.0.1:11434", model = "qwen3.8", num_ctx = 131072, think = false
    # worker = "openai": api_base = "https://api.openai.com/v1", api_key_env = "OPENAI_API_KEY", model = "...",
    #                    max_context = 128000, api_price_in / api_price_out = USD per 1M tokens, api_budget_usd = 20
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
WORKERS = ("claude", "ollama", "openai")

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
    # worker = "openai": any OpenAI-compatible /chat/completions (OpenAI, Gemini's OpenAI endpoint, ...) - see
    # openai_worker.py. The key is read from the environment variable named here, never from this file.
    api_base: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    max_context: int = 128000                    # the model's context window in tokens (prompt + answer)
    api_max_tokens_field: str = "max_completion_tokens"   # the request field for num_predict ("max_tokens" for some)
    api_reasoning_effort: str | None = None      # a thinking model's `reasoning_effort` ("none" | "low" | "medium" |
                                                 # "high"); its reasoning counts against num_predict and is billed
    api_price_in: float | None = None            # USD per million input tokens - with api_price_out, each call's cost
    api_price_out: float | None = None           # USD per million output tokens   is counted (usage, summary)
    api_budget_usd: float | None = None          # a ceiling for the whole run: past it, no further call is sent
    num_ctx: int = 65536                         # the context the model is run with - Ollama cuts longer prompts silently
    num_predict: int = 16384                     # the longest answer
    think: bool | None = None                    # a thinking model's reasoning on/off (None: the model's default)
    temperature: float | None = None             # None: the model's (Modelfile) default
    max_file_chars: int | None = None            # a file put into an Ollama prompt is cut beyond this; None:
                                                 # half of num_ctx (a digest that fits the context is never cut)
    feedback_rounds: int | None = None           # revisions a refused submission gets (RP-MODEL-OUTPUT); None: the
                                                 # contract's one - a smaller model may be given two or three
    batch_chars: int | None = None               # the material one fan-out call may carry ($BUDGET); None: the
                                                 # worker's own - 0 for claude (the tools' batch sizes), and for ollama
                                                 # what fits num_ctx and max_file_chars, so no batch is ever cut
    max_parallel: int = 4
    ollama_keep_alive: str | None = "30m"        # how long the server keeps the model loaded after a call: the
                                                 # network steps between model Units run longer than Ollama's 5 min,
                                                 # and a reload before the first byte trips a proxy's timeout
    ollama_busy_retries: int = 4                 # an Ollama call that the server or its proxy dropped (busy, a
    ollama_busy_wait_s: float = 120.0            # model reload, error 524) is tried again after this, then twice
                                                 # as long each time (at most 15 minutes)
    ollama_parallel: int = 1                     # fan-out calls at once to one Ollama server: it answers one at a
                                                 # time, and a queued request sends nothing (a proxy closes it)
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
        if self.worker in ("ollama", "openai") and not self.model:
            raise ValueError(f'worker = "{self.worker}" needs a model (e.g. model = "qwen3.8" for ollama, or the '
                             'model name your API key may use for openai)')
        self.module_root = Path(self.module_root)

    @property
    def inline(self) -> bool:
        """A worker without tools: the conductor puts the files into the prompt and writes the JSON answer (ollama,
        openai). A claude worker reads and writes with its own tools."""
        return self.worker != "claude"

    def context_tokens(self) -> int:
        """The context an inline worker's prompt must fit: Ollama's num_ctx, or the API model's max_context."""
        return int(self.num_ctx if self.worker == "ollama" else self.max_context)

    def parallel(self) -> int:
        """Fan-out workers at once: max_parallel, but for an Ollama server at most ollama_parallel."""
        return max(1, min(self.max_parallel, self.ollama_parallel)) if self.worker == "ollama" else self.max_parallel

    def batch_budget(self) -> int:
        """$BUDGET: characters of papers, candidates or terms one worker call is given (a plan command's --max-chars).
        0 keeps the tools' own batch sizes (a claude worker reads its files itself); an inline worker gets everything
        pasted into one prompt, so its batches are cut to what the context and max_file_chars hold."""
        if self.batch_chars is not None:
            return max(0, int(self.batch_chars))
        if not self.inline:
            return 0
        # at most 40k characters (~12k tokens) whatever the context: a server reads such a prompt and sends its first
        # byte before a proxy gives up (100 s at Cloudflare; ~17k tokens took longer on a 27B model), and a refused
        # batch costs little to ask again
        return max(8000, min(self.file_chars(), int(self.context_tokens() * 3.0 * 0.4), 40000))

    def file_chars(self) -> int:
        """The most of one file an inline prompt carries: max_file_chars, or half the context (~3 characters a token)."""
        return int(self.max_file_chars) if self.max_file_chars else int(self.context_tokens() * 3.0 * 0.5)

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
