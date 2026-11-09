#!/usr/bin/env python3
"""The evidence a Step 6 review (new fusion-block architecture) may cite, loaded from the research folder.

In the new architecture `step6_sota_review.md` (B2) does not cite `(AuthorYear)` keys. It cites ids:

    X0019                         a collision            knowledge/collisions.jsonl
    galt2019#E1, galt2019#C2      an experiment / a unit knowledge/decon/{key}.json
    P_draft_Alpha_Band_Power      a Point                knowledge_cards.json["points"]
    D_/E_/A_draft_...             a Line                 knowledge/lines/*.md
    F_draft_T1_...                a Plane                knowledge/planes/*.md
    galt2019                      a bare paper key       step4_references.bib (Paper–theme mapping only)

`load_world` reads all of that once; check_step6_contract.py and check_numeric_claims.py both use it, so the two checks
agree on what is legal and on which papers an id stands for.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from step6_common import BIB_KEY_RE, split_frontmatter

COLLISION_RE = re.compile(r"(?<![A-Za-z0-9_])X\d{4}(?![A-Za-z0-9_])")
CARD_RE = re.compile(r"(?<![A-Za-z0-9_])[PDEAFB]_draft_[A-Za-z0-9_]*[A-Za-z0-9]")
UNIT_RE = re.compile(r"(?<![A-Za-z0-9_#])([a-z][a-z0-9]*)#([A-Z]\d+)(?![A-Za-z0-9_])")
TBD = "(TBD)"

DEBATE_RESULTS = {"conflict", "boundary"}
FINDING_RESULTS = {"agree", "boundary"}


@dataclass
class World:
    rd: Path
    bib_keys: set[str] = field(default_factory=set)
    planes: list[dict] = field(default_factory=list)           # knowledge_cards.json["planes"]
    methodology: dict[str, str] = field(default_factory=dict)  # paper key -> class
    points: dict[str, dict] = field(default_factory=dict)      # P_draft_x -> card
    lines: dict[str, dict] = field(default_factory=dict)       # line id -> {"fm": {...}, "papers": [...]}
    plane_ids: set[str] = field(default_factory=set)
    collisions: dict[str, dict] = field(default_factory=dict)  # X0001 -> row
    decon: dict[str, dict] = field(default_factory=dict)       # paper key -> decon record
    units: dict[str, str] = field(default_factory=dict)        # unit id (also exp id) -> paper key
    exps: dict[str, dict] = field(default_factory=dict)        # exp id -> experiment
    fulltext: dict[str, str] = field(default_factory=dict)     # paper key -> full text (step5_full_text/{key}.md)
    abstracts: dict[str, str] = field(default_factory=dict)    # paper key -> abstract (step2 raw / snowball records)

    # ---- what an id stands for -------------------------------------------------------------------------------
    def kind(self, ident: str) -> str | None:
        if ident in self.collisions:
            return "collision"
        if ident in self.units:
            return "exp" if ident in self.exps else "unit"
        if ident in self.points:
            return "point"
        if ident in self.lines:
            return "line"
        if ident in self.plane_ids:
            return "plane"
        if ident in self.bib_keys:
            return "paper"
        return None

    def papers_of(self, ident: str) -> set[str]:
        """The papers an id rests on (the sources a number cited with it may be found in)."""
        kind = self.kind(ident)
        if kind in ("exp", "unit"):
            return {self.units[ident]}
        if kind == "paper":
            return {ident}
        if kind == "collision":
            return {s.get("paper") for s in self.collisions[ident].get("sides") or [] if s.get("paper")}
        if kind == "point":
            p = self.points[ident]
            return {x for x in [p.get("source"), *(p.get("also_in") or [])] if x}
        if kind == "line":
            return set(self.lines[ident]["papers"])
        if kind == "plane":
            for pl in self.planes:
                if f"F_draft_T{pl['n']}_{pl['slug']}" == ident or ident.startswith(f"F_draft_T{pl['n']}_"):
                    return set(pl.get("member_papers") or [])
        return set()

    def paper_basis(self, key: str) -> str:
        """'full-text' when the decon record was read from a full text, else 'abstract'."""
        return "full-text" if (self.decon.get(key) or {}).get("basis") == "full-text" else "abstract"

    def evidence_papers(self) -> set[str]:
        return {p for pl in self.planes for p in pl.get("member_papers") or []}


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def ids_in(text: str, world: World | None = None) -> list[tuple[str, str]]:
    """(id, form) for every id in text: collisions, cards, unit ids and (when `world` is given) bare paper keys."""
    found: list[tuple[str, str]] = []
    found += [(m.group(0), "collision") for m in COLLISION_RE.finditer(text)]
    found += [(m.group(0), "card") for m in CARD_RE.finditer(text)]
    found += [(m.group(0), "unit") for m in UNIT_RE.finditer(text)]
    if world and world.bib_keys:
        masked = UNIT_RE.sub(" ", text)
        for m in re.finditer(r"(?<![A-Za-z0-9_#])([a-z][a-z0-9]*)(?![A-Za-z0-9_#])", masked):
            if m.group(1) in world.bib_keys:
                found.append((m.group(1), "paper"))
    return found


def strip_ids(text: str) -> str:
    """Remove ids so the digits inside them (X0019, galt2019#E1) never count as claim numbers."""
    text = UNIT_RE.sub(" ", text)
    text = CARD_RE.sub(" ", text)
    return COLLISION_RE.sub(" ", text)


def load_world(rd: Path) -> World:
    rd = Path(rd).resolve()
    w = World(rd=rd)
    bib = rd / "step4_references.bib"
    if bib.exists():
        w.bib_keys = set(BIB_KEY_RE.findall(bib.read_text(encoding="utf-8")))

    cards = _read_json(rd / "knowledge_cards.json", {})
    w.planes = cards.get("planes") or []
    w.methodology = cards.get("methodology") or {}
    for p in cards.get("points") or []:
        w.points[f"P_draft_{p['slug']}"] = p

    for path in sorted((rd / "knowledge" / "lines").glob("*.md")):
        if path.name == "frontmatter_patches.md":
            continue
        fm, _, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        papers = set(re.findall(r"decon/([A-Za-z0-9]+)\.json", fm.get("provenance", "")))
        w.lines[fm.get("id") or path.stem] = {"fm": fm, "papers": sorted(papers), "file": path.name}
    for path in sorted((rd / "knowledge" / "planes").glob("*.md")):
        w.plane_ids.add(path.stem)

    cp = rd / "knowledge" / "collisions.jsonl"
    if cp.exists():
        for line in cp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                w.collisions[row["collision_id"]] = row

    for path in sorted((rd / "knowledge" / "decon").glob("*.json")):
        rec = _read_json(path, None)
        if not rec:
            continue
        key = rec.get("citation_key") or path.stem
        w.decon[key] = rec
        for u in rec.get("units") or []:
            w.units[u["id"]] = key
        for e in rec.get("experiments") or []:
            w.units[e["exp_id"]] = key
            w.exps[e["exp_id"]] = e

    ft = rd / "step5_full_text"
    for key in w.decon:
        p = ft / f"{key}.md"
        if p.exists():
            w.fulltext[key] = p.read_text(encoding="utf-8")

    # abstracts: step2 raw / snowball records, keyed through step4_citation_keys.jsonl (paper id -> key)
    id2key = {}
    kp = rd / "step4_citation_keys.jsonl"
    if kp.exists():
        for line in kp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("key"):
                    id2key[r.get("id")] = r["key"]
    records = list((_read_json(rd / "step2_raw_papers.json", {}).get("papers") or []))
    records += _read_json(rd / "step2b_snowball_papers.json", {}).get("papers") or []
    for r in records:
        key = id2key.get(r.get("id"))
        if key and r.get("abstract") and key not in w.abstracts:
            w.abstracts[key] = r["abstract"]
    return w
