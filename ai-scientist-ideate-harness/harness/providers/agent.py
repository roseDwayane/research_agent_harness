"""An agent provider: a worker with tools of its own. It opens the files, runs the step's skill commands and writes
its answer itself; the shell (shell.py) checks what it left. None is built in (claude -p was one, and is removed):
it is the kind that could run B6, whose `consume` and journal lookup a chat model cannot.

What every agent shares, whatever runs it:
  AGENT_RULES   the shell's rules at the head of its system prompt
  the shims     the skill commands it may run, as two scripts the conductor writes on its PATH (<state>/bin):
                ``ideate-tool`` = scripts/ideate_tools.py and ``ideate-bridge`` = scripts/mcp_bridge.py, run with
                the configured interpreter; its system prompt lists the allowed commands in that form

A new agent (another coding-agent CLI, an API with tool use) subclasses AgentProvider and implements run(): start
the agent in req.cwd with req.system, req.task and self.bin_dir() on its PATH, allow req.commands (and req.tools),
deny reading req.scope.forbid, continue req.resume, and return a WorkerResult with its session id.
"""
from __future__ import annotations

import shlex
import stat
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from .base import Provider

if TYPE_CHECKING:
    from ..config import HarnessConfig

SHIMS = {"ideate-tool": "ideate_tools.py", "ideate-bridge": "mcp_bridge.py"}

AGENT_RULES = """\
You are one Unit (a small step) of the ai-scientist ideate pipeline, run by a code conductor. Rules of the shell:
- Do exactly the task below, following the Unit's rules (appended). Do not run other Units' steps.
- Write only the files the task names (and scratch files under _work/ if you need any). Never edit a file another Unit
  owns, the ledger (_state/ledger.jsonl), or the ideas archive.
- Skill commands: run them as `ideate-tool <subcommand> ...` (= scripts/ideate_tools.py) or `ideate-bridge ...`
  (= scripts/mcp_bridge.py); only the subcommands listed under "Commands you may run" are allowed.
- Knowledge comes from the papers on disk, never from memory: a field you cannot support from a source is (TBD).
- No human is available: decide by the rules; where a rule leaves a choice, take the conservative one and say why.
- When the files are written, stop and reply with one short paragraph: what you wrote and any doubt. The conductor
  checks the files; if it finds problems it will tell you, in this same session, what to fix.
"""


def shim_form(cmd: str) -> str:
    """A recipe's command as an agent runs it: `ideate_tools.py list-papers` -> `ideate-tool list-papers`."""
    words = cmd.split()
    if words and words[0] in SHIMS.values():
        name = next(k for k, v in SHIMS.items() if v == words[0])
        return " ".join([name, *words[1:]])
    return cmd


def write_shims(bin_dir: Path, cfg: HarnessConfig) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name, script in SHIMS.items():
        p = bin_dir / name
        target = Path(cfg.module_root) / "scripts" / script
        p.write_text(f"#!/bin/sh\nexec {shlex.quote(cfg.python)} {shlex.quote(str(target))} \"$@\"\n", encoding="utf-8")
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


class AgentProvider(Provider):
    """A worker with tools: it runs the step's skill commands itself, through the shims."""
    runs_commands = True
    rules = AGENT_RULES

    def __init__(self, cfg: HarnessConfig, state_dir: Path | None = None):
        super().__init__(cfg, state_dir)
        self._bin: Path | None = None
        self._lock = threading.Lock()            # a fan-out's first calls start together: the shims are written once

    def command_forms(self, commands: list[str]) -> list[str]:
        return [shim_form(c) for c in commands]

    def bin_dir(self) -> Path | None:
        """The shims' folder (<state>/bin), written on first use; None for a provider made without a state folder."""
        with self._lock:
            if self._bin is None and self.state_dir is not None:
                self._bin = write_shims(self.state_dir / "bin", self.cfg)
            return self._bin
