"""The ledger of the literature search: what each Unit did, on which inputs, with which outputs - and what follows.

Every search-block command records its Unit's `begin` and, once the Unit's own checks pass, its `done`
(<RD>/_state/ledger.jsonl, append-only). A Unit instance is current when its last `done` stands, its outputs still
hash as recorded, and its inputs still hash as they did at `begin`; otherwise it is stale. Between `begin` and `done`
the tool compares a snapshot of the research folder: a change outside the Unit's declared files fails the `done`.
The Unit's files come from its card (`io` in scripts/ideate_units.json).

Views, rebuilt after every `done` and owned by no Unit: <RD>/STATUS.md and <RD>/search_caveats.json (the search
block's caveats - its exit contract).

  ideate_tools.py next   <RD>            the next Unit to run, with its rules and commands
  ideate_tools.py status <RD> [--json]   every Unit's state; rebuilds STATUS.md and search_caveats.json
"""

from __future__ import annotations

import fnmatch
import json
import os
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from it_common import die, now_iso, read_json, read_jsonl, resolve_topic_file, sha256_file, sha256_json

ORDER = ["A1.p", "A1.q", "A1.v", "A1.e", "A2.s", "A2.m", "A2.c", "A3.b", "A3.g", "A3", "A5", "A4.k", "A4.b"]
# the fusion block (docs/decisions/PLAN_ideate_fusion.md): once per topic, deconstruct -> align -> collide -> reconstruct
FUSION = ["A7.D", "A7.A1", "A7.A2", "A7.A3", "B1", "A7.X1", "A7.X2", "B3.c", "B3", "A7.R1", "A7.R2", "A7.R3", "B2",
          "B3.5", "F.9"]
# A6 full text (it_fulltext): between the two, a block of its own so that a topic whose full texts were fetched before
# these Units existed has no fulltext events - and its fusion Units do not go stale for want of them (unit_state)
FULLTEXT = ["A6.d", "A6.c"]
BLOCKS = {"search": ORDER, "fulltext": FULLTEXT, "fusion": FUSION}   # ORDER stays the search block's list (an alias)
LEDGER = "_state/ledger.jsonl"
SNAPS = "_state/ledger_snap"
VIEWS = ["STATUS.md", "search_caveats.json", "fulltext_caveats.json", "step1_protocol.md",
         # fusion views: re-rendered by whichever command needs them, owned by no Unit (armor §2.4)
         "fusion_caveats.json", "knowledge/_notes/*.md", "knowledge/points/*.md", "knowledge/planes/*.md",
         "knowledge/_MANIFEST.md", "knowledge/concept_index.json", "knowledge/methods_matrix.json",
         "knowledge/methods_matrix.md", "knowledge/fusion_map.md"]
# never snapshotted: large, written by later blocks, or the ledger's own state. A fusion Unit's snapshot does look at
# knowledge/ and step5_full_text/ (its own ground); a search Unit's does not, so neither block is blamed for the other.
IGNORE_DIRS = {"pdfs", "step5_full_text", "knowledge", "report", "_work_ignore"}
IGNORE_DIRS_BY_BLOCK = {"search": IGNORE_DIRS, "fulltext": {"knowledge", "report", "_work_ignore"},
                        "fusion": {"pdfs", "report", "_work_ignore"}}
# _state/errors/** and ERRORS.md: the harness's error reports (scholar_research.v2), written beside any open Unit
IGNORE_GLOBS = ["_state/net/**", "_state/ledger*", "_state/ledger_snap/**", "_state/errors/**", "ERRORS.md", "gen_*/**",
                "*.tmp", "**/.DS_Store",
                "**/__pycache__/**"]
ICON = {"done": "✔", "stale": "↻", "running": "⏳", "waiting": "⏳", "failed": "✖", "todo": "·"}

COMMANDS = {
    "A1.p": ["ideate_tools.py frame set-protocol $RD $RD/_state/A1/protocol.json"],
    "A1.q": ["ideate_tools.py frame set-strategy $RD $RD/_state/A1/strategy.json", "mcp_bridge.py probe $RD"],
    "A1.v": ["ideate_tools.py frame set-context $RD $RD/_state/A1/context.json"],
    "A1.e": ["ideate_tools.py frame eval-brief $RD", "(one subagent: read the brief, return the JSON)",
             "ideate_tools.py frame set-evaluation $RD $RD/_state/A1e/round_<n>.json"],
    "A2.s": ["mcp_bridge.py search $RD"],
    "A2.m": ["mcp_bridge.py merge $RD"],
    "A2.c": ["ideate_tools.py search-check $RD", "(judge every query)", "ideate_tools.py relevance-set $RD verdicts.json"],
    "A3.b": ["mcp_bridge.py bibliometrics $RD"],
    "A3.g": ["ideate_tools.py screen-gate $RD"],
    "A3": ["ideate_tools.py screen-plan $RD", "(one subagent per batch)", "ideate_tools.py screen-merge $RD",
           "ideate_tools.py screen-build $RD $RD/screening_scores.json"],
    "A5": ["mcp_bridge.py snowball $RD"],
    "A4.k": ["ideate_tools.py export $RD"],
    "A4.b": ["mcp_bridge.py bibliography $RD"],
    # full text (references/scholar-pipeline.md §2): every command below is the Unit's boundary; its checks close it
    "A6.d": ["ideate_tools.py tier1 $RD", "mcp_bridge.py download $RD", "ideate_tools.py arxiv-pdfs $RD",
             "(paywalls ate the budget? once:) ideate_tools.py tier1 $RD --top-up, then download and arxiv-pdfs again"],
    "A6.c": ["IDEATE_PYTHON=$PY bash pdf2md.sh $RD (in the background)", "ideate_tools.py figures $RD",
             "ideate_tools.py fulltext-status $RD"],
    # fusion block (references/fusion/): the Units the model writes are opened with unit-begin and closed with unit-done
    "A7.D": ["ideate_tools.py decon-plan $RD",
             "(one subagent per batch)", "ideate_tools.py decon-merge $RD"],
    "A7.A1": ["ideate_tools.py align-terms $RD", "(write the vocabulary)", "ideate_tools.py align-set $RD vocab.json"],
    "A7.A2": ["ideate_tools.py align-coords $RD --suggest", "ideate_tools.py align-coords $RD --auto",
              "ideate_tools.py align-coords $RD --apply coords.json"],
    "A7.A3": ["ideate_tools.py unit-begin $RD A7.A3", "ideate_tools.py align-points $RD", "(write concept Points)",
              "ideate_tools.py build-cards $RD $RD/knowledge_cards.json", "ideate_tools.py unit-done $RD A7.A3"],
    "B1": ["ideate_tools.py env-probe $RD --write (the experiments' interpreter)", "ideate_tools.py lens-set $RD lens.json",
           "ideate_tools.py build-methods $RD $RD/knowledge/methods_matrix_input.json $RD/knowledge/decon/*.json"],
    "A7.X1": ["ideate_tools.py collide-candidates $RD"],
    "A7.X2": ["ideate_tools.py collide-plan $RD", "(one subagent per batch)", "ideate_tools.py collide-merge $RD"],
    "B3.c": ["ideate_tools.py collide-plan $RD --lens", "(one subagent)", "ideate_tools.py collide-merge $RD"],
    "B3": ["(write the gap list)", "ideate_tools.py gaps-set $RD gaps.json"],
    "A7.R1": ["ideate_tools.py unit-begin $RD A7.R1", "ideate_tools.py recon-candidates $RD",
              "(Lines, findings Points)", "ideate_tools.py unit-done $RD A7.R1"],
    "A7.R2": ["ideate_tools.py unit-begin $RD A7.R2", "(Planes)", "ideate_tools.py build-cards $RD $RD/knowledge_cards.json",
              "ideate_tools.py unit-done $RD A7.R2"],
    "A7.R3": ["ideate_tools.py unit-begin $RD A7.R3", "(the descriptive Body)", "ideate_tools.py unit-done $RD A7.R3"],
    "B2": ["ideate_tools.py unit-begin $RD B2", "(step6_sota_review.md)", "ideate_tools.py unit-done $RD B2"],
    "B3.5": ["ideate_tools.py unit-begin $RD B3.5", "ideate_tools.py questions-prefill $RD GAP_NNN",
             "(questions/Q_NNN.md)", "ideate_tools.py unit-done $RD B3.5"],
    "F.9": ["ideate_tools.py questions-index $RD", "ideate_tools.py concept-index $RD"],
}


