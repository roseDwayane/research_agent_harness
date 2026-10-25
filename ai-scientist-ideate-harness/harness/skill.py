"""The boundary to the Unit implementation: scripts/ideate_tools.py, scripts/mcp_bridge.py, scripts/pdf2md.sh.

The conductor never re-implements a Unit; it runs the skill's commands as a recipe lists them and reads what they
print. A command is written as the skill's documentation writes it (`ideate_tools.py a2-check $RD`); placeholders are
expanded by ``expand`` before it runs:

  $RD     the research folder (<topic>_research/)      $GEN    the generation folder (<RD>/gen_k)
  $K      the generation number                         $TOPIC  the topic markdown
  $PY     the interpreter for scripts/                  $SK     the module root (this skill)
  $IDEAS  the ideas archive (<topic>.json)              $ROUND  the B5 round
  $DEPTH  quick | standard | deep
  $<NAME> a value an earlier step of the same recipe captured from its output ("capture", recipes.py)
"""
from __future__ import annotations

import glob
import json
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import HarnessConfig

_EXTERNAL = re.compile(r"\b(429|5\d\d|timeout|timed out|rate.?limit|unreachable|connection (refused|reset|error)|"
                       r"HTTP ?error|service unavailable)\b", re.I)
_ENVIRONMENT = re.compile(r"not available|not installed|No module named|API_KEY|api key|poppler|interpreter|"
                          r"command not found", re.I)
_INPUT = re.compile(r"not found|refuses|refused|missing|no step|not done|run .* first|before ", re.I)
_PLACEHOLDER = re.compile(r"\$([A-Z][A-Z0-9_]*)\b")


@dataclass
class CommandResult:
    command: str
    argv: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def tail(self, n: int = 3, width: int = 400) -> str:
        lines = [ln for ln in (self.stderr or self.stdout).strip().splitlines() if ln.strip()]
        return " · ".join(lines[-n:])[:width]


@dataclass
class Subs:
    """The values of the placeholders for one Unit instance."""
    rd: Path
    topic: Path | None = None
    gen: int | None = None
    round: int | None = None
    extra: dict[str, str] = field(default_factory=dict)
    phase: str = "main"

    @property
    def gen_dir(self) -> Path | None:
        return self.rd / f"gen_{self.gen}" if self.gen is not None else None

    @property
    def ideas(self) -> Path | None:
        return self.topic.with_suffix(".json") if self.topic else None


def classify_failure(text: str) -> str:
    """The v2 category of a failed command, from what it printed (ideate_v2.errors.CATEGORIES)."""
    if "Traceback" in text and not _ENVIRONMENT.search(text):
        if _EXTERNAL.search(text):
            return "external_service"
        return "tool_invocation"
    if _EXTERNAL.search(text):
        return "external_service"
    if "wrote outside" in text:
        return "check_failed"
    if "KeyboardInterrupt" in text or "InjectedFailure" in text:
        return "interrupted"
    if _ENVIRONMENT.search(text):
        return "environment"
    if _INPUT.search(text):
        return "input_contract"
    return "tool_invocation"


