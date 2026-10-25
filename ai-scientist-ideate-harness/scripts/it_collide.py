"""Collide - put aligned units against each other, and the field against our conditions; every comparison is recorded
(rules: references/fusion/F3-collide.md; decision record docs/decisions/PLAN_ideate_fusion.md).

  A7.X1  candidates   which units are compared, by rule: claims sharing a construct (else a measure), assumptions
                      shared by several papers, an assumption against other papers' claims on its coordinates, matrix
                      rows on the same dataset x metric x split, a method family's lineage over the years; capped by
                      depth, the cut recorded                               -> knowledge/collision_candidates.json
  A7.X2  judgements   one judgement per candidate, one or more relations each (agree, conflict, boundary, extends,
                      untested-shared, assumption-challenged, analogy, incommensurable, independent) with the sides and
                      the axes on which they differ; fanned out in batches  -> knowledge/collisions.jsonl (append-only)
  B3.c   lens         the field against this topic's lens: a convention the machine cannot follow, a cell nobody filled
                      (convention-vs-lens, empty-cell, independent)          -> the same two files
  B3     gaps         the gap list, once per topic: every gap points at collisions; move, scores and ranking checked
                      and computed                                          -> step7_gaps.json, step7_gap_analysis.md (view)

  ideate_tools.py collide-candidates <RD>
  ideate_tools.py collide-plan  <RD> [--size 10] [--lens]   batches of unjudged candidates (paper x paper, or the lens's)
  ideate_tools.py collide-merge <RD> [--revise REASON]      answers -> collisions.jsonl; notes re-rendered
  ideate_tools.py gaps-set      <RD> gaps.json              B3: validate, rank, write + render
  ideate_tools.py collide-check <RD> [--unit A7.X1|A7.X2|B3.c|B3|all] [--json]
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from it_common import (append_jsonl, die, now_iso, read_json, read_jsonl, sha256_json, write_json, write_json_stable,
                       write_text)

TBD = "(TBD)"
CANDS = "knowledge/collision_candidates.json"
LOG = "knowledge/collisions.jsonl"
WORK = "knowledge/_work/A7X"
GAPS = "step7_gaps.json"
GAPS_MD = "step7_gap_analysis.md"
RULES = "references/fusion/F3-collide.md"

PAPER_TYPES = ("numbers", "assumption-vs-claim", "same-coords", "shared-assumption", "lineage")   # truncation order
LENS_TYPES = ("convention-vs-lens", "empty-cell")
RESULTS_PAPER = ("agree", "conflict", "boundary", "extends", "untested-shared", "assumption-challenged", "assumption-at-stake",
                 "criterion-unmet", "analogy", "incommensurable", "independent")
RESULTS_LENS = ("convention-vs-lens", "empty-cell", "independent")
AXES_DIFFER = ("data", "population", "contrast", "measure-definition", "time-anchor", "baseline", "split-unit", "analysis",
               "method-config", "power", "claim-strength", "none")
RELATIONAL = {"agree", "conflict", "boundary", "extends", "untested-shared", "assumption-challenged", "assumption-at-stake",
              "criterion-unmet", "analogy"}
FINDINGS_ONLY = {"agree", "conflict", "boundary", "extends", "analogy"}     # between results: claims or matrix rows
ARGUED = {"causes", "shows", "suggests"}       # strong enough for a straight conflict (axes_differ none)
GROUP_MAX = 8
CAPS = {"quick": 0, "standard": 150, "deep": 400}
EMPTY_CELL_CAP = 30
MOVES_EXT = ("add-evidence", "confirm-assumed", "apply-wider")
MOVES_CON = ("kind", "part-whole", "development", "cause", "perspective")
GAP_TYPES = ("methodological", "population", "measurement", "temporal", "integration")
# a collision result -> the moves it suggests by default (question-craft.md section 3); a different move needs a reason
DEFAULT_MOVES = {"agree": {"add-evidence"}, "boundary": {"part-whole", "apply-wider"}, "extends": {"development"},
                 "untested-shared": {"confirm-assumed"}, "assumption-challenged": {"cause", "confirm-assumed"},
                 "criterion-unmet": {"add-evidence", "apply-wider"}, "assumption-at-stake": {"confirm-assumed"},
                 "analogy": {"apply-wider", "perspective"}, "convention-vs-lens": {"confirm-assumed", "apply-wider"},
                 "empty-cell": set(MOVES_EXT)}
# judgement checks, shared by collide-merge (refusals) and collide-check (findings): the code leads each message
JUDGEMENT_CODES = ("H02", "H03", "H04", "H05", "H06", "H08")
SOURCE_ORDER = ("conflict-none", "untested-shared", "assumption-challenged / assumption-at-stake", "criterion-unmet",
                "boundary", "conflict-axis", "extends", "convention-vs-lens", "not-done-recurring", "empty-cell")
CONSEQUENCE = ("conflict", "untested-shared", "assumption-challenged", "assumption-at-stake", "criterion-unmet")
MUST_ACCOUNT = ("untested-shared", "assumption-challenged", "assumption-at-stake", "criterion-unmet")
FEAS_CAP = {"yes": 5, "partial": 4, "obtainable": 4, "no": 2}    # the highest feasibility a cited lens verdict allows
GAP_AXES = ("construct", "measure", "population", "data", "split", "method_family") + tuple(a for a in AXES_DIFFER if a != "none")


def F(level, code, unit, msg):
    return {"level": level, "code": code, "unit": unit, "msg": msg}


def errors(fs):
    return [f for f in fs if f["level"] == "ERROR"]


def _cfg(rd) -> dict:
    p = Path(rd) / "step0_session_config.json"
    return read_json(p) if p.exists() else {}


def _first(v):
    return v if isinstance(v, str) else (v[0] if v else "unstated")


def _vals(v) -> list:
    return [x for x in (v if isinstance(v, list) else [v]) if x not in (None, "", "unstated", "n/a")]


# ================================================================================================ inputs
def inputs(rd) -> dict:
    """Everything the step reads: evidence records, alignment, the matrix, the lens."""
    import it_align
    rd = Path(rd)
    recs = it_align.evidence_records(rd)
    al = it_align.load_alignment(rd)
    mm_p = rd / "knowledge" / "methods_matrix.json"
    mm = read_json(mm_p) if mm_p.exists() else {}
    lens = read_json(it_align.lens_path(rd)) if it_align.lens_path(rd).exists() else {}
    units = {u["id"]: {**u, "paper": k, "basis": r.get("basis"), "year": None}
             for k, r in recs.items() for u in r.get("units") or []}
    pp = {}
    sl = rd / "step3_shortlist.json"
    if sl.exists():
        d = read_json(sl)
        pp = {p["citation_key"]: p for p in (d.get("papers") if isinstance(d, dict) else d) or [] if p.get("citation_key")}
    for u in units.values():
        u["year"] = (pp.get(u["paper"]) or {}).get("year")
    rows = {r["exp_id"]: r for r in mm.get("experiments") or [] if r.get("citation_key") in recs}
    return {"recs": recs, "al": al, "mm": mm, "lens": lens, "units": units, "rows": rows, "papers": pp,
            "depth": _cfg(rd).get("depth", "standard")}


def _key(prefix: str, members: list) -> str:
    return "K" + hashlib.sha1((prefix + "|" + "|".join(sorted(members))).encode()).hexdigest()[:10]


# ================================================================================================ A7.X1 candidates
def _chunks(units: list, coords: dict, axis_order=("measure", "data", "method_family"), mq=lambda m: m) -> list[list]:
    """A group larger than GROUP_MAX is split by the next coordinate (a measure by its quantity), then in year order -
    never silently cut. A split is taken when at least one part still holds two papers; a split in which every part
    holds one paper only is not (it would drop every comparison the group exists for)."""
    if len(units) <= GROUP_MAX:
        return [units]
    for axis in axis_order:
        by = defaultdict(list)
        for u in units:
            v = _first(coords[u["id"]]["axes"].get(axis))
            by[mq(v) if axis == "measure" else v].append(u)
        if len(by) > 1 and any(len({u["paper"] for u in g}) >= 2 for g in by.values()):
            # parts with one paper are dropped by the caller: their units meet the others in their own groups
            return [c for g in by.values() for c in _chunks(g, coords, axis_order[axis_order.index(axis) + 1:], mq)]
    units = sorted(units, key=lambda u: (u.get("year") or 0, u["id"]))
    return [units[i:i + GROUP_MAX] for i in range(0, len(units), GROUP_MAX)]


def paper_candidates(I: dict) -> list[dict]:
    coords = I["al"].get("coords") or {}
    units = {uid: u for uid, u in I["units"].items() if uid in coords}
    out = []
    # a measure meets the others on its quantity: normalisation variants of one quantity (dB vs change from baseline)
    # are separate concepts, and a conflict between them is exactly what must not be split apart
    qty = {c["id"]: "q:" + c["quantity"] for c in ((I["al"].get("vocab") or {}).get("concepts") or []) if c.get("quantity")}
    mq = lambda m: qty.get(m, m)

    def group_key(u):
        """A unit meets the others on its construct AND on its measure: two papers may read one measure as different
        constructs (high-alpha power as preparation vs as efficiency), which is exactly a collision to judge."""
        ax = coords[u["id"]]["axes"]
        return [("construct", x) for x in _vals(ax.get("construct"))] + \
            [("measure", x) for x in dict.fromkeys(mq(m) for m in _vals(ax.get("measure")))]

    groups = {"claim": defaultdict(list), "assumption": defaultdict(list)}
    for u in units.values():
        if u["kind"] in groups:
            for k in group_key(u):
                groups[u["kind"]][k].append(u)

    def add(ctype, members, key, extra=None):
        ids = [m["id"] for m in members]
        out.append({"id": _key(ctype, ids), "type": ctype, "key": f"{key[0]}={key[1]}", "members": sorted(ids),
                    "papers": sorted({m["paper"] for m in members}), **(extra or {})})

    for kind, ctype in (("claim", "same-coords"), ("assumption", "shared-assumption")):
        for key, us in sorted(groups[kind].items()):
            if len({u["paper"] for u in us}) < 2:
                continue
            order = ("construct", "data", "method_family") if key[0] == "measure" else ("measure", "data", "method_family")
            for chunk in _chunks(us, coords, order, mq=mq):
                if len({u["paper"] for u in chunk}) >= 2:
                    add(ctype, chunk, key)
    for key, assumptions in sorted(groups["assumption"].items()):
        claims = groups["claim"].get(key) or []
        by_paper = defaultdict(list)
        for a in assumptions:
            by_paper[a["paper"]].append(a)
        for paper, own in sorted(by_paper.items()):          # one candidate per paper's premises on this coordinate
            own = sorted(own, key=lambda a: a["id"])[:3]
            others = sorted((c for c in claims if c["paper"] != paper), key=lambda c: (c.get("year") or 0, c["id"]))
            if others:
                add("assumption-vs-claim", [*own, *others[:GROUP_MAX - len(own)]], key)
    # matrix rows: the same dataset x primary metric x split, from >= 2 papers, with a reported headline
    by = defaultdict(list)
    import it_align                                    # a not-shared dataset (own recordings, a placeholder, an
    _V = it_align.Vocab(I["al"].get("vocab") or {})    # unidentified one) is no benchmark: papers on it are not
    not_shared = {it_align.norm(n) for cid, c in _V.concepts.items() if c.get("kind") == "dataset" and c.get("not_shared")
                  for n in (c.get("name"), cid.partition(":")[2])}           # comparable by their numbers
    for r in I["rows"].values():
        if str(r.get("headline") or TBD).startswith(("(TBD)", "(NR)", "(NA)")):
            continue
        for d in r.get("data") or []:
            if it_align.norm(d.get("name")) in not_shared:
                continue
            k = (d.get("name"), (r.get("metrics") or [TBD])[0], r.get("split"))
            if TBD not in k and None not in k:
                by[k].append(r)
    for k, rs in sorted(by.items(), key=lambda kv: str(kv[0])):
        if len({r["citation_key"] for r in rs}) >= 2:
            rs = sorted(rs, key=lambda r: (r.get("year") or 0, r["exp_id"]))[:GROUP_MAX]
            ids = [r["exp_id"] for r in rs]
            out.append({"id": _key("numbers", ids), "type": "numbers", "key": " x ".join(map(str, k)), "members": sorted(ids),
                        "papers": sorted({r["citation_key"] for r in rs})})
    # lineage: one method family over the years, >= 2 papers
    fam = defaultdict(list)
    for r in I["rows"].values():
        for f in r.get("method_family") or []:
            if not str(f).startswith("("):
                fam[f].append(r)
    for f, rs in sorted(fam.items()):
        years = {r.get("year") for r in rs if r.get("year")}
        if len({r["citation_key"] for r in rs}) >= 2 and len(years) >= 2:
            rs = sorted(rs, key=lambda r: (r.get("year") or 0, r["exp_id"]))
            # the papers' premises about this method family come along: a lineage is where a later result puts an
            # earlier paper's premise at stake
            prem = [u["id"] for u in I["units"].values() if u["kind"] == "assumption"
                    and u["paper"] in {r["citation_key"] for r in rs}
                    and f"method-family:{f}" in _vals(((I["al"].get("coords") or {}).get(u["id"]) or {}).get("axes", {}).get("method_family"))]
            for i in range(0, len(rs), GROUP_MAX):
                part = rs[i:i + GROUP_MAX]
                if len({r["citation_key"] for r in part}) >= 2:
                    room = max(0, GROUP_MAX + 4 - len(part))
                    ids = [r["exp_id"] for r in part] + [a for a in prem if a.split("#")[0] in {r["citation_key"] for r in part}][:room]
                    out.append({"id": _key("lineage", ids), "type": "lineage", "key": f"method_family={f}",
                                "members": sorted(ids), "papers": sorted({r["citation_key"] for r in part})})
    # one comparison, not two: a group whose members all sit in a larger group of the same type is dropped
    seen, uniq = set(), []
    for c in sorted(out, key=lambda c: -len(c["members"])):
        if c["id"] in seen or any(u["type"] == c["type"] and set(c["members"]) <= set(u["members"]) for u in uniq):
            continue
        seen.add(c["id"])
        uniq.append(c)
    return uniq


def lens_candidates(I: dict) -> list[dict]:
    """B3.c: the field's conventions against what this machine can do; the cells nobody filled."""
    import it_align
    lens, mm = I["lens"], I["mm"]
    if not lens:
        return []
    V = it_align.Vocab((I["al"].get("vocab") or {}))
    on = lens.get("on_coords") or {}
    by_name = {}
    for cid, c in V.concepts.items():
        by_name[(c.get("kind"), c.get("name"))] = cid
        by_name[(c.get("kind"), cid.partition(":")[2])] = cid
    out = []
    conv = (mm.get("aggregates") or {}).get("conventions_full_text") or {}
    for dim, items in sorted(conv.items()):
        for it in items:
            if it.get("status") not in ("convention", "common"):
                continue
            refs = []
            if dim == "dataset":
                cid = by_name.get(("dataset", it["item"]))
                if cid and (on.get(cid) or {}).get("on_disk") != "yes":
                    refs.append(f"lens:{cid}")
            fams = {f for r in I["rows"].values() if r.get("evidence") == "full-text"
                    for f in r.get("method_family") or []
                    if it["item"] in ([d.get("name") for d in r.get("data") or []] + [r.get("split")] + (r.get("baselines") or [])
                                      + (r.get("metrics") or [])[:1])}
            for f in sorted(fams):
                cid = by_name.get(("method-family", f))
                if cid and (on.get(cid) or {}).get("affordable") in ("partial", "no"):
                    refs.append(f"lens:{cid}")
            members = [f"convention:{dim}:{it['item']}", *refs]
            if refs:
                out.append({"id": _key("convention-vs-lens", members), "type": "convention-vs-lens",
                            "key": f"{dim}={it['item']} ({it.get('status')}, share {it.get('share')})", "members": sorted(members),
                            "papers": sorted(it.get("papers") or [])})
    for ds, fm in empty_cells(mm, by_name):
        members = [f"cell:{ds}|{fm}"]
        out.append({"id": _key("empty-cell", members), "type": "empty-cell", "key": f"dataset={ds} x method_family={fm}",
                    "members": members, "papers": []})
    return out


