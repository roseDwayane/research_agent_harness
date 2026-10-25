"""A person's interventions in the literature search: <RD>/_human/search_overrides.json (rules:
references/search/README.md#intervening). The flow never stops to ask; a person drops an entry here, and the Unit that
owns the decision applies it the next time it runs - recorded in the ledger, its downstream Units then stale.

  {"entries": [
    {"kind": "include",    "id": "paper_123", "reason": "...", "by": "<who>"},   # A3 screen-build: a person's inclusion
    {"kind": "exclude",    "id": "paper_045", "reason": "...", "by": "<who>"},   # A3 screen-build: a person's exclusion
    {"kind": "reread",     "id": "paper_210", "reason": "...", "by": "<who>"},   # A3 screen-plan: a blind second reading
    {"kind": "seed",       "id": "paper_007", "action": "add" | "remove", "reason": "..."},   # A5 forward seeds
    {"kind": "known_item", "title": "...", "doi": "10.x/y", "reason": "..."}]}           # A2.c: must be found

A person's include / exclude is final (a person is the reviewer): the shortlist marks it `decided_by: human` and the
PRISMA counts list it apart. A retraction (X-RET) cannot be included.
"""

from __future__ import annotations

from pathlib import Path

from it_common import read_json

PATH = "_human/search_overrides.json"
KINDS = {"include": "A3", "exclude": "A3", "reread": "A3", "seed": "A5", "known_item": "A2.c"}


def F(level, code, unit, msg):
    return {"level": level, "code": code, "unit": unit, "msg": msg}


def entries(rd: Path, kind: str | None = None) -> list[dict]:
    p = Path(rd) / PATH
    if not p.exists():
        return []
    es = read_json(p).get("entries") or []
    return [e for e in es if kind is None or e.get("kind") == kind]


def check(rd: Path, papers: dict | None = None, gate: dict | None = None) -> list[dict]:
    """O01 an entry that cannot be applied as written; O02 one that names a paper the collection does not hold."""
    fs = []
    for i, e in enumerate(entries(rd)):
        k = e.get("kind")
        if k not in KINDS:
            fs.append(F("ERROR", "O01", "A3", f"override {i}: kind {k!r} is not one of {sorted(KINDS)}"))
            continue
        if not str(e.get("reason", "")).strip():
            fs.append(F("ERROR", "O01", KINDS[k], f"override {i} ({k}): every override needs a reason"))
        if k == "known_item" and not (e.get("title") or e.get("doi")):
            fs.append(F("ERROR", "O01", "A2.c", f"override {i}: a known item needs a title or a DOI"))
        if k == "seed" and e.get("action") not in ("add", "remove"):
            fs.append(F("ERROR", "O01", "A5", f"override {i}: a seed override's action is add or remove"))
        if k != "known_item" and papers is not None and e.get("id") not in papers:
            fs.append(F("ERROR", "O02", KINDS[k], f"override {i} ({k}): {e.get('id')!r} is not a candidate of this collection"))
        if k == "include" and gate and (gate.get(e.get("id")) or {}).get("code") == "X-RET":
            fs.append(F("ERROR", "O02", "A3", f"override {i}: {e.get('id')} is retracted and cannot be included"))
    return fs
