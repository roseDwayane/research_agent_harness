"""What every provider shares: the call it is given, what it returns, the files it may touch, and the Unit's rules it
works under. The executor (executors.py) speaks only this - it never asks which provider runs.

  WorkerRequest   one call: the task, the system prompt, the folder, the FileScope, the step's commands and tools,
                  the session to resume
  WorkerResult    what came back: ok, text, session_id, tokens, cost, and when not ok the error and its ideate_v2
                  category (a TRANSPORT one is sent again by the executor, after the provider's wait)
  FileScope       what one worker may read and write, decided by the executor: a chat provider (chat.py) puts the
                  reads into the prompt and writes only what the scope allows; an agent (agent.py) opens the files
                  itself and has the forbidden ones denied
  Provider        the interface: run(request) -> WorkerResult, and what the executor and HarnessConfig ask of it
  unit_prompt     the Unit's rules (its card, the commands it may run, the reference sections) for a system prompt
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from ideate_v2 import retry

if TYPE_CHECKING:
    from ..config import HarnessConfig
    from ..context import RunContext

# a worker failure of these categories is the transport's (RP-TRANSPORT, owner unit-transport): the same call again
TRANSPORT = ("external_service", "timeout")
# where any worker may write besides its files, and what none may write (FileScope.target)
SCRATCH = ("_work/**", "knowledge/_work/**", "_state/harness/decisions/**")
PROTECTED = ("_state/ledger*", "_state/ledger_snap/**", "_state/errors/**", "_state/net/**", "ERRORS.md",
             "step0_session_config.json")
CHARS_PER_TOKEN = 3.0            # a conservative estimate for mixed English, JSON and Markdown


@dataclass
class WorkerResult:
    ok: bool
    text: str = ""
    session_id: str | None = None
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0
    turns: int = 0
    error: str = ""
    error_category: str = ""                    # ideate_v2 category when not ok
    argv: list[str] = field(default_factory=list)   # what was run, for a provider that starts a process

    @property
    def metrics(self) -> dict:
        return {"tokens_in": self.tokens_in, "tokens_out": self.tokens_out, "cost_usd": round(self.cost_usd, 6),
                "calls": 1, "duration_ms": self.duration_ms}


@dataclass
class FileScope:
    """What one worker may read and write - decided by the executor, enforced by the provider."""
    base: Path                                            # relative paths in the answer resolve against it
    reads: list[tuple[str, Path]] = field(default_factory=list)      # (the name the task uses, the file to show)
    writes: list[Path] = field(default_factory=list)      # files the step must leave written
    globs: list[str] = field(default_factory=list)        # base-relative patterns it may also write
    forbid: list[Path] = field(default_factory=list)      # never shown (a scorer's blinding)
    lookups: list[tuple[str, str]] = field(default_factory=list)     # (command, output) the conductor ran
    schema: dict | None = None                            # the one write's JSON schema: the answer is that object
    unavailable: list[str] = field(default_factory=list)  # commands the task asks the worker itself to run
    max_file_chars: int = 60000

    def target(self, path: str) -> Path | None:
        """Where an answered path may be written, or None when the scope does not allow it."""
        p = Path(path.strip())
        if p.is_absolute():
            dest = p
        else:
            dest = self.base / p
        try:
            dest = dest.resolve()
            rel = dest.relative_to(self.base.resolve()).as_posix()
        except (ValueError, OSError):
            rel = None
        for w in self.writes:                                 # an exact name of the task (also its bare file name)
            if dest == w.resolve() or (not p.is_absolute() and p.as_posix().lstrip("./") == w.name and
                                       len([x for x in self.writes if x.name == w.name]) == 1):
                return w
        if rel is None or ".." in Path(rel).parts:
            return None
        if any(fnmatch.fnmatch(rel, g) for g in PROTECTED):
            return None
        if any(fnmatch.fnmatch(rel, g) for g in self.globs):
            return dest
        return None


@dataclass
class WorkerRequest:
    """One worker call, the same for every provider: each uses what it can and ignores the rest (an agent opens its
    files itself and needs no scope.reads; a chat model cannot run `commands`, the conductor ran the lookups)."""
    task: str
    system: str
    cwd: Path
    scope: FileScope | None = None                        # None: nothing named, cwd as the base
    commands: list[str] = field(default_factory=list)     # the skill commands the step lets the worker run itself
    tools: list[str] = field(default_factory=list)        # an agent's extra tools (B6's journal lookup: WebSearch)
    add_dirs: list[Path] = field(default_factory=list)    # folders besides cwd an agent may read (topic, references/)
    resume: str | None = None                             # an earlier call's session_id: that conversation goes on
    timeout: float | None = None                          # None: [harness] worker_timeout_s
    log_dir: Path | None = None                           # where the provider leaves the call's prompt and answer
    label: str = "worker"                                 # names the call's log files
    say: Callable[[str], None] | None = None              # a progress line for the console

    def __post_init__(self) -> None:
        self.cwd = Path(self.cwd)
        if self.scope is None:
            self.scope = FileScope(base=self.cwd)


class Provider:
    """Who does a model Unit's write and fanout steps: the interface between the executor and a model.

    One provider is made per run (RunContext.provider) from the run's config and state folder. Making one must be
    cheap and leave nothing on disk - a dry run makes one too. The class attributes say what kind it is:

      name           the [harness] worker value it is registered under (providers/__init__.py)
      runs_commands  True: an agent with tools - it opens its files and runs the step's skill commands itself
                     (agent.py); False: the conductor runs the read-only lookups and puts the files into the
                     prompt (chat.py)
      rules          the shell's rules: the head of its system prompt

    A subclass implements run(); everything else has a default it may override. The classmethods are asked before
    any provider is made (HarnessConfig: whether the config can run, the fan-out width, the batch size).
    """
    name = ""
    runs_commands = False
    rules = ""

    def __init__(self, cfg: HarnessConfig, state_dir: Path | None = None):
        self.cfg = cfg
        self.state_dir = Path(state_dir) if state_dir is not None else None

    # ------------------------------------------------------------------------------------------------ settings
    @classmethod
    def check_config(cls, cfg: HarnessConfig) -> None:
        """Raise ValueError for a configuration this provider cannot run with."""

    @classmethod
    def default_model(cls, cfg: HarnessConfig) -> str | None:
        """The model when [harness] model is not set (HarnessConfig fills it in); None: the provider needs one, or
        leaves the choice to its own tool (an agent)."""
        return None

    @classmethod
    def options_of(cls, cfg: HarnessConfig) -> dict:
        """This provider's own settings in a config: the [harness.provider_options.<name>] table."""
        return dict((cfg.provider_options or {}).get(cls.name) or {})

    @classmethod
    def window(cls, cfg: HarnessConfig) -> int | None:
        """The context the model runs with, in tokens; None when the provider manages its own (an agent)."""
        return None

    @classmethod
    def parallel(cls, cfg: HarnessConfig) -> int:
        """Fan-out calls at once."""
        return cfg.max_parallel

    @classmethod
    def file_chars(cls, cfg: HarnessConfig) -> int:
        """The most of one file a prompt carries (FileScope.max_file_chars): max_file_chars, or half the window."""
        if cfg.max_file_chars:
            return int(cfg.max_file_chars)
        w = cls.window(cfg)
        return int(w * CHARS_PER_TOKEN * 0.5) if w else 60000

    @classmethod
    def batch_budget(cls, cfg: HarnessConfig) -> int:
        """$BUDGET without [harness] batch_chars: characters of material one fan-out call is given (a plan command's
        --max-chars). 0 keeps the tools' own batch sizes: an agent reads its batch itself."""
        return 0

    def options(self) -> dict:
        """This provider's own settings: the [harness.provider_options.<name>] table."""
        return self.options_of(self.cfg)

    # ------------------------------------------------------------------------------------------------ the calls
    @property
    def label(self) -> str:
        """The tool the run's events name for this provider's calls."""
        return self.name

    @property
    def model(self) -> str | None:
        """The model the calls name: [harness] model, or the provider's default."""
        return self.cfg.model or self.default_model(self.cfg)

    def system_prompt(self, root: Path, unit: dict, card: dict | None, rules: list[str], commands: list[str]) -> str:
        """The provider's rules, then the Unit's: its card, the commands it may run, the reference sections."""
        return self.rules + unit_prompt(root, unit, card, rules, self.command_forms(commands))

    def command_forms(self, commands: list[str]) -> list[str]:
        """The step's skill commands as the worker is told to run them; none for one that cannot run them."""
        return list(commands) if self.runs_commands else []

    def run(self, req: WorkerRequest) -> WorkerResult:
        """One worker turn: do the task, leave the files written, say how it went (never raise for a model's or a
        server's failure: return it, with its ideate_v2 category)."""
        raise NotImplementedError(f"{type(self).__name__}.run")

    def retry_delay(self, ctx: RunContext, wr: WorkerResult, attempt: int, error_id: str) -> float | None:
        """A call that failed in transport (TRANSPORT): the seconds to wait before it is sent again, None to give
        up. The default is the contract's RP-TRANSPORT (owner unit-transport)."""
        d = retry.decide(ctx.reg, "RP-TRANSPORT", {"error_category": wr.error_category, "severity": "degraded",
                                                   "retryable": True, "error_id": error_id}, attempt, "unit-transport")
        return d["delay_s"] if d["action"] == "retry" else None

    def before_resend(self, say: Callable[[str], None] | None = None) -> None:
        """After the wait, before a dropped call is sent again (Ollama: until the server is free)."""


