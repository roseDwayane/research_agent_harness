"""Align - put every paper's units on one set of coordinates, and ourselves on the same ones
(rules: references/fusion/F2-align.md; decision record docs/decisions/PLAN_ideate_fusion.md).

  A7.A1  vocabulary   one concept per thing the papers name: kind, name, definition, the spellings that mean it; a
                      false friend (one word, two meanings) is split by a per-paper override; a measure reached by two
                      papers' definitions carries an equivalence note        -> knowledge/alignment.json `vocab`
  A7.A2  coordinates  every claim and assumption -> {construct, measure, population, data, split, method_family}
                      (a concept id or "unstated"); the tool suggests from the text and the paper's rows, the model
                      settles what the tool cannot                          -> knowledge/alignment.json `coords`
  A7.A3  concept Points  candidates: concepts reached by >= 2 papers (the old Pass 1 rule, counted); the cards go
                      through build-cards with origin align                 -> knowledge/_work/A7A/point_candidates.json
  B1     lens         who is looking (domain, venues, compute, scope) and what is on this machine (env-probe),
                      put on the same concepts: dataset on disk, method family affordable  -> <RD>/lens.json

  The methods-matrix input is a projection of the vocabulary and the lens (never written by hand):
  knowledge/methods_matrix_input.json -> build-methods <RD> knowledge/methods_matrix_input.json knowledge/decon/*.json

  ideate_tools.py align-terms  <RD>                     the worklist: every word the records use, grouped
  ideate_tools.py align-set    <RD> vocab.json          A7.A1 (refused while a check fails)
  ideate_tools.py align-coords <RD> --suggest | --auto | --apply coords.json      A7.A2
  ideate_tools.py align-points <RD>                     A7.A3 candidates
  ideate_tools.py lens-set     <RD> lens.json           B1 (run `env-probe <RD> --write` first)
  ideate_tools.py align-check  <RD> [--unit A7.A1|A7.A2|A7.A3|B1|all] [--json]
"""

from __future__ import annotations

import functools
import json
import re
from collections import defaultdict
from pathlib import Path

from it_common import die, now_iso, read_json, sha256_json, write_json

SCHEMA = "ai-scientist-alignment/1"
LENS_SCHEMA = "ai-scientist-lens/1"
TBD, NR, NA = "(TBD)", "(NR)", "(NA)"
UNSTATED = "unstated"
NOT_APPLICABLE = "n/a"      # the axis does not apply to this unit (no split in a non-predictive ANOVA) - not a gap
CONCEPT_KINDS = ("method-family", "method", "construct", "measure", "dataset", "split", "population", "paradigm",
                 "condition")    # condition: a contrast condition a result is compared against (missed putts, low pressure)
# what a word of a given origin may be aligned to
TERM_KINDS = {"method": {"method-family", "method"}, "measure": {"measure"}, "dataset": {"dataset"},
              "split": {"split"}, "population": {"population"}, "construct": {"construct"}, "paradigm": {"paradigm"},
              "condition": {"condition"}}
ROW_FIELDS = {"method_family": {"method-family"}, "data": {"dataset"},
              "baselines": {"method", "method-family", "condition", "population"},
              "metrics": {"measure"}, "split": {"split"}}
AXES = {"construct": "construct", "measure": "measure", "population": "population", "data": "dataset",
        "split": "split", "method_family": "method-family"}
POINT_KINDS = ("method-family", "method", "construct", "measure", "paradigm")   # datasets and splits surface in Planes
COORD_UNIT_KINDS = ("claim", "assumption")
VERDICT_ON_DISK = ("yes", "obtainable", "no")
VERDICT_AFFORD = ("yes", "partial", "no")
PERSONA_KEYS = ("expert_domain", "target_venues", "compute", "scope")
WORK = "knowledge/_work/A7A"
ID_RE = re.compile(r"^(" + "|".join(CONCEPT_KINDS) + r"):[a-z0-9][a-z0-9-]*$")


def F(level, code, unit, msg):
    return {"level": level, "code": code, "unit": unit, "msg": msg}


def errors(fs):
    return [f for f in fs if f["level"] == "ERROR"]


def norm(s) -> str:
    """How two spellings are compared: case-folded; hyphens, underscores and runs of whitespace are one space (so a
    kebab slug matches the spelled-out words); outer punctuation dropped."""
    return re.sub(r"[\s\-_\u2010-\u2015]+", " ", str(s or "").casefold()).strip(" .,;:()[]\"'")


def _is_tag(v) -> bool:
    return isinstance(v, str) and v.strip().upper().startswith((TBD, NR, NA))


# ================================================================================================ inputs
def alignment_path(rd) -> Path:
    return Path(rd) / "knowledge" / "alignment.json"


def lens_path(rd) -> Path:
    return Path(rd) / "lens.json"


def load_alignment(rd) -> dict:
    p = alignment_path(rd)
    return read_json(p) if p.exists() else {"schema": SCHEMA}


def evidence_records(rd) -> dict:
    """Records that are evidence: eligible full texts and abstract-only papers (an ineligible paper is not)."""
    import it_decon
    return {k: r for k, r in it_decon.records(rd).items()
            if not r.get("_unreadable") and (r.get("eligibility") or {}).get("verdict") in ("eligible", "abstract-only")}


def occurrences(recs: dict) -> list[dict]:
    """Every word the records use that must sit on the vocabulary: their terms and the names in their matrix rows."""
    out = []
    for key, r in sorted(recs.items()):
        for t in r.get("terms") or []:
            if str(t.get("term") or "").strip():
                out.append({"paper": key, "string": t["term"].strip(), "origin": f"term:{t.get('kind')}",
                            "allowed": sorted(TERM_KINDS.get(t.get("kind"), set())), "definition": t.get("definition")})
        for row in r.get("experiments") or []:
            for field, kinds in ROW_FIELDS.items():
                v = row.get(field)
                vals = [d.get("name") for d in v if isinstance(d, dict)] if field == "data" and isinstance(v, list) else \
                    (v if isinstance(v, list) else [v])
                for s in vals:
                    if isinstance(s, str) and s.strip() and not _is_tag(s):
                        out.append({"paper": key, "string": s.strip(), "origin": f"row:{field}",
                                    "allowed": sorted(kinds), "exp_id": row.get("exp_id")})
    return out


def basis_of(recs: dict) -> str:
    """What the vocabulary was built from: the words, their origins and definitions (not the order of the files)."""
    return sha256_json(sorted((o["paper"], o["string"], o["origin"], o.get("definition") or "") for o in occurrences(recs)))


def unit_sha(u: dict) -> str:
    """What a unit's coordinates were judged on: its text and scope."""
    return sha256_json([u.get("text"), json.dumps(u.get("scope"), sort_keys=True)])[:16]


def unit_shas(recs: dict) -> dict:
    return {u["id"]: unit_sha(u) for r in recs.values() for u in r.get("units") or [] if u.get("kind") in COORD_UNIT_KINDS}


def units_basis(recs: dict) -> str:
    return sha256_json(sorted((u["id"], u.get("text"), json.dumps(u.get("scope"), sort_keys=True))
                              for r in recs.values() for u in r.get("units") or [] if u.get("kind") in COORD_UNIT_KINDS))


# ================================================================================================ vocabulary
class Vocab:
    def __init__(self, vocab: dict):
        self.concepts = {c.get("id"): c for c in vocab.get("concepts") or [] if isinstance(c, dict)}
        self.overrides = vocab.get("overrides") or {}
        self.unaligned = vocab.get("unaligned") or []
        self.variant = {}
        self.clash = defaultdict(set)
        for cid, c in self.concepts.items():
            for v in [c.get("name"), str(cid or "").partition(":")[2], *(c.get("variants") or [])]:   # the slug is a spelling too
                n = norm(v)
                if not n:
                    continue
                if n in self.variant and self.variant[n] != cid:
                    self.clash[n] |= {self.variant[n], cid}
                self.variant.setdefault(n, cid)

    def resolve(self, paper: str, string: str, origin: str | None = None) -> str | None:
        """An override is a concept id, or {origin: concept id} for a word one paper uses in two roles (`term:measure`,
        `row:method_family`, or just `term` / `row`)."""
        if self.is_unaligned(paper, string):     # set aside for this paper, even where the spelling has a concept
            return None
        ov = self.overrides.get(paper) or {}
        for s, cid in ov.items():
            if norm(s) != norm(string):
                continue
            if isinstance(cid, dict):
                pick = cid.get(origin) or (cid.get(origin.split(":")[0]) if origin else None)
                if pick:
                    return pick
                continue
            return cid
        return self.variant.get(norm(string))

    def is_unaligned(self, paper: str, string: str) -> bool:
        return any(u.get("paper") == paper and norm(u.get("string")) == norm(string) for u in self.unaligned)

    def kind(self, cid) -> str | None:
        return (self.concepts.get(cid) or {}).get("kind")