# ================================================================================================ cards and specs
_CARDS: dict = {}


def cards() -> dict:
    if not _CARDS:
        reg = read_json(Path(__file__).resolve().parent / "ideate_units.json")
        _CARDS.update({c["id"]: c for c in reg["units"]})
    return _CARDS


def block_of(unit: str) -> str:
    return next((b for b, us in BLOCKS.items() if unit in us), "search")


def requires(unit: str) -> list[str]:
    out = []
    for r in cards()[unit].get("requires") or []:
        tok = str(r).split()[0].strip("(),")
        if tok in cards() and tok != unit:
            out.append(tok)
    return out


def _cfg(rd: Path) -> dict:
    p = Path(rd) / "step0_session_config.json"
    return read_json(p) if p.exists() else {}


def _strip(x, keys: set):
    if isinstance(x, dict):
        return {k: _strip(v, keys) for k, v in x.items() if k not in keys}
    if isinstance(x, list):
        return [_strip(v, keys) for v in x]
    return x


def spec_id(spec: dict) -> str:
    if "basis" in spec:
        return f"basis:{spec['basis']}"
    if "step0" in spec:
        return f"step0:{spec['step0']}" + (f"[{','.join(spec['pick'])}]" if spec.get("pick") else "")
    if spec.get("topic"):
        return "topic"
    sid = spec.get("file") or spec.get("glob")
    if spec.get("strip"):
        sid += " -" + ",".join(spec["strip"])
    if spec.get("kinds"):
        sid += " kinds=" + ",".join(spec["kinds"])
    if spec.get("view"):
        sid += " view=" + spec["view"]
    elif spec.get("part"):
        sid += " part=" + spec["part"]
    return sid


def _basis(rd: Path, cfg: dict, name: str):
    """Inputs that a declared revision must not invalidate, hashed the way the Unit's own checks see them."""
    if name == "protocol_written":                # what A1.q was built on (it_frame.protocol_content_hash: A1.p's own
        from it_frame import protocol_content_hash    # protocol, A2.c's added and retired terms excluded)
        return protocol_content_hash(cfg)
    if name == "protocol_evaluated":              # what A1.e judged (it_frame.protocol_hash: A2.c's revisions excluded)
        from it_frame import protocol_hash
        return protocol_hash(cfg)
    if name == "query_renderings":                # what A2.s must have run: every active query's rendering, and D1
        from it_search import DENSE_ID, instance_hash
        qs = sorted((q["id"], instance_hash(cfg, q)) for q in cfg.get("queries") or [] if q.get("status", "active") == "active")
        seeds = sorted(k.get("doi") or "" for k in ((cfg.get("scope_probe") or {}).get("known_items") or []) if k.get("resolved"))
        return sha256_json({"queries": qs, DENSE_ID: seeds, "depth": cfg.get("depth")})
    raise KeyError(name)


def spec_hash(rd: Path, spec: dict, cfg: dict | None = None) -> str | None:
    rd = Path(rd)
    if "basis" in spec:
        cfg = _cfg(rd) if cfg is None else cfg
        return _basis(rd, cfg, spec["basis"]) if "protocol" in cfg else None
    if "step0" in spec:
        cfg = _cfg(rd) if cfg is None else cfg
        if spec["step0"] not in cfg:
            return None
        v = cfg[spec["step0"]]
        if spec.get("pick") and isinstance(v, dict):
            v = {k: v.get(k) for k in spec["pick"]}
        return sha256_json(v)
    if spec.get("topic"):
        cfg = _cfg(rd) if cfg is None else cfg
        tf = resolve_topic_file(rd, cfg.get("topic_file"))
        if tf is None and rd.name.endswith("_research"):       # before A1.p writes step0: the sibling <topic>.md
            sib = rd.resolve().parent / (rd.name[: -len("_research")] + ".md")
            tf = sib if sib.exists() else None
        return sha256_file(tf) if tf else None
    if "glob" in spec:
        files = sorted(rd.glob(spec["glob"]))
        return sha256_json([[f.relative_to(rd).as_posix(), sha256_file(f)] for f in files]) if files else None
    p = rd / spec["file"]
    if not p.exists():
        return None
    if spec.get("view") == "snowball_basis":     # A5: the screening judgements its latest round drew seeds from
        from it_snowball import seed_basis
        return sha256_json(seed_basis(rd))
    if spec.get("view") == "soft_criteria":      # A3: the criteria A1.e's E6 made soft (none: as if absent)
        from it_frame import soft_criteria
        soft = {k: {f: v for f, v in s.items() if f != "linked"} for k, s in soft_criteria(rd).items()}
        return sha256_json(soft) if soft else None   # `linked` follows from the criteria A3 reads anyway
    if spec.get("part"):                         # fusion: one Unit's part of a file several Units write
        v = _part(read_jsonl(p) if p.suffix == ".jsonl" else read_json(p), spec["part"])
        empty = not v or (isinstance(v, dict) and all(x in (None, {}, []) for x in v.values()))
        return None if empty else sha256_json(v)     # an empty part = no part, as a missing file
    if spec.get("strip") or spec.get("kinds"):
        data = read_json(p)
        if spec.get("kinds"):
            data = [e for e in (data.get("entries") or []) if e.get("kind") in spec["kinds"]]
            if not data:
                return None                      # no entry of these kinds = no file, for the Units that read them
        if spec.get("strip"):
            data = _strip(data, set(spec["strip"]))
        return sha256_json(data)
    return sha256_file(p)


def _part(data: dict, part: str):
    """The part of a shared fusion file one Unit owns or reads: alignment.json (vocab / coords),
    knowledge_cards.json (concept Points / findings Points / Planes), collisions.jsonl (paper / lens judgements)."""
    if part in ("collisions-paper", "collisions-lens"):
        from it_collide import LENS_TYPES
        return [r for r in data if (r.get("type") in LENS_TYPES) == (part == "collisions-lens")]
    if part == "vocab":
        return {k: data.get(k) for k in ("vocab", "vocab_basis")}
    if part == "coords":
        return {k: data.get(k) for k in ("coords", "coords_basis")}
    pts = data.get("points") or []
    if part == "points-align":                 # without `collisions`: A7.R1 attaches those (part align-point-collisions)
        return [{k: v for k, v in p.items() if k != "collisions"} for p in pts if p.get("origin") == "align"]
    if part == "align-point-collisions":
        return {p.get("slug"): p.get("collisions") for p in pts if p.get("origin") == "align" and p.get("collisions")}
    if part == "points-collide":
        return [p for p in pts if p.get("origin") == "collide"]
    if part == "planes":
        return data.get("planes") or []
    raise KeyError(part)


def io(unit: str) -> dict:
    return cards()[unit].get("io") or {"reads": [], "owns": [], "scratch": [], "also_writes": []}


def hashes(rd: Path, specs: list) -> dict:
    cfg = _cfg(rd)
    return {spec_id(s): spec_hash(rd, s, cfg) for s in specs}


def tool_hash(unit: str) -> str:
    """The version of the code a Unit ran: the hash of the modules its card names."""
    here = Path(__file__).resolve().parent
    mods = sorted({str(c).partition(":")[0] for c in cards()[unit].get("code") or []})
    return sha256_json([[m, sha256_file(here / m)] for m in mods])[:16]


# ====================================================================================================== snapshots
def _ignored(rel: str, dirs: set | None = None) -> bool:
    if rel.split("/", 1)[0] in (IGNORE_DIRS if dirs is None else dirs):
        return True
    return any(fnmatch.fnmatch(rel, g) for g in IGNORE_GLOBS)


