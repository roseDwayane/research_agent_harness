"""The dry run: the whole conductor on fixtures - no network, no tokens, no skill command executed.

FakeExecutor plays every Unit: it copies the Unit's output artifacts from a fixture research folder (default
evals/datasets/fusion_ready for Stage A, evals/datasets/planning/gen_1 for a generation) and, for a Unit on the legacy
ledger, appends a begin/done pair whose hashes are computed from the files as they are (the skill's formats). So ideate_v2's
contract half of every gate (requires_done, requires_artifacts, rules) is evaluated for real; FakeSkill answers only
the legacy half (the skill's own commands) and the Units' check commands, which pass unless a fault is injected.

Faults (``--inject KEY=TOKEN[,TOKEN...]``; the n-th token applies to the n-th attempt of that Unit):
  A3=external_service            attempt 1 fails with that ideate_v2 category (any of CATEGORIES)
  A3=external_service,external_service   attempts 1 and 2 fail
  A3=check:C05                   the Unit's check reports ERROR C05 after attempt 1
  GATE-tree-check=fail           the legacy half of that gate fails (once per token)
  B5=revise:P2                   B5 round 2 decides ReviseHypothesis entering at P2 (default: finalize)
  GATE-coherence=fail,fail       the coherence gate fails twice: after the forced revision too
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ideate_v2.errors import CATEGORIES
from ideate_v2.gates import artifact_paths
from ideate_v2.jsonio import sha256_json
from ideate_v2.ledger import PLANNING_FILES, ledger_block, spec_hash, spec_id

from .config import MODULE_ROOT
from .context import CODE_FOR, RunContext, instance_of
from .executors import ExecResult
from .recipes import Recipe
from .skill import CommandResult, Skill, Subs

DATASETS = MODULE_ROOT / "evals" / "datasets"
TOPIC_FIXTURE = DATASETS / "fusion_ready"
GEN_FIXTURE = DATASETS / "planning" / "gen_1"


def _hashes(rd: Path, specs: list[dict]) -> dict:
    """Ledger hashes of a card's io specs; the forms v2 cannot reproduce get a placeholder (v2 reports them as
    unverifiable either way)."""
    p = rd / "step0_session_config.json"
    cfg = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    out = {}
    for s in specs:
        sid = spec_id(s)
        status, h = spec_hash(rd, sid, cfg)
        out[sid] = h if status == "verified" else "dry-run:" + sha256_json(sid)[:16]
    return out


def parse_inject(items: list[str] | None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for item in items or []:
        key, _, tokens = item.partition("=")
        if not key or not tokens:
            raise ValueError(f"--inject {item!r}: KEY=TOKEN[,TOKEN...]")
        out.setdefault(key.strip(), []).extend(t.strip() for t in tokens.split(",") if t.strip())
    for key, toks in out.items():
        for t in toks:
            if not (t in CATEGORIES or t.startswith(("check:", "revise:")) or t in ("fail", "finalize")):
                raise ValueError(f"--inject {key}: unknown token {t!r}")
    return out


class FaultBook:
    """Tokens are consumed in order per key; a key without tokens behaves normally."""

    def __init__(self, inject: dict[str, list[str]]):
        self.left = {k: list(v) for k, v in inject.items()}

    def take(self, key: str) -> str | None:
        q = self.left.get(key)
        return q.pop(0) if q else None

    def peek_check(self, unit: str) -> str | None:
        q = self.left.get(unit)
        if q and q[0].startswith("check:"):
            return q.pop(0)[len("check:"):]
        return None


class FakeSkill(Skill):
    """The skill boundary of a dry run: commands are logged, not run; checks pass unless injected."""

    def __init__(self, cfg, faults: FaultBook):
        super().__init__(cfg)
        self.faults = faults
        self.pending_findings: dict[str, list[dict]] = {}

    def run(self, cmd: str, subs: Subs, timeout: float | None = None) -> CommandResult:
        res = CommandResult(self.expand(cmd, subs, quote=False), [], 0, "(dry run: not executed)\n")
        self.calls.append(res)
        return res

    def unit_findings(self, unit: str, commands: list[str], subs: Subs):
        found = self.pending_findings.pop(unit, [])
        return found, [CommandResult(c, [], 1 if found else 0) for c in commands]

    def gate_check(self, gate: dict, subs: Subs):
        token = self.faults.take(gate["id"])
        cmds = [self.expand(c, subs, quote=False) for c in _gate_cmds(gate)]
        if token == "fail":
            return False, [CommandResult(c, [], 1, "", "(dry run: injected gate failure)") for c in cmds]
        return True, [CommandResult(c, [], 0) for c in cmds]


def _gate_cmds(gate: dict) -> list[str]:
    from .skill import gate_commands
    return gate_commands(gate)


class FakeExecutor:
    """Copies a Unit's outputs (and its ledger events) from the fixtures."""

    def __init__(self, faults: FaultBook, topic_fixture: Path | None = None, gen_fixture: Path | None = None):
        self.faults = faults
        self.topic_fx = Path(topic_fixture or TOPIC_FIXTURE)
        self.gen_fx = Path(gen_fixture or GEN_FIXTURE)

    # --------------------------------------------------------------------------------------------- execute
    def execute(self, ctx: RunContext, unit: str, recipe: Recipe | None, phase: str, gen: int | None,
                attempt: int) -> ExecResult:
        inst = instance_of(gen, phase)
        token = self.faults.take(unit) if not (unit == "B5" and phase != "round2") else None
        if token in CATEGORIES:
            rec = ctx.error(CODE_FOR.get(token, "IDEATE.TOOL.FAILED"), f"dry run: injected {token} on attempt "
                            f"{attempt}", unit=unit, instance=inst, attempt=attempt, category=token)
            return ExecResult(False, [rec], {"calls": 1})
        if token and token.startswith("check:"):
            ctx.skill.pending_findings[unit] = [{"level": "ERROR", "code": token[6:], "unit": unit,
                                                 "message": "dry run: injected check finding"}]
        ctx.say(f"      (dry run) {unit} {phase}")
        on_ledger = ledger_block(ctx.reg, unit) is not None
        io = (ctx.reg.legacy_card(unit) or {}).get("io") or {}
        inputs = _hashes(ctx.rd, [s for s in io.get("reads") or [] if s.get("hash_at") != "done"]) if on_ledger else {}
        if unit == "B5":
            self._b5(ctx, gen, phase, token)
        elif unit == "P0":
            (ctx.rd / f"gen_{gen}").mkdir(parents=True, exist_ok=True)
        if unit == "B6":
            self._b6(ctx, gen, abandoned=phase == "abandon")
        else:
            self._copy_outputs(ctx, unit, gen)
        if unit == "P0":
            self._take_question(ctx, gen)
        if on_ledger:
            self._ledger(ctx, unit, inputs)
        return ExecResult(True, [], {"calls": 1})

    # --------------------------------------------------------------------------------------------- outputs
    def _copy_outputs(self, ctx: RunContext, unit: str, gen: int | None) -> None:
        reg = ctx.reg
        src_base = self.gen_fx if gen is not None else self.topic_fx
        dst_base = ctx.rd / f"gen_{gen}" if gen is not None else ctx.rd
        arts = list(reg.units[unit]["outputs"]["artifacts"])
        arts += [a["id"] for a in reg.of_kind("artifact") if a.get("kind") == "view" and
                 set(a.get("derived_from") or []) & set(arts)]
        for art_id in arts:
            art = reg.get(art_id)
            if art.get("kind") not in ("file", "part", "view"):
                continue
            files = artifact_paths(reg, art_id, src_base)
            if not files and gen is not None:          # a generation artifact the gen fixture lacks: try the topic one
                files = artifact_paths(reg, art_id, self.topic_fx)
                src_base = self.topic_fx if files else src_base
            if files:
                for f in files:
                    dst = dst_base / f.relative_to(src_base)
                    if art["kind"] == "part" and dst.exists():
                        continue                       # another Unit's part of the same file is already there
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dst)
            else:
                self._stub(dst_base, art["path"], art["kind"])
            src_base = self.gen_fx if gen is not None else self.topic_fx
        if gen is not None:                            # the files ideate_v2 reads a planning Unit's state from
            for rel in PLANNING_FILES.get(unit, []):
                src, dst = self.gen_fx / rel, dst_base / rel
                if src.is_file() and not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)

    @staticmethod
    def _stub(base: Path, pattern: str, kind: str) -> None:
        path = pattern.split(",")[0].strip()
        if path.startswith("gen_k/"):
            path = path[len("gen_k/"):]
        for token, value in (("<key>", "dryrun2026"), ("<Name>", "dry_run_idea"), ("<topic>", "topic"), ("Q_NNN", "Q_001"),
                             ("<id>", "Q01"), ("<hash>", "0000"), ("*", "dry_run")):
            path = path.replace(token, value)
        p = base / path
        if p.exists() and kind == "part":
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text({".json": "{}\n", ".jsonl": "", ".md": "# (dry run stub)\n"}.get(p.suffix, ""), encoding="utf-8")

    def _ledger(self, ctx: RunContext, unit: str, inputs: dict) -> None:
        """begin + done as the skill's ledger records them: the inputs the Unit's card declares, hashed before it ran,
        and its outputs, hashed now (the same formats as it_ledger; evals/build_datasets.py does the same)."""
        io = (ctx.reg.legacy_card(unit) or {}).get("io") or {}
        at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        lines = [{"ev": "begin", "unit": unit, "inst": "-", "at": at, "inputs": inputs},
                 {"ev": "done", "unit": unit, "inst": "-", "at": at, "inputs": inputs,
                  "outputs": _hashes(ctx.rd, io.get("owns") or []), "counts": {}, "degraded": [], "tool": "dry-run"}]
        path = ctx.rd / "_state" / "ledger.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            for ln in lines:
                f.write(json.dumps(ln, ensure_ascii=False) + "\n")

    # --------------------------------------------------------------------------------------------- Stage B
    def _b5(self, ctx: RunContext, gen: int | None, phase: str, token: str | None) -> None:
        if phase == "round2":
            d = {"decision": "finalize", "reason": "dry run: default"}
            if token and token.startswith("revise:"):
                d = {"decision": "revise", "enters": token.split(":", 1)[1], "reason": "dry run: injected"}
            p = ctx.decision_path(gen)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(d, indent=1) + "\n", encoding="utf-8")

    @staticmethod
    def _take_question(ctx: RunContext, gen: int | None) -> None:
        """question-take: the generation gets the next ready question nobody used (question-next's choice)."""
        from .loops import ready_questions_left
        qp = ctx.rd / f"gen_{gen}" / "question.json"
        q = json.loads(qp.read_text(encoding="utf-8")) if qp.is_file() else {}
        qp.write_text("{}", encoding="utf-8")                  # this generation's own (fixture) id must not count
        left = ready_questions_left(ctx.rd)
        q["id"] = left[0] if left else q.get("id", "Q_001")
        qp.write_text(json.dumps(q, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    def _b6(self, ctx: RunContext, gen: int | None, abandoned: bool = False) -> None:
        gd = ctx.rd / f"gen_{gen}"
        if abandoned:                                          # consume --abandoned: nothing appended
            cfg_path = ctx.rd / "step0_session_config.json"
            qp = gd / "question.json"
            if cfg_path.is_file() and qp.is_file():
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                cfg.setdefault("consumed", []).append({"question": json.loads(qp.read_text(encoding="utf-8")).get("id"),
                                                       "abandoned": "dry run: T09", "gen": gen})
                cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            return
        idea = json.loads((gd / "idea.json").read_text(encoding="utf-8")) if (gd / "idea.json").is_file() else {}
        archive = ctx.topic.with_suffix(".json") if ctx.topic else ctx.rd.parent / "ideas.json"
        ideas = json.loads(archive.read_text(encoding="utf-8")) if archive.is_file() else []
        ideas.append({**idea, "Name": f"{idea.get('Name', 'dry_run_idea')}_{gen}"} if idea else {"Name": f"dry_{gen}"})
        archive.write_text(json.dumps(ideas, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        cfg_path = ctx.rd / "step0_session_config.json"
        if cfg_path.is_file():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            q = json.loads((gd / "question.json").read_text(encoding="utf-8")).get("id") if (gd / "question.json").is_file() else None
            cfg.setdefault("consumed", []).append({"question": q, "idea": ideas[-1].get("Name"), "gen": gen})
            cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        for rel in (f"body/B_draft_{ideas[-1].get('Name')}.md", "step8_journal_recommendations.md"):
            p = gd / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.exists():
                p.write_text("# (dry run stub)\n", encoding="utf-8")

