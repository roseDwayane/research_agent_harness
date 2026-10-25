"""One Claude worker = one `claude -p` process: the Unit's rules as its system prompt, one task, a small set of tools.

The worker writes files; it does not decide whether it succeeded. The shell (shell.py) checks what it wrote, and a
rejected answer goes back to the same session (``resume``) with the findings - the RP-MODEL-OUTPUT retry.

Tools: Read/Write/Edit/Glob/Grep, and Bash only for the skill commands the recipe allows, through two shims the
conductor writes per run (``<RD>/_state/harness/bin``): ``ideate-tool`` = scripts/ideate_tools.py and
``ideate-bridge`` = scripts/mcp_bridge.py, run with the configured interpreter. Paths a worker must not read (a
scorer's blinding) are denied with Read(...) rules; an isolated worker (A1.e) runs in a folder of its own and gets
the rules inline, so the research folder is not in its reach at all.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import stat
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import HarnessConfig

SHIMS = {"ideate-tool": "ideate_tools.py", "ideate-bridge": "mcp_bridge.py"}
BASE_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep"]
_HEADING = re.compile(r"^(#+)\s")
_ANCHOR = re.compile(r'^<a id="[^"]+"></a>\s*$')

SHELL_RULES = """\
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
    argv: list[str] = field(default_factory=list)

    @property
    def metrics(self) -> dict:
        return {"tokens_in": self.tokens_in, "tokens_out": self.tokens_out, "cost_usd": round(self.cost_usd, 6),
                "calls": 1, "duration_ms": self.duration_ms}


# -------------------------------------------------------------------------------------------------- the rules
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
    if not _ANCHOR.match(lines[start]):           # an anchor inside a paragraph: up to the next anchor or heading
        end = next((i for i in range(start + 1, len(lines)) if 'id="' in lines[i] or _HEADING.match(lines[i])),
                   len(lines))
        return "\n".join(lines[start:end]).strip()
    head = next((i for i in range(start, len(lines)) if _HEADING.match(lines[i])), None)
    if head is None:
        return "\n".join(lines[start + 1:]).strip()
    level = len(_HEADING.match(lines[head]).group(1))
    end = len(lines)
    for i in range(head + 1, len(lines)):
        m = _HEADING.match(lines[i])
        if m and len(m.group(1)) <= level:
            end = i - 1 if i - 1 > head and _ANCHOR.match(lines[i - 1]) else i   # the next section's own anchor
            break
    return "\n".join(lines[head:end]).strip()


def system_prompt(root: Path, unit: dict, card: dict | None, rules: list[str], commands: list[str]) -> str:
    parts = [SHELL_RULES, f"\n# Unit {unit['id']} - {unit.get('name', '')}\n"]
    if card:
        if card.get("purpose"):
            parts.append(f"Purpose: {card['purpose']}\n")
        if card.get("done_when"):
            dw = card["done_when"]
            parts.append("Done when: " + ("; ".join(map(str, dw)) if isinstance(dw, list) else str(dw)) + "\n")
        if card.get("forbidden"):
            parts.append("Never read or use: " + "; ".join(map(str, card["forbidden"])) + "\n")
    if commands:
        parts.append("\n## Commands you may run\n" + "\n".join(f"- `{_shim_form(c)}`" for c in commands) + "\n")
    for a in rules:
        parts.append(f"\n## Rules: {a}\n\n{rules_text(root, a)}\n")
    return "".join(parts)


def _shim_form(cmd: str) -> str:
    words = cmd.split()
    if words and words[0] in SHIMS.values():
        name = next(k for k, v in SHIMS.items() if v == words[0])
        return " ".join([name, *words[1:]])
    return cmd


def allowed_bash(commands: list[str]) -> list[str]:
    """Bash permission rules for the allowed skill commands: `ideate-tool list-papers:*`."""
    out = []
    for c in commands:
        words = _shim_form(c).split()
        if words and words[0] in SHIMS:
            prefix = " ".join(words[:2]) if len(words) > 1 and not words[1].startswith("$") else words[0]
            out.append(f"Bash({prefix}:*)")
    return sorted(set(out))