def snapshot(rd: Path, block: str = "search") -> dict:
    rd = Path(rd)
    files = {}
    ign = IGNORE_DIRS_BY_BLOCK.get(block, IGNORE_DIRS)
    for root, dirs, names in os.walk(rd):
        relroot = Path(root).relative_to(rd).as_posix()
        dirs[:] = [d for d in dirs if not _ignored(f"{relroot}/{d}".lstrip("./") + "/x", ign)]
        for n in names:
            rel = f"{relroot}/{n}" if relroot != "." else n
            if _ignored(rel, ign):
                continue
            st = os.stat(os.path.join(root, n))
            files[rel] = [st.st_size, st.st_mtime_ns]
    cfg = _cfg(rd)
    return {"files": files, "step0": {k: sha256_json(v) for k, v in cfg.items()}}


def _changed(before: dict, after: dict) -> tuple[set, set]:
    fb, fa = before.get("files") or {}, after.get("files") or {}
    paths = {p for p in set(fb) | set(fa) if fb.get(p) != fa.get(p)} - {"step0_session_config.json"}
    sb, sa = before.get("step0") or {}, after.get("step0") or {}
    keys = {k for k in set(sb) | set(sa) if sb.get(k) != sa.get(k)}
    return paths, keys


def _allowed(unit: str) -> tuple[list, set]:
    spec = io(unit)
    globs, keys = list(VIEWS), set()
    for s in (spec.get("owns") or []) + (spec.get("also_writes") or []):
        if "step0" in s:
            keys.add(s["step0"])
        elif "file" in s or "glob" in s:
            globs.append(s.get("file") or s.get("glob"))
    globs += spec.get("scratch") or []
    return globs, keys


def _match(rel: str, globs: list) -> bool:
    return any(rel == g or fnmatch.fnmatch(rel, g) or (g.endswith("/**") and rel.startswith(g[:-3] + "/")) for g in globs)


# ========================================================================================================= events
def _events(rd: Path) -> list:
    return read_jsonl(Path(rd) / LEDGER)


def _append(rd: Path, ev: dict) -> None:
    """The ledger's own writer: atomic, and outside the interrupt harness (an injected failure must not hide the
    events that show where a run stopped)."""
    p = Path(rd) / LEDGER
    p.parent.mkdir(parents=True, exist_ok=True)
    old = p.read_text(encoding="utf-8") if p.exists() else ""
    tmp = p.with_suffix(".jsonl.tmp")
    tmp.write_text(old + json.dumps(ev, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def _snap_path(rd: Path, unit: str, inst: str) -> Path:
    return Path(rd) / SNAPS / f"{unit}@{inst}.json"


def _foreign_parts(unit: str) -> list[dict]:
    """The parts other fusion Units own of a file this Unit also writes (alignment.json, knowledge_cards.json,
    collisions.jsonl): the file-level check lets the write through, so the parts are compared themselves."""
    if unit not in FUSION:
        return []
    spec = io(unit)
    files = {s["file"] for s in (spec.get("owns") or []) + (spec.get("also_writes") or []) if "file" in s}
    mine = {spec_id(s) for s in spec.get("owns") or []}
    out = {}
    for u in FUSION:
        for s in io(u).get("owns") or []:
            if s.get("part") and s["file"] in files and spec_id(s) not in mine:
                out[spec_id(s)] = s
    return list(out.values())


def begin(rd: Path, unit: str, inst: str = "-") -> None:
    rd = Path(rd)
    snap = snapshot(rd, block_of(unit))
    snap["parts"] = hashes(rd, _foreign_parts(unit))
    p = _snap_path(rd, unit, inst)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snap), encoding="utf-8")
    os.replace(tmp, p)
    _append(rd, {"ev": "begin", "unit": unit, "inst": inst, "at": now_iso(), "inputs": hashes(rd, io(unit).get("reads") or [])})


def _last(rd: Path, unit: str, inst: str | None = None, evs=None) -> tuple[int, dict] | tuple[None, None]:
    evs = _events(rd) if evs is None else evs
    for i in range(len(evs) - 1, -1, -1):
        e = evs[i]
        if e.get("unit") == unit and (inst is None or e.get("inst") == inst):
            return i, e
    return None, None


def _begin_event(evs: list, unit: str, inst: str) -> tuple[int | None, dict | None]:
    for i in range(len(evs) - 1, -1, -1):
        e = evs[i]
        if e.get("unit") == unit and e.get("inst") == inst:
            return (i, e) if e["ev"] == "begin" else (None, None)
    return None, None


def violations(rd: Path, unit: str, inst: str = "-") -> list[str]:
    """What changed since `begin` outside this Unit's files - minus what other Units recorded as theirs meanwhile."""
    rd = Path(rd)
    p = _snap_path(rd, unit, inst)
    if not p.exists():
        return []
    before, after = read_json(p), snapshot(rd, block_of(unit))
    paths, keys = _changed(before, after)
    globs, okeys = _allowed(unit)
    evs = _events(rd)
    bi, _ = _begin_event(evs, unit, inst)
    for e in evs[(bi or 0) + 1:]:
        if e.get("ev") in ("done", "pending", "fail") and e.get("unit") != unit:
            g, k = _allowed(e["unit"])
            globs, okeys = globs + g, okeys | k
    if unit in FUSION:                           # fusion Units may run side by side (reconstruct beside the questions):
        last = {}                                # a Unit begun earlier and still open writes its own files meanwhile
        for e in evs:
            if e.get("ev") in ("begin", "done", "pending", "fail"):
                last[e.get("unit")] = e["ev"]
        for u, ev in last.items():
            if ev == "begin" and u != unit and u in FUSION:
                g, k = _allowed(u)
                globs, okeys = globs + g, okeys | k
    bad = sorted(x for x in paths if not _match(x, globs))
    bad += sorted(f"step0:{k}" for k in keys if k not in okeys)
    if before.get("parts"):                      # another Unit's part of a shared fusion file, unless that Unit ran too
        last = {}
        for e in evs:
            if e.get("ev") in ("begin", "done", "pending", "fail"):
                last[e.get("unit")] = e["ev"]
        ran = {e["unit"] for e in evs[(bi or 0) + 1:] if e.get("unit") not in (unit, None)
               and e.get("ev") in ("begin", "done", "pending", "fail")}
        ran |= {u for u, ev in last.items() if ev == "begin" and u != unit}    # still open: one command closing two Units
        others = {spec_id(s) for u in ran if u in FUSION for s in io(u).get("owns") or []}
        now = hashes(rd, _foreign_parts(unit))
        bad += sorted(sid for sid, h in before["parts"].items() if now.get(sid) != h and sid not in others)
    return bad


def done(rd: Path, unit: str, inst: str = "-", degraded: list | None = None, model: str | None = None,
         render_views: bool = True) -> dict:
    rd = Path(rd)
    evs = _events(rd)
    bi, b = _begin_event(evs, unit, inst)
    if b is None:                                # a done with no begin (a command that is its own boundary)
        begin(rd, unit, inst)
        evs = _events(rd)
        bi, b = _begin_event(evs, unit, inst)
    bad = violations(rd, unit, inst)
    if bad:
        _append(rd, {"ev": "fail", "unit": unit, "inst": inst, "at": now_iso(),
                     "why": "wrote outside its declared files: " + ", ".join(bad[:8])})
        die(f"{unit}: wrote outside its declared files ({', '.join(bad[:8])}): the done is refused; "
            "undo those changes or declare them on the card", 3)
    late = [s_ for s_ in io(unit).get("reads") or [] if s_.get("hash_at") == "done"]   # a view over its own output
    ev = {"ev": "done", "unit": unit, "inst": inst, "at": now_iso(), "inputs": {**(b.get("inputs") or {}), **hashes(rd, late)},
          "outputs": hashes(rd, io(unit).get("owns") or []), "counts": counts(rd, unit),
          "degraded": degraded or [], "tool": tool_hash(unit)}
    if model:
        ev["model"] = model
    _append(rd, ev)
    if render_views:
        render_fusion_only(rd) if unit in FUSION or unit in FULLTEXT else render(rd)
    return ev


