"""Recipes: how each Unit is executed, as data (contracts/recipes/{search,fusion,planning}.json).

A recipe is a list of steps per phase. Most Units have one phase, `main`; B5 has one per round.

  {"run": "<command>"}                  the conductor runs a skill command (skill.py placeholders)
        "submit": true                  a rejection is the model's to fix: it goes back to the last write step's
                                        worker (same session) and the steps from that write on run again
                                        (retry policy RP-MODEL-OUTPUT, owner unit-tool)
        "optional": true                a failure is recorded as a warning and the recipe goes on
        "depth": ["standard", "deep"]   run only at these depths
        "capture": {"name": "Q", "regex": "question-next: (Q_\\d+)"}   a value from its output, $Q in later steps
  {"write": {...}}                      one Claude worker writes files (claude_worker.py)
        "task"      what to do, in the words of the rules (placeholders allowed)
        "rules"     the reference sections it follows: "references/search/A1-frame.md#a1p"
        "reads"     paths it should read (beyond the rules); "writes": the files it must leave behind
        "forbid"    paths it must not read (a scorer's blinding: bibliometrics, venues)
        "commands"  skill commands it may run itself (e.g. a lookup: "ideate_tools.py list-papers")
        "isolated"  true: an independent reader (A1.e): it sees only `reads` and the rules, not the research folder
        "tools"     extra Claude Code tools beyond Read/Write/Edit/Glob/Grep (B6's journal lookup: WebSearch, WebFetch)
  {"fanout": {...}}                     one worker per batch file, at most max_parallel at once
        "batches"   a glob under $RD: "_state/fanout/A3/batch_*.in.json"
        "task"      the instruction per batch; {batch} {out} {brief} are filled in
        "brief"     the brief every batch worker reads ($RD-relative)
        "out"       where a batch's answer goes: field:<key> | rdfield:<key> | items:<list>.<key> | suffix:<a>><b>
                    (executors.RecipeExecutor._batch_outs)
        "rules", "forbid", "commands" as for write

  {"freeze": ["$GEN/argument.json", ...]}   copy each file to <name>_r1<ext> unless that copy exists (cp -n)
  any step: "when_file": "<path>"   run the step only when that file exists (B5's second blind restatement)

  "partial_phases": phases after which the Unit is not closed - no output contract, no check (B5's rounds before
                    finalize, B6's abandon, A2.c's replan); every other phase ends with both

  "check": the Unit's own check commands, printing JSON findings (an ERROR fails the Unit)
  "status": "draft" until the recipe ran on a real topic and was reviewed; then "reviewed"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ideate_v2.jsonio import read_json

from .config import MODULE_ROOT

RECIPES_DIR = MODULE_ROOT / "contracts" / "recipes"
SCHEMA = "ideate-harness-recipes/1"
STEP_KINDS = ("run", "write", "fanout", "freeze")
STATUSES = ("draft", "reviewed")
SCRIPTS = ("ideate_tools.py", "mcp_bridge.py", "pdf2md.sh")
_KIND_EXPECT = {                       # contract kind -> the step kinds its recipe must contain
    "script": set(), "model": {"write"}, "hybrid": {"write"}, "subagent": {"write"}, "fanout": {"fanout"}}
_PH = re.compile(r"\$([A-Z][A-Z0-9_]*)\b")
_KNOWN_PH = {"RD", "GEN", "K", "TOPIC", "PY", "SK", "IDEAS", "ROUND", "DEPTH"}


@dataclass
class Step:
    kind: str
    spec: dict

    @property
    def command(self) -> str:
        return self.spec["run"] if self.kind == "run" else ""


@dataclass
class Recipe:
    unit: str
    phases: dict[str, list[Step]]
    check: list[str] = field(default_factory=list)
    status: str = "draft"
    scope: str = "topic"
    note: str = ""
    partial: list[str] = field(default_factory=list)      # phases that do not close the Unit (no output contract)

    @property
    def step_kinds(self) -> set[str]:
        return {s.kind for steps in self.phases.values() for s in steps}

    @property
    def executor(self) -> str:
        kinds = self.step_kinds
        return "fanout" if "fanout" in kinds else "claude" if "write" in kinds else "script"

    def steps(self, phase: str = "main") -> list[Step]:
        if phase not in self.phases:
            raise KeyError(f"{self.unit} has no phase {phase!r} (has {', '.join(self.phases)})")
        return self.phases[phase]


def _step(raw: dict) -> Step:
    kinds = [k for k in STEP_KINDS if k in raw]
    if len(kinds) != 1:
        raise ValueError(f"a step needs exactly one of {STEP_KINDS}: {raw}")
    return Step(kinds[0], raw)


def parse(doc: dict) -> list[Recipe]:
    out = []
    for r in doc.get("recipes") or []:
        phases = {name: [_step(s) for s in steps] for name, steps in (r.get("phases") or {}).items()}
        out.append(Recipe(r["unit"], phases, list(r.get("check") or []), r.get("status", "draft"),
                          r.get("scope", "topic"), r.get("note", ""), list(r.get("partial_phases") or [])))
    return out


def load(directory: Path | None = None) -> dict[str, Recipe]:
    d = Path(directory or RECIPES_DIR)
    recipes: dict[str, Recipe] = {}
    for f in sorted(d.glob("*.json")):
        doc = read_json(f)
        if doc.get("schema") != SCHEMA:
            raise ValueError(f"{f.name}: schema must be {SCHEMA}")
        for r in parse(doc):
            if r.unit in recipes:
                raise ValueError(f"{f.name}: a second recipe for {r.unit}")
            recipes[r.unit] = r
    return recipes


# --------------------------------------------------------------------------------------------------- validation
def _commands(r: Recipe) -> list[str]:
    cmds = [s.command for steps in r.phases.values() for s in steps if s.kind == "run"] + list(r.check)
    for steps in r.phases.values():
        for s in steps:
            if s.kind in ("write", "fanout"):
                cmds += list((s.spec[s.kind] or {}).get("commands") or [])
    return cmds


def _texts(r: Recipe) -> list[str]:
    out = _commands(r)
    for steps in r.phases.values():
        for s in steps:
            if s.kind in ("write", "fanout"):
                body = s.spec[s.kind] or {}
                out += [str(body.get("task", ""))] + [str(x) for k in ("reads", "writes", "forbid") for x in body.get(k) or []]
    return out


def validate(recipes: dict[str, Recipe], reg, root: Path | None = None) -> list[dict]:
    """Findings {level, code, unit, message}: a recipe per Unit, steps that match the Unit's kind, commands of the
    skill, rules files that exist, known placeholders."""
    root = Path(root or MODULE_ROOT)
    out = []

    def f(level, code, unit, msg):
        out.append({"level": level, "code": code, "unit": unit, "message": msg})

    for u in reg.units:
        if u not in recipes:
            f("ERROR", "R-MISSING", u, "no recipe")
    for u, r in recipes.items():
        if u not in reg.units:
            f("ERROR", "R-UNKNOWN", u, "recipe for a Unit the contracts do not have")
            continue
        if r.status not in STATUSES:
            f("ERROR", "R-STATUS", u, f"status {r.status!r} (one of {STATUSES})")
        if not r.phases or not any(r.phases.values()):
            f("ERROR", "R-EMPTY", u, "no steps")
        kind = reg.units[u].get("kind")
        want = _KIND_EXPECT.get(kind, set())
        have = r.step_kinds - {"run"}
        if kind == "script" and have:
            f("ERROR", "R-KIND", u, f"a script Unit with {sorted(have)} steps")
        elif want and not want <= have:
            f("ERROR", "R-KIND", u, f"a {kind} Unit needs a {'/'.join(sorted(want))} step")
        scope = "generation" if (reg.get(reg.step_of(u)) or {}).get("block") == "BLK-planning" else "topic"
        if r.scope != scope:
            f("ERROR", "R-SCOPE", u, f"scope {r.scope!r}, the Unit's step is {scope}-scoped")
        for cmd in _commands(r):
            words = cmd.split()
            head = words[1] if words[:1] == ["bash"] and len(words) > 1 else (words[0] if words else "")
            if head not in SCRIPTS:
                f("ERROR", "R-COMMAND", u, f"not a skill command: {cmd!r}")
            elif not (root / "scripts" / head).is_file():
                f("ERROR", "R-COMMAND", u, f"scripts/{head} does not exist")
        captured = {s.spec["capture"]["name"] for steps in r.phases.values() for s in steps
                    if s.kind == "run" and s.spec.get("capture")}
        for text in _texts(r):
            for ph in _PH.findall(text):
                if ph not in _KNOWN_PH | captured:
                    f("ERROR", "R-PLACEHOLDER", u, f"unknown placeholder ${ph} in {text[:80]!r}")
        for steps in r.phases.values():
            for s in steps:
                if s.kind == "write":
                    body = s.spec["write"] or {}
                    if not body.get("task"):
                        f("ERROR", "R-WRITE", u, "a write step without a task")
                    if not body.get("writes"):
                        f("WARN", "R-WRITE", u, "a write step that names no file it must write")
                if s.kind == "fanout":
                    body = s.spec["fanout"] or {}
                    for k in ("batches", "task", "out"):
                        if not body.get(k):
                            f("ERROR", "R-FANOUT", u, f"a fanout step without {k!r}")
                    if body.get("out") and not re.match(r"^((rd)?field:\w+|items:\w+\.\w+|suffix:.+>.+)$", body["out"]):
                        f("ERROR", "R-FANOUT", u, f"out {body['out']!r}: field:<key>, rdfield:<key>, items:<list>.<key> "
                          "or suffix:<in>><out>")
                for anchor in ((s.spec.get(s.kind) or {}).get("rules") or []) if s.kind in ("write", "fanout") else []:
                    path = anchor.split("#")[0]
                    if not (root / path).is_file():
                        f("ERROR", "R-RULES", u, f"rules file {path} does not exist")
        if not r.check and kind != "script":
            f("WARN", "R-CHECK", u, "no check command: only the output contract decides done")
        for ph in r.partial:
            if ph not in r.phases:
                f("ERROR", "R-PHASE", u, f"partial phase {ph!r} is not a phase of the recipe")
        if r.status == "draft":
            f("INFO", "R-DRAFT", u, "draft: not yet run on a real topic")
    return out
