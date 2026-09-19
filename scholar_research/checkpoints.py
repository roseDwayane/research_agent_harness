"""The four human checkpoints, in three modes (plan §5).

interactive  print the review material, read a decision from stdin
file         take the decision from a decisions.toml section
auto         apply the default rule (no borderline rescue; lock top gap; approve)

Every decision is written to ``checkpoints.json`` so replay re-applies the
same human choice without asking again.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from .config import tomllib
from .session import CHECKPOINT_NAMES
from .steps.base import Context
from .utils import load_json, truncate


class NeedsHuman(RuntimeError):
    def __init__(self, n: int, material: str):
        self.checkpoint, self.material = n, material
        super().__init__(f"Checkpoint {n} ({CHECKPOINT_NAMES[n]}) needs a human decision")


def load_decisions(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    with open(path, "rb") as fh:
        return tomllib.load(fh)


# --------------------------------------------------------------------------- #
def resolve(ctx: Context, n: int) -> dict[str, Any]:
    """Return the decision dict for checkpoint n, recording it if new."""
    s = ctx.session
    existing = s.load_checkpoints().get(n)
    if existing is not None:
        return existing.decision
    material = render_material(ctx, n)
    mode = ctx.checkpoint_mode
    if mode == "file":
        section = ctx.decisions.get(f"checkpoint{n}")
        if section is None:
            raise NeedsHuman(n, material + f"\n\n→ add a [checkpoint{n}] section to the decisions file")
        decision = normalize(n, section)
    elif mode == "auto":
        decision = auto_decision(ctx, n)
    else:
        if not sys.stdin.isatty():
            raise NeedsHuman(n, material)
        ctx.say(material)
        decision = ask(ctx, n)
    s.record_checkpoint(n, mode, decision)
    apply(ctx, n, decision)
    return decision


def normalize(n: int, raw: dict[str, Any]) -> dict[str, Any]:
    if n == 1:
        return {"approved": bool(raw.get("approved", True)), "note": raw.get("note", "")}
    if n == 2:
        inc = raw.get("include", [])
        if isinstance(inc, str):
            inc = [x.strip() for x in inc.split(",") if x.strip()]
        return {"include": sorted(set(inc))}
    if n == 3:
        lock = raw.get("lock")
        if not lock:
            raise ValueError("checkpoint3 needs `lock = \"GAP_00N\"`")
        drop = raw.get("drop", [])
        if isinstance(drop, str):
            drop = [x.strip() for x in drop.split(",") if x.strip()]
        return {"lock": _gap_id(lock), "drop": [_gap_id(d) for d in drop], "constraint": raw.get("constraint", "")}
    if n == 4:
        return {"approved": bool(raw.get("approved", True)), "journal": raw.get("journal"), "note": raw.get("note", "")}
    raise ValueError(n)


def _gap_id(x: str) -> str:
    m = re.search(r"(\d+)", str(x))
    return f"GAP_{int(m.group(1)):03d}" if m else str(x)


def auto_decision(ctx: Context, n: int) -> dict[str, Any]:
    if n == 1:
        return {"approved": True, "note": "auto"}
    if n == 2:
        return {"include": []}
    if n == 3:
        gaps = load_json(ctx.session.path("step7_gaps.json"))["gaps"]
        return {"lock": gaps[0]["id"], "drop": [g["id"] for g in gaps[1:]], "constraint": ""}
    if n == 4:
        return {"approved": True, "journal": None, "note": "auto"}
    raise ValueError(n)


def apply(ctx: Context, n: int, decision: dict[str, Any]) -> None:
    if n == 2 and decision.get("include"):
        from .steps.s3_screen import apply_checkpoint2

        apply_checkpoint2(ctx, decision["include"])
    if n == 1 and not decision.get("approved", True):
        raise RuntimeError("Checkpoint 1 rejected — edit step0_session_config.json and re-run `step 1` or record approval")
    if n == 4 and not decision.get("approved", True):
        raise RuntimeError("Checkpoint 4 rejected — re-run step 8 with a constraint or record approval")


# --------------------------------------------------------------------------- #
def render_material(ctx: Context, n: int) -> str:
    s = ctx.session
    if n == 1:
        cfg = s.load_config()
        p, z = cfg.pico, cfg.pico_zh
        lines = [f"\n⛳ Checkpoint 1: 初始定向核准 — {cfg.topic}", "", "| PICO | English | 繁體中文 |", "|---|---|---|"]
        for k in ("population", "intervention", "comparison", "outcome", "setting"):
            lines.append(f"| {k} | {getattr(p, k)} | {getattr(z, k) if z else ''} |")
        lines += [f"| timeframe | {p.timeframe} | |", ""]
        lines += [f"{q.id} [{q.strategy}] {q.query}\n    ↳ {q.rationale}" for q in cfg.queries]
        lines += ["", "Edit step0_session_config.json to adjust PICO/queries, then approve. / 可先編輯 step0_session_config.json 再核准。"]
        return "\n".join(lines)
    if n == 2:
        rec = load_json(s.path("step3_screening_all.json"))
        bord = [p for p in rec["papers"] if p["screening"]["category"] == "borderline"]
        lines = [f"\n⛳ Checkpoint 2: 邊緣打撈 — {len(bord)} borderline papers", "", "| ID | Composite | Hub | Title | Rationale |", "|---|---|---|---|---|"]
        for p in bord:
            lines.append(f"| {p['id']} | {p['screening']['composite']:.2f} | {'Yes' if p['citation_network']['is_hub'] else '—'} | {truncate(p['title'], 70)} | {truncate(p['screening']['rationale'], 80)} |")
        lines += ["", "Enter paper IDs to include (comma-separated) or leave blank. / 輸入要納入的論文 ID，或直接 Enter。"]
        return "\n".join(lines)
    if n == 3:
        gaps = load_json(s.path("step7_gaps.json"))["gaps"]
        lines = ["\n⛳ Checkpoint 3: 戰場選擇", "", "| Rank | Gap | Type | Sev | Nov | Fea | Composite | Title |", "|---|---|---|---|---|---|---|---|"]
        for g in gaps:
            x = g["gap"]
            lines.append(f"| {g['rank']} | {g['id']} | {x['gap_type']} | {x['severity']} | {x['novelty']} | {x['feasibility']} | {g['composite']:.2f} | {x['title_en']} / {x['title_zh']} |")
        lines += ["", "Say e.g. `Lock GAP_001, drop GAP_002` (optionally `; constraint: observational only`). / 例：「鎖定 GAP_001，放棄 GAP_002」"]
        return "\n".join(lines)
    if n == 4:
        spec = load_json(s.path("step8_hypothesis.json"))["spec"]
        lines = ["\n⛳ Checkpoint 4: 護城河確認", "", "IN scope:"] + [f"  - {x['dimension_en']}: {x['spec_en']}" for x in spec["scope_in"]] + ["", "OUT scope:"] + [f"  - {x['exclusion_en']} — {x['rationale_en']}" for x in spec["scope_out"]] + ["", f"H1: {spec['hypotheses'][0]['h1_en']}", f"Top journal: {spec['journals'][0]['name']}", "", "Type `approve` (optionally `approve; journal: <name>`) or `reject`. / 輸入「核准」或「拒絕」。"]
        return "\n".join(lines)
    raise ValueError(n)


def ask(ctx: Context, n: int) -> dict[str, Any]:
    ans = input("> ").strip()
    return parse_answer(n, ans)


def parse_answer(n: int, ans: str) -> dict[str, Any]:
    low = ans.lower()
    if n == 1:
        ok = low in ("", "y", "yes", "ok", "approve", "approved", "proceed", "通過", "核准", "同意")
        return {"approved": ok, "note": ans}
    if n == 2:
        if low in ("", "no", "none", "no changes", "proceed", "無", "沒有"):
            return {"include": []}
        ids = re.findall(r"paper_\d{3}", ans)
        return {"include": sorted(set(ids))}
    if n == 3:
        constraint = ""
        if ";" in ans and "constraint" in low:
            ans, c = ans.split(";", 1)
            constraint = c.split(":", 1)[-1].strip()
        ids = re.findall(r"GAP[_\s]?(\d+)", ans, re.I)
        if not ids:
            raise ValueError("no GAP id found in answer")
        lock = f"GAP_{int(ids[0]):03d}"
        m = re.search(r"(drop|放棄)(.*)$", ans, re.I)
        drop = [f"GAP_{int(x):03d}" for x in re.findall(r"GAP[_\s]?(\d+)", m.group(2), re.I)] if m else []
        return {"lock": lock, "drop": [d for d in drop if d != lock], "constraint": constraint}
    if n == 4:
        journal = None
        if "journal" in low and ":" in ans:
            journal = ans.split("journal", 1)[1].split(":", 1)[1].strip().strip(".")
        ok = any(w in low for w in ("approve", "approved", "yes", "ok", "核准", "同意", "scope approved")) or low == ""
        return {"approved": ok, "journal": journal, "note": ans}
    raise ValueError(n)