def vocab_problems(vocab: dict, occ: list[dict]) -> list[dict]:
    U = "A7.A1"
    fs = []
    V = Vocab(vocab)
    ids = [c.get("id") for c in vocab.get("concepts") or []]
    for c in vocab.get("concepts") or []:
        cid = str(c.get("id") or "")
        if not ID_RE.match(cid) or c.get("kind") != cid.partition(":")[0]:
            fs.append(F("ERROR", "A01", U, f"concept {cid or '?'}: id must be <kind>:<kebab-slug> with kind {CONCEPT_KINDS} "
                                            f"matching its `kind` ({c.get('kind')!r})"))
        if not str(c.get("name") or "").strip() or not str(c.get("definition") or "").strip():
            fs.append(F("ERROR", "A01", U, f"concept {cid}: needs a name and a one-line definition"))
        fam = c.get("family")
        if fam and V.kind(fam) != "method-family":
            fs.append(F("ERROR", "A01", U, f"concept {cid}: family {fam!r} is not a method-family concept"))
        q = c.get("quantity")
        if q is not None and (c.get("kind") != "measure" or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(q))):
            fs.append(F("ERROR", "A01", U, f"concept {cid}: `quantity` (a kebab name shared by the normalisation variants "
                                            "of one measured quantity) belongs on measure concepts only"))
    for d in {i for i in ids if ids.count(i) > 1}:
        fs.append(F("ERROR", "A01", U, f"concept id {d} appears twice"))
    for n, cids in sorted(V.clash.items()):
        fs.append(F("ERROR", "A02", U, f"the spelling {n!r} is claimed by {sorted(cids)} - one spelling, one concept; a word "
                                        "that means different things in different papers is split with `overrides`"))
    papers = {o["paper"] for o in occ}
    by_paper = defaultdict(set)
    for o in occ:
        by_paper[o["paper"]].add(norm(o["string"]))
    for paper, ov in (vocab.get("overrides") or {}).items():
        for s, target in (ov or {}).items():
            for cid in (target.values() if isinstance(target, dict) else [target]):
                if cid not in V.concepts:
                    fs.append(F("ERROR", "A06", U, f"override {paper}/{s!r} -> {cid!r}: no such concept"))
            if paper not in papers or norm(s) not in by_paper[paper]:
                fs.append(F("ERROR", "A06", U, f"override {paper}/{s!r}: that paper does not use that word"))
    missing, wrong, seen = [], [], set()
    for o in occ:
        sig = (o["paper"], norm(o["string"]), o["origin"])
        if sig in seen:
            continue
        seen.add(sig)
        cid = V.resolve(o["paper"], o["string"], o["origin"])
        if cid is None:
            if not V.is_unaligned(o["paper"], o["string"]):
                missing.append(f"{o['paper']}:{o['string']!r} ({o['origin']})")
        elif V.kind(cid) not in o["allowed"]:
            wrong.append(f"{o['paper']}:{o['string']!r} ({o['origin']}) -> {cid} (a {V.kind(cid)}; allowed {o['allowed']})")
    if missing:
        fs.append(F("ERROR", "A03", U, f"{len(missing)} word(s) on no concept and not listed as unaligned: {missing[:8]}"
                                        f"{' …' if len(missing) > 8 else ''}"))
    if wrong:
        fs.append(F("ERROR", "A04", U, f"{len(wrong)} word(s) on a concept of the wrong kind: {wrong[:6]}"
                                        f"{' …' if len(wrong) > 6 else ''}"))
    for u in vocab.get("unaligned") or []:
        if not str(u.get("reason") or "").strip():
            fs.append(F("ERROR", "A07", U, f"unaligned {u.get('paper')}:{u.get('string')!r} needs a reason"))
        elif u.get("paper") not in papers or norm(u.get("string")) not in by_paper[u.get("paper")]:
            fs.append(F("ERROR", "A07", U, f"unaligned {u.get('paper')}:{u.get('string')!r}: that paper does not use that word"))
    for cid, by in unjudged_measures(V, occ).items():
        eq = V.concepts[cid].get("equivalence") or {}
        fs.append(F("ERROR", "A05", U, f"{cid}: {len(by)} papers define it ({sorted(by)}); `equivalence` must list all "
                                        f"of them with `because` (or split the false friend with overrides) - "
                                        f"not covered: {sorted(set(by) - set(eq.get('papers') or []))}"))
    return fs


def unjudged_measures(V, occ: list[dict]) -> dict:
    """{measure: {paper: (its word, its definition)}} for each measure two or more papers define that no equivalence
    note covers - the same thing only if someone read both definitions and said so (A05). Two spellings of one word
    ("signal-to-noise ratio", "... ratios"), each defined by one paper, land here: neither was asked with the other."""
    defs = defaultdict(dict)
    for o in occ:
        if o.get("definition"):
            cid = V.resolve(o["paper"], o["string"])
            if cid and V.kind(cid) == "measure":
                defs[cid][o["paper"]] = (o["string"], o["definition"])
    out = {}
    for cid, by in defs.items():
        eq = V.concepts[cid].get("equivalence") or {}
        if len(by) >= 2 and (set(by) - set(eq.get("papers") or []) or not str(eq.get("because") or "").strip()):
            out[cid] = by
    return out


# ================================================================================================ coordinates
@functools.lru_cache(maxsize=None)
def _rx(n: str):
    """A spelling as a pattern: whole words, hyphen or space between them (norm() treats them alike). Compiled once:
    the index is rebuilt per paper, and thousands of spellings overflow re's own cache."""
    return re.compile(r"(?<![\w])" + r"[\s\-_]+".join(map(re.escape, n.split(" "))) + r"(?![\w])", re.I)


def _variant_index(V: Vocab, paper: str | None = None) -> dict:
    """{kind: [(regex, concept)]}, longest spelling first within a kind - so 'decoding accuracy' wins over 'accuracy' -
    but a spelling of one kind never hides a spelling of another ('readiness potential' the method family and the
    measure of the same name both match). The paper's overrides come first; its set-aside words never match."""
    by_kind = defaultdict(list)
    items = [(norm(s), c) for s, cid in ((V.overrides.get(paper) or {}).items() if paper else [])
             for c in (cid.values() if isinstance(cid, dict) else [cid])]
    items += sorted(V.variant.items(), key=lambda kv: -len(kv[0]))
    seen = set()
    for n, cid in items:
        if len(n) < 2 or (paper and V.is_unaligned(paper, n)) or n in seen or V.kind(cid) is None:
            continue
        seen.add(n)
        by_kind[V.kind(cid)].append((_rx(n), cid))
    for k in by_kind:
        by_kind[k].sort(key=lambda rc: -len(rc[0].pattern))
    return by_kind


def suggest(rd, recs: dict, V: Vocab) -> dict:
    """Per claim / assumption unit: the concepts its text, scope and quote name, by axis, plus the paper's rows as a
    fallback for data, split and method family. One candidate on an axis = a suggestion; several = ambiguous."""
    out = {}
    for key, r in recs.items():
        idx = _variant_index(V, key)
        rows = r.get("experiments") or []
        row_c = defaultdict(set)
        for o in occurrences({key: {"experiments": rows}}):
            cid = V.resolve(key, o["string"])
            if cid:
                row_c[V.kind(cid)].add(cid)
                fam = (V.concepts.get(cid) or {}).get("family")
                if fam:
                    row_c["method-family"].add(fam)
        for u in r.get("units") or []:
            if u.get("kind") not in COORD_UNIT_KINDS:
                continue
            # the reader's statement and the scope, not the quote: a quote carries the paper's surrounding words
            # (Carey's C6 quote named "expertise", which the claim is not about)
            text = " ".join([str(u.get("text") or ""),
                             *[str(v) for v in (u.get("scope") or {}).values() if not _is_tag(v)]])
            found = defaultdict(set)
            for kind, pats in idx.items():
                masked = text
                for rx, cid in pats:
                    if rx.search(masked):
                        found[kind].add(cid)
                        masked = rx.sub(" ", masked)
                        fam = (V.concepts.get(cid) or {}).get("family")
                        if fam:
                            found["method-family"].add(fam)
            cand, origin = {}, {}
            for axis, kind in AXES.items():
                c = found.get(kind) or set()
                o = "text"
                if not c and axis in ("data", "split", "method_family") and row_c.get(kind):
                    c, o = row_c[kind], "row"
                cand[axis] = sorted(c)
                origin[axis] = o if c else None
            out[u["id"]] = {"paper": key, "kind": u["kind"], "text": u.get("text"), "candidates": cand, "from": origin,
                            "ambiguous": sorted(a for a, c in cand.items() if len(c) > 1)}
    return out