def pending(rd: Path, unit: str, why: str, inst: str = "-") -> None:
    """The command finished, but the Unit's checks do not pass yet (a probe to run, a verdict to give)."""
    _append(rd, {"ev": "pending", "unit": unit, "inst": inst, "at": now_iso(), "why": why})
    render_fusion_only(rd) if unit in FUSION or unit in FULLTEXT else render(rd)


def fail(rd: Path, unit: str, why: str, inst: str = "-") -> None:
    _append(rd, {"ev": "fail", "unit": unit, "inst": inst, "at": now_iso(), "why": why})


def note(rd: Path, unit: str, ev: str, **fields) -> None:
    """override / revise / degraded events: recorded, they change no state by themselves."""
    _append(rd, {"ev": ev, "unit": unit, "at": now_iso(), **fields})


@contextmanager
def run_unit(rd: Path, unit: str, inst: str = "-", check=None, degraded=None):
    """begin; the body; then done when `check()` (a list of findings) has no ERROR, else pending. An exception in
    the body - a refusal, a crash, an injected failure - records `fail` and propagates."""
    begin(rd, unit, inst)
    clean_exit = None
    try:
        yield
    except SystemExit as e:
        if e.code not in (None, 0):
            fail(rd, unit, f"SystemExit {e.code}: {str(e)[:160]}", inst)
            raise
        clean_exit = e                           # a command that ends with exit 0 finished: judge it, then exit
    except BaseException as e:  # noqa: BLE001 - die(), a refusal, an injected failure
        fail(rd, unit, f"{type(e).__name__}: {str(e)[:160]}", inst)
        raise
    errs = [f for f in (check() if check else []) if f.get("level") == "ERROR"]
    if errs:
        pending(rd, unit, f"{errs[0]['code']}: {errs[0]['msg'][:160]}", inst)
    else:
        done(rd, unit, inst, degraded=(degraded() if callable(degraded) else degraded))
    if clean_exit is not None:
        raise clean_exit


# ========================================================================================================== state
def unit_state(rd: Path, unit: str, evs: list | None = None, _seen=None) -> dict:
    """{state, why, inst, event} - state: todo | running | waiting | failed | done | stale."""
    rd = Path(rd)
    evs = _events(rd) if evs is None else evs
    mine = [e for e in evs if e.get("unit") == unit and e.get("ev") in ("begin", "done", "pending", "fail")]
    if not mine:
        return {"state": "todo", "why": "", "event": None}
    last = mine[-1]
    lastdone = next((e for e in reversed(mine) if e["ev"] == "done"), None)
    if last["ev"] == "begin":
        return {"state": "running", "why": f"begun {last['at']}, no done: interrupted or still running", "event": last}
    if last["ev"] == "pending":
        return {"state": "waiting", "why": last.get("why", ""), "event": last}
    if last["ev"] == "fail":
        return {"state": "failed", "why": last.get("why", ""), "event": last}
    spec = io(unit)
    cur_out = hashes(rd, spec.get("owns") or [])
    changed_out = [k for k, v in (lastdone.get("outputs") or {}).items() if cur_out.get(k) != v]
    revisers = {r.get("by") for r in cards()[unit].get("revised_by") or []}
    after = evs[evs.index(lastdone) + 1:] if lastdone in evs else []
    if changed_out and any(e.get("unit") in revisers for e in after):
        changed_out = []                          # a declared reviser changed it: logged as a deviation, not stale
    if changed_out:
        return {"state": "stale", "why": "its output changed since done: " + ", ".join(changed_out[:3]), "event": lastdone,
                "changed": changed_out}
    cur_in = hashes(rd, spec.get("reads") or [])
    rec_in = lastdone.get("inputs") or {}
    changed_in = [k for k, v in rec_in.items() if k in cur_in and cur_in.get(k) != v]
    changed_in += [k for k, v in cur_in.items() if k not in rec_in and v is not None]   # read now, not recorded then
    if changed_in:
        return {"state": "stale", "why": "input changed: " + ", ".join(changed_in[:3]), "event": lastdone,
                "changed": changed_in}
    seen = set(_seen or ()) | {unit}
    own = {spec_id(s_) for s_ in spec.get("owns") or []}
    for up in requires(unit):
        if up in seen:
            continue
        if block_of(up) != block_of(unit) and not any(e.get("unit") in BLOCKS[block_of(up)] for e in evs):
            continue                             # that block ran before the ledger (a topic framed before protocols)
        st = unit_state(rd, up, evs, seen)
        if st["state"] == "stale" and st.get("changed") and set(st["changed"]) <= own:
            continue                             # stale only because of this Unit's own output: the loop A5 -> A3
        if st["state"] != "done":
            return {"state": "stale", "why": f"upstream {up} is {st['state']}", "event": lastdone,
                    "changed": st.get("changed") or []}
    return {"state": "done", "why": "", "event": lastdone}


def states(rd: Path, block: str = "search") -> dict:
    evs = _events(rd)
    return {u: unit_state(rd, u, evs) for u in BLOCKS[block]}


def next_unit(rd: Path, block: str = "search") -> tuple[str | None, dict]:
    st = states(rd, block)
    for u in BLOCKS[block]:
        if u == "A1.v" and st[u]["state"] == "todo" and st["A1.e"]["state"] != "done":
            continue                              # A1.v serves Stage B; it does not hold up the search
        if st[u]["state"] != "done":
            return u, st
    return None, st


def current_block(rd: Path) -> str:
    """The block a bare `status` / `next` speaks for: the fusion block once it has begun (a fusion event in the ledger, or
    knowledge/decon/), else the full-text block once it has begun (an A6 event, or a candidate list), else the search."""
    rd = Path(rd)
    evs = _events(rd)
    if (rd / "knowledge" / "decon").is_dir() or any(e.get("unit") in FUSION for e in evs):
        return "fusion"
    if (rd / "step3_tier1_candidates.json").exists() or any(e.get("unit") in FULLTEXT for e in evs):
        return "fulltext"
    return "search"


# ========================================================================================================= counts
def _j(rd, name):
    p = Path(rd) / name
    return read_json(p) if p.exists() else None


