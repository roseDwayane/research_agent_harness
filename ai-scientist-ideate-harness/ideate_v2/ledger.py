"""Read-only view of the legacy ledger (<RD>/_state/ledger.jsonl) with v2 dependency semantics.

States follow the legacy it_ledger.unit_state: todo | running | waiting | failed | done | stale. Differences, by design
(decision D-11):
- hashes are recomputed only for spec ids v2 can reproduce exactly (plain files, globs, step0 keys with or without a
  pick); basis/view/part/strip/kinds specs are counted as ``unverifiable`` and left to ``ideate_tools.py status``;
- upstream staleness uses the v2 ``requires`` (e.g. B1 also requires A1.v, decision D-12); as in the legacy rule, an
  upstream that is stale only through this Unit's own output does not make it stale (the A5 -> A3 re-screen).
v2 never writes the legacy ledger.
"""
from __future__ import annotations

import re
from pathlib import Path

from .jsonio import read_json, read_jsonl, sha256_file, sha256_json
from .registry import Registry

LEDGER_REL = "_state/ledger.jsonl"
STATE_EVENTS = ("begin", "done", "pending", "fail")
_STEP0 = re.compile(r"^step0:([A-Za-z0-9_]+)(?:\[([A-Za-z0-9_,]+)\])?$")
_UNVERIFIABLE = re.compile(r"^(basis:|topic$)| (view|part|kinds)=| -")


def ledger_block(reg: Registry, unit_id: str) -> str | None:
    """The legacy ledger block of a Unit: search, fulltext, fusion - or None when it is not on the ledger."""
    u = reg.units.get(unit_id) or {}
    if not u.get("on_ledger"):
        return None
    if unit_id in ("A6.d", "A6.c"):
        return "fulltext"
    block = (reg.get(u["step"]) if u.get("step") in reg.index else {}).get("block")
    return {"BLK-search": "search", "BLK-fusion": "fusion"}.get(block)


def load_events(run_dir: Path) -> tuple[list[dict], list[dict]]:
    return read_jsonl(Path(run_dir) / LEDGER_REL)


def spec_hash(run_dir: Path, sid: str, cfg: dict) -> tuple[str, str | None]:
    """-> ("verified" | "unverifiable", hash or None). Formats match legacy it_ledger.spec_hash for the forms it
    reproduces."""
    if _UNVERIFIABLE.search(sid):
        return "unverifiable", None
    m = _STEP0.match(sid)
    if m:
        key, pick = m.group(1), m.group(2)
        if key not in cfg:
            return "verified", None
        v = cfg[key]
        if pick and isinstance(v, dict):
            v = {k: v.get(k) for k in pick.split(",")}
        return "verified", sha256_json(v)
    rd = Path(run_dir)
    if any(ch in sid for ch in "*?["):
        files = sorted(p for p in rd.glob(sid) if p.is_file())
        return "verified", (sha256_json([[f.relative_to(rd).as_posix(), sha256_file(f)] for f in files]) if files
                            else None)
    return "verified", sha256_file(rd / sid)


def spec_id(spec: dict) -> str:
    """The ledger key of an io spec - a port of the legacy it_ledger.spec_id."""
    if "basis" in spec:
        return f"basis:{spec['basis']}"
    if "step0" in spec:
        return f"step0:{spec['step0']}" + (f"[{','.join(spec['pick'])}]" if spec.get("pick") else "")
    if spec.get("topic"):
        return "topic"
    sid = spec.get("file") or spec.get("glob") or ""
    if spec.get("strip"):
        sid += " -" + ",".join(spec["strip"])
    if spec.get("kinds"):
        sid += " kinds=" + ",".join(spec["kinds"])
    if spec.get("view"):
        sid += " view=" + spec["view"]
    elif spec.get("part"):
        sid += " part=" + spec["part"]
    return sid


def declared_reads(reg: Registry, unit_id: str) -> list[str]:
    """Spec ids of the inputs the legacy card declares (hashed at begin)."""
    io = (reg.legacy_card(unit_id) or {}).get("io") or {}
    return [spec_id(s) for s in io.get("reads") or [] if isinstance(s, dict) and s.get("hash_at") != "done"]


def _revisers(reg: Registry, unit_id: str) -> set[str]:
    card = reg.legacy_card(unit_id) or {}
    return {r.get("by") for r in card.get("revised_by") or [] if isinstance(r, dict)}