def coords_problems(al: dict, recs: dict) -> list[dict]:
    U = "A7.A2"
    fs = []
    V = Vocab(al.get("vocab") or {})
    coords = al.get("coords") or {}
    want = {u["id"]: k for k, r in recs.items() for u in r.get("units") or [] if u.get("kind") in COORD_UNIT_KINDS}
    missing = sorted(set(want) - set(coords))
    if missing:
        fs.append(F("ERROR", "A09", U, f"{len(missing)} claim / assumption unit(s) without coordinates: {missing[:8]}"
                                        f"{' …' if len(missing) > 8 else ''} (align-coords)"))
    for uid in sorted(set(coords) - set(want)):
        fs.append(F("ERROR", "A09", U, f"coordinates for {uid}, which is not a claim or assumption of an evidence record"))
    for uid, c in sorted(coords.items()):
        if uid not in want:
            continue
        if set(c.get("axes") or {}) != set(AXES):
            fs.append(F("ERROR", "A09", U, f"{uid}: axes must be exactly {list(AXES)}"))
            continue
        for axis, v in c["axes"].items():
            vals = v if isinstance(v, list) else [v]
            for x in vals:
                if x in (UNSTATED, NOT_APPLICABLE):
                    continue
                if V.kind(x) != AXES[axis]:
                    fs.append(F("ERROR", "A09", U, f"{uid}: {axis} = {x!r} is not a {AXES[axis]} concept"))
        if c.get("by") not in ("auto", "model"):
            fs.append(F("ERROR", "A09", U, f"{uid}: `by` must be auto or model"))
        ax = c.get("axes") or {}
        if ax.get("construct") == UNSTATED and ax.get("measure") == UNSTATED:
            fs.append(F("WARN", "A10", U, f"{uid}: neither construct nor measure stated - this unit cannot collide with anything"))
    shas = unit_shas(recs)
    if coords and all(c.get("unit_sha") for c in coords.values()):
        changed = sorted(u for u, c in coords.items() if u in shas and c["unit_sha"] != shas[u])
        if changed:
            fs.append(F("ERROR", "A11", U, f"STALE: {len(changed)} unit(s) changed after their coordinates were set: "
                                            f"{changed[:8]} - re-place them (align-coords --apply)"))
    elif al.get("coords_basis") and al["coords_basis"] != units_basis(recs):      # coordinates without fingerprints
        fs.append(F("ERROR", "A11", U, "STALE: claim or assumption units changed after the coordinates were set - "
                                        "align-coords --suggest, then --auto / --apply"))
    return fs


# ================================================================================================ concept Points
def point_candidates(al: dict, recs: dict) -> list[dict]:
    """Concepts of a Point kind that >= 2 papers reach - through their words or their units' coordinates."""
    V = Vocab(al.get("vocab") or {})
    reach = defaultdict(lambda: {"papers": set(), "units": set()})
    for o in occurrences(recs):
        cid = V.resolve(o["paper"], o["string"])
        if cid:
            reach[cid]["papers"].add(o["paper"])
            fam = (V.concepts.get(cid) or {}).get("family")
            if fam:
                reach[fam]["papers"].add(o["paper"])
    for uid, c in (al.get("coords") or {}).items():
        key = uid.split("#")[0]
        for v in (c.get("axes") or {}).values():
            for x in (v if isinstance(v, list) else [v]):
                if x in V.concepts:
                    reach[x]["papers"].add(key)
                    reach[x]["units"].add(uid)
    out = []
    for cid, r in reach.items():
        if V.kind(cid) in POINT_KINDS and len(r["papers"]) >= 2:
            c = V.concepts[cid]
            out.append({"concept": cid, "name": c.get("name"), "kind": V.kind(cid), "papers": sorted(r["papers"]),
                        "units": sorted(r["units"])})
    return sorted(out, key=lambda x: (-len(x["papers"]), x["concept"]))


def points_problems(rd, al: dict, recs: dict) -> list[dict]:
    U = "A7.A3"
    fs = []
    p = Path(rd) / "knowledge_cards.json"
    if not p.exists():
        return fs
    cands = {c["concept"]: c for c in point_candidates(al, recs)}
    units = {u["id"] for r in recs.values() for u in r.get("units") or []}
    for pt in read_json(p).get("points") or []:
        if pt.get("origin") != "align":
            continue
        cid = pt.get("concept")
        if cid not in cands:
            fs.append(F("ERROR", "A12", U, f"Point {pt.get('slug')}: origin align needs `concept` = a concept that >= 2 "
                                            f"papers reach (align-points); {cid!r} is not one"))
        bad = [x for x in pt.get("unit_refs") or [] if x not in units]
        if bad:
            fs.append(F("ERROR", "A12", U, f"Point {pt.get('slug')}: unit_refs not found: {bad[:5]}"))
        elif cid in cands:
            alien = [x for x in pt.get("unit_refs") or [] if x.split("#")[0] not in cands[cid]["papers"]]
            if alien:
                fs.append(F("ERROR", "A12", U, f"Point {pt.get('slug')}: unit_refs {alien[:5]} come from papers that do "
                                                f"not reach {cid}"))
    return fs


# ================================================================================================ lens (B1)
def lens_problems(rd, al: dict, recs: dict, lens: dict | None = None) -> list[dict]:
    U = "B1"
    fs = []
    if lens is None:
        p = lens_path(rd)
        if not p.exists():
            return [F("ERROR", "T01", U, "lens.json missing (lens-set)")]
        lens = read_json(p)
    if lens.get("schema") != LENS_SCHEMA:
        fs.append(F("ERROR", "T01", U, f"lens.json: schema must be {LENS_SCHEMA}"))
    per = lens.get("persona") or {}
    miss = [k for k in PERSONA_KEYS if not per.get(k)]
    if miss:
        fs.append(F("ERROR", "T01", U, f"lens.json persona needs {miss}"))
    cfg_p = Path(rd) / "step0_session_config.json"
    probe = ((read_json(cfg_p).get("local_environment") or {}).get("probe") if cfg_p.exists() else None) or {}
    local = lens.get("local") or {}
    if not probe:
        fs.append(F("ERROR", "T02", U, "no env-probe in step0 (ideate_tools.py env-probe <RD> --write)"))
    elif local.get("date") != probe.get("date"):
        fs.append(F("ERROR", "T02", U, f"STALE: lens.json carries the probe of {local.get('date')}, step0 holds "
                                        f"{probe.get('date')} - lens-set again"))
    V = Vocab(al.get("vocab") or {})
    used = defaultdict(set)
    for o in occurrences(recs):
        cid = V.resolve(o["paper"], o["string"])
        if cid:
            used[cid].add(o["paper"])
    on = lens.get("on_coords") or {}
    need = [cid for cid in V.concepts if V.kind(cid) == "method-family" or
            (V.kind(cid) == "dataset" and len(used[cid]) >= 2 and not V.concepts[cid].get("not_shared"))]
    for cid in sorted(set(need) - set(on)):
        fs.append(F("ERROR", "T03", U, f"{cid}: no verdict in lens.json on_coords"))
    children = {str(c).casefold() for kids in (local.get("data_roots") or {}).values() for c in kids} | \
               {str(r).casefold() for r in (local.get("data_roots") or {})}
    for cid, v in sorted(on.items()):
        k = V.kind(cid)
        if k is None:
            fs.append(F("ERROR", "T03", U, f"on_coords {cid}: no such concept"))
        elif k == "dataset" and v.get("on_disk") not in VERDICT_ON_DISK:
            fs.append(F("ERROR", "T03", U, f"{cid}: on_disk must be one of {VERDICT_ON_DISK}"))
        elif k == "method-family" and v.get("affordable") not in VERDICT_AFFORD:
            fs.append(F("ERROR", "T03", U, f"{cid}: affordable must be one of {VERDICT_AFFORD}"))
        elif k not in ("dataset", "method-family"):
            fs.append(F("ERROR", "T03", U, f"{cid}: on_coords holds datasets and method families only"))
        if not str(v.get("why") or "").strip():
            fs.append(F("ERROR", "T03", U, f"{cid}: verdict without `why`"))
        if k == "dataset" and v.get("on_disk") == "yes":
            where = str(v.get("where") or "").casefold()
            if not where or not any(c and c in where for c in children):
                fs.append(F("ERROR", "T04", U, f"{cid}: on_disk yes must name `where` - a path under a data root the "
                                                "probe listed"))
    # our own data - the recordings a topic is often built around - need not be in any paper's vocabulary
    for d in lens.get("own_data") or []:
        where = Path(str(d.get("where") or "")).expanduser()
        if not str(d.get("name") or "").strip() or not str(d.get("what") or "").strip():
            fs.append(F("ERROR", "T05", U, f"own_data {d.get('name')!r}: needs name, where and what"))
        elif not str(d.get("where") or "").strip() or not where.exists():
            fs.append(F("ERROR", "T05", U, f"own_data {d.get('name')!r}: `where` {d.get('where')!r} does not exist on this "
                                            "machine"))
    return fs