def counts(rd: Path, unit: str) -> dict:
    rd = Path(rd)
    cfg = _cfg(rd)
    p = cfg.get("protocol") or {}
    try:
        if unit == "A1.p":
            crit = p.get("criteria") or {}
            return {"framework": (p.get("framework") or {}).get("name"), "axes": len(p.get("axes") or []),
                    "criteria": len(crit.get("inclusion") or []) + len(crit.get("exclusion") or [])}
        if unit == "A1.q":
            sp = cfg.get("scope_probe") or {}
            return {"queries": sum(1 for q in cfg.get("queries") or [] if q.get("status", "active") == "active"),
                    "known_items": len(cfg.get("known_items") or []),
                    "probe": "skipped" if sp.get("skipped") else ("ok" if sp else "none")}
        if unit == "A1.e":
            ev = _j(rd, "step1_protocol_evaluation.json") or {}
            return {"status": (ev.get("final") or {}).get("status"), "rounds": len(ev.get("rounds") or [])}
        if unit == "A1.v":
            return {"venues": len(cfg.get("target_venues") or [])}
        if unit == "A2.s":
            files = list(rd.glob("step2_queries/*.json"))
            return {"instances": len(files)}
        if unit == "A2.m":
            sm = (_j(rd, "step2_raw_papers.json") or {}).get("search_summary") or {}
            return {"records": sm.get("total_raw_results"), "papers": sm.get("after_dedup"), "dense_only": sm.get("dense_only")}
        if unit == "A2.c":
            rel = _j(rd, "step2_relevance_check.json") or {}
            last = (rel.get("rounds") or [{}])[-1]
            c = Counter(v.get("verdict") for v in last.get("verdicts") or [])
            return {"rounds": len(rel.get("rounds") or []), **{k: c.get(k, 0) for k in ("ok", "replan", "accept-weak")}}
        if unit == "A3.b":
            b = (_j(rd, "step3_bibliometrics.json") or {}).get("papers") or {}
            return {"candidates": len(b), "openalex": sum(1 for r in b.values() if r.get("metadata") != "none"),
                    "with_snip": sum(1 for r in b.values() if (r.get("venue") or {}).get("snip") is not None)}
        if unit == "A3.g":
            return {"excluded": len((_j(rd, "step3_gate.json") or {}).get("excluded") or [])}
        if unit == "A3":
            sl = _j(rd, "step3_shortlist.json") or {}
            sm = sl.get("summary") or {}
            sc = _j(rd, "screening_scores.json") or {}
            return {"included": sm.get("included"), "excluded": sm.get("excluded"), "tiers": sm.get("tiers"),
                    "rescued": sum(1 for e in sc.get("scores") or [] if e.get("rescue")),
                    "human": sum(1 for q in sl.get("papers") or [] if (q.get("screening") or {}).get("decided_by") == "human")}
        if unit == "A5":
            sb = _j(rd, "step2b_snowball_papers.json") or {}
            r = (sb.get("rounds") or [{}])[-1]
            return {"rounds": len(sb.get("rounds") or []), "added": len(sb.get("papers") or []),
                    "by_direction": r.get("by_direction")}
        if unit == "A4.k":
            log = read_jsonl(rd / "step4_citation_keys.jsonl")
            sl = {q["id"] for q in (_j(rd, "step3_shortlist.json") or {}).get("papers") or []}
            return {"keys": len(log), "active": sum(1 for e in log if e["id"] in sl)}
        if unit == "A4.b":
            m = (_j(rd, "step4_bib_metadata.json") or {}).get("entries") or {}
            return {"entries": len(m), "crossref": sum(1 for v in m.values() if v.get("source") == "crossref")}
        if unit in FUSION:
            return fusion_counts(rd, unit)
        if unit in FULLTEXT:
            from it_fulltext import counts as fulltext_counts
            return fulltext_counts(rd, unit)
    except Exception as e:  # noqa: BLE001 - a count never blocks a done
        return {"error": f"{type(e).__name__}: {str(e)[:80]}"}
    return {}


def fusion_counts(rd: Path, unit: str) -> dict:
    kd = rd / "knowledge"
    if unit == "A7.D":
        recs = [read_json(f) for f in sorted((kd / "decon").glob("*.json"))]
        kinds = Counter(u.get("kind") for r in recs for u in r.get("units") or [])
        return {"records": len(recs), "full_text": sum(1 for r in recs if r.get("basis") == "full-text"),
                "ineligible": sum(1 for r in recs if (r.get("eligibility") or {}).get("verdict") == "ineligible"),
                "units": sum(kinds.values()), "claims": kinds.get("claim", 0),
                "rows": sum(len(r.get("experiments") or []) for r in recs)}
    al = _j(rd, "knowledge/alignment.json") or {}
    if unit == "A7.A1":
        cs = (al.get("vocab") or {}).get("concepts") or []
        return {"concepts": len(cs), "families": sum(1 for c in cs if c.get("kind") == "method-family"),
                "overrides": sum(len(v) for v in ((al.get("vocab") or {}).get("overrides") or {}).values()),
                "set_aside": len((al.get("vocab") or {}).get("unaligned") or [])}
    if unit == "A7.A2":
        co = al.get("coords") or {}
        return {"units": len(co), "model": sum(1 for c in co.values() if c.get("by") == "model")}
    cards_ = _j(rd, "knowledge_cards.json") or {}
    if unit == "A7.A3":
        return {"points": sum(1 for p in cards_.get("points") or [] if p.get("origin") == "align")}
    if unit == "B1":
        lens = _j(rd, "lens.json") or {}
        on = lens.get("on_coords") or {}
        return {"verdicts": len(on), "affordable": sum(1 for v in on.values() if v.get("affordable") == "yes"),
                "own_data": len(lens.get("own_data") or [])}
    if unit == "A7.X1":
        c = _j(rd, "knowledge/collision_candidates.json") or {}
        return {"candidates": len(c.get("candidates") or []), "cut": len(c.get("truncated") or [])}
    if unit in ("A7.X2", "B3.c"):
        from it_collide import LENS_TYPES, current, log
        cur = [r for r in current(log(rd)) if (r.get("type") in LENS_TYPES) == (unit == "B3.c")]
        res = Counter(r["result"] for r in cur)
        return {"relations": len(cur), "conflict": res.get("conflict", 0),
                "premises": sum(res.get(k, 0) for k in ("untested-shared", "assumption-challenged", "assumption-at-stake",
                                                         "criterion-unmet")),
                "independent": res.get("independent", 0)}
    if unit == "B3":
        g = _j(rd, "step7_gaps.json") or {}
        from it_collide import MOVES_CON
        return {"gaps": len(g.get("gaps") or []), "contradiction": sum(1 for x in g.get("gaps") or [] if x.get("move") in MOVES_CON),
                "set_aside": len(g.get("not_gaps") or [])}
    if unit == "A7.R1":
        lines = [f for f in (kd / "lines").glob("*.md") if not f.name.startswith("frontmatter")] if (kd / "lines").is_dir() else []
        return {"lines": len(lines), "findings_points": sum(1 for p in cards_.get("points") or [] if p.get("origin") == "collide")}
    if unit == "A7.R2":
        return {"planes": len(cards_.get("planes") or []),
                "papers": sum(len(p.get("member_papers") or []) for p in cards_.get("planes") or [])}
    if unit == "A7.R3":
        return {"bodies": len(list((kd / "body").glob("*_descriptive.md"))) if (kd / "body").is_dir() else 0}
    if unit == "B2":
        p = rd / "step6_sota_review.md"
        return {"themes": p.read_text(encoding="utf-8").count("\n## Theme ") if p.exists() else 0}
    if unit == "B3.5":                           # the index is F.9's, written after: count the question files
        import re
        st = [m.group(1) for f in sorted((rd / "questions").glob("Q_*.md"))
              for m in [re.search(r"^status:\s*(\S+)", f.read_text(encoding="utf-8"), re.M)] if m]
        return {"questions": len(st), "ready": st.count("ready"), "abandoned": st.count("abandoned"),
                "target": (_j(rd, "questions/index.json") or {}).get("target_ready")}
    if unit == "F.9":
        idx = _j(rd, "questions/index.json") or {}
        qs = idx.get("questions") or []
        return {"questions": len(qs), "ready": idx.get("ready"), "target": idx.get("target_ready"),
                "abandoned": sum(1 for q in qs if q.get("status") == "abandoned")}
    return {}