def write_shims(bin_dir: Path, cfg: HarnessConfig) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name, script in SHIMS.items():
        p = bin_dir / name
        target = Path(cfg.module_root) / "scripts" / script
        p.write_text(f"#!/bin/sh\nexec {shlex.quote(cfg.python)} {shlex.quote(str(target))} \"$@\"\n", encoding="utf-8")
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


# -------------------------------------------------------------------------------------------------- one call
def run_worker(cfg: HarnessConfig, *, task: str, system: str, cwd: Path, allowed: list[str], add_dirs: list[Path],
               deny_read: list[Path], budget_usd: float | None, bin_dir: Path | None, resume: str | None = None,
               timeout: float | None = None, log_dir: Path | None = None, label: str = "worker") -> WorkerResult:
    cwd.mkdir(parents=True, exist_ok=True)
    sys_file = (log_dir or cwd) / f"{label}.system.md"
    sys_file.parent.mkdir(parents=True, exist_ok=True)
    sys_file.write_text(system, encoding="utf-8")
    argv = [cfg.claude, "-p", task, "--output-format", "json",
            "--append-system-prompt-file", str(sys_file),
            "--allowedTools", ",".join(BASE_TOOLS + allowed)]
    if deny_read:
        argv += ["--disallowedTools", ",".join(f"Read(/{p.resolve()})" for p in deny_read)]
    for d in add_dirs:
        argv += ["--add-dir", str(d)]
    if cfg.model:
        argv += ["--model", cfg.model]
    if budget_usd:
        argv += ["--max-budget-usd", str(budget_usd)]
    if resume:
        argv += ["--resume", resume]
    env = cfg.env()
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    t0 = time.time()
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=env, timeout=timeout or cfg.worker_timeout_s)
    except subprocess.TimeoutExpired:
        return WorkerResult(False, error=f"worker timed out after {timeout or cfg.worker_timeout_s}s",
                            error_category="timeout", argv=argv, duration_ms=int((time.time() - t0) * 1000))
    except OSError as e:
        return WorkerResult(False, error=f"could not start {cfg.claude!r}: {e}", error_category="environment", argv=argv)
    if log_dir is not None:
        (log_dir / f"{label}.out.json").write_text(p.stdout or "", encoding="utf-8")
        if p.stderr.strip():
            (log_dir / f"{label}.err.txt").write_text(p.stderr, encoding="utf-8")
    return parse_result(p.returncode, p.stdout, p.stderr, argv, int((time.time() - t0) * 1000))


def parse_result(code: int, stdout: str, stderr: str, argv: list[str], elapsed_ms: int) -> WorkerResult:
    data = None
    out = (stdout or "").strip()
    if out:
        try:
            data = json.loads(out[out.index("{"):]) if "{" in out else None
        except ValueError:
            data = None
    if not isinstance(data, dict):
        why = (stderr or stdout or "").strip().splitlines()[-1:] or [f"exit {code}, no JSON result"]
        text = why[0][:400]
        cat = "environment" if re.search(r"not found|No such file|login|auth|API key", text, re.I) else (
            "external_service" if re.search(r"429|overloaded|rate.?limit|5\d\d|network", text, re.I) else "tool_invocation")
        return WorkerResult(False, error=text, error_category=cat, argv=argv, duration_ms=elapsed_ms)
    usage = data.get("usage") or {}
    tin = int(usage.get("input_tokens") or 0) + int(usage.get("cache_creation_input_tokens") or 0) + \
        int(usage.get("cache_read_input_tokens") or 0)
    res = WorkerResult(ok=not data.get("is_error") and code == 0, text=str(data.get("result") or ""),
                       session_id=data.get("session_id"), cost_usd=float(data.get("total_cost_usd") or 0.0),
                       tokens_in=tin, tokens_out=int(usage.get("output_tokens") or 0),
                       duration_ms=int(data.get("duration_ms") or elapsed_ms), turns=int(data.get("num_turns") or 0),
                       argv=argv)
    if not res.ok:
        sub = str(data.get("subtype") or "")
        res.error = res.text[:400] or sub or f"exit {code}"
        res.error_category = "budget" if "budget" in sub or "max_turns" in sub else (
            "external_service" if re.search(r"429|overloaded|rate.?limit", res.error, re.I) else "model_output")
    return res