# ================================================================================================ projection
def project_matrix_input(al: dict, lens: dict | None) -> dict:
    """knowledge/methods_matrix_input.json, rebuilt from the vocabulary (and the lens): never written by hand."""
    V = Vocab(al.get("vocab") or {})
    tag = lambda cid: cid.partition(":")[2]
    out = {"_note": "projection of knowledge/alignment.json (and lens.json) by it_align - do not edit",
           "vocab": {"method_family": {tag(c): V.concepts[c].get("definition") for c in sorted(V.concepts)
                                       if V.kind(c) == "method-family"}},
           "aliases": {"method_family": {}, "dataset": {}, "baseline": {}, "metric": {}, "split": {}},
           # public data one paper used still counts as a benchmark when another paper uses it; only placeholders and
           # unidentifiable data stay out of the conventions and the holes grid
           "not_shared_datasets": sorted(V.concepts[c]["name"] for c in V.concepts
                                         if V.kind(c) == "dataset" and V.concepts[c].get("not_shared")
                                         and V.concepts[c].get("not_shared_reason") != "single-use")}
    spell = lambda c: sorted({V.concepts[c].get("name"), tag(c), *(V.concepts[c].get("variants") or [])} - {None})
    over = defaultdict(set)
    for _, ov in (al.get("vocab") or {}).get("overrides", {}).items():
        for s, target in (ov or {}).items():
            for cid in (target.values() if isinstance(target, dict) else [target]):
                over[cid].add(s)
    for c in sorted(V.concepts):
        k, names = V.kind(c), sorted(set(spell(c)) | over[c])
        if k == "method-family":
            out["aliases"]["method_family"][tag(c)] = names
        elif k == "dataset":
            out["aliases"]["dataset"][V.concepts[c]["name"]] = names
        elif k == "measure":
            out["aliases"]["metric"][V.concepts[c]["name"]] = names
        elif k == "split":
            out["aliases"]["split"][V.concepts[c]["name"]] = names
        if k in ("method", "method-family", "condition", "population"):     # what a baseline may be
            out["aliases"]["baseline"][V.concepts[c]["name"]] = names
    if lens:
        out["affordable"] = {tag(c): f"{v.get('affordable')} - {v.get('why')}" for c, v in sorted((lens.get("on_coords") or {}).items())
                             if V.kind(c) == "method-family" and v.get("affordable")}
    return out


def matrix_input_path(rd) -> Path:
    return Path(rd) / "knowledge" / "methods_matrix_input.json"


def write_projection(rd) -> None:
    al = load_alignment(rd)
    if not al.get("vocab"):
        return
    lens = read_json(lens_path(rd)) if lens_path(rd).exists() else None
    write_json(matrix_input_path(rd), project_matrix_input(al, lens))


# ================================================================================================ checks
def run_checks(rd, unit="all") -> list[dict]:
    rd = Path(rd)
    recs = evidence_records(rd)
    al = load_alignment(rd)
    fs = []
    if unit in ("all", "A7.A1"):
        if not al.get("vocab"):
            fs.append(F("ERROR", "A08", "A7.A1", "knowledge/alignment.json has no vocabulary (align-terms, align-set)"))
        else:
            fs += vocab_problems(al["vocab"], occurrences(recs))
            if al.get("vocab_basis") != basis_of(recs):
                fs.append(F("ERROR", "A08", "A7.A1", "STALE: the records' words changed after the vocabulary was set - "
                                                      "align-terms, then align-set"))
            mi = matrix_input_path(rd)
            lens = read_json(lens_path(rd)) if lens_path(rd).exists() else None
            if not mi.exists() or read_json(mi) != project_matrix_input(al, lens):
                fs.append(F("ERROR", "A13", "A7.A1", "knowledge/methods_matrix_input.json is not the projection of the "
                                                      "vocabulary (edited by hand?) - align-set or lens-set rewrites it"))
    if unit in ("all", "A7.A2") and al.get("vocab"):
        fs += coords_problems(al, recs)
    if unit in ("all", "A7.A3") and al.get("vocab"):
        fs += points_problems(rd, al, recs)
    if unit in ("all", "B1"):
        fs += lens_problems(rd, al, recs)
    return fs


# ================================================================================================ commands
def _work(rd) -> Path:
    p = Path(rd) / WORK
    p.mkdir(parents=True, exist_ok=True)
    return p


def terms_worklist(rd, vocab: dict | None = None) -> dict:
    recs = evidence_records(rd)
    al = load_alignment(rd)
    V = Vocab(vocab if vocab is not None else al.get("vocab") or {})
    groups = {}
    for o in occurrences(recs):
        g = groups.setdefault(norm(o["string"]), {"string": o["string"], "origins": set(), "allowed": set(),
                                                  "papers": set(), "definitions": [], "concept": None})
        g["origins"].add(o["origin"])
        g["allowed"] |= set(o["allowed"])
        g["papers"].add(o["paper"])
        if o.get("definition"):
            g["definitions"].append({"paper": o["paper"], "text": o["definition"]})
        g["concept"] = g["concept"] or V.resolve(o["paper"], o["string"], o["origin"])
    items = sorted(({**g, "origins": sorted(g["origins"]), "allowed": sorted(g["allowed"]), "papers": sorted(g["papers"])}
                    for g in groups.values()), key=lambda g: (-len(g["papers"]), norm(g["string"])))
    return {"at": now_iso(), "records": len(recs), "words": len(items),
            "unplaced": sum(1 for g in items if not g["concept"]), "items": items}


# ---- A7.A1 in batches (a worker that is given its batch in the prompt): the model names a concept for each word, the
# code builds the vocabulary from the answers. The draft (knowledge/_work/A7A/vocab.json) grows pass by pass.
def _slug(s) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s or "").casefold()).strip("-") or "unnamed"


def _draft(rd) -> dict:
    f = _work(rd) / "vocab.json"
    return read_json(f) if f.exists() else json.loads(json.dumps(load_alignment(rd).get("vocab") or {}))


def vocab_batches(rd, max_chars: int = 0, size: int = 60) -> list[list[dict]]:
    """The words still on no concept, grouped by the kinds they may take, each with how many papers use it and - for
    a measure two papers define - their definitions (the model then says whether they are the same measure).
    A word whose roles share no kind ("EEG" a population term in one paper, a dataset in another) is asked once per
    role; its `uses` (paper, origin) say where the answer goes - per paper and role, not as a spelling of the word."""
    V = Vocab(_draft(rd))
    by_word = defaultdict(list)
    for o in occurrences(evidence_records(rd)):
        by_word[norm(o["string"])].append(o)
    items = []
    for occ in by_word.values():
        shared = set.intersection(*(set(o["allowed"]) for o in occ))
        # open: on no concept, or on one of a kind this use may not take (another role's concept by its name)
        open_ = [o for o in occ if not V.is_unaligned(o["paper"], o["string"])
                 and V.kind(V.resolve(o["paper"], o["string"], o["origin"])) not in o["allowed"]]
        if not open_:
            continue
        roles = [open_] if shared else [[o for o in open_ if o["allowed"] == list(k)]
                                        for k in sorted({tuple(o["allowed"]) for o in open_})]
        for role in roles:
            defs = {o["paper"]: str(o["definition"])[:200] for o in role if o.get("definition")}
            it = {"word": role[0]["string"], "kinds": sorted(shared) if shared else role[0]["allowed"],
                  "papers": len({o["paper"] for o in role}), **({"definitions": defs} if len(defs) >= 2 else {})}
            if not shared:
                it["uses"] = [list(u) for u in sorted({(o["paper"], o["origin"]) for o in role})]
            items.append(it)
    for cid, by in unjudged_measures(V, [o for occ in by_word.values() for o in occ]).items():
        items.append({"word": V.concepts[cid].get("name") or cid, "kinds": ["measure"], "concept": cid,
                      "papers": len(by), "definitions": {k: str(d)[:200] for k, (_, d) in by.items()},
                      "words": {k: w for k, (w, _) in by.items()}})     # placed already: is it one measure?
    items.sort(key=lambda it: (it["kinds"], norm(it["word"])))
    out, cur, used = [], [], 0
    for i, it in enumerate(items, 1):
        it = {"key": f"w{i:04d}", **it}
        n = len(json.dumps(it, ensure_ascii=False))
        if cur and (len(cur) >= size or (max_chars and used + n > max_chars)):
            out.append(cur)
            cur, used = [], 0
        cur.append(it)
        used += n
    return out + ([cur] if cur else [])