def status_line(unit: str, c: dict) -> str:
    if not c:
        return ""
    f = {
        "A1.p": lambda: f"{c.get('framework')} · {c.get('axes')} axes · {c.get('criteria')} criteria",
        "A1.q": lambda: f"{c.get('queries')} queries · {c.get('known_items')} known items · probe {c.get('probe')}",
        "A1.e": lambda: f"{c.get('status')} after {c.get('rounds')} round(s)",
        "A1.v": lambda: f"{c.get('venues')} venues",
        "A2.s": lambda: f"{c.get('instances')} instances",
        "A2.m": lambda: f"{c.get('records')} records → {c.get('papers')} papers · dense-only {c.get('dense_only')}",
        "A2.c": lambda: f"{c.get('rounds')} round(s), the last: ok {c.get('ok')} · replan {c.get('replan')} · accept-weak {c.get('accept-weak')}",
        "A3.b": lambda: f"{c.get('candidates')} candidates · OpenAlex {c.get('openalex')} · SNIP {c.get('with_snip')}",
        "A3.g": lambda: f"{c.get('excluded')} excluded mechanically",
        "A3": lambda: (f"{c.get('included')} included (" + " · ".join(f"T{k} {v}" for k, v in (c.get("tiers") or {}).items())
                       + f") · {c.get('excluded')} excluded"
                       + (f" · {c['rescued']} read again" if c.get("rescued") else "")
                       + (f" · {c['human']} by a person" if c.get("human") else "")),
        "A5": lambda: f"{c.get('rounds')} round(s), {c.get('added')} additions {c.get('by_direction') or ''}",
        "A4.k": lambda: f"{c.get('active')} active keys of {c.get('keys')}",
        "A4.b": lambda: f"{c.get('entries')} entries · {c.get('crossref')} from Crossref",
        "A6.d": lambda: f"{c.get('in_hand')} of {c.get('candidates')} PDFs in hand (budget {c.get('budget')}) · "
                        f"{c.get('no_doi')} without DOI · {c.get('top_ups')} top-up",
        "A6.c": lambda: f"{c.get('full-text')} full text · {c.get('full-text-plain')} plain · {c.get('pdf-only')} pdf-only · "
                        f"{c.get('abstract-only')} abstract-only · {c.get('figure_pages')} figure pages",
        "A7.D": lambda: f"{c.get('records')} records ({c.get('full_text')} full text, {c.get('ineligible')} ineligible) · "
                        f"{c.get('units')} units · {c.get('rows')} rows",
        "A7.A1": lambda: f"{c.get('concepts')} concepts ({c.get('families')} method families) · {c.get('overrides')} overrides · "
                         f"{c.get('set_aside')} set aside",
        "A7.A2": lambda: f"{c.get('units')} units placed ({c.get('model')} by judgement)",
        "A7.A3": lambda: f"{c.get('points')} concept Points",
        "B1": lambda: f"{c.get('verdicts')} verdicts ({c.get('affordable')} affordable) · own data {c.get('own_data')}",
        "A7.X1": lambda: f"{c.get('candidates')} candidates · {c.get('cut')} cut",
        "A7.X2": lambda: f"{c.get('relations')} relations · {c.get('conflict')} conflict · {c.get('premises')} on premises · "
                         f"{c.get('independent')} independent",
        "B3.c": lambda: f"{c.get('relations')} lens relations",
        "B3": lambda: f"{c.get('gaps')} gaps ({c.get('contradiction')} contradiction moves) · {c.get('set_aside')} set aside",
        "A7.R1": lambda: f"{c.get('lines')} Lines · {c.get('findings_points')} findings Points",
        "A7.R2": lambda: f"{c.get('planes')} Planes · {c.get('papers')} papers placed",
        "A7.R3": lambda: f"{c.get('bodies')} descriptive Body",
        "B2": lambda: f"synthesis over {c.get('themes')} themes",
        "B3.5": lambda: f"{c.get('ready')} ready of {c.get('questions')} (target {c.get('target')}) · {c.get('abandoned')} abandoned",
        "F.9": lambda: f"index: {c.get('ready')} ready / target {c.get('target')}",
    }.get(unit)
    try:
        return f() if f else json.dumps(c)
    except Exception:  # noqa: BLE001
        return json.dumps(c)


# ========================================================================================================= caveats
# caveat code -> the Unit that raises it (cards name these codes in `degraded`; `units check` verifies the names)
CAVEAT_UNITS = {"probe-skipped": "A1.q", "protocol-doubts": "A1.e", "source-failed": "A2.s", "source-dead": "A2.s",
                "dense-skipped": "A2.s", "doi-recovery-skipped": "A2.m", "accept-weak": "A2.c",
                "known-item-missing": "A2.c", "no-metadata": "A3.b", "snip-unavailable": "A3.b", "abstract-fill": "A3.b",
                "abstract-fill-partial": "A3.b", "few-included": "A3", "refs-sparse": "A5", "backward-fallback": "A5",
                "similar-skipped": "A5", "snowball-failed": "A5", "snowball-no-metadata": "A5", "bib-offline": "A4.b",
                "exported-before-snowball": "A4.k"}


def caveats(rd: Path) -> list[dict]:
    rd = Path(rd)
    cfg = _cfg(rd)
    out = []

    def add(code, text, must, unit=None):
        out.append({"code": code, "unit": unit or CAVEAT_UNITS.get(code, "?"), "text": text, "must_disclose": bool(must)})
    sp = cfg.get("scope_probe") or {}
    if sp.get("skipped"):
        add("probe-skipped", f"the scope probe did not run: {sp['skipped']}", False)
    ev = (_j(rd, "step1_protocol_evaluation.json") or {}).get("final") or {}
    if ev.get("status") == "accepted-with-doubts":
        add("protocol-doubts", "the protocol was accepted with unresolved findings: "
            + "; ".join(str(x.get("check", x)) if isinstance(x, dict) else str(x) for x in ev.get("unresolved") or []), True)
    for c in ((_j(rd, "step2_raw_papers.json") or {}).get("search_summary") or {}).get("caveats") or []:
        add(c["code"], c["text"], c.get("must_disclose"), "A2.s")
    for c in (_j(rd, "step2_relevance_check.json") or {}).get("caveats") or []:
        add(c["code"], c["text"], c.get("must_disclose"), "A2.c")
    for c in (_j(rd, "step3_bibliometrics.json") or {}).get("caveats") or []:
        add(c["code"], c["text"], c.get("must_disclose"), "A3.b")
    sm = (_j(rd, "step3_shortlist.json") or {}).get("summary") or {}
    if sm and (sm.get("included") or 0) < 10:
        add("few-included", f"only {sm.get('included')} papers were included: every gap and idea is preliminary", True)
    for c in (_j(rd, "step2b_snowball_papers.json") or {}).get("caveats") or []:
        add(c["code"], c["text"], c.get("must_disclose"), "A5")
    if (_j(rd, "step4_bib_metadata.json") or {}).get("offline"):
        add("bib-offline", "the bibliography was built without Crossref (entries from the search records)", False)
    md = rd / "step4_citation_keys.md"
    if md.exists() and "Exported before the snowball" in md.read_text(encoding="utf-8"):
        add("exported-before-snowball", "citation keys were minted before the snowball (see step4_citation_keys.md)", True)
    return out


FULLTEXT_CAVEAT_UNITS = {"fulltext-short": "A6.d", "fulltext-plain": "A6.c", "pdf-unconverted": "A6.c"}


def fulltext_caveats(rd: Path) -> list[dict]:
    """The full-text Units' caveats: what the fusion block reads from fewer or poorer full texts than the depth asked."""
    from it_fulltext import caveats as raw
    return [{"code": code, "unit": FULLTEXT_CAVEAT_UNITS[code], "text": text, "must_disclose": bool(must)}
            for code, text, must in raw(Path(rd))]


FUSION_CAVEAT_UNITS = {"abstract-heavy": "A7.D", "lens-stale": "B1", "candidates-cut": "A7.X1",
                       "incommensurable-open": "A7.X2", "record-revisions-queued": "B3", "questions-short": "B3.5"}


