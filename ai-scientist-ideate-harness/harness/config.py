"""HarnessConfig: everything a run can be tuned by, from `harness.toml` ([harness] table) and the command line.

    [harness]
    python = "/path/to/python"          # interpreter for scripts/ (needs the mcp package); default: this one
    worker = "claude"                   # the provider of the model Units (harness/providers/): "claude" = the Anthropic
                                        # Messages API, "gpt" = the OpenAI API, "gemini" = the Gemini API, "ollama" =
                                        # an Ollama server, or "package.module:Class"
    # worker = "ollama": ollama_url = "http://127.0.0.1:11434", model = "qwen3.8", num_ctx = 131072, think = false
    model = "claude-opus-5-5"           # optional; default: the provider's own (claude: claude-opus-5-5, gpt:
                                        # gpt-6-astra, gemini: gemini-4-argon; ollama needs one)
    max_parallel = 4                    # fan-out workers at once
    worker_timeout_s = 3600
    command_timeout_s = 3600
    depth = "standard"                  # quick | standard | deep
    max_num_generations = 3
    num_reflections = 3

    [harness.loop_bounds]               # the loops the contracts leave unbounded (OQ-07); others come from the contracts
    "LOOP-03" = 2

    [harness.provider_options.claude]   # a provider's own settings (Provider.options()), under its worker name: the
    effort = "high"                     # APIs' are in harness/providers/claude.py, gpt.py, gemini.py

    [harness.provider_options.my_api]   # ... and a provider of one's own reads its table the same way
    base_url = "https://llm.example.org/v1"
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

# [harness] keys of the claude -p worker, removed with it: a config that still sets them is told so
REMOVED_KEYS = ("claude", "default_budget_usd", "unit_budget_usd")

# Conservative bounds for the loops the contracts state no number for (OQ-07). LOOP-11 is bounded by the ready
# questions that remain and LOOP-12 by max_num_generations; they are not listed here.
DEFAULT_LOOP_BOUNDS = {"LOOP-03": 2, "LOOP-05": 1, "LOOP-06": 1}


@dataclass
class HarnessConfig:
    python: str = sys.executable
    worker: str = "claude"                       # the provider of the model Units (providers/): "claude" (Messages
                                                 # API) | "gpt" | "gemini" | "ollama" | "package.module:Class"
    model: str | None = None                     # None: the provider's default_model() (claude: claude-opus-5-5,
                                                 # gpt: gpt-6-astra, gemini: gemini-4-argon)
    ollama_url: str = "http://127.0.0.1:11434"   # worker = "ollama": the server (OLLAMA_API_KEY -> Bearer header)
    ollama_api_key_env: str = "OLLAMA_API_KEY"
    num_ctx: int = 65536                         # the context the model is run with - Ollama cuts longer prompts silently
    num_predict: int = 16384                     # the longest answer
    think: bool | None = None                    # a thinking model's reasoning on/off (None: the model's default)
    temperature: float | None = None             # None: the model's (Modelfile) default
    max_file_chars: int | None = None            # a file put into a chat prompt is cut beyond this; None: half
                                                 # of the context (a digest that fits the context is never cut)
    feedback_rounds: int | None = None           # revisions a refused submission gets (RP-MODEL-OUTPUT); None: the
                                                 # contract's one - a smaller model may be given two or three
    batch_chars: int | None = None               # the material one fan-out call may carry ($BUDGET); None: the
                                                 # provider's own - 0 for an agent (the tools' batch sizes), and
                                                 # for a chat model (claude, gpt, gemini, ollama) what fits its context and
                                                 # max_file_chars, at most 40k characters, so no batch is ever cut
    max_parallel: int = 4
    ollama_keep_alive: str | None = "30m"        # how long the server keeps the model loaded after a call: the
                                                 # network steps between model Units run longer than Ollama's 5 min,
                                                 # and a reload before the first byte trips a proxy's timeout
    ollama_busy_retries: int = 4                 # an Ollama call that the server or its proxy dropped (busy, a
    ollama_busy_wait_s: float = 120.0            # model reload, error 524) is tried again after this, then twice
                                                 # as long each time (at most 15 minutes)
    ollama_parallel: int = 1                     # fan-out calls at once to one Ollama server: it answers one at a
                                                 # time, and a queued request sends nothing (a proxy closes it)
    provider_options: dict[str, dict] = field(default_factory=dict)   # [harness.provider_options.<name>]: a
                                                 # provider's own settings (claude's, or one of your own)
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
        provider = self.provider_class()              # an unknown worker raises here
        if not self.model:
            self.model = provider.default_model(self)
        provider.check_config(self)                  # a config its provider cannot run with
        self.module_root = Path(self.module_root)

    def provider_class(self):
        """The provider class `worker` names (harness/providers/)."""
        from .providers import provider_class        # here, not at the top: a provider's module may import this one
        return provider_class(self.worker)

    def parallel(self) -> int:
        """Fan-out workers at once: max_parallel, or fewer where the provider says so (an Ollama server: ollama_parallel)."""
        return self.provider_class().parallel(self)

    def batch_budget(self) -> int:
        """$BUDGET: characters of papers, candidates or terms one worker call is given (a plan command's --max-chars):
        batch_chars, or the provider's own - 0 keeps the tools' batch sizes (an agent reads its files itself); a chat
        model gets everything pasted into one prompt, so its batches are cut to what the context and max_file_chars
        hold."""
        if self.batch_chars is not None:
            return max(0, int(self.batch_chars))
        return self.provider_class().batch_budget(self)

    def file_chars(self) -> int:
        """The most of one file a prompt carries: max_file_chars, or half of the provider's context window."""
        return self.provider_class().file_chars(self)

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
        gone = sorted(set(data) & set(REMOVED_KEYS))
        if gone:
            raise ValueError(f"[harness] key(s) in {path} that went with the claude -p worker: {', '.join(gone)} - "
                             "remove them (a worker's tokens and cost are in the run's summary)")
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"unknown [harness] key(s) in {path}: {', '.join(unknown)}")
        data.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**data)