def vocab_schema(items: list[dict]) -> dict:
    # bounded strings: a model caught repeating itself inside one stops at the bound, not at num_predict
    s, text = {"type": "string", "maxLength": 120}, {"type": "string", "maxLength": 400}
    props = {}
    for it in items:
        p = {"kind": {"enum": list(it["kinds"]) + ["unaligned"]}, "slug": s, "name": s, "definition": text}
        if it.get("definitions"):
            p.update({"same_measure": {"type": "boolean"}, "because": text})
        props[it["key"]] = {"type": "object", "properties": p, "required": list(p), "additionalProperties": False}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def vocab_from_answers(rd) -> tuple[dict, int]:
    """The draft vocabulary plus every batch answer -> (vocabulary, words placed). Rules, in code:
    - a word's concept is `<kind>:<slug>`; the first answer to name a concept gives its name and definition;
    - `unaligned` sets the word aside for every paper that uses it, the definition line as the reason;
    - a measure two papers define is one measure only when the answer says so (`same_measure` + `because`, the
      equivalence note); otherwise each further paper gets its own measure through an override - "the same thing
      only if someone read both definitions and said so" (A05)."""
    vocab = _draft(rd)
    concepts = {c["id"]: c for c in vocab.get("concepts") or [] if isinstance(c, dict)}
    overrides, unaligned = vocab.get("overrides") or {}, vocab.get("unaligned") or []
    papers_of = {norm(g["string"]): g["papers"] for g in terms_worklist(rd, vocab)["items"]}
    placed = 0
    for bf in sorted(_work(rd).glob("vbatch_*.json")):
        b = read_json(bf)
        af = Path(rd) / b["answer"]
        ans = read_json(af) if af.exists() else {}
        for it in b["items"]:
            a = ans.get(it["key"])
            if not isinstance(a, dict) or a.get("kind") not in list(it["kinds"]) + ["unaligned"]:
                continue                                       # left for the next pass
            placed += 1
            if it.get("concept") in concepts:                   # one measure several papers define: the same?
                _judge_measure(concepts, overrides, it, a)
                continue
            word, uses = it["word"], it.get("uses") or []
            papers = sorted({k for k, _ in uses}) if uses else papers_of.get(norm(word), [])
            if a["kind"] == "unaligned":
                unaligned += [{"paper": k, "string": word, "reason": a.get("definition") or "set aside by the reader"}
                              for k in papers]
                continue
            cid = f"{a['kind']}:{_slug(a.get('slug') or word)}"
            c = concepts.setdefault(cid, {"id": cid, "kind": a["kind"], "name": a.get("name") or word,
                                          "definition": a.get("definition") or "(TBD)", "variants": []})
            target = {k: cid for k in papers}                  # paper -> the concept its use of the word is on
            defs = it.get("definitions") or {}
            if defs and a.get("same_measure") and str(a.get("because") or "").strip():
                c["equivalence"] = {"papers": sorted(defs), "because": a["because"]}
            elif defs:                                         # not said to be the same: one measure per paper
                for k in sorted(defs)[1:]:
                    target[k] = f"{cid}-{_slug(k)}"
                    concepts.setdefault(target[k], {"id": target[k], "kind": a["kind"], "name": f"{c['name']} ({k})",
                                                    "definition": defs[k], "variants": []})
            if uses:                                           # one role of a word with several: per paper and role
                for k, origin in uses:
                    ov = overrides.setdefault(k, {})
                    ov[word] = ov[word] if isinstance(ov.get(word), dict) else {}
                    ov[word][origin] = target[k]
                continue
            c["variants"] = sorted(set(c.get("variants") or []) | {word})
            for k in papers:
                if target[k] != cid:
                    overrides.setdefault(k, {})[word] = target[k]
    vocab.update(concepts=list(concepts.values()), overrides=overrides, unaligned=unaligned)
    return _separate_spellings(vocab), placed


def _judge_measure(concepts: dict, overrides: dict, it: dict, a: dict) -> None:
    """The answer to a measure several papers define, read side by side: one measure (the equivalence note), or the
    first paper keeps it and each further paper's word goes to a measure of its own (an override)."""
    cid, defs = it["concept"], it["definitions"]
    if a.get("same_measure") and str(a.get("because") or "").strip():
        eq = concepts[cid].get("equivalence") or {}
        concepts[cid]["equivalence"] = {"papers": sorted(set(eq.get("papers") or []) | set(defs)), "because": a["because"]}
        return
    for k in sorted(defs)[1:]:
        new = f"{cid}-{_slug(k)}"
        concepts.setdefault(new, {"id": new, "kind": "measure", "name": f"{concepts[cid]['name']} ({k})",
                                  "definition": defs[k], "variants": []})
        ov, w = overrides.setdefault(k, {}), it["words"][k]
        ov[w] = {origin: new for origin in ov[w]} if isinstance(ov.get(w), dict) else new


def _separate_spellings(vocab: dict) -> dict:
    """One spelling, one concept (A02). Two concepts of the same kind that share a spelling are one concept ("adda"
    and "adversarial discriminative domain adaptation"): the later is merged into the first. Two of different kinds
    ("Accuracy" a measure and a method) are told apart by the kind, once, in the slug and name of the one that has
    the spelling only as its name or slug - a word a paper uses (a variant) stays where it was placed."""
    for _ in range(5):                                 # a merge can uncover the next clash: a few passes
        clash = Vocab(vocab).clash
        if not clash:
            break
        by_id = {c["id"]: c for c in vocab["concepts"]}
        dropped, redirect = set(), {}
        for n, cids in clash.items():
            keep, *others = sorted(cids)
            for cid in others:
                a, b = by_id.get(keep), by_id.get(cid)
                if a is None or b is None or cid in dropped or keep in dropped:
                    continue
                if a["kind"] == b["kind"]:             # the same thing under two slugs
                    a["variants"] = sorted(set(a.get("variants") or []) | set(b.get("variants") or []) | {b["name"]})
                    dropped.add(cid)
                    redirect[cid] = keep
                    continue
                move = a if n in {norm(v) for v in b.get("variants") or []} else b
                new = f"{move['id']}-{move['kind']}"
                if move["id"].endswith("-" + move["kind"]):
                    continue                           # told apart already
                if new in by_id:                       # told apart in an earlier pass: that concept, its words joined
                    by_id[new]["variants"] = sorted(set(by_id[new].get("variants") or []) | set(move.get("variants") or []))
                    dropped.add(move["id"])
                    redirect[move["id"]] = new
                else:
                    redirect[move["id"]] = new
                    move["id"], move["name"] = new, f"{move['name']} ({move['kind']})"
        vocab["concepts"] = [c for c in vocab["concepts"] if c["id"] not in dropped]
        for c in vocab["concepts"]:                    # what pointed at a moved concept follows it
            if c.get("family") in redirect:
                c["family"] = redirect[c["family"]]
        for ov in (vocab.get("overrides") or {}).values():
            for w, target in list(ov.items()):
                if isinstance(target, dict):           # {origin: concept} for a word with several roles
                    ov[w] = {o: redirect.get(cid, cid) for o, cid in target.items()}
                elif target in redirect:
                    ov[w] = redirect[target]
    return vocab


def cmd_terms(a):
    rd = Path(a.research_dir)
    if getattr(a, "batches", False):
        wd = _work(rd)
        for old in [*wd.glob("vbatch_*.json"), *(wd / "schemas").glob("vbatch_*.json"),
                    *(wd / "vanswers").glob("vbatch_*.json")]:          # merged already (--merge-answers)
            old.unlink()
        bs = vocab_batches(rd, getattr(a, "max_chars", 0) or 0)
        for i, items in enumerate(bs, 1):
            write_json(wd / f"vbatch_{i:03d}.json", {"batch": i, "items": items,
                                                     "answer": f"{WORK}/vanswers/vbatch_{i:03d}.json"})
            write_json(wd / "schemas" / f"vbatch_{i:03d}.json", vocab_schema(items))
        print(f"align-terms --batches: {sum(len(b) for b in bs)} word(s) to place in {len(bs)} batch(es) -> {WORK}/")
        return
    if getattr(a, "merge_answers", False):
        vocab, placed = vocab_from_answers(rd)
        write_json(_work(rd) / "vocab.json", normal_vocab(vocab))
        print(f"align-terms --merge-answers: {placed} word(s) placed; {len(vocab['concepts'])} concept(s) in the draft "
              f"-> {WORK}/vocab.json")
        return
    wl = terms_worklist(rd)
    write_json(_work(rd) / "terms.json", wl)
    (_work(rd) / "vocab.json").unlink(missing_ok=True)   # A7.A1 starts again: the batches build on alignment.json
    print(f"align-terms: {wl['words']} distinct word(s) from {wl['records']} record(s); {wl['unplaced']} on no concept yet "
          f"-> {WORK}/terms.json")


def cmd_set(a):
    from it_ledger import run_unit
    rd = Path(a.research_dir)
    with run_unit(rd, "A7.A1", check=lambda: run_checks(rd, "A7.A1")):
        _cmd_set(a)


def drop_withdrawn(vocab: dict, keys: set) -> tuple[dict, int]:
    """The vocabulary without the per-paper entries of papers that left the records (F1: a paper leaving the
    shortlist is withdrawn): their overrides, their set-aside words, their names in equivalence notes. The concepts
    and spellings stay - another paper may use them, and an unused spelling harms nothing."""
    v = json.loads(json.dumps(vocab))
    ov = v.get("overrides") or {}
    gone = sum(len(x) for k, x in ov.items() if k not in keys)
    v["overrides"] = {k: x for k, x in ov.items() if k in keys}
    un = v.get("unaligned") or []
    keep = [u for u in un if not u.get("paper") or u["paper"] in keys]
    gone += len(un) - len(keep)
    v["unaligned"] = keep
    for c in v.get("concepts") or []:
        eq = c.get("equivalence")
        if isinstance(eq, dict) and eq.get("papers"):
            kept = [p for p in eq["papers"] if p in keys]
            gone += len(eq["papers"]) - len(kept)
            eq["papers"] = kept
    return v, gone