def fusion_caveats(rd: Path) -> list[dict]:
    """The fusion block's caveats (its exit contract beside questions/index.json): what the planning block must know -
    the full-text Units' first, since deconstruct reads what they fetched."""
    rd = Path(rd)
    out = fulltext_caveats(rd)

    def add(code, text, must):
        out.append({"code": code, "unit": FUSION_CAVEAT_UNITS[code], "text": text, "must_disclose": bool(must)})
    recs = [read_json(f) for f in sorted((rd / "knowledge" / "decon").glob("*.json"))] if (rd / "knowledge" / "decon").is_dir() else []
    if recs:
        ab = sum(1 for r in recs if r.get("basis") == "abstract")
        if ab / len(recs) > 0.5:
            add("abstract-heavy", f"{ab} of {len(recs)} papers were read from the abstract only", True)
    lens, cfg = _j(rd, "lens.json"), _cfg(rd)
    if lens and (lens.get("local") or {}).get("date") != ((cfg.get("local_environment") or {}).get("probe") or {}).get("date"):
        add("lens-stale", "the machine was probed again after the lens was set (lens-set)", False)
    cands = _j(rd, "knowledge/collision_candidates.json") or {}
    if cands.get("truncated"):
        add("candidates-cut", f"{len(cands['truncated'])} collision candidates were cut at the depth cap", True)
    try:
        from it_collide import current, log
        inc = [r["collision_id"] for r in current(log(rd)) if r["result"] == "incommensurable"]
        if inc:
            add("incommensurable-open", f"incommensurable collisions not yet resolved by a vocabulary revision: {inc[:6]}", True)
    except Exception:  # noqa: BLE001
        pass
    if (_j(rd, "step7_gaps.json") or {}).get("revisions_needed"):
        add("record-revisions-queued", "source checks found text the records do not hold (step7_gaps.json "
                                       "revisions_needed) - decon-merge --revise", False)
    idx = _j(rd, "questions/index.json") or {}
    if idx and (idx.get("ready") or 0) < (idx.get("target_ready") or 0):
        add("questions-short", f"{idx.get('ready')} ready questions of the {idx.get('target_ready')} wanted", True)
    return out


def degraded_codes(rd: Path, unit: str) -> list[str]:
    """The caveat codes this Unit's outputs carry now - recorded in its `done` as the degradation string."""
    if unit in FUSION:
        return sorted({c["code"] for c in fusion_caveats(rd) if c["unit"] == unit})
    if unit in FULLTEXT:
        return sorted({c["code"] for c in fulltext_caveats(rd) if c["unit"] == unit})
    return sorted({c["code"] for c in caveats(rd) if c["unit"] == unit})


# ========================================================================================================== views
def _funnel(rd: Path) -> list[str]:
    raw = _j(rd, "step2_raw_papers.json") or {}
    sm = raw.get("search_summary") or {}
    gate = (_j(rd, "step3_gate.json") or {}).get("excluded") or []
    sl = _j(rd, "step3_shortlist.json") or {}
    ssum = sl.get("summary") or {}
    sb = _j(rd, "step2b_snowball_papers.json") or {}
    L = ["| Stage | Records |", "|---|---|"]
    for db, d in sorted((sm.get("identification") or {}).items()):
        L.append(f"| identified · {db} | {d.get('retrieved')} (of {d.get('reported_total_sum')} reported) |")
    if sm:
        L.append(f"| after deduplication | {sm.get('after_dedup')} |")
    if sb.get("papers"):
        L.append(f"| added by the snowball | {len(sb['papers'])} |")
    if gate:
        L.append(f"| excluded mechanically | {len(gate)} |")
    for code, n in sorted((ssum.get("excluded_by_reason") or {}).items()):
        if code not in ("X-RET", "X-TYPE", "X-LANG"):     # the gate's codes are the line above; X-REC is screening
            L.append(f"| excluded · {code} | {n} |")
    if ssum:
        L.append(f"| **included** | **{ssum.get('included')}** |")
    return L