def unit_states(reg: Registry, run_dir: Path, events: list[dict] | None = None) -> dict[str, dict]:
    rd = Path(run_dir)
    if events is None:
        events, _ = load_events(rd)
    cfg_path = rd / "step0_session_config.json"
    try:
        cfg = read_json(cfg_path) if cfg_path.is_file() else {}
    except ValueError:
        cfg = {}
    blocks_seen = {ledger_block(reg, e.get("unit")) for e in events if e.get("unit") in reg.units}
    memo: dict[str, dict] = {}

    def state(unit: str, stack: tuple = ()) -> dict:
        if unit in memo:
            return memo[unit]
        mine = [(i, e) for i, e in enumerate(events) if e.get("unit") == unit and e.get("ev") in STATE_EVENTS]
        res: dict = {"state": "todo", "why": "", "inst": None, "at": None, "changed": [], "unverifiable": 0}
        if not mine:
            memo[unit] = res
            return res
        idx, last = mine[-1]
        res.update(inst=last.get("inst"), at=last.get("at"))
        if last["ev"] == "begin":
            res.update(state="running", why=f"begun {last.get('at')}, no done: interrupted or still running")
        elif last["ev"] == "pending":
            res.update(state="waiting", why=str(last.get("why", "")))
        elif last["ev"] == "fail":
            res.update(state="failed", why=str(last.get("why", "")))
        else:
            res.update(state="done")
            changed_out, unverifiable = [], 0
            for sid, h in (last.get("outputs") or {}).items():
                status, cur = spec_hash(rd, sid, cfg)
                if status == "unverifiable":
                    unverifiable += 1
                elif cur != h:
                    changed_out.append(sid)
            later_units = {e.get("unit") for e in events[idx + 1:]}
            if changed_out and later_units & _revisers(reg, unit):
                changed_out = []                     # a declared reviser changed it: a deviation, not stale
            changed_in = []
            recorded = last.get("inputs") or {}
            for sid, h in recorded.items():
                status, cur = spec_hash(rd, sid, cfg)
                if status == "unverifiable":
                    unverifiable += 1
                elif cur != h:
                    changed_in.append(sid)
            for sid in declared_reads(reg, unit):       # legacy rule: read now, not recorded then = changed
                if sid in recorded:
                    continue
                status, cur = spec_hash(rd, sid, cfg)
                if status == "unverifiable":
                    unverifiable += 1
                elif cur is not None:
                    changed_in.append(sid)
            res["unverifiable"] = unverifiable
            if changed_out:
                res.update(state="stale", why="its output changed since done: " + ", ".join(changed_out[:3]),
                           changed=changed_out)
            elif changed_in:
                res.update(state="stale", why="input changed: " + ", ".join(changed_in[:3]), changed=changed_in)
            else:
                own = set(last.get("outputs") or {})
                for up in reg.requires(unit):
                    if up in stack or up == unit or ledger_block(reg, up) is None:
                        continue
                    if ledger_block(reg, up) not in blocks_seen:
                        continue                     # that block ran before the ledger existed
                    st = state(up, stack + (unit,))
                    if st["state"] == "stale" and st.get("changed") and set(st["changed"]) <= own:
                        continue                     # stale only through this Unit's own output: the loop A5 -> A3
                    if st["state"] != "done":
                        res.update(state="stale", why=f"upstream {up} is {st['state']}", changed=st.get("changed") or [])
                        break
        memo[unit] = res
        return res

    return {u: state(u) for u in reg.unit_order() if ledger_block(reg, u) is not None}


def next_runnable(reg: Registry, states: dict[str, dict]) -> list[dict]:
    """Units that should run next: not done, and every on-ledger upstream done."""
    out = []
    for u in reg.topo_order([x for x in states]):
        st = states[u]["state"]
        if st == "done":
            continue
        ups = [r for r in reg.requires(u) if r in states]
        if all(states[r]["state"] == "done" for r in ups):
            action = {"todo": "run", "running": "resume (interrupted?)", "waiting": "finish its checks",
                      "failed": "fix and re-run", "stale": "re-run"}[st]
            out.append({"unit": u, "state": st, "action": action, "why": states[u]["why"]})
    return out


# ------------------------------------------------------------------------------------------- planning (gen_k)
PLANNING_FILES = {
    "P0": ["question.json", "step7b_problem.md"],
    "P1": ["step8_hypothesis.md", "argument.json", "p1_prefill.json"],
    "P2": ["argument.json"],
    "P3": ["decision_tree.json"],
    "P4": ["attack_plan.json", "related_work.md"],
    "P5": ["packaging.json", "idea_draft.json"],
    "B5": ["reflection_log.md", "idea.json"],
    "B6": ["step8_journal_recommendations.md"],
}


def planning_status(run_dir: Path, generation: int) -> dict:
    """Presence-based state of a generation's planning Units (they are not on the ledger yet - OQ-06).
    P2 counts as done when argument.json has experiments; B6 when its journal file exists."""
    gd = Path(run_dir) / f"gen_{int(generation)}"
    if not gd.is_dir():
        return {"generation": generation, "exists": False, "units": {}}
    units = {}
    for u, files in PLANNING_FILES.items():
        present = [f for f in files if (gd / f).is_file()]
        state = "done" if len(present) == len(files) else ("partial" if present else "todo")
        if u == "P2" and state == "done":
            try:
                arg = read_json(gd / "argument.json")
                state = "done" if arg.get("experiments") else "todo"
            except (ValueError, OSError):
                state = "unreadable"
        units[u] = {"state": state, "present": present, "missing": [f for f in files if f not in present],
                    "basis": "file presence (not on the ledger)"}
    return {"generation": generation, "exists": True, "units": units}