def normal_vocab(vocab: dict) -> dict:
    """What code settles in a vocabulary draft: an id whose kind prefix disagrees with its `kind` takes the kind
    (`<kind>:<slug>`); a `family` given as a bare slug names the method-family concept of that slug, and a family
    that names no method-family concept is dropped (it is optional); `quantity` belongs on measures only."""
    v = json.loads(json.dumps(vocab or {}))
    concepts = [c for c in v.get("concepts") or [] if isinstance(c, dict)]
    for c in concepts:
        cid, kind = str(c.get("id") or ""), c.get("kind")
        slug = re.sub(r"[^a-z0-9-]+", "-", (cid.partition(":")[2] or cid).lower()).strip("-")
        if kind in CONCEPT_KINDS and slug and cid != f"{kind}:{slug}":
            c["id"] = f"{kind}:{slug}"
    fams = {c["id"] for c in concepts if c.get("kind") == "method-family"}
    for c in concepts:
        fam = c.get("family")
        if fam and fam not in fams:
            alt = "method-family:" + str(fam).partition(":")[2 if ":" in str(fam) else 0].strip()
            if alt in fams:
                c["family"] = alt
            else:
                c.pop("family")
        if "quantity" in c and c.get("kind") != "measure":
            c.pop("quantity")
    v["concepts"] = concepts
    return v


def _cmd_set(a):
    rd = Path(a.research_dir)
    vocab = normal_vocab(read_json(Path(a.vocab_json)))
    recs = evidence_records(rd)
    vocab, gone = drop_withdrawn(vocab, set(recs))
    if gone:
        print(f"align-set: {gone} per-paper entr(y/ies) of papers no longer among the records dropped "
              "(overrides, set-aside words, equivalence papers)")
    fs = vocab_problems(vocab, occurrences(recs))
    _print(fs)
    if errors(fs):
        print("align-set: NOT written")
        raise SystemExit(1)
    al = load_alignment(rd)
    hist = list(al.get("history") or [])
    if al.get("vocab"):
        hist.append({"at": now_iso(), "unit": "A7.A1", "reason": a.reason or "vocabulary revised",
                     "previous": sha256_json(al["vocab"])})
    al.update(schema=SCHEMA, vocab=vocab, vocab_basis=basis_of(recs), vocab_at=now_iso(), history=hist)
    write_json(alignment_path(rd), al)
    write_projection(rd)
    print(f"align-set: {len(vocab.get('concepts') or [])} concept(s), {sum(len(v) for v in (vocab.get('overrides') or {}).values())} "
          f"override(s), {len(vocab.get('unaligned') or [])} unaligned -> knowledge/alignment.json; "
          "knowledge/methods_matrix_input.json rewritten")


COORD_CHOICE = (UNSTATED, NOT_APPLICABLE)


def coord_batches(rd, max_chars: int = 0, size: int = 40) -> list[dict]:
    """The units still without coordinates, for a worker that is given its batch in the prompt: per unit its one-line
    text, the axes the tool could not settle (`ask`, each with the concepts the tool suggests, or every concept of that
    axis's kind when it suggests none) and the axes it did settle (`fixed`). The tool suggests, the model places."""
    recs, al = evidence_records(rd), load_alignment(rd)
    V = Vocab(al.get("vocab") or {})
    sug = suggest(rd, recs, V)
    coords = al.get("coords") or {}
    of_kind = {ax: sorted(c for c in V.concepts if V.kind(c) == k) for ax, k in AXES.items()}
    items = []
    for uid, s_ in sorted(sug.items()):
        if uid in coords:
            continue
        c = s_["candidates"]
        ask = {ax: c[ax] for ax in s_["ambiguous"]}
        if not (c["construct"] or c["measure"]):               # nothing to collide on yet: the model places it
            ask.update({ax: ["*"] for ax in ("construct", "measure")})      # "*": any concept of the axis's kind
        if not ask:                                            # nothing for the model: --auto places it
            continue
        fixed = {ax: (v[0] if v else UNSTATED) for ax, v in c.items() if ax not in ask}
        items.append({"id": uid, "kind": s_["kind"], "text": re.sub(r"\s+", " ", str(s_["text"]))[:240], "ask": ask,
                      "fixed": fixed})
    out, cur, used = [], [], 0
    for it in items:
        n = len(json.dumps(it, ensure_ascii=False))
        if cur and (len(cur) >= size or (max_chars and used + n > max_chars)):
            out.append(cur)
            cur, used = [], 0
        cur.append(it)
        used += n
    return out + ([cur] if cur else [])


def coord_choices(rd) -> dict:
    """Every construct and measure concept, once per batch (`"*"` in a unit's `ask` means any of them)."""
    V = Vocab(load_alignment(rd).get("vocab") or {})
    return {ax: [f"{c} - {V.concepts[c].get('name')}" for c in sorted(V.concepts) if V.kind(c) == AXES[ax]]
            for ax in ("construct", "measure")}


def coord_schema(units: list[dict], choices: dict | None = None) -> dict:
    props = {}
    for u in units:
        ax = {a: {"type": "array", "minItems": 1, "maxItems": 4, "items": {"enum": (
            [x.split(" - ")[0] for x in (choices or {}).get(a, [])] if opts == ["*"] else list(opts)) + list(COORD_CHOICE)}}
              for a, opts in u["ask"].items()}
        props[u["id"]] = {"type": "object", "properties": ax, "required": list(ax), "additionalProperties": False}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def cmd_coords(a):
    rd = Path(a.research_dir)
    if getattr(a, "batches", False):                # a worklist only: no Unit boundary
        wd = _work(rd)
        for old in [*wd.glob("coord_batch_*.json"), *(wd / "schemas").glob("coord_batch_*.json")]:
            old.unlink()
        ch = coord_choices(rd)
        bs = coord_batches(rd, max(0, (getattr(a, "max_chars", 0) or 0) - len(json.dumps(ch, ensure_ascii=False))))
        for i, units in enumerate(bs, 1):
            star = any(v == ["*"] for u in units for v in u["ask"].values())
            write_json(wd / f"coord_batch_{i:03d}.json", {"batch": i, "units": units, **({"choices": ch} if star else {}),
                                                           "answer": f"{WORK}/coord_answers/coord_batch_{i:03d}.json"})
            write_json(wd / "schemas" / f"coord_batch_{i:03d}.json", coord_schema(units, ch))
        print(f"align-coords --batches: {sum(len(b) for b in bs)} unit(s) to place in {len(bs)} batch(es) -> {WORK}/")
        return
    if a.suggest or not (a.auto or a.apply or getattr(a, "apply_answers", False)):
        return _cmd_coords(a)
    from it_ledger import run_unit
    with run_unit(rd, "A7.A2", check=lambda: run_checks(rd, "A7.A2")):
        _cmd_coords(a)


def _cmd_coords(a):
    rd = Path(a.research_dir)
    recs = evidence_records(rd)
    al = load_alignment(rd)
    if not al.get("vocab"):
        die("no vocabulary yet: align-terms, align-set", 2)
    V = Vocab(al["vocab"])
    sug = suggest(rd, recs, V) if (a.suggest or a.auto) else {}    # --apply alone needs no suggestions
    if a.suggest:
        write_json(_work(rd) / "coords_suggest.json", sug)
        amb = sum(1 for s in sug.values() if s["ambiguous"])
        print(f"align-coords: {len(sug)} unit(s); {amb} with an ambiguous axis -> {WORK}/coords_suggest.json")
        return
    coords = dict(al.get("coords") or {})
    if a.auto:
        n = 0
        for uid, s in sug.items():
            c = s["candidates"]
            if s["ambiguous"] or uid in coords or not (c["construct"] or c["measure"]):
                continue                     # nothing to collide on yet: the model places it
            coords[uid] = {"axes": {ax: (c[0] if c else UNSTATED) for ax, c in s["candidates"].items()}, "by": "auto",
                           "from": s["from"]}
            n += 1
        print(f"align-coords --auto: {n} unit(s) set from unambiguous suggestions; "
              f"{sum(1 for u in sug if u not in coords)} left for --apply")
    if a.apply:
        ans = read_json(Path(a.apply))
        for uid, c in ans.items():
            coords[uid] = {"axes": c.get("axes", c), "by": "model", "note": c.get("note")} if isinstance(c, dict) else c
        print(f"align-coords --apply: {len(ans)} unit(s) from {a.apply}")
    if getattr(a, "apply_answers", False):          # the batches' answers: the asked axes, joined to the fixed ones
        ans, n = {}, 0
        Vk = Vocab(al["vocab"])
        ok = lambda ax, x: x in COORD_CHOICE or Vk.kind(x) == AXES[ax]     # noqa: E731 - else: placed next pass
        for bf in sorted(_work(rd).glob("coord_batch_*.json")):
            b = read_json(bf)
            af = rd / b["answer"]
            got = read_json(af) if af.exists() else {}
            for u in b["units"]:
                g = got.get(u["id"])
                if not isinstance(g, dict) or not all(ok(ax, x) for ax in u["ask"] for x in (g.get(ax) or [])):
                    continue
                axes = dict(u["fixed"])
                for ax in u["ask"]:
                    v = [x for x in (g.get(ax) or []) if x] or [UNSTATED]
                    v = list(dict.fromkeys(v))
                    axes[ax] = v[0] if len(v) == 1 else [x for x in v if x not in COORD_CHOICE] or v[0]
                coords[u["id"]] = {"axes": axes, "by": "model"}
                ans[u["id"]] = True
                n += 1
        print(f"align-coords --apply-answers: {n} unit(s) placed from the batch answers")
    shas = unit_shas(recs)
    gone = [u for u in coords if u not in shas]
    if gone:                                     # units of records withdrawn from the shortlist (F1) leave with them
        coords = {u: c for u, c in coords.items() if u in shas}
        print(f"align-coords: {len(gone)} coordinate(s) of units no longer in any record dropped")
    placed = (set(ans) if (a.apply or getattr(a, "apply_answers", False)) else set()) | \
        {u for u, c in coords.items() if c.get("by") == "auto" and not c.get("unit_sha")}
    legacy = [u for u, c in coords.items() if not c.get("unit_sha") and u not in placed]
    for uid in placed & set(shas):
        coords[uid] = {**coords[uid], "unit_sha": shas[uid]}
    if legacy:                                   # coordinates set before per-unit fingerprints: stamped now, as they stand
        for uid in legacy:
            if uid in shas:
                coords[uid] = {**coords[uid], "unit_sha": shas[uid]}
        print(f"align-coords: {len(legacy)} coordinate(s) set before per-unit fingerprints were stamped as they stand; "
              "a unit changed before this run and not re-placed in it is not re-checked")
    trial = {**al, "coords": coords}
    fs = [f for f in coords_problems(trial, recs) if f["code"] != "A09" or "without coordinates" not in f["msg"]]
    _print(fs)
    if errors(fs):
        print("align-coords: NOT written")
        raise SystemExit(1)
    al.update(coords=coords, coords_basis=units_basis(recs), coords_at=now_iso())
    write_json(alignment_path(rd), al)