def render(rd: Path) -> None:
    """STATUS.md and search_caveats.json, from the ledger and the Units' files. Owned by no Unit; never edited."""
    rd = Path(rd)
    if "protocol" not in _cfg(rd):
        return
    st = states(rd)
    nxt, _ = next_unit(rd)
    cav = caveats(rd)
    tmp = rd / "search_caveats.json.tmp"
    tmp.write_text(json.dumps({"schema": "ideate-search-caveats/1", "at": now_iso(), "caveats": cav,
                               "must_disclose": [c for c in cav if c["must_disclose"]]}, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    os.replace(tmp, rd / "search_caveats.json")
    L = ["<!-- generated from _state/ledger.jsonl (`ideate_tools.py status`) - do not edit -->",
         f"# STATUS — {_cfg(rd).get('topic') or rd.name}", "",
         "## Literature search (A1–A5)", "",
         ("**Next:** " + nxt + " — " + " · ".join(f"`{c}`" for c in COMMANDS.get(nxt, []))) if nxt else
         "**Next:** the search block is complete — A6 full text (`next $RD --block fulltext`).", "",
         "| Unit | State | Counts | Audit |", "|---|---|---|---|"]
    for u in ORDER:
        s = st[u]
        ev = s.get("event") or {}
        line = status_line(u, ev.get("counts") or {}) if ev.get("ev") == "done" else ""
        why = f" — {s['why']}" if s["why"] else ""
        L.append(f"| {u} | {ICON[s['state']]} {s['state']}{why} | {line} | {cards()[u].get('audit', '')[:80]} |")
    L += ["", "## Funnel", ""] + _funnel(rd)
    L += ["", f"## Caveats ({len(cav)}; must disclose {sum(1 for c in cav if c['must_disclose'])})", ""]
    L += [f"- **{c['code']}** [{c['unit']}]{' (must disclose)' if c['must_disclose'] else ''}: {c['text'][:200]}" for c in cav] \
        or ["- none"]
    ov = _j(rd, "_human/search_overrides.json")
    if ov and ov.get("entries"):
        L += ["", f"## A person's overrides ({len(ov['entries'])})", ""]
        L += [f"- {e.get('kind')} {e.get('id') or e.get('title') or ''} — {e.get('reason', '')[:120]}" for e in ov["entries"]]
    if _fulltext_began(rd):
        L += _render_fulltext(rd)
    if (rd / "knowledge" / "decon").is_dir():
        L += _render_fusion(rd)
    tmp = rd / "STATUS.md.tmp"
    tmp.write_text("\n".join(L) + "\n", encoding="utf-8")
    os.replace(tmp, rd / "STATUS.md")


def _fulltext_began(rd: Path) -> bool:
    return (Path(rd) / "step3_tier1_candidates.json").exists() or any(e.get("unit") in FULLTEXT for e in _events(rd))


def _render_fulltext(rd: Path) -> list[str]:
    st = states(rd, "fulltext")
    nxt, _ = next_unit(rd, "fulltext")
    cav = fulltext_caveats(rd)
    tmp = rd / "fulltext_caveats.json.tmp"
    tmp.write_text(json.dumps({"schema": "ideate-fulltext-caveats/1", "at": now_iso(), "caveats": cav,
                               "must_disclose": [c for c in cav if c["must_disclose"]]}, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    os.replace(tmp, rd / "fulltext_caveats.json")
    L = ["", "## Full text (A6)", "",
         ("**Next:** " + nxt + " — " + " · ".join(f"`{c}`" for c in COMMANDS.get(nxt, []))) if nxt else
         "**Next:** the full texts are in — the fusion block (`next $RD --block fusion`).", "",
         "| Unit | State | Counts | Audit |", "|---|---|---|---|"]
    for u in FULLTEXT:
        s = st[u]
        ev = s.get("event") or {}
        line = status_line(u, ev.get("counts") or {}) if ev.get("ev") == "done" else ""
        why = f" — {s['why']}" if s["why"] else ""
        L.append(f"| {u} | {ICON[s['state']]} {s['state']}{why} | {line} | {cards()[u].get('audit', '')[:80]} |")
    L += ["", f"### Full-text caveats ({len(cav)})", ""] + ([f"- **{c['code']}** [{c['unit']}]: {c['text'][:200]}" for c in cav]
                                                          or ["- none"])
    return L


def _render_fusion(rd: Path) -> list[str]:
    st = states(rd, "fusion")
    nxt, _ = next_unit(rd, "fusion")
    cav = fusion_caveats(rd)
    tmp = rd / "fusion_caveats.json.tmp"
    tmp.write_text(json.dumps({"schema": "ideate-fusion-caveats/1", "at": now_iso(), "caveats": cav,
                               "must_disclose": [c for c in cav if c["must_disclose"]]}, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    os.replace(tmp, rd / "fusion_caveats.json")
    L = ["", "## Literature fusion (A6–B3.5)", "",
         ("**Next:** " + nxt + " — " + " · ".join(f"`{c}`" for c in COMMANDS.get(nxt, []))) if nxt else
         "**Next:** the fusion block is complete — the planning block takes a question (`question-next`).", "",
         "| Unit | State | Counts | Audit |", "|---|---|---|---|"]
    for u in FUSION:
        s = st[u]
        ev = s.get("event") or {}
        line = status_line(u, ev.get("counts") or {}) if ev.get("ev") == "done" else ""
        why = f" — {s['why']}" if s["why"] else ""
        L.append(f"| {u} | {ICON[s['state']]} {s['state']}{why} | {line} | {cards()[u].get('audit', '')[:80]} |")
    L += ["", f"### Fusion caveats ({len(cav)})", ""] + ([f"- **{c['code']}** [{c['unit']}]: {c['text'][:200]}" for c in cav]
                                                       or ["- none"])
    return L


def render_fusion_only(rd: Path) -> None:
    """A topic whose search ran before the ledger (or before protocols) gets no search section: the fusion block still
    writes its own."""
    rd = Path(rd)
    if any(e.get("unit") in ORDER for e in _events(rd)):
        return render(rd)
    L = ["<!-- generated from _state/ledger.jsonl (`ideate_tools.py status`) - do not edit -->",
         f"# STATUS — {_cfg(rd).get('topic') or rd.name}", ""]
    if _fulltext_began(rd):
        L += _render_fulltext(rd)
    if (rd / "knowledge" / "decon").is_dir() or any(e.get("unit") in FUSION for e in _events(rd)):
        L += _render_fusion(rd)
    tmp = rd / "STATUS.md.tmp"
    tmp.write_text("\n".join(L) + "\n", encoding="utf-8")
    os.replace(tmp, rd / "STATUS.md")


# ======================================================================================================= commands
def cmd_status(a):
    rd = Path(a.research_dir)
    block = a.block or current_block(rd)
    st = states(rd, block)
    render_fusion_only(rd) if block in ("fusion", "fulltext") else render(rd)
    if a.json:
        print(json.dumps({u: {"state": s["state"], "why": s["why"], "changed": s.get("changed") or []}
                          for u, s in st.items()}, indent=2))
        return
    print(f"{block} block:")
    for u in BLOCKS[block]:
        s = st[u]
        ev = s.get("event") or {}
        line = status_line(u, ev.get("counts") or {}) if ev.get("ev") == "done" else ""
        print(f"  {ICON[s['state']]} {u:<5} {s['state']:<8} {line}{('  — ' + s['why']) if s['why'] else ''}")
    print(f"-> {rd / 'STATUS.md'}")


def cmd_next(a):
    rd = Path(a.research_dir)
    block = a.block or current_block(rd)
    u, st = next_unit(rd, block)
    if u is None and block == "fulltext":
        print("the full texts are in: A6.d and A6.c are current. Next: the fusion block "
              "(`ideate_tools.py next $RD --block fusion`).")
        return
    if u is None and block == "fusion":
        print("the fusion block is complete: every Unit is current. The planning block takes a question: "
              "ideate_tools.py question-next $RD")
        return
    if u is None:
        print("the literature search is complete: every Unit is current. Next: A6 full text "
              "(`ideate_tools.py next $RD --block fulltext`; scholar-pipeline.md §2), then the fusion block.")
        sb = _j(rd, "step2b_snowball_papers.json") or {}
        try:
            from it_snowball import ROUND2_GROWTH, growth
            g = growth(rd)
            if g is not None and g >= ROUND2_GROWTH and len(sb.get("rounds") or []) == 1:
                print(f"  optional: A5 round 2 (round 1 grew the included set by {g:.0%}): mcp_bridge.py snowball $RD --round 2")
        except Exception:  # noqa: BLE001
            pass
        return
    c = cards()[u]
    s = st[u]
    print(f"next: {u} — {c['purpose']}")
    print(f"  state: {s['state']}{(' — ' + s['why']) if s['why'] else ''}")
    print(f"  rules: {c['rules']}")
    for cmd in COMMANDS.get(u, []):
        print(f"  $ {cmd}" if not cmd.startswith("(") else f"    {cmd}")


# fusion Units the model writes by hand, closed by their checks (the others are closed by their own tools)
MODEL_UNITS = ["A7.A3", "A7.R1", "A7.R2", "A7.R3", "B2", "B3.5"]


def fusion_check(rd: Path, unit: str) -> list:
    """A fusion Unit's own checks (the same ones its command or unit-done runs)."""
    if unit == "A7.D":
        from it_decon import run_checks as decon
        return decon(rd)
    if unit in ("A7.A1", "A7.A2", "A7.A3", "B1"):
        from it_align import run_checks as align
        return align(rd, unit)
    if unit in ("A7.X1", "A7.X2", "B3.c", "B3"):
        from it_collide import run_checks as collide
        return collide(rd, unit)
    from it_recon import run_checks as recon
    return recon(rd, unit)


def cmd_adopt(a):
    """A topic fused before the ledger: every fusion Unit whose files pass its checks is recorded done (an `adopt`
    note says so), in run order, up to the first that does not - that one is recorded pending."""
    rd = Path(a.research_dir)
    st = states(rd, "fusion")
    for u in FUSION:
        if st[u]["state"] != "todo":
            print(f"  {u}: {st[u]['state']} - already on the ledger, left alone")
            continue
        errs = [f for f in fusion_check(rd, u) if f.get("level") == "ERROR"]
        if errs:
            pending(rd, u, f"adopt: {errs[0]['code']}: {errs[0]['msg'][:160]}")
            print(f"  {u}: its checks do not pass ({errs[0]['code']}) - recorded pending; the Units after it stay todo")
            raise SystemExit(1)
        note(rd, u, "adopt", why="files written before the fusion block was on the ledger; its checks pass")
        done(rd, u, degraded=degraded_codes(rd, u), render_views=False)
        print(f"  {u}: adopted (checks pass)")
    render_fusion_only(rd)


def cmd_unit_begin(a):
    rd = Path(a.research_dir)
    begin(rd, a.unit)
    print(f"{a.unit} begun: write its files, then `ideate_tools.py unit-done {rd} {a.unit}`")


def cmd_unit_done(a):
    rd = Path(a.research_dir)
    errs = [f for f in fusion_check(rd, a.unit) if f.get("level") == "ERROR"]
    if errs:
        pending(rd, a.unit, f"{errs[0]['code']}: {errs[0]['msg'][:160]}")
        for f in errs[:8]:
            print(f"  ERROR {f['code']} {f['msg']}")
        print(f"{a.unit}: pending - its checks do not pass yet")
        raise SystemExit(1)
    done(rd, a.unit, degraded=degraded_codes(rd, a.unit))
    print(f"{a.unit}: done")


def add_parsers(sub) -> None:
    sp = sub.add_parser("status", help="every Unit's state in a block (default: the first one not complete); rebuilds "
                                       "STATUS.md and the block's caveats")
    sp.add_argument("research_dir")
    sp.add_argument("--block", choices=list(BLOCKS))
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_status)
    sp = sub.add_parser("next", help="the next Unit to run (search first, then fusion), with its rules and commands")
    sp.add_argument("research_dir")
    sp.add_argument("--block", choices=list(BLOCKS))
    sp.set_defaults(fn=cmd_next)
    sp = sub.add_parser("adopt", help="fusion: put a topic fused before the ledger on it - each Unit whose checks pass is "
                                      "recorded done, in order, up to the first that does not")
    sp.add_argument("research_dir")
    sp.set_defaults(fn=cmd_adopt)
    sp = sub.add_parser("unit-begin", help="fusion: open a Unit the model writes (A7.A3, A7.R1-R3, B2, B3.5)")
    sp.add_argument("research_dir")
    sp.add_argument("unit", choices=MODEL_UNITS)
    sp.set_defaults(fn=cmd_unit_begin)
    sp = sub.add_parser("unit-done", help="fusion: close such a Unit - done when its checks pass, else pending")
    sp.add_argument("research_dir")
    sp.add_argument("unit", choices=MODEL_UNITS)
    sp.set_defaults(fn=cmd_unit_done)