# -------------------------------------------------------------------------------------------------- the rules
_HEADING = re.compile(r"^(#+)\s")
_ANCHOR = re.compile(r'^<a id="[^"]+"></a>\s*$')
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")


def _headings(lines: list[str]) -> list[re.Match | None]:
    """_HEADING per line, None inside a fenced code block: a `# comment` in a bash block, or a heading in a ~~~markdown
    template, is not a heading of the rules (it cut A1.q's, A3's, A7.D's and B3.5's rules short). A fence closes only
    on its own kind of marker, so a ``` block inside a ~~~ template stays inside."""
    out, fence = [], None
    for ln in lines:
        m = _FENCE.match(ln)
        if m and fence is None:
            fence = m.group(1)
        elif m and fence is not None and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) \
                and not ln.strip()[len(m.group(1)):].strip():
            fence = None
        elif fence is None:
            out.append(_HEADING.match(ln))
            continue
        out.append(None)
    return out


def rules_text(root: Path, anchor: str) -> str:
    """The section an anchor names ("references/search/A1-frame.md#a1p": from `<a id="a1p">` to the next heading of
    the same or a higher level), or the whole file when there is no #."""
    path, _, aid = anchor.partition("#")
    text = (Path(root) / path).read_text(encoding="utf-8")
    if not aid:
        return text
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if f'id="{aid}"' in ln), None)
    if start is None:
        return text                               # an anchor that moved: the whole file is still the rule
    hd = _headings(lines)
    if not _ANCHOR.match(lines[start]):           # an anchor inside a paragraph: up to the next anchor or heading
        end = next((i for i in range(start + 1, len(lines)) if 'id="' in lines[i] or hd[i]), len(lines))
        return "\n".join(lines[start:end]).strip()
    head = next((i for i in range(start, len(lines)) if hd[i]), None)
    if head is None:
        return "\n".join(lines[start + 1:]).strip()
    level = len(hd[head].group(1))
    end = len(lines)
    for i in range(head + 1, len(lines)):
        m = hd[i]
        if m and len(m.group(1)) <= level:
            end = i - 1 if i - 1 > head and _ANCHOR.match(lines[i - 1]) else i   # the next section's own anchor
            break
    return "\n".join(lines[head:end]).strip()


def unit_prompt(root: Path, unit: dict, card: dict | None, rules: list[str], commands: list[str]) -> str:
    """The Unit's part of a system prompt: its id and card, the commands it may run (in the form the worker runs
    them), and the reference sections its recipe names."""
    parts = [f"\n# Unit {unit['id']} - {unit.get('name', '')}\n"]
    if card:
        if card.get("purpose"):
            parts.append(f"Purpose: {card['purpose']}\n")
        if card.get("done_when"):
            dw = card["done_when"]
            # a card's entries are {check, codes, negative_fixture}: the check is what the worker needs, not the dict
            items = [d.get("check") or str(d) if isinstance(d, dict) else str(d) for d in dw] if isinstance(dw, list) else [str(dw)]
            parts.append("Done when: " + "; ".join(items) + "\n")
        if card.get("forbidden"):
            parts.append("Never read or use: " + "; ".join(map(str, card["forbidden"])) + "\n")
    if commands:
        parts.append("\n## Commands you may run\n" + "\n".join(f"- `{c}`" for c in commands) + "\n")
    for a in rules:
        parts.append(f"\n## Rules: {a}\n\n{rules_text(root, a)}\n")
    return "".join(parts)