def empty_cells(mm: dict, by_name: dict) -> list:
    """The matrix's empty dataset x family cells, on method-family concepts only (a word the vocabulary set aside is not
    a family), with the cap shared across the datasets as the paper cap is across types (in the matrix's family order
    within a dataset). Truncated in dataset order instead, one dataset took every slot on a 97-paper topic."""
    cells = [(ds, fm) for ds, fm in (mm.get("aggregates") or {}).get("dataset_family_empty_cells") or []
             if ("method-family", fm) in by_name]
    as_cands = [{"type": ds, "papers": [], "key": f"{i:04d}", "cell": (ds, fm)} for i, (ds, fm) in enumerate(cells)]
    kept, _ = share_cap(as_cands, EMPTY_CELL_CAP, types=list(dict.fromkeys(ds for ds, _ in cells)))
    return [c["cell"] for c in kept]


def share_cap(paper: list, cap: int, types=None) -> tuple[list, list]:
    """The depth cap shared across candidate types, so that no type is starved: a type smaller than an equal share is kept
    whole and the rest of the cap is shared among the others (water-filling); within a type, papers-many first. A cap
    taken in type order instead cut every shared-assumption and lineage candidate on a 97-paper topic."""
    types = list(types or PAPER_TYPES)
    by = {t: [c for c in paper if c["type"] == t] for t in types}
    quota, left, open_ = {t: 0 for t in types}, cap, [t for t in types if by[t]]
    while open_ and left > 0:
        share = max(1, left // len(open_))
        for t in list(open_):
            take = min(share, len(by[t]) - quota[t], left)
            quota[t] += take
            left -= take
            if quota[t] == len(by[t]):
                open_.remove(t)
            if left == 0:
                break
    kept = [c for t in types for c in by[t][:quota[t]]]
    cut = [c for t in types for c in by[t][quota[t]:]]
    return kept, cut


def build_candidates(rd) -> dict:
    I = inputs(rd)
    paper = paper_candidates(I)
    paper.sort(key=lambda c: (PAPER_TYPES.index(c["type"]), -len(c["papers"]), c["key"]))
    cap = CAPS.get(I["depth"], CAPS["standard"])
    kept, cut = share_cap(paper, cap)
    return {"at": now_iso(), "depth": I["depth"], "cap": cap,
            "basis": sha256_json({"coords": I["al"].get("coords"), "rows": sorted(I["rows"]), "lens": I["lens"].get("on_coords")}),
            "candidates": kept + lens_candidates(I),
            "truncated": [{"id": c["id"], "type": c["type"], "key": c["key"]} for c in cut],
            "counts": dict(Counter(c["type"] for c in kept + lens_candidates(I)))}


# ================================================================================================ A7.X2 judgements
def log(rd) -> list[dict]:
    return read_jsonl(Path(rd) / LOG)


def current(records: list[dict], keep_duplicates: bool = False) -> list[dict]:
    """Records not superseded by a later judgement of the same candidate, nor retired (their candidate no longer exists);
    a retire record is bookkeeping, never a relation. A relation already recorded on another candidate (same result,
    same sides) is kept in the log as `duplicate_of` - it shows the candidate was judged - but counts once: only the
    coverage checks ask for duplicates."""
    gone = {x for r in records for x in (r.get("supersedes") or []) + (r.get("retires") or [])}
    return [r for r in records if r["collision_id"] not in gone and r.get("result") != "retired"
            and (keep_duplicates or not r.get("duplicate_of"))]


def signature(result: str, side_ids) -> tuple:
    return (result, tuple(sorted(side_ids)))


def _member_info(I: dict, mid: str) -> dict | None:
    if mid in I["units"]:
        u = I["units"][mid]
        return {"id": mid, "paper": u["paper"], "kind": u["kind"], "basis": u["basis"], "year": u["year"],
                "builds_on": ((I["recs"].get(u["paper"]) or {}).get("summary") or {}).get("builds_on"),
                "builds_on_keys": ((I["recs"].get(u["paper"]) or {}).get("summary") or {}).get("builds_on_keys"),
                "text": u.get("text"), "quote": u.get("quote"), "where": u.get("where"), "strength": u.get("strength"),
                "scope": u.get("scope"), "overreach": u.get("overreach"),
                "coords": ((I["al"].get("coords") or {}).get(mid) or {}).get("axes")}
    if mid in I["rows"]:
        r = I["rows"][mid]
        return {"id": mid, "paper": r["citation_key"], "kind": "row", "basis": r.get("evidence"), "year": r.get("year"),
                "builds_on": ((I["recs"].get(r["citation_key"]) or {}).get("summary") or {}).get("builds_on"),
                "builds_on_keys": ((I["recs"].get(r["citation_key"]) or {}).get("summary") or {}).get("builds_on_keys"),
                **{k: r.get(k) for k in ("data", "split", "metrics", "method_family", "baselines", "headline", "stats",
                                          "design_choices", "where")}}
    if mid.startswith(("convention:", "cell:", "lens:")):
        if mid.startswith("lens:"):
            return {"id": mid, "kind": "lens", "verdict": (I["lens"].get("on_coords") or {}).get(mid[5:])}
        return {"id": mid, "kind": mid.split(":")[0]}
    return None


def judgement_problems(I: dict, cand: dict, rels: list[dict], model: str) -> list[str]:
    out = []
    lens = cand["type"] in LENS_TYPES
    allowed = RESULTS_LENS if lens else RESULTS_PAPER
    if not model:
        out.append("H08 `model` missing")
    if not rels:
        out.append("H01 a judgement needs at least one relation (`independent` when there is none)")
    for i, r in enumerate(rels):
        res = r.get("result")
        tag = f"relation {i + 1} ({res})"
        if res not in allowed:
            out.append(f"H03 {tag}: result must be one of {allowed} for a {cand['type']} candidate")
            continue
        sides = r.get("sides") or []
        alien = [s for s in sides if s not in cand["members"]]
        if alien:
            out.append(f"H02 {tag}: sides {alien} are not members of the candidate")
            continue
        info = [_member_info(I, s) for s in sides]
        if any(x is None for x in info):
            out.append(f"H02 {tag}: a side no longer exists")
            continue
        ax = r.get("axes_differ") or []
        if [a for a in ax if a not in AXES_DIFFER]:
            out.append(f"H03 {tag}: axes_differ codes are {AXES_DIFFER}")
        if res in ("conflict", "boundary") and not ax:
            out.append(f"H03 {tag}: name the axes on which the sides differ (`none` for a straight conflict)")
        if not str(r.get("reason") or "").strip():
            out.append(f"H03 {tag}: reason missing")
        papers = {x.get("paper") for x in info if x.get("paper")}
        if res in RELATIONAL and (len(sides) < 2 or len(papers) < 2):
            out.append(f"H05 {tag}: a relation needs sides from at least two papers")
        if res == "conflict" and ax == ["none"]:
            weak = [x["id"] for x in info if x.get("kind") == "claim" and
                    (x.get("strength") not in ARGUED or str(x.get("overreach") or "").strip())]
            if weak:
                out.append(f"H04 {tag}: a straight conflict (axes none) needs both claims argued (causes / shows / "
                           f"suggests) without an overreach note; {weak} do not qualify - that is claim-strength")
        if res == "untested-shared" and (not any(x.get("kind") == "assumption" for x in info) or
                                         any(x.get("kind") not in ("assumption", "claim", "row") for x in info)):
            out.append(f"H05 {tag}: untested-shared holds at least one assumption, plus the other papers' assumptions, or "
                       "their claims or rows that rest on the premise without testing it")
        if res in FINDINGS_ONLY and any(x.get("kind") not in ("claim", "row") for x in info):
            out.append(f"H05 {tag}: {res} relates findings (claims or rows); a premise goes to untested-shared, "
                       "assumption-challenged, assumption-at-stake or criterion-unmet")
        if res == "assumption-at-stake":
            ks = Counter(x.get("kind") for x in info)
            if ks.get("assumption") != 1 or not (ks.get("claim") or ks.get("row")):
                out.append(f"H05 {tag}: one assumption and the other papers' results that show what rides on it")
        if res == "criterion-unmet":
            crit_paper = info[0].get("paper") if info else None
            head = [x for x in info if x.get("paper") == crit_paper]
            rest = [x for x in info if x.get("paper") != crit_paper]
            if (not info or any(x.get("kind") not in ("assumption", "claim") for x in head) or not rest
                    or info[:len(head)] != head):
                out.append(f"H05 {tag}: criterion-unmet lists the unit(s) stating the criterion first (one paper), then the "
                           "other paper's units or rows that do not meet it")
        if res == "assumption-challenged":
            ks = Counter(x.get("kind") for x in info)
            if ks.get("assumption") != 1 or not (ks.get("claim") or ks.get("row")):
                out.append(f"H05 {tag}: one assumption and the claims or rows that challenge it")
        if res == "extends" and all(x.get("year") for x in info):      # an undated paper: order by builds_on, unchecked
            years = [x.get("year") for x in info]
            if years != sorted(years):
                out.append(f"H05 {tag}: list the sides in year order, the earlier first (the later extends it)")
        if res == "incommensurable" and not str(r.get("vocab_issue") or "").strip():
            out.append(f"H06 {tag}: say which concept merged things that differ (`vocab_issue`) - it goes back to align-set")
    return out


def same_data(I: dict, r: dict) -> list[str]:
    """Dataset concepts that sides from different papers share: an agreement on one dataset is not a replication.
    Placeholders ('own recordings', not_shared_reason placeholder) never count - each paper's own data is its own."""
    import it_align
    V = it_align.Vocab(I["al"].get("vocab") or {})
    coords = I["al"].get("coords") or {}
    by_name = {norm_name: cid for cid, c in V.concepts.items() if c.get("kind") == "dataset"
               for norm_name in {it_align.norm(c.get("name")), it_align.norm(cid.partition(":")[2])}}
    per_paper = defaultdict(set)
    for s in r.get("sides") or []:
        sid, paper = s.get("id"), s.get("paper")
        if not paper:
            continue
        if sid in coords:
            per_paper[paper] |= set(_vals((coords[sid].get("axes") or {}).get("data")))
        elif sid in I["rows"]:
            for d in I["rows"][sid].get("data") or []:
                cid = by_name.get(it_align.norm(d.get("name")))
                if cid:
                    per_paper[paper].add(cid)
    placeholder = {cid for cid, c in V.concepts.items() if c.get("not_shared_reason") == "placeholder"}
    shared = set()
    papers = list(per_paper)
    for i, a in enumerate(papers):
        for b in papers[i + 1:]:
            shared |= (per_paper[a] & per_paper[b]) - placeholder
    return sorted(shared)


def evidence_level(info: list[dict]) -> str:
    b = {x.get("basis") for x in info if x.get("basis")}
    return "full-text" if b == {"full-text"} else "abstract" if b == {"abstract"} else "mixed" if b else "n/a"


def plan(rd, size=10, lens=False) -> dict:
    rd = Path(rd)
    cands = read_json(rd / CANDS)
    I = inputs(rd)
    judged = {r["candidate"] for r in current(log(rd), keep_duplicates=True)}   # a candidate whose relations all repeat
    want = [c for c in cands["candidates"] if (c["type"] in LENS_TYPES) == lens and c["id"] not in judged]  # others is judged
    wd = rd / WORK
    (wd / "answers").mkdir(parents=True, exist_ok=True)
    pre = "lens_batch" if lens else "batch"      # the two plans never touch each other's files
    for old in wd.glob(f"{pre}_*.json"):
        old.unlink()
    # batch numbers restart with every plan: earlier answers move out of the way, or a new batch_001 would be answered
    # by an old one
    old_answers = sorted((wd / "answers").glob(f"{pre}_*.json"))
    if old_answers:
        arch = wd / "answers" / ("_superseded_" + now_iso().replace(":", "").replace("-", ""))
        arch.mkdir(parents=True, exist_ok=True)
        for f in old_answers:
            f.rename(arch / f.name)
    V = (I["al"].get("vocab") or {}).get("concepts") or []
    eq = {c["id"]: c.get("equivalence") for c in V if c.get("equivalence")}
    batches = []
    for i in range(0, len(want), size):
        n = len(batches) + 1
        part = want[i:i + size]
        items = []
        for c in part:
            members = [_member_info(I, m) for m in c["members"]]
            cnt = Counter(x for m in members for x in {y for v in ((m or {}).get("coords") or {}).values() for y in _vals(v)})
            used = {x for x, k in cnt.items() if k >= 2} | {c["key"].partition("=")[2]}
            items.append({**c, "members": members, "equivalence_notes": {k: eq[k] for k in sorted(used) if k in eq}})
        b = {"batch": n, "rules": RULES, "results": list(RESULTS_LENS if lens else RESULTS_PAPER),
             "axes_differ": list(AXES_DIFFER), "answer": f"{WORK}/answers/{pre}_{n:03d}.json", "candidates": items}
        write_json(wd / f"{pre}_{n:03d}.json", b)
        batches.append({"batch": n, "candidates": [c["id"] for c in part]})
    out = {"at": now_iso(), "lens": lens, "unjudged": len(want), "batches": batches}
    write_json(wd / ("plan_lens.json" if lens else "plan.json"), out)
    return out


def merge(rd, revise: str | None = None) -> dict:
    rd = Path(rd)
    cands = {c["id"]: c for c in read_json(rd / CANDS)["candidates"]}
    I = inputs(rd)
    recs = log(rd)
    cur = current(recs, keep_duplicates=True)
    by_cand = defaultdict(list)
    for r in cur:
        by_cand[r["candidate"]].append(r["collision_id"])
    seen_sig = {signature(r["result"], [s["id"] for s in r["sides"]]): r["collision_id"]
                for r in cur if not r.get("duplicate_of") and r["sides"]}
    n = max([int(r["collision_id"][1:]) for r in recs] or [0])
    new, refused, kept, now = [], [], 0, set()
    for f in sorted([*(rd / WORK / "answers").glob("batch_*.json"), *(rd / WORK / "answers").glob("lens_batch_*.json")]):
        ans = read_json(f)
        model = str(ans.get("model") or "").strip()
        for j in ans.get("judgements") or []:
            cid = j.get("candidate")
            cand = cands.get(cid)
            if not cand:
                refused.append((cid, ["H07 not a current candidate (stale answer?)"]))
                continue
            if cid in now or (cid in by_cand and not revise):
                kept += 1
                continue
            probs = judgement_problems(I, cand, j.get("relations") or [], model)
            if probs:
                refused.append((cid, probs))
                continue
            for rel in j["relations"]:
                n += 1
                info = [_member_info(I, s) for s in rel.get("sides") or []]
                sig = signature(rel["result"], rel.get("sides") or [])
                dup = seen_sig.get(sig) if rel.get("sides") else None
                if not dup and rel.get("sides"):
                    seen_sig[sig] = f"X{n:04d}"
                new.append({"collision_id": f"X{n:04d}", "candidate": cid, "type": cand["type"], "result": rel["result"],
                            "sides": [{"id": x["id"], "paper": x.get("paper"), "kind": x.get("kind"),
                                       "quote": x.get("quote") or x.get("headline")} for x in info],
                            "axes_differ": rel.get("axes_differ") or [], "reason": rel.get("reason"),
                            **({"detail": rel["detail"]} if rel.get("detail") else {}),
                            **({"vocab_issue": rel["vocab_issue"]} if rel.get("vocab_issue") else {}),
                            **({"duplicate_of": dup} if dup else {}),
                            "evidence_level": evidence_level(info), "model": model, "at": now_iso(),
                            "batch": f.name, **({"supersedes": by_cand[cid], "revision": revise} if cid in by_cand else {})})
            now.add(cid)
    append_jsonl(rd / LOG, new)
    import it_decon
    it_decon.render_all(rd)          # Disagrees with: is a projection of the log
    return {"written": len(new), "kept": kept, "refused": refused, "duplicates": sum(1 for r in new if r.get("duplicate_of"))}


def disagreements_of(rd, key: str) -> list[str]:
    """`Disagrees with:` lines of a reading note: the current conflict and assumption-challenged collisions with
    another paper, as `otherkey - reason [X0007; axes ...]`."""
    out = []
    for r in current(log(rd)):
        if r["result"] not in ("conflict", "assumption-challenged"):
            continue
        papers = [s.get("paper") for s in r["sides"]]
        if key not in papers:
            continue
        for other in sorted({p for p in papers if p and p != key}):
            ax = ", ".join(r.get("axes_differ") or []) or "-"
            out.append(f"{other} — {r['reason']} [{r['collision_id']}; {r['result']}; axes {ax}]")
    return out


# ================================================================================================ checks
def collision_problems(rd, cands: dict | None = None) -> list[dict]:
    rd = Path(rd)
    fs = []
    p = rd / CANDS
    if not p.exists():
        return [F("ERROR", "H01", "A7.X1", "no knowledge/collision_candidates.json (collide-candidates)")]
    cands = cands or read_json(p)
    fresh = build_candidates(rd)
    if fresh["basis"] != cands.get("basis"):
        fs.append(F("ERROR", "H07", "A7.X1", "STALE: coordinates, matrix rows or the lens changed after the candidates "
                                              "were listed - collide-candidates again"))
    ids = {c["id"]: c for c in cands["candidates"]}
    cur = current(log(rd), keep_duplicates=True)
    judged = {r["candidate"] for r in cur}
    for unit, types in (("A7.X2", PAPER_TYPES), ("B3.c", LENS_TYPES)):
        if unit == "A7.X2" and cands.get("depth") == "quick":
            continue
        miss = [c for c in cands["candidates"] if c["type"] in types and c["id"] not in judged]
        if miss:
            fs.append(F("ERROR", "H01", unit, f"{len(miss)} candidate(s) without a judgement: {[c['id'] for c in miss[:6]]}"
                                               f"{' …' if len(miss) > 6 else ''} (collide-plan{' --lens' if unit == 'B3.c' else ''})"))
    orphan = sorted({r["candidate"] for r in cur} - set(ids))
    if orphan:
        fs.append(F("ERROR", "H07", "A7.X2", f"{len(orphan)} judged candidate(s) no longer listed (their members changed): "
                                              f"{orphan[:6]} - re-judge with collide-plan"))
    I = inputs(rd)
    for r in cur:
        if r["candidate"] not in ids:
            continue
        unit = "B3.c" if r["type"] in LENS_TYPES else "A7.X2"
        rel = {"result": r["result"], "sides": [s["id"] for s in r["sides"]], "axes_differ": r.get("axes_differ"),
               "reason": r.get("reason"), "vocab_issue": r.get("vocab_issue")}
        for msg in judgement_problems(I, ids[r["candidate"]], [rel], r.get("model") or ""):
            code = msg[:3] if msg[:3] in JUDGEMENT_CODES else "H03"
            fs.append(F("ERROR", code, unit, f"{r['collision_id']}: {msg[4:]}"))
        if r["result"] == "incommensurable":
            hist = (I["al"].get("history") or [])
            if not any(h.get("at", "") > r["at"] for h in hist) and not I["al"].get("vocab_at", "") > r["at"]:
                fs.append(F("ERROR", "H06", unit, f"{r['collision_id']}: incommensurable, and the vocabulary was not revised "
                                                   "since (align-set --reason)"))
    return fs


# ================================================================================================ B3 gaps
def gaps_problems(rd, doc: dict) -> list[dict]:
    U = "B3"
    rd = Path(rd)
    fs = []
    cur = {r["collision_id"]: r for r in current(log(rd))}
    I = inputs(rd)
    import it_decon
    pp = it_decon.papers(rd)
    lens_on = I["lens"].get("on_coords") or {}
    ids = []
    used = set()
    for g in doc.get("gaps") or []:
        gid = str(g.get("id") or "")
        ids.append(gid)
        tag = gid or "?"
        if not re.fullmatch(r"GAP_\d{3}", gid):
            fs.append(F("ERROR", "W01", U, f"{tag}: id must be GAP_NNN"))
        for k in ("title", "description", "why_it_matters"):
            if not str(g.get(k) or "").strip():
                fs.append(F("ERROR", "W01", U, f"{tag}: `{k}` missing"))
        ty = g.get("type") or {}
        if ty.get("primary") not in GAP_TYPES or (ty.get("secondary") and ty["secondary"] not in GAP_TYPES):
            fs.append(F("ERROR", "W01", U, f"{tag}: type.primary (and secondary) from {GAP_TYPES}"))
        for s in ("severity", "novelty", "feasibility"):
            if g.get(s) not in (1, 2, 3, 4, 5):
                fs.append(F("ERROR", "W01", U, f"{tag}: {s} must be an integer 1-5"))
        cols = g.get("collisions") or []
        nd = g.get("not_done") or []
        bad = [c for c in cols if c not in cur]
        nd_bad = [u for u in nd if u not in I["units"] or I["units"][u]["kind"] != "not-done"]
        nd_papers = {u.split("#")[0] for u in nd if u not in nd_bad}
        if bad or nd_bad or (not cols and len(nd_papers) < 2):
            fs.append(F("ERROR", "W02", U, f"{tag}: a gap rests on current collisions, or on the same not-done item in >= 2 "
                                            f"papers (`not_done` unit ids) - got collisions {bad or cols or 'none'}, "
                                            f"not_done {nd_bad or nd or 'none'}"))
        used |= set(cols)
        for ax in g.get("axes") or []:
            if ax not in GAP_AXES:
                fs.append(F("ERROR", "W01", U, f"{tag}: axis {ax!r} is not one of {GAP_AXES}"))
        sup = g.get("supporting") or []
        if len({s.get("key") for s in sup}) < 2 or any(s.get("key") not in pp or not str(s.get("how") or "").strip() for s in sup):
            fs.append(F("ERROR", "W03", U, f"{tag}: supporting needs >= 2 shortlisted papers, each with how it shows the gap"))
        move = g.get("move")
        if move not in MOVES_EXT + MOVES_CON:
            fs.append(F("ERROR", "W04", U, f"{tag}: move must be one of {MOVES_EXT + MOVES_CON}"))
        else:
            # the defaults come from the gap's PRIMARY collision (listed first): adding collisions never widens them
            r = cur.get(cols[0]) or {} if cols else {}
            res = r.get("result")
            if res == "conflict":
                dflt = {"cause", "kind", "perspective"} if r.get("axes_differ") == ["none"] else \
                    {"kind", "part-whole", "cause", "apply-wider"}
            elif res:
                dflt = DEFAULT_MOVES.get(res, set())
            else:
                dflt = set(MOVES_EXT)                    # recurring not-done: an absence
            if dflt and move not in dflt and not str(g.get("move_reason") or "").strip():
                fs.append(F("ERROR", "W04", U, f"{tag}: move {move!r} is not a default of its primary collision "
                                                f"({cols[0] if cols else 'not-done'}: {sorted(dflt)}) - give move_reason"))
        if move in MOVES_CON or move == "confirm-assumed":
            scs = g.get("source_check") or []
            scs = scs if isinstance(scs, list) else [scs]
            if not scs or any(s.get("key") not in pp for s in scs):
                fs.append(F("ERROR", "W05", U, f"{tag}: a {move} gap needs source_check {{key, where, quote}} (or a list) on "
                                                "the paper(s) whose claim or premise it turns on"))
            for sc in scs:
                key = sc.get("key")
                if key not in pp:
                    continue
                basis, text, _ = it_decon.source(rd, key, pp[key])
                if basis != "full-text":
                    fs.append(F("ERROR", "W05", U, f"{tag}: source check on {key} needs its full text - none was obtained; "
                                                    "reclassify as an extension move or drop the gap"))
                else:
                    prob = it_decon.quote_problem(sc.get("quote"), it_decon.squash(text))
                    if prob or not str(sc.get("where") or "").strip():
                        fs.append(F("ERROR", "W05", U, f"{tag}: source check on {key}: {prob or 'where missing'}"))
        gap_papers = {s.get("key") for s in sup}
        if g.get("severity") in (4, 5):
            ev = g.get("consequence_evidence") or []
            # a consequence must bear on this gap: one of its own collisions, or one that shares a paper with its support
            strong = [e for e in ev if e in cur and cur[e]["result"] in CONSEQUENCE and
                      (e in cols or {s.get("paper") for s in cur[e]["sides"]} & gap_papers)]
            fut = {e.split("#")[0] for e in ev if re.search(r"#F\d+$", str(e)) and e in I["units"]}
            if not strong and len(fut) < 2:
                fs.append(F("ERROR", "W06", U, f"{tag}: severity {g['severity']} needs a citable consequence bearing on this "
                                                f"gap - a {' / '.join(CONSEQUENCE)} collision of its own or sharing a "
                                                "supporting paper, or the same future-work call (#F units) in >= 2 papers"))
        results = {(cur.get(c) or {}).get("result") for c in cols}
        if (results == {"empty-cell"} or (not cols and nd)) and (g.get("severity") or 0) > 3 and not any(
                e in cur and cur[e]["result"] in CONSEQUENCE for e in g.get("consequence_evidence") or []):
            fs.append(F("ERROR", "W07", U, f"{tag}: built on an absence only (empty cells or recurring not-done) - nobody "
                                            "is shown to need it: severity at most 3 without a consequence collision"))
        fb = g.get("feasibility_basis") or []
        own = {f"own:{d.get('name')}" for d in I["lens"].get("own_data") or []}
        known = [x for x in fb if (str(x).startswith("lens:") and x[5:] in lens_on) or x in own]
        if not fb or len(known) != len(fb):
            fs.append(F("ERROR", "W08", U, f"{tag}: feasibility_basis must cite lens verdicts (lens:<concept>) or own data "
                                            f"(own:<name>); unknown: {sorted(set(fb) - set(known))}"))
        else:
            caps = [FEAS_CAP.get(lens_on[x[5:]].get("affordable") or lens_on[x[5:]].get("on_disk"), 5)
                    for x in fb if x.startswith("lens:")]
            if caps and (g.get("feasibility") or 0) > min(caps):
                fs.append(F("ERROR", "W08", U, f"{tag}: feasibility {g.get('feasibility')} above what its weakest cited "
                                                f"verdict allows ({min(caps)}: yes 5, partial / obtainable 4, no 2)"))
    for d in {i for i in ids if ids.count(i) > 1}:
        fs.append(F("ERROR", "W01", U, f"{d} appears twice"))
    # every collision a gap could turn on is either used or set aside with a reason
    must = [r for r in cur.values() if r["result"] in MUST_ACCOUNT
            or (r["result"] == "conflict" and r.get("axes_differ") == ["none"])]
    set_aside = {x.get("collision"): x for x in doc.get("not_gaps") or []}
    left = [r["collision_id"] for r in must if r["collision_id"] not in used and
            not str((set_aside.get(r["collision_id"]) or {}).get("why") or "").strip()]
    if left:
        fs.append(F("ERROR", "W10", U, f"{len(left)} straight-conflict or premise collision(s) neither in a gap nor set "
                                        f"aside with a reason in not_gaps: {left[:8]}"))
    return fs


def composite(g) -> float:
    return round(g["severity"] * 0.40 + g["novelty"] * 0.30 + g["feasibility"] * 0.30, 2)


def rank(gaps: list[dict]) -> list[dict]:
    """The formula and the tie-break of research-cycle §3 - within 0.3 of each other, a contradiction move first, then
    severity - made transitive: gaps are taken in composite order and grouped while each stays within 0.30 of its group's
    top (integer hundredths: 3.70 - 3.40 is exactly 30, not 0.30000000000000027); each group is ordered by move class,
    severity, composite."""
    hund = lambda g: round(composite(g) * 100)
    order = sorted(gaps, key=lambda g: (-hund(g), g["id"]))
    groups = []
    for g in order:
        if groups and hund(groups[-1][0]) - hund(g) <= 30:
            groups[-1].append(g)
        else:
            groups.append([g])
    return [g for grp in groups for g in sorted(grp, key=lambda g: (g["move"] not in MOVES_CON, -g["severity"], -hund(g),
                                                                       -g["novelty"], -g["feasibility"], g["id"]))]


def render_gaps(rd, doc: dict) -> str:
    cur = {r["collision_id"]: r for r in current(log(rd))}
    gaps = rank(doc["gaps"])
    lvl = lambda c: (cur.get(c) or {}).get("evidence_level", "?")
    L = ["Source order used: collision order (fusion block) — " + " → ".join(SOURCE_ORDER) + ".", "",
         f"# Gap analysis — {doc.get('topic') or 'topic'} (fusion block, once per topic)", "",
         "Ranked by composite; gaps within 0.30 of their group's top are ordered contradiction move first, then severity "
         "(research-cycle §3 tie-break).", "",
         "| rank | gap | move | composite | severity | novelty | feasibility | rests on (evidence level) |",
         "|---|---|---|---|---|---|---|---|"]
    for i, g in enumerate(gaps, 1):
        rests = ", ".join(f"{c} ({lvl(c)})" for c in g["collisions"]) or "not done: " + ", ".join(g.get("not_done") or [])
        L.append(f"| {i} | {g['id']} {g['title']} | {g['move']} | {composite(g):.2f} | {g['severity']} | {g['novelty']} | "
                 f"{g['feasibility']} | {rests} |")
    for g in gaps:
        ty = g["type"]
        L += ["", f"## {g['id']} — {g['title']}", "",
              f"- **Description**: {g['description']}",
              f"- **Type**: {ty['primary']}" + (f" (secondary: {ty['secondary']})" if ty.get("secondary") else ""),
              f"- **Move**: `{g['move']}`" + (f" — {g['move_reason']}" if g.get("move_reason") else ""),
              f"- **Axes**: {', '.join(g.get('axes') or []) or '-'}",
              "- **Collisions**: " + "; ".join(f"{c} ({cur[c]['result']}: {cur[c]['reason']})" for c in g["collisions"] if c in cur),
              "- **Supporting evidence**:"] + [f"  - [{s['key']}] {s['how']}" for s in g["supporting"]] + \
             ["- **Counter-evidence**:"] + ([f"  - [{s['key']}] {s.get('why_open', '')}" for s in g.get("counter") or []] or ["  - none found"])
        scs = g.get("source_check") or []
        for sc in (scs if isinstance(scs, list) else [scs]):
            L.append(f"- **Source check**: [{sc['key']}] {sc['where']}: \"{sc['quote']}\"")
        if g.get("not_done"):
            L.append(f"- **Not done in**: {', '.join(g['not_done'])} (reading notes)")
        if g.get("novelty_basis"):
            L.append(f"- **Novelty basis**: {g['novelty_basis']}")
        L += [f"- **Why it matters**: {g['why_it_matters']}" + (f" (evidence: {', '.join(g.get('consequence_evidence') or [])})"
                                                               if g.get("consequence_evidence") else ""),
              f"- **Feasibility basis**: {', '.join(g.get('feasibility_basis') or [])}",
              f"- **Priority score**: composite = {g['severity']} × 0.40 + {g['novelty']} × 0.30 + {g['feasibility']} × 0.30 "
              f"= {composite(g):.2f}"]
    if doc.get("not_gaps"):
        L += ["", "## Collisions set aside", ""] + [f"- {x['collision']}: {x['why']}" for x in doc["not_gaps"]]
    if doc.get("single_paper"):
        L += ["", "## In scope, one paper only (not gaps yet)", ""] + [f"- {x}" for x in doc["single_paper"]]
    if doc.get("adjacent"):
        L += ["", "## Adjacent opportunities (outside the scope, not ranked)", ""] + [f"- {x}" for x in doc["adjacent"]]
    if doc.get("revisions_needed"):
        L += ["", "## Record revisions queued by source checks (decon-merge --revise)", ""] + \
             [f"- [{x.get('key')}] {x.get('where')}: \"{x.get('quote')}\" — {x.get('why')}" for x in doc["revisions_needed"]]
    L += ["", f"<!-- view of {GAPS}, rendered by `ideate_tools.py gaps-set`: edit the JSON, not this file -->"]
    return "\n".join(L) + "\n"


# ================================================================================================ commands
def _print(fs, as_json=False):
    if as_json:
        print(json.dumps(fs, indent=2, ensure_ascii=False))
        return
    for f in fs:
        print(f"  {f['level']:<5} {f['code']} [{f['unit']}] {f['msg']}")


def cmd_candidates(a):
    from it_ledger import degraded_codes, run_unit
    rd = Path(a.research_dir)
    with run_unit(rd, "A7.X1", check=lambda: run_checks(rd, "A7.X1"), degraded=lambda: degraded_codes(rd, "A7.X1")):
        _cmd_candidates(a)


def _cmd_candidates(a):
    rd = Path(a.research_dir)
    out = build_candidates(rd)
    write_json_stable(rd / CANDS, out)
    print(f"collide-candidates: {len(out['candidates'])} candidate(s) {out['counts']}; {len(out['truncated'])} cut at the "
          f"{out['depth']} cap of {out['cap']} -> {CANDS}")


def cmd_plan(a):
    rd = Path(a.research_dir)
    out = plan(rd, a.size, a.lens)
    if not out["batches"]:                  # nothing left to judge: no merge will follow, so the plan closes the Unit
        from it_ledger import run_unit
        unit = "B3.c" if a.lens else "A7.X2"
        with run_unit(rd, unit, check=lambda: run_checks(rd, unit)):
            pass
    print(f"collide-plan{' --lens' if a.lens else ''}: {out['unjudged']} unjudged candidate(s) -> {len(out['batches'])} "
          f"batch(es) in {WORK}/")
    if out["batches"]:
        print(f"  one subagent per batch: read {RULES} and its batch file, write the answer path it names; then collide-merge")


def merge_units(rd, revise=None) -> list[str]:
    """The Units one collide-merge closes: A7.X2 for the paper batches' answers, B3.c for the lens batch's - each only
    when its answers hold a judgement not yet in the log (or with --revise)."""
    ans = Path(rd) / WORK / "answers"
    judged = {r["candidate"] for r in current(log(rd), keep_duplicates=True)}
    units = []
    for u, pat in (("A7.X2", "batch_*.json"), ("B3.c", "lens_batch_*.json")):
        js = [j for f in sorted(ans.glob(pat)) for j in (read_json(f).get("judgements") or [])]
        if js and (revise or any(j.get("candidate") not in judged for j in js)):
            units.append(u)
    return units or ["A7.X2"]


def cmd_merge(a):
    from contextlib import ExitStack
    from it_ledger import degraded_codes, run_unit
    rd = Path(a.research_dir)
    with ExitStack() as stack:
        for u in merge_units(rd, a.revise):
            stack.enter_context(run_unit(rd, u, check=lambda u=u: run_checks(rd, u),
                                         degraded=lambda u=u: degraded_codes(rd, u)))
        code = _cmd_merge(a)          # a refused judgement leaves its candidate unjudged: the checks keep the Unit pending
    raise SystemExit(code)


def _cmd_merge(a) -> int:
    out = merge(Path(a.research_dir), a.revise)
    print(f"collide-merge: {out['written']} collision record(s) written ({out['duplicates']} repeat a relation already "
          f"recorded on another candidate - kept as duplicate_of), {out['kept']} judgement(s) already in the log, "
          f"{len(out['refused'])} refused")
    for cid, why in out["refused"]:
        print(f"  REFUSED {cid}:")
        for w in why[:6]:
            print(f"    - {w}")
    return 1 if out["refused"] else 0


def retire(rd, reason: str) -> list[str]:
    """Judgements whose candidate is no longer listed (its members changed after a vocabulary or coordinate revision)
    are retired by one appended record - the log stays append-only, and nothing is silently dropped."""
    rd = Path(rd)
    ids = {c["id"] for c in read_json(rd / CANDS)["candidates"]}
    recs = log(rd)
    gone = [r["collision_id"] for r in current(recs, keep_duplicates=True) if r["candidate"] not in ids]
    if gone:
        n = max(int(r["collision_id"][1:]) for r in recs) + 1
        append_jsonl(rd / LOG, [{"collision_id": f"X{n:04d}", "result": "retired", "retires": gone, "reason": reason,
                                 "candidate": None, "type": "retire", "sides": [], "at": now_iso()}])
        import it_decon
        it_decon.render_all(rd)
    return gone


def cmd_retire(a):
    from it_ledger import run_unit
    rd = Path(a.research_dir)
    with run_unit(rd, "A7.X2", check=lambda: run_checks(rd, "A7.X2")):       # a revision of the judgements
        _cmd_retire(a)


def _cmd_retire(a):
    gone = retire(Path(a.research_dir), a.reason)
    print(f"collide-retire: {len(gone)} judgement(s) of candidates no longer listed retired" + (f": {gone[:12]}" if gone else ""))


def cmd_gaps(a):
    from it_ledger import degraded_codes, run_unit
    rd = Path(a.research_dir)
    with run_unit(rd, "B3", check=lambda: run_checks(rd, "B3"), degraded=lambda: degraded_codes(rd, "B3")):
        _cmd_gaps(a)


def _cmd_gaps(a):
    rd = Path(a.research_dir)
    doc = read_json(Path(a.gaps_json))
    fs = gaps_problems(rd, doc)
    _print(fs)
    if errors(fs):
        print("gaps-set: NOT written")
        raise SystemExit(1)
    old = read_json(rd / GAPS) if (rd / GAPS).exists() else None
    retired = sorted((set(g["id"] for g in (old or {}).get("gaps") or []) | set((old or {}).get("retired") or []))
                     - {g["id"] for g in doc["gaps"]})
    doc = {**doc, "topic": doc.get("topic") or _cfg(rd).get("topic"), "ranked": [g["id"] for g in rank(doc["gaps"])], "composites": {g["id"]: composite(g) for g in doc["gaps"]},
           "retired": retired, "at": now_iso()}
    reused = [g["id"] for g in doc["gaps"] if g["id"] in set((old or {}).get("retired") or [])]
    if reused:
        die(f"gap id(s) {reused} were retired and are never reused - take the next number", 1)
    write_json_stable(rd / GAPS, doc)
    write_text(rd / GAPS_MD, render_gaps(rd, doc))
    print(f"gaps-set: {len(doc['gaps'])} gap(s) ranked {doc['ranked']} -> {GAPS}, {GAPS_MD}")


def run_checks(rd, unit="all") -> list[dict]:
    rd = Path(rd)
    fs = [f for f in collision_problems(rd) if unit == "all" or f["unit"] == unit]
    if unit in ("all", "B3"):
        p = rd / GAPS
        if not p.exists():
            fs.append(F("ERROR", "W01", "B3", f"{GAPS} missing (gaps-set)"))
        else:
            doc = read_json(p)
            fs += gaps_problems(rd, doc)
            md = rd / GAPS_MD
            if not md.exists() or md.read_text(encoding="utf-8") != render_gaps(rd, doc):
                fs.append(F("ERROR", "W09", "B3", f"{GAPS_MD} is not the rendering of {GAPS} (edited by hand?) - gaps-set again"))
    return fs


def answer_problems(rd, path) -> list[str]:
    """One answer file checked as collide-merge would, nothing written (a subagent's self-check)."""
    rd = Path(rd)
    cands = {c["id"]: c for c in read_json(rd / CANDS)["candidates"]}
    I = inputs(rd)
    ans = read_json(Path(path))
    out = []
    for j in ans.get("judgements") or []:
        cand = cands.get(j.get("candidate"))
        if not cand:
            out.append(f"{j.get('candidate')}: not a current candidate")
            continue
        out += [f"{cand['id']}: {m}" for m in judgement_problems(I, cand, j.get("relations") or [], str(ans.get("model") or ""))]
    return out


def cmd_check(a):
    if a.answer:
        paths = [f if Path(f).exists() else Path(a.research_dir) / f for f in a.answer]
        missing = [str(p) for p in paths if not Path(p).exists()]
        if missing:
            die(f"answer file(s) not found: {missing}", 2)
        probs = [p for f in paths for p in answer_problems(a.research_dir, f)]
        for p in probs:
            print(f"  REFUSED {p}")
        print("OK" if not probs else f"{len(probs)} problem(s)")
        raise SystemExit(1 if probs else 0)
    fs = run_checks(Path(a.research_dir), a.unit)
    _print(fs, a.json)
    if not a.json:
        print("OK" if not errors(fs) else f"{len(errors(fs))} error(s)")
    raise SystemExit(1 if errors(fs) else 0)


def add_parsers(sub) -> None:
    sp = sub.add_parser("collide-candidates", help="A7.X1 (+ B3.c): list what is compared -> collision_candidates.json")
    sp.add_argument("research_dir")
    sp.set_defaults(fn=cmd_candidates)
    sp = sub.add_parser("collide-plan", help="A7.X2 / B3.c: batches of unjudged candidates for the subagents")
    sp.add_argument("research_dir")
    sp.add_argument("--size", type=int, default=10)
    sp.add_argument("--lens", action="store_true", help="the lens candidates (B3.c) instead of the paper x paper ones")
    sp.set_defaults(fn=cmd_plan)
    sp = sub.add_parser("collide-merge", help="A7.X2 / B3.c: answers -> collisions.jsonl (append-only); notes re-rendered")
    sp.add_argument("research_dir")
    sp.add_argument("--revise", metavar="REASON", help="re-judge candidates that have a judgement (supersedes it)")
    sp.set_defaults(fn=cmd_merge)
    sp = sub.add_parser("collide-retire", help="A7.X2: retire judgements whose candidate is no longer listed (append-only)")
    sp.add_argument("research_dir")
    sp.add_argument("--reason", required=True)
    sp.set_defaults(fn=cmd_retire)
    sp = sub.add_parser("gaps-set", help="B3: validate, rank and write the gap list -> step7_gaps.json + step7_gap_analysis.md")
    sp.add_argument("research_dir")
    sp.add_argument("gaps_json")
    sp.set_defaults(fn=cmd_gaps)
    sp = sub.add_parser("collide-check", help="collision and gap checks (H01-H08, W01-W10)")
    sp.add_argument("research_dir")
    sp.add_argument("--unit", default="all", choices=["all", "A7.X1", "A7.X2", "B3.c", "B3"])
    sp.add_argument("--answer", nargs="+", metavar="FILE", help="check answer file(s) as collide-merge would; nothing written")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_check)