class Skill:
    """Runs the skill's commands with the configured interpreter, from the module root."""

    def __init__(self, cfg: HarnessConfig):
        self.cfg = cfg
        self.root = Path(cfg.module_root)
        self.scripts = self.root / "scripts"
        if not (self.scripts / "ideate_units.json").is_file():
            raise FileNotFoundError(f"{self.root} is not the ideate skill (no scripts/ideate_units.json)")
        self.calls: list[CommandResult] = []

    # ------------------------------------------------------------------------------------------------ commands
    def expand(self, cmd: str, subs: Subs, quote: bool = True) -> str:
        """Fill in the placeholders; quote=True for a command line (shlex-quoted values), False for a path or text."""
        values = {"RD": subs.rd, "GEN": subs.gen_dir, "K": subs.gen, "TOPIC": subs.topic, "PY": self.cfg.python,
                  "SK": self.root, "IDEAS": subs.ideas, "ROUND": subs.round, "DEPTH": self.cfg.depth, **subs.extra}

        def repl(m: re.Match) -> str:
            v = values.get(m.group(1))
            if v is None:
                raise ValueError(f"placeholder ${m.group(1)} has no value here (command: {cmd})")
            return shlex.quote(str(v)) if quote else str(v)
        return _PLACEHOLDER.sub(repl, cmd)

    def argv(self, cmd: str) -> list[str]:
        """`ideate_tools.py a2-check /rd` -> [python, scripts/ideate_tools.py, a2-check, /rd]."""
        words = []
        for w in shlex.split(cmd):                 # no shell runs the command: expand a file glob here
            hits = sorted(glob.glob(w)) if any(ch in w for ch in "*?[") and w.startswith("/") else []
            words += hits or [w]
        if not words:
            raise ValueError("empty command")
        if words[0].endswith(".py"):
            return [self.cfg.python, str(self.scripts / words[0]), *words[1:]]
        if words[0] == "bash" and len(words) > 1 and words[1].endswith(".sh"):
            return ["bash", str(self.scripts / words[1]), *words[2:]]
        raise ValueError(f"not a skill command (expected <script>.py or bash <script>.sh): {cmd}")

    def run(self, cmd: str, subs: Subs, timeout: float | None = None) -> CommandResult:
        line = self.expand(cmd, subs)
        argv = self.argv(line)
        t0 = time.time()
        try:
            p = subprocess.run(argv, cwd=self.root, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", env=self.cfg.env(), timeout=timeout or self.cfg.command_timeout_s)
            res = CommandResult(line, argv, p.returncode, p.stdout, p.stderr, round(time.time() - t0, 3))
        except subprocess.TimeoutExpired as e:
            res = CommandResult(line, argv, 124, (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes)
                                else (e.stdout or ""), f"timed out after {e.timeout}s", round(time.time() - t0, 3))
        except OSError as e:
            res = CommandResult(line, argv, 127, "", f"could not start: {e}", round(time.time() - t0, 3))
        self.calls.append(res)
        return res

    # ------------------------------------------------------------------------------------------------ checks
    def findings(self, cmd: str, subs: Subs, timeout: float | None = None) -> tuple[CommandResult, list[dict] | None]:
        """Run a check command (it should print JSON findings) -> (result, findings or None when unreadable).

        Findings are normalised to {level, code, message, unit?}. `argument-check --json` prints {findings: [...]}, the
        block checks print a list."""
        res = self.run(cmd, subs, timeout=timeout or 900)
        return res, parse_findings(res.stdout)


    def unit_findings(self, unit: str, commands: list[str], subs: Subs) -> tuple[list[dict], list[CommandResult]]:
        """Run a Unit's check commands -> (findings of this Unit, the results). An unreadable output with a non-zero
        exit is one ERROR finding (the check said no without saying why in JSON)."""
        found, results = [], []
        for cmd in commands:
            res, fs = self.findings(cmd, subs)
            results.append(res)
            if fs is None:
                if not res.ok:
                    found.append({"level": "ERROR", "code": f"EXIT{res.returncode}", "message": res.tail(),
                                  "unit": unit})
                continue
            found += [f for f in fs if f.get("unit") in (None, unit)]
        return found, results

    def gate_check(self, gate: dict, subs: Subs) -> tuple[bool, list[CommandResult]]:
        """The legacy half of a gate: every command of gate_commands exits 0."""
        results = [self.run(cmd, subs, timeout=900) for cmd in gate_commands(gate)]
        return all(r.ok for r in results), results

def parse_findings(out: str) -> list[dict] | None:
    out = (out or "").strip()
    data = None
    for opener in ("[", "{"):
        i = out.find(opener)
        if i < 0:
            continue
        try:
            data = json.loads(out[i:])
            break
        except ValueError:
            continue
    if isinstance(data, dict):
        data = data.get("findings")
    if not isinstance(data, list):
        return None
    norm = []
    for f in data:
        if not isinstance(f, dict):
            continue
        norm.append({"level": str(f.get("level", "")).upper(), "code": str(f.get("code") or f.get("check") or "?"),
                     "message": str(f.get("msg") or f.get("message") or ""), "unit": f.get("unit")})
    return norm


# the legacy half of each gate (decision D-10: a gate passes when ideate_v2's contract check AND these pass). The
# contracts state them as prose (`legacy_command`); the coherence gate is four commands.
COHERENCE = ["ideate_tools.py argument-check $GEN --idea $GEN/idea_draft.json", "ideate_tools.py tree-check $GEN",
             "ideate_tools.py attack-check $GEN --idea $GEN/idea_draft.json",
             "ideate_tools.py pack-check $GEN --idea $GEN/idea_draft.json"]


def gate_commands(gate: dict) -> list[str]:
    if gate["id"] == "GATE-coherence":
        return list(COHERENCE)
    cmd = (gate.get("legacy_command") or "").replace("<RD>", "$RD").replace("<gen_dir>", "$GEN")
    return [cmd] if cmd else []