def point_batches(cands: list[dict], recs: dict, max_chars: int = 0, size: int = 15,
                  defs: dict | None = None) -> list[list[dict]]:
    """The candidates for a worker that is given its batch in the prompt: each with its vocabulary definition, its
    papers and up to 12 of its units as one line of text - what the card fields are written from (a worker with tools
    looks them up)."""
    text = {u["id"]: u.get("text") for r in recs.values() for u in r.get("units") or []}
    items = [{**{k: c[k] for k in ("concept", "name", "kind")}, "definition": (defs or {}).get(c["concept"]) or "",
              "papers": c["papers"][:20], "n_papers": len(c["papers"]),
              "units": [{"id": u, "text": re.sub(r"\s+", " ", str(text.get(u) or ""))[:160]} for u in c["units"][:12]]}
             for c in cands]
    out, cur, used = [], [], 0
    for it in items:
        n = len(json.dumps(it, ensure_ascii=False))
        if cur and (len(cur) >= size or (max_chars and used + n > max_chars)):
            out.append(cur)
            cur, used = [], 0
        cur.append(it)
        used += n
    return out + ([cur] if cur else [])


POINT_TEXT = ("description", "purpose", "core_claim", "expanded", "method", "findings")   # knowledge-templates.md
CLAIM_TYPES = ["theoretical", "empirical", "methodological", "conceptual"]


def point_schema(items: list[dict]) -> dict:
    """Per candidate: does the topic turn on it (keep), and the card's text - the rest of the Point is code's."""
    s = {"type": "string", "maxLength": 1200}                  # bounded, as in vocab_schema
    p = {"keep": {"type": "boolean"}, "claim_type": {"enum": CLAIM_TYPES}, **{f: s for f in POINT_TEXT}}
    one = {"type": "object", "properties": p, "required": list(p), "additionalProperties": False}
    props = {it["concept"]: one for it in items}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def points_from_answers(rd) -> list[dict]:
    """The Points the batch answers keep (origin align). The model gave the decision and the text; the structure is
    the candidate's: slug and name from the concept, `source` the earliest of its papers, `also_in` the others,
    `unit_refs` the units shown, `source_files` the papers' records. A field left empty is (TBD), never filled in."""
    sl = Path(rd) / "step3_shortlist.json"
    years = {p.get("citation_key"): p.get("year") for p in (read_json(sl).get("papers") or [])} if sl.exists() else {}
    pts, slugs = [], set()
    for bf in sorted(_work(rd).glob("point_batch_*.json")):
        b = read_json(bf)
        af = Path(rd) / b["answer"]
        ans = read_json(af) if af.exists() else {}
        for c in b["candidates"]:
            a = ans.get(c["concept"])
            if not isinstance(a, dict) or a.get("keep") is not True:
                continue
            papers = sorted(c["papers"], key=lambda k: (years.get(k) or 9999, k))
            # the archived style: Subject_Identity_In_EEG_Representations (an acronym keeps its capitals)
            slug = "_".join(w[0].upper() + w[1:] for w in re.split(r"[^A-Za-z0-9]+", c["name"]) if w) or _slug(c["concept"])
            slug = slug if slug not in slugs else f"{slug}_{c['kind'].title()}"
            slugs.add(slug)
            pts.append({"slug": slug, "name": c["name"], "origin": "align", "concept": c["concept"],
                        "claim_type": a.get("claim_type") if a.get("claim_type") in CLAIM_TYPES else "methodological",
                        "source": papers[0], "year": years.get(papers[0]), "also_in": papers[1:],
                        "unit_refs": [u["id"] for u in c["units"]],
                        **{f: str(a.get(f) or "").strip() or "(TBD)" for f in POINT_TEXT},
                        "tags": [], "domain": [], "field": [],
                        "source_files": [f"knowledge/decon/{k}.json" for k in papers]})
    return pts


def cmd_points(a):
    rd = Path(a.research_dir)
    if getattr(a, "merge_answers", False):
        pts = points_from_answers(rd)
        write_json(_work(rd) / "points_part.json", {"points": pts})
        print(f"align-points --merge-answers: {len(pts)} Point(s) kept -> {WORK}/points_part.json")
        return
    al = load_alignment(rd)
    recs = evidence_records(rd)
    cands = point_candidates(al, recs)
    write_json(_work(rd) / "point_candidates.json", cands)
    if getattr(a, "batches", False):
        wd = _work(rd)
        for old in [*wd.glob("point_batch_*.json"), *(wd / "point_answers").glob("point_batch_*.json"),
                    *(wd / "schemas").glob("point_batch_*.json")]:
            old.unlink()
        defs = {c.get("id"): c.get("definition") for c in (al.get("vocab") or {}).get("concepts") or []}
        bs = point_batches(cands, recs, getattr(a, "max_chars", 0) or 0, defs=defs)
        for i, b in enumerate(bs, 1):
            write_json(wd / f"point_batch_{i:03d}.json", {"batch": i, "candidates": b,
                                                          "answer": f"{WORK}/point_answers/point_batch_{i:03d}.json"})
            write_json(wd / "schemas" / f"point_batch_{i:03d}.json", point_schema(b))
        print(f"align-points --batches: {len(cands)} candidate(s) in {len(bs)} batch(es) -> {WORK}/point_batch_*.json")
    print(f"align-points: {len(cands)} concept(s) reached by >= 2 papers -> {WORK}/point_candidates.json")
    for c in cands:
        print(f"  {len(c['papers']):>3} papers  {c['concept']}")


def cmd_lens(a):
    from it_ledger import degraded_codes, run_unit
    rd = Path(a.research_dir)
    with run_unit(rd, "B1", check=lambda: run_checks(rd, "B1"), degraded=lambda: degraded_codes(rd, "B1")):
        _cmd_lens(a)


def lens_need(rd, al: dict, recs: dict) -> tuple[list[str], list[str], dict]:
    """(method families, datasets) the lens must judge - lens_problems' T03 - and the papers using each concept."""
    V = Vocab(al.get("vocab") or {})
    used = defaultdict(set)
    for o in occurrences(recs):
        cid = V.resolve(o["paper"], o["string"])
        if cid:
            used[cid].add(o["paper"])
    fams = sorted(c for c in V.concepts if V.kind(c) == "method-family")
    data = sorted(c for c in V.concepts if V.kind(c) == "dataset" and len(used[c]) >= 2
                  and not V.concepts[c].get("not_shared"))
    return fams, data, used


def cmd_lens_brief(a):
    """B1 for a worker that cannot open files: the persona's inputs, what is on this machine (step0's probe) and the
    concepts that need a verdict - one line each - and the answer's schema (one verdict per concept)."""
    rd = Path(a.research_dir)
    cfg = read_json(Path(rd) / "step0_session_config.json")
    probe = (cfg.get("local_environment") or {}).get("probe") or {}
    al, recs = load_alignment(rd), evidence_records(rd)
    V = Vocab(al.get("vocab") or {})
    fams, data, used = lens_need(rd, al, recs)
    one = lambda c: f"- {c} · {V.concepts[c].get('name')} · {len(used[c])} paper(s) · " \
                    f"{str(V.concepts[c].get('definition') or '')[:140]}"                       # noqa: E731
    roots = probe.get("data_roots") or {}
    L = ["# B1 lens brief - who is looking, what this machine holds, and the concepts to judge", "",
         f"Topic: {cfg.get('topic')}", f"Expert domain (A1.v): {cfg.get('expert_domain') or '(TBD)'}",
         f"Target venues (A1.v): {', '.join(cfg.get('target_venues') or []) or '(TBD)'}", "",
         "## This machine (env-probe)", f"interpreter: {probe.get('interpreter')}",
         "packages: " + ", ".join(f"{k} {v}" if v else f"{k} MISSING" for k, v in (probe.get("packages") or {}).items()),
         "data roots: " + ("; ".join(f"{r}: {', '.join(map(str, kids[:12]))}" for r, kids in roots.items()) or "none found"),
         "", f"## Method families ({len(fams)}): affordable here? yes / partial / no, and why",
         "yes: the compute suffices and its packages import · partial: the compute suffices but a MISSING package must "
         "be installed first (pip / conda), or only part fits · no: it needs what installing cannot give (a GPU for its "
         "scale, a sensor, data nobody can get) - a missing package alone is never no"] + [one(c) for c in fams] + \
        ["", f"## Datasets used by >= 2 papers ({len(data)}): on disk? yes (name `where`: a path under a data root "
             "above) / obtainable / no, and why",
         "obtainable: not here, but public (a download, a request form) or of a kind anyone can make or download "
         "(simulated data, a public recording of that kind) - name the source · no: only its authors hold it - no data "
         "root here is a reason for not yes, never for no"] + [one(c) for c in data]
    s_ = {"type": "string"}
    fam_v = {"type": "object", "properties": {"affordable": {"enum": list(VERDICT_AFFORD)}, "why": s_},
             "required": ["affordable", "why"], "additionalProperties": False}
    dat_v = {"type": "object", "properties": {"on_disk": {"enum": list(VERDICT_ON_DISK)}, "where": s_, "why": s_},
             "required": ["on_disk", "where", "why"], "additionalProperties": False}
    schema = {"type": "object", "additionalProperties": False, "required": ["persona", "on_coords"], "properties": {
        "persona": {"type": "object", "properties": {k: s_ for k in ("expert_domain", "compute", "scope")} |
                    {"target_venues": {"type": "array", "items": s_, "minItems": 1}},
                    "required": list(PERSONA_KEYS), "additionalProperties": False},
        "on_coords": {"type": "object", "additionalProperties": False, "required": fams + data,
                      "properties": {**{c: fam_v for c in fams}, **{c: dat_v for c in data}}}}}
    wd = _work(rd).parent / "B1"
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "brief.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    write_json(wd / "lens.schema.json", schema)
    print(f"lens-brief: {len(fams)} method famil(y/ies), {len(data)} dataset(s) to judge -> knowledge/_work/B1/brief.md")


def _normal_lens(ans: dict, cfg: dict) -> dict:
    """What code settles in a lens answer: an empty `where` is no `where`; persona keys the answer leaves empty take
    A1.v's values (step0)."""
    ans = dict(ans)
    on = {}
    for c, v in (ans.get("on_coords") or {}).items():
        on[c] = {k: x for k, x in (v or {}).items() if not (k == "where" and not str(x or "").strip())}
    ans["on_coords"] = on
    per = dict(ans.get("persona") or {})
    for k in ("expert_domain", "target_venues"):
        if not per.get(k) and cfg.get(k):
            per[k] = cfg[k]
    ans["persona"] = per
    return ans


def _cmd_lens(a):
    rd = Path(a.research_dir)
    ans = _normal_lens(read_json(Path(a.lens_json)), read_json(Path(rd) / "step0_session_config.json"))
    cfg = read_json(Path(rd) / "step0_session_config.json")
    probe = (cfg.get("local_environment") or {}).get("probe")
    if not probe:
        die("no env-probe in step0: run `ideate_tools.py env-probe <RD> --write` first", 2)
    lens = {"schema": LENS_SCHEMA, "persona": ans.get("persona") or {}, "local": probe,
            "on_coords": ans.get("on_coords") or {}, "own_data": ans.get("own_data") or [], "at": now_iso(),
            "frozen_inputs": {"alignment": sha256_json(load_alignment(rd).get("vocab") or {})}}
    fs = lens_problems(rd, load_alignment(rd), evidence_records(rd), lens)
    _print(fs)
    if errors(fs):
        print("lens-set: NOT written")
        raise SystemExit(1)
    old = read_json(lens_path(rd)) if lens_path(rd).exists() else None
    same = lambda d: {k: v for k, v in (d or {}).items() if k not in ("at", "history")}
    if old and same(old) == json.loads(json.dumps(same(lens))):
        print("lens-set: unchanged - lens.json kept (the Units downstream stay current)")
        return
    hist = (old or {}).get("history", []) + ([{"at": now_iso(), "reason": a.reason or "lens revised",
                                                "previous": sha256_json({k: v for k, v in old.items() if k != "history"})}]
                                              if old else [])
    write_json(lens_path(rd), {**lens, "history": hist})
    write_projection(rd)
    print(f"lens-set: lens.json written ({len(lens['on_coords'])} verdict(s)); methods_matrix_input.json rewritten")


def _print(fs, as_json=False):
    if as_json:
        print(json.dumps(fs, indent=2, ensure_ascii=False))
        return
    for f in fs:
        print(f"  {f['level']:<5} {f['code']} [{f['unit']}] {f['msg']}")


def cmd_check(a):
    fs = run_checks(Path(a.research_dir), a.unit)
    _print(fs, a.json)
    if not a.json:
        print("OK" if not errors(fs) else f"{len(errors(fs))} error(s)")
    raise SystemExit(1 if errors(fs) else 0)


def add_parsers(sub) -> None:
    sp = sub.add_parser("lens-brief", help="B1: the brief and answer schema for a worker that cannot open files")
    sp.add_argument("research_dir")
    sp.set_defaults(fn=cmd_lens_brief)
    sp = sub.add_parser("align-terms", help="A7.A1: the worklist of every word the decon records use")
    sp.add_argument("research_dir")
    sp.add_argument("--batches", action="store_true", help="the words on no concept yet, in batches (with a schema)")
    sp.add_argument("--merge-answers", action="store_true", help="the batch answers into the draft vocabulary")
    sp.add_argument("--max-chars", type=int, default=0, help="--batches: at most this many characters per batch")
    sp.set_defaults(fn=cmd_terms)
    sp = sub.add_parser("align-set", help="A7.A1: validate and write the vocabulary; project methods_matrix_input.json")
    sp.add_argument("research_dir")
    sp.add_argument("vocab_json")
    sp.add_argument("--reason", help="why a vocabulary that exists is revised (e.g. an incommensurable collision)")
    sp.set_defaults(fn=cmd_set)
    sp = sub.add_parser("align-coords", help="A7.A2: coordinates of every claim and assumption")
    sp.add_argument("research_dir")
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--suggest", action="store_true", help="write the tool's suggestions; nothing is set")
    g.add_argument("--auto", action="store_true", help="set every unambiguous suggestion (by: auto)")
    g.add_argument("--apply", metavar="FILE", help="set the model's coordinates {unit id: {axes: {...}, note}}")
    g.add_argument("--batches", action="store_true", help="the units --auto left, in batches that ask only their "
                   "ambiguous axes (a worker given its batch in the prompt); nothing is set")
    g.add_argument("--apply-answers", action="store_true", help="set the coordinates from every batch answer")
    sp.add_argument("--max-chars", type=int, default=0, help="--batches: at most this many characters per batch")
    sp.set_defaults(fn=cmd_coords)
    sp = sub.add_parser("align-points", help="A7.A3: concepts reached by >= 2 papers (Point candidates)")
    sp.add_argument("research_dir")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--batches", action="store_true", help="also the candidates in batches with their units' text")
    g.add_argument("--merge-answers", action="store_true", help="the Points the batch answers keep -> points_part.json")
    sp.add_argument("--max-chars", type=int, default=0, help="--batches: at most this many characters per batch")
    sp.set_defaults(fn=cmd_points)
    sp = sub.add_parser("lens-set", help="B1: the lens (persona + this machine on the concepts) -> lens.json")
    sp.add_argument("research_dir")
    sp.add_argument("lens_json")
    sp.add_argument("--reason", help="why an existing lens is replaced (a new probe, a dataset downloaded)")
    sp.set_defaults(fn=cmd_lens)
    sp = sub.add_parser("align-check", help="alignment and lens checks (A01-A13, T01-T05)")
    sp.add_argument("research_dir")
    sp.add_argument("--unit", default="all", choices=["all", "A7.A1", "A7.A2", "A7.A3", "B1"])
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_check)
