"""trace - from one item of the literature search back to every Unit that decided something about it.

  ideate_tools.py trace <RD> <paper_id | citation_key | query_id | protocol | X0001 | GAP_001 | Q_001> [--json]

For a paper: which queries and sources found it (A2.s), how it was merged and numbered (A2.m), its bibliometrics
(A3.b), a mechanical exclusion (A3.g), its scores with their quoted evidence, batch and model, a rescue, a person's
decision (A3), its snowball route or its use as a seed (A5), its key and bibliography entry (A4), whether it was a
full-text candidate and every fetch attempt with its reason (A6.d), and its access level (A6.c). For a query: how it
was written (A1.q) and revised (A2.c), its instances and per-source results (A2.s), the verdicts it got (A2.c).

The fusion block (references/fusion/) adds: for a paper, its record (A7.D), where its units were placed (A7.A2), the
collisions it is a side of (A7.X2, B3.c), the Lines, Planes, gaps and questions that cite it; for a collision, its
candidate (A7.X1), judgement, supersessions, and the gaps, Lines and questions built on it; for a gap, its moves and
evidence (B3) and its questions (B3.5, F.9); for a question, its gap, collisions and screens.

Each item ends with where a comment on it goes - the Unit that owns the decision, and the entry to use - and which
Units are downstream of that decision (they go stale, or are re-checked, when it changes).
"""

from __future__ import annotations

import json
from pathlib import Path

from it_common import die, read_json, read_jsonl

ROUTES = {
    "relevance / inclusion": ("A3", "_human/search_overrides.json: include / exclude / reread"),
    "impact, citations, venue": ("A3.b", "data from OpenAlex / Scopus: report a wrong record; `mcp_bridge.py bibliometrics`"),
    "a mechanical exclusion": ("A3.g", "the record's type / language / retraction comes from OpenAlex"),
    "found by / merged with": ("A2.m", "the merge rules are fixed; a wrong merge is a defect to report"),
    "a snowball seed": ("A5", "_human/search_overrides.json: seed add / remove"),
    "the citation key": ("A4.k", "keys never change; a key minted from a wrong author list stays (see step4_citation_keys.md)"),
    "the BibTeX entry": ("A4.b", "Crossref metadata; `mcp_bridge.py bibliography` rebuilds it"),
    "the query's wording": ("A1.q", "before the search: `frame set-strategy`; after: A2.c's `frame query-revise`"),
    "the query's verdict": ("A2.c", "`ideate_tools.py search-check`, then a new round with `relevance-set`"),
    "a known item to find": ("A2.c", "_human/search_overrides.json: known_item"),
    "the frame, axes or criteria": ("A1.p", "`frame set-protocol --note <reason>` (a logged deviation); after the search, "
                                            "a synonym through A2.c's `frame add-terms`, a criterion through A3's `screen-amend`"),
    "the protocol's evaluation": ("A1.e", "`frame eval-brief` for a new round after a revision"),
    "venues, expert domain, environment": ("A1.v", "`frame set-context` (read by Stage B, not by the search)"),
    # full text
    "the full text": ("A6.d", "save the PDF as pdfs/<key>.pdf (the access log's 'Worth fetching by hand'), or "
                              "`mcp_bridge.py download <RD> --retry-failed`; then A6.c"),
    "the conversion": ("A6.c", "delete step5_full_text/<key>.md and run `pdf2md.sh` again, then `fulltext-status`"),
    # the fusion block
    "the paper's record": ("A7.D", "`decon-merge <RD> --revise <reason>` with a corrected answer (B3's source checks "
                                   "queue these in step7_gaps.json revisions_needed)"),
    "a word's concept": ("A7.A1", "`align-set <RD> vocab.json --reason` (an override scoped to term: or row:)"),
    "a unit's coordinates": ("A7.A2", "`align-coords <RD> --apply coords.json`"),
    "the lens": ("B1", "`lens-set <RD> lens.json --reason`"),
    "a missing comparison": ("A7.X1", "the candidate rules are fixed: a pair appears when the vocabulary or the "
                                      "coordinates put both sides on the same place"),
    "the judgement": ("A7.X2", "a new answer through `collide-merge <RD> --revise <reason>` (the log is append-only: "
                               "supersedes); a judgement on a word mismatch is incommensurable -> A7.A1"),
    "a lens judgement": ("B3.c", "`collide-plan <RD> --lens`, then `collide-merge`"),
    "the gap": ("B3", "`gaps-set <RD> gaps.json` (gap ids are never reused)"),
    "a Line or findings Point": ("A7.R1", "knowledge/lines/, knowledge_cards.json; `unit-done <RD> A7.R1`"),
    "a Plane": ("A7.R2", "knowledge_cards.json planes; `unit-done <RD> A7.R2`"),
    "the Body": ("A7.R3", "knowledge/body/<topic>_descriptive.md; `unit-done <RD> A7.R3`"),
    "the synthesis": ("B2", "step6_sota_review.md; `unit-done <RD> B2`"),
    "the question": ("B3.5", "questions/Q_NNN.md (status, screens), `unit-done <RD> B3.5`"),
    "the question index": ("F.9", "`questions-index <RD>` rebuilds it"),
}


def _j(rd: Path, name: str):
    p = Path(rd) / name
    return read_json(p) if p.exists() else None


def dependents(unit: str) -> list[str]:
    """Every Unit downstream of `unit` (through the cards' `requires`), in run order."""
    from it_ledger import BLOCKS, block_of, requires
    order = BLOCKS[block_of(unit)]          # within the block: the fusion block as a whole follows the search
    out, frontier = set(), {unit}
    while frontier:
        nxt = {u for u in order if set(requires(u)) & frontier and u not in out and u != unit}
        out |= nxt
        frontier = nxt
    return [u for u in order if u in out]


def _route(*aspects) -> list[str]:
    lines = []
    for a in aspects:
        unit, how = ROUTES[a]
        stale = dependents(unit)
        lines.append(f"  comment on {a} -> {unit}: {how}" + (f"  (downstream: {', '.join(stale)})" if stale else ""))
    return lines


# ========================================================================================================== papers
def _exclusion(rd: Path, pid: str, entry: dict | None, gate: dict, bibrec: dict, paper: dict) -> str:
    from it_overrides import entries as overrides
    from it_screen import INCLUDE_AT, is_included
    if pid in gate:
        return f"{gate[pid]['code']} ({gate[pid].get('detail')})"
    human = [e for e in overrides(rd) if e.get("id") == pid and e.get("kind") == "exclude"]
    if human:
        return f"HUMAN (by {human[-1].get('by') or 'a person'}: {human[-1].get('reason')})"
    if not entry:
        return "no entry (not scored yet, or cleared by a bulk rule)"
    if "duplicate_of" in entry:
        return f"DUP of {entry['duplicate_of']}"
    if "violates" in entry:
        return f"{'+'.join(entry['violates'])}: {entry.get('rationale')}"
    comp = round(entry["rel"] * 0.5 + entry["qual"] * 0.3 + (bibrec.get("impact") or 3.0) * 0.2, 2)
    if comp >= INCLUDE_AT and not is_included(entry["rel"], comp, paper):
        return f"FLOOR (relevance {entry['rel']} < 3 for a {paper.get('found_via')} paper; composite {comp})"
    return f"SCORE (composite {comp} < {INCLUDE_AT})"


def trace_paper(rd: Path, pid: str) -> dict:
    rd = Path(rd)
    raw = {p["id"]: p for p in (_j(rd, "step2_raw_papers.json") or {}).get("papers") or []}
    sb = _j(rd, "step2b_snowball_papers.json") or {}
    snow = {p["id"]: p for p in sb.get("papers") or []}
    paper = raw.get(pid) or snow.get(pid)
    if paper is None:
        die(f"{pid} is not a candidate of this collection", 2)
    reg = next((e for e in read_jsonl(rd / "_state/paper_ids.jsonl") if e["id"] == pid), {})
    bibrec = ((_j(rd, "step3_bibliometrics.json") or {}).get("papers") or {}).get(pid) or {}
    gate = {e["id"]: e for e in (_j(rd, "step3_gate.json") or {}).get("excluded") or []}
    scores = _j(rd, "screening_scores.json") or {}
    entry = next((e for e in scores.get("scores") or [] if e.get("id") == pid), None)
    superseded = [e for e in scores.get("superseded") or [] if e.get("id") == pid]
    sl = {q["id"]: q for q in (_j(rd, "step3_shortlist.json") or {}).get("papers") or []}
    keylog = [e for e in read_jsonl(rd / "step4_citation_keys.jsonl") if e["id"] == pid]
    bibmeta = (_j(rd, "step4_bib_metadata.json") or {}).get("entries") or {}
    out = {"id": pid, "title": paper.get("title"), "year": paper.get("year"), "steps": []}
    add = lambda unit, text, where: out["steps"].append({"unit": unit, "text": text, "where": where})
    if pid in raw:
        add("A2.s", f"found by {', '.join(paper.get('found_by') or [])} in {', '.join(paper.get('sources_found_in') or [])}",
            "step2_queries/")
        add("A2.m", f"merged {paper.get('merged_from', 1)} record(s); id minted by {reg.get('minted_by', '?')}"
            + (f"; sem_pct {paper.get('sem_pct')}" if paper.get("sem_pct") is not None else "")
            + ("; no anchor term" if paper.get("anchor_match") is False else ""), "step2_raw_papers.json")
    else:
        s = snow[pid]
        ev = {"backward": f"cited by {s.get('cocited_by_included')} included papers",
              "cocitation": f"co-cited {s.get('cocited_with_seeds')} times by two-seed citers",
              "forward": f"cites seeds {', '.join(s.get('cites_seeds') or [])}", "similar": "an embedding neighbour"}
        add("A5", f"snowball round {s.get('round')}: " + "; ".join(ev.get(d, d) for d in s.get("snowball_direction") or []),
            "step2b_snowball_papers.json")
    if bibrec:
        v = bibrec.get("venue") or {}
        add("A3.b", f"impact {bibrec.get('impact')} (normalised citations {bibrec.get('cit_pct')}, cited by "
            f"{bibrec.get('in_degree')} candidates, venue {v.get('name') or '-'}{', SNIP ' + str(v.get('snip')) if v.get('snip') is not None else ''})"
            + ("; no OpenAlex record" if bibrec.get("metadata") == "none" else ""), "step3_bibliometrics.json")
    if pid in gate:
        add("A3.g", f"excluded mechanically: {gate[pid]['code']}", "step3_gate.json")
    for e in superseded:
        add("A3", f"first reading (batch {e.get('batch')}, {e.get('model')}): rel {e.get('rel')} qual {e.get('qual')} — "
            f"{str(e.get('rationale'))[:120]}", "screening_scores.json › superseded")
    if entry:
        evd = entry.get("evidence") or {}
        txt = (f"rel {entry.get('rel')} · qual {entry.get('qual')} — {str(entry.get('rationale'))[:140]}"
               if "rel" in entry else (f"violates {entry.get('violates')}" if "violates" in entry else f"duplicate of {entry.get('duplicate_of')}"))
        add("A3", f"{txt} (batch {entry.get('batch')}, {entry.get('model')})"
            + (f"; evidence problem «{evd.get('problem')}», method «{evd.get('method')}»" if evd else "")
            + (f"; read again on request of {entry['rescue'].get('by') or '-'}: {entry['rescue'].get('reason')}" if entry.get("rescue") else ""),
            "screening_scores.json")
    if pid in sl:
        s = sl[pid]["screening"]
        add("A3", f"INCLUDED · composite {s.get('composite')} · tier {s.get('tier')} · roles {', '.join(sl[pid].get('roles') or [])}"
            + (f" · decided by {s.get('human_by')}: {s.get('human_reason')}" if s.get("decided_by") == "human" else ""),
            "step3_shortlist.json")
    else:
        add("A3", "EXCLUDED · " + _exclusion(rd, pid, entry, gate, bibrec, paper), "step3_screening_results.md")
    for r in sb.get("rounds") or []:
        if pid in (r.get("status", {}).get("forward", {}).get("seeds") or []):
            add("A5", f"forward seed in round {r.get('round')}", "step2b_snowball_papers.json › rounds")
        if pid in (r.get("status", {}).get("similar", {}).get("seeds") or []):
            add("A5", f"similar seed in round {r.get('round')}", "step2b_snowball_papers.json › rounds")
    if keylog:
        from it_ledger import unit_state
        k = keylog[0]
        gone = "" if pid in sl else (" — retired" if unit_state(rd, "A4.k")["state"] == "done"
                                     else " — left the shortlist: retired when A4.k runs again")
        add("A4.k", f"key {k['key']} (authors from {k.get('authors_basis')}, {k.get('n_authors')} author(s))" + gone,
            "step4_citation_keys.jsonl")
        m = bibmeta.get(k["key"])
        if m:
            add("A4.b", f"entry from {m.get('source')}" + (f" ({m['why']})" if m.get("why") else ""), "step4_references.bib")
        from it_fulltext import trace as fulltext_trace
        for unit, text, where in fulltext_trace(rd, k["key"]):       # A6.d: candidate, attempts · A6.c: access level
            if unit in ("A6.d", "A6.c"):
                add(unit, text, where)
    out["comments"] = _route("relevance / inclusion", "impact, citations, venue", "found by / merged with",
                             "a snowball seed", "the citation key", "the BibTeX entry", "the full text", "the conversion")
    if keylog and (rd / "knowledge" / "decon" / f"{keylog[0]['key']}.json").exists():
        fused = trace_paper_fusion(rd, keylog[0]["key"])
        out["steps"] += fused["steps"]
        out["comments"] += fused["comments"]
    return out


# ========================================================================================================== fusion
def _fusion(rd: Path) -> dict:
    from it_collide import current, log
    rd = Path(rd)
    recs = log(rd)
    lines = {}
    for f in sorted((rd / "knowledge" / "lines").glob("*.md")) if (rd / "knowledge" / "lines").is_dir() else []:
        if not f.name.startswith("frontmatter"):           # frontmatter_patches.md is not a Line
            lines[f.stem] = f.read_text(encoding="utf-8")
    return {"log": recs, "current": {r["collision_id"]: r for r in current(recs, keep_duplicates=True)},
            "gaps": _j(rd, "step7_gaps.json") or {}, "index": _j(rd, "questions/index.json") or {},
            "cards": _j(rd, "knowledge_cards.json") or {}, "lines": lines,
            "cands": {c["id"]: c for c in (_j(rd, "knowledge/collision_candidates.json") or {}).get("candidates") or []}}


def _cites(text: str, ids) -> bool:
    import re
    return any(re.search(rf"(?<![\w#]){re.escape(i)}(?![\w])", text) for i in ids)


def trace_paper_fusion(rd: Path, key: str) -> dict:
    """A paper through the fusion block: its record, where its units were placed, every collision it is a side of, and
    the Lines, Planes, gaps and questions that build on it."""
    rd = Path(rd)
    rec = read_json(rd / "knowledge" / "decon" / f"{key}.json")
    out = {"id": key, "title": str((rec.get("summary") or {}).get("problem") or "")[:100], "steps": []}
    add = lambda unit, text, where: out["steps"].append({"unit": unit, "text": text, "where": where})
    kinds = {}
    for u in rec.get("units") or []:
        kinds[u.get("kind")] = kinds.get(u.get("kind"), 0) + 1
    el = rec.get("eligibility") or {}
    add("A7.D", f"read from the {rec.get('basis')} ({rec.get('model')}): " + ", ".join(f"{n} {k}" for k, n in kinds.items())
        + f", {len(rec.get('experiments') or [])} matrix row(s)" + (f"; eligibility {el.get('verdict')}" if el else "")
        + (f"; revised {len(rec.get('history') or [])}x" if rec.get("history") else ""), f"knowledge/decon/{key}.json")
    al = _j(rd, "knowledge/alignment.json") or {}
    mine = {uid: c for uid, c in (al.get("coords") or {}).items() if uid.split("#")[0] == key}
    if mine:
        by = {}
        for c in mine.values():
            by[c.get("by")] = by.get(c.get("by"), 0) + 1
        add("A7.A2", f"{len(mine)} unit(s) placed (" + ", ".join(f"{n} by {b}" for b, n in by.items()) + ")",
            "knowledge/alignment.json › coords")
    ov = [(w, o) for w, scoped in ((al.get("vocab") or {}).get("overrides") or {}).items() for o in [scoped]
          if isinstance(o, dict) and any(key in str(k) for k in o)]
    if ov:
        add("A7.A1", f"vocabulary overrides naming it: {[w for w, _ in ov][:6]}", "knowledge/alignment.json › vocab.overrides")
    F = _fusion(rd)
    from it_collide import LENS_TYPES
    for cid, r in F["current"].items():
        if any(s.get("paper") == key for s in r.get("sides") or []):
            add("B3.c" if r.get("type") in LENS_TYPES else "A7.X2",
                f"{cid} {r['result']} ({r.get('type')}) with {', '.join(s['id'] for s in r['sides'] if s.get('paper') != key) or '-'}"
                + (f" — duplicate of {r['duplicate_of']}" if r.get("duplicate_of") else ""), "knowledge/collisions.jsonl")
    pts = [p.get("slug") for p in F["cards"].get("points") or [] if any(str(u).startswith(key + "#") for u in p.get("unit_refs") or [])]
    if pts:
        add("A7.A3", f"Points from its units: {pts[:8]}", "knowledge_cards.json › points")
    ln = [n for n, t in F["lines"].items() if _cites(t, [key])]
    if ln:
        add("A7.R1", f"Lines citing it: {ln[:8]}", "knowledge/lines/")
    pl = [p.get("slug") for p in F["cards"].get("planes") or [] if key in (p.get("member_papers") or [])]
    if pl:
        add("A7.R2", f"member of Plane(s) {pl}", "knowledge_cards.json › planes")
    bodies = sorted((rd / "knowledge" / "body").glob("*_descriptive.md")) if (rd / "knowledge" / "body").is_dir() else []
    bd = [f.stem for f in bodies if _cites(f.read_text(encoding="utf-8"), [key])]
    if bd:
        add("A7.R3", f"cited in the descriptive Body {bd}", "knowledge/body/")
    sota = rd / "step6_sota_review.md"
    if sota.exists() and _cites(sota.read_text(encoding="utf-8"), [key]):
        add("B2", "cited in the synthesis", "step6_sota_review.md")
    for g in F["gaps"].get("gaps") or []:
        sides = [s.get("key") for s in (g.get("supporting") or []) + (g.get("counter") or [])]
        sc = g.get("source_check") or []
        if key in sides or key in {s.get("key") for s in (sc if isinstance(sc, list) else [sc])}:
            add("B3", f"{g['id']} ({g.get('move')}): {g.get('title')}", "step7_gaps.json")
    out["comments"] = _route("the paper's record", "a word's concept", "a unit's coordinates", "the lens", "the judgement")
    return out


def trace_collision(rd: Path, cid: str) -> dict:
    rd = Path(rd)
    F = _fusion(rd)
    rec = next((r for r in F["log"] if r.get("collision_id") == cid), None)
    if rec is None:
        die(f"{cid} is not in knowledge/collisions.jsonl", 2)
    from it_collide import LENS_TYPES
    unit = "B3.c" if rec.get("type") in LENS_TYPES else "A7.X2"
    out = {"id": cid, "title": rec.get("reason"), "steps": []}
    add = lambda u, text, where: out["steps"].append({"unit": u, "text": text, "where": where})
    c = F["cands"].get(rec.get("candidate"))
    if c:
        add("A7.X1", f"candidate {c['id']} ({c.get('type')}) on «{c.get('key')}»: {len(c.get('members') or [])} member(s)",
            "knowledge/collision_candidates.json")
    elif rec.get("candidate"):
        add("A7.X1", f"candidate {rec['candidate']} is no longer listed (the vocabulary or coordinates changed)",
            "knowledge/collision_candidates.json")
    add(unit, f"{rec['result']} between " + " / ".join(f"{s['id']} «{str(s.get('quote'))[:70]}»" for s in rec.get("sides") or [])
        + (f"; axes differ: {', '.join(rec.get('axes_differ') or [])}" if rec.get("axes_differ") else "")
        + f" ({rec.get('batch')}, {rec.get('model')})", "knowledge/collisions.jsonl")
    if rec.get("vocab_issue"):
        add("A7.A1", f"vocabulary issue raised: {rec['vocab_issue']}", "knowledge/collisions.jsonl")
    for r in F["log"]:
        if cid in (r.get("supersedes") or []) or r.get("supersedes") == cid:
            add(unit, f"superseded by {r['collision_id']} ({r['result']})", "knowledge/collisions.jsonl")
        if cid in (r.get("retires") or []):
            add("A7.X2", f"retired by {r['collision_id']}: {r.get('reason')}", "knowledge/collisions.jsonl")
        if r.get("duplicate_of") == cid:
            add(unit, f"repeated by {r['collision_id']} on candidate {r.get('candidate')}", "knowledge/collisions.jsonl")
    if rec.get("duplicate_of"):
        add(unit, f"a repeat of {rec['duplicate_of']}", "knowledge/collisions.jsonl")
    ln = [n for n, t in F["lines"].items() if _cites(t, [cid])]
    if ln:
        add("A7.R1", f"Lines built on it: {ln}", "knowledge/lines/")
    for g in F["gaps"].get("gaps") or []:
        if cid in (g.get("collisions") or []) + (g.get("consequence_evidence") or []):
            add("B3", f"{g['id']} ({g.get('move')}): {g.get('title')}", "step7_gaps.json")
    for q in F["index"].get("questions") or []:
        if cid in q.get("collisions") or []:
            add("B3.5", f"{q['id']} ({q.get('status')}): {q.get('research_question')}", f"questions/{q['id']}.md")
    out["comments"] = _route("the judgement" if unit == "A7.X2" else "a lens judgement", "a missing comparison", "a word's concept")
    return out


def trace_gap(rd: Path, gid: str) -> dict:
    rd = Path(rd)
    F = _fusion(rd)
    g = next((x for x in F["gaps"].get("gaps") or [] if x.get("id") == gid), None)
    if g is None:
        why = " (retired)" if gid in (F["gaps"].get("retired") or []) else ""
        die(f"{gid} is not a current gap of step7_gaps.json{why}", 2)
    out = {"id": gid, "title": g.get("title"), "steps": []}
    add = lambda u, text, where: out["steps"].append({"unit": u, "text": text, "where": where})
    for cid in g.get("collisions") or []:
        r = F["current"].get(cid) or {}
        add("A7.X2", f"{cid} {r.get('result', '(not current)')}: {str(r.get('reason'))[:140]}", "knowledge/collisions.jsonl")
    ranked = F["gaps"].get("ranked") or []
    add("B3", f"move {g.get('move')} · type {(g.get('type') or {}).get('primary')} · axes {g.get('axes')} · severity "
        f"{g.get('severity')} novelty {g.get('novelty')} feasibility {g.get('feasibility')} (basis {g.get('feasibility_basis')}) · "
        f"composite {(F['gaps'].get('composites') or {}).get(gid)} · rank {ranked.index(gid) + 1 if gid in ranked else '-'}",
        "step7_gaps.json")
    sc = g.get("source_check") or []
    for s in sc if isinstance(sc, list) else [sc]:
        add("B3", f"source check: {s.get('key')} {s.get('where')} «{str(s.get('quote'))[:100]}»", "step7_gaps.json")
    add("B3", "supporting: " + "; ".join(f"{s.get('key')} ({s.get('how')})" for s in g.get("supporting") or [])
        + (" · counter: " + "; ".join(f"{s.get('key')} ({s.get('how')})" for s in g["counter"]) if g.get("counter") else ""),
        "step7_gap_analysis.md")
    for q in F["index"].get("questions") or []:
        if q.get("gap") == gid:
            add("B3.5", f"{q['id']} ({q.get('status')}, axes {q.get('axes')}): {q.get('research_question')}", f"questions/{q['id']}.md")
    out["comments"] = _route("the gap", "the judgement", "a lens judgement", "the question")
    return out


def trace_question(rd: Path, qid: str) -> dict:
    rd = Path(rd)
    F = _fusion(rd)
    q = next((x for x in F["index"].get("questions") or [] if x.get("id") == qid), None)
    if q is None:
        die(f"{qid} is not in questions/index.json (questions-index)", 2)
    out = {"id": qid, "title": q.get("research_question"), "steps": []}
    add = lambda u, text, where: out["steps"].append({"unit": u, "text": text, "where": where})
    g = next((x for x in F["gaps"].get("gaps") or [] if x.get("id") == q.get("gap")), {})
    add("B3", f"on {q.get('gap')} (rank {q.get('gap_rank')}, move {g.get('move')}): {g.get('title')}", "step7_gaps.json")
    for cid in q.get("collisions") or []:
        r = F["current"].get(cid) or {}
        add("A7.X2", f"{cid} {r.get('result', '(not current)')}: {str(r.get('reason'))[:140]}", "knowledge/collisions.jsonl")
    add("B3.5", f"{q.get('status')} · axes {q.get('axes')} · study {q.get('study')} · screens "
        + ", ".join(f"{k} {v}" for k, v in (q.get("screens") or {}).items()), f"questions/{qid}.md")
    add("F.9", f"ready {F['index'].get('ready')} of target {F['index'].get('target_ready')}", "questions/index.json")
    taken = [e for e in (_j(rd, "step0_session_config.json") or {}).get("consumed") or [] if e.get("question") == qid]
    if taken:
        add("F.9", f"taken by generation {taken[-1].get('generation')} as idea {taken[-1].get('idea')}",
            "step0_session_config.json › consumed")
    out["comments"] = _route("the question", "the question index", "the gap")
    return out


# ========================================================================================================= queries
def trace_query(rd: Path, qid: str) -> dict:
    rd = Path(rd)
    cfg = _j(rd, "step0_session_config.json") or {}
    q = next((x for x in cfg.get("queries") or [] if x.get("id") == qid), None)
    if q is None and qid != "D1":
        die(f"{qid} is not a query of this topic", 2)
    out = {"id": qid, "title": (q or {}).get("flat_query") or "dense instance", "steps": []}
    add = lambda unit, text, where: out["steps"].append({"unit": unit, "text": text, "where": where})
    if q:
        add("A1.q" if q.get("added_by") != "A2.c" else "A2.c",
            f"{q.get('strategy')} · axes {json.dumps(q.get('axes'))} · flat «{q.get('flat_query')}» · {q.get('status', 'active')}"
            + (f" (retired by {q['retired_by']}: {q.get('retire_reason')})" if q.get("retired_by") else ""), "step0_session_config.json › queries")
        for h in cfg.get("queries_history") or []:
            if qid in (h.get("retired"), (h.get("added") or {}).get("id")):
                add("A2.c", f"revision round {h.get('round')}: retired {h.get('retired')}, added {(h.get('added') or {}).get('id')} — "
                    f"{h.get('reason')}", "step0_session_config.json › queries_history")
    insts = sorted((rd / "step2_queries").glob(f"{qid}@*.json"))
    from it_search import source_status
    for f in insts:
        r = read_json(f)
        per = "; ".join(f"{src}: {n}/{tot}" if st == "ok" else f"{src}: {st}" for src, (st, n, tot, _) in source_status(r).items())
        add("A2.s", f"instance {f.name}: {per or 'no per-source record'}", f"step2_queries/{f.name}")
    raw = (_j(rd, "step2_raw_papers.json") or {}).get("papers") or []
    found = [p for p in raw if qid in (p.get("found_by") or [])]
    add("A2.m", f"{len(found)} papers in the collection carry it in found_by ({sum(1 for p in found if p.get('found_by') == [qid])} only it)",
        "step2_raw_papers.json")
    for r in (_j(rd, "step2_relevance_check.json") or {}).get("rounds") or []:
        v = next((x for x in r.get("verdicts") or [] if x.get("query") == qid), None)
        if v:
            add("A2.c", f"round {r.get('round')}: {v.get('verdict')}" + (f" — {v.get('reason')}" if v.get("reason") else ""),
                "step2_relevance_check.md")
    out["comments"] = _route("the query's wording", "the query's verdict", "a known item to find")
    return out


def trace_protocol(rd: Path) -> dict:
    rd = Path(rd)
    cfg = _j(rd, "step0_session_config.json") or {}
    p = cfg.get("protocol") or {}
    fw = p.get("framework") or {}
    crit = p.get("criteria") or {}
    out = {"id": "protocol", "title": cfg.get("topic"), "steps": []}
    add = lambda unit, text, where: out["steps"].append({"unit": unit, "text": text, "where": where})
    add("A1.p", f"{p.get('review_type')} / {p.get('reporting_standard')} · {fw.get('name')}: "
        + ", ".join(f"{x.get('slot')} ({x.get('operational_role')})" for x in fw.get("slots") or []), "step0 › protocol.framework")
    for a in p.get("axes") or []:
        added = [x.get("term") for x in a.get("added") or []]
        add("A1.p", f"axis {a.get('id')} {a.get('kind')} «{a.get('name')}»: {len(a.get('terms') or [])} terms"
            + (f" (+{', '.join(added)} added by A2.c)" if added else ""), "step0 › protocol.axes")
    add("A1.p", f"criteria: {', '.join(c.get('id', '?') for c in (crit.get('inclusion') or []) + (crit.get('exclusion') or []))}"
        f" · timeframe {p.get('timeframe')}", "step0 › protocol.criteria")
    for h in (p.get("history") or [])[1:]:
        add(h.get("by", "A1.p"), f"{h.get('action')}: {h.get('note', '')}", "step0 › protocol.history")
    amend = (_j(rd, "screening_scores.json") or {}).get("criteria_amendments") or []
    for x in amend:
        add("A3", f"criteria amendment: {x.get('change')} — {x.get('reason')}", "screening_scores.json › criteria_amendments")
    ev = _j(rd, "step1_protocol_evaluation.json") or {}
    for r in ev.get("rounds") or []:
        fails = [f.get("check") for f in r.get("findings") or [] if f.get("result") == "fail"]
        add("A1.e", f"round {r.get('round')}: {r.get('verdict')}" + (f" (failed {', '.join(fails)})" if fails else ""),
            "step1_protocol_evaluation.md")
    if ev.get("final"):
        add("A1.e", f"final: {ev['final'].get('status')}", "step1_protocol_evaluation.json › final")
    if cfg.get("target_venues"):
        add("A1.v", f"venues {', '.join(map(str, cfg.get('target_venues') or []))} · domain {cfg.get('expert_domain')}",
            "step0 › target_venues, expert_domain, local_environment")
    out["comments"] = _route("the frame, axes or criteria", "the protocol's evaluation", "venues, expert domain, environment")
    return out


def trace(rd: Path, item: str) -> dict:
    rd = Path(rd)
    if item == "protocol":
        return trace_protocol(rd)
    if item.startswith("paper_"):
        return trace_paper(rd, item)
    import re
    if re.fullmatch(r"X\d{4}", item):
        return trace_collision(rd, item)
    if re.fullmatch(r"GAP_\d{3}", item):
        return trace_gap(rd, item)
    if re.fullmatch(r"Q_\d{3}", item):
        return trace_question(rd, item)
    if item[:1] in ("Q", "D") and item[1:2].isdigit():
        return trace_query(rd, item)
    k = next((e for e in read_jsonl(rd / "step4_citation_keys.jsonl") if e["key"] == item), None)
    if k:
        return trace_paper(rd, k["id"])
    if (rd / "knowledge" / "decon" / f"{item}.json").exists():     # a topic whose search ran before the key registry
        return trace_paper_fusion(rd, item)
    die(f"{item!r} is not a paper id, a citation key, a query id, a collision, a gap or a question of this topic", 2)


def cmd_trace(a):
    out = trace(Path(a.research_dir), a.item)
    if a.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return
    print(f"{out['id']}  {str(out.get('title'))[:100]}" + (f" ({out['year']})" if out.get("year") else ""))
    for s in out["steps"]:
        print(f"  {s['unit']:<5} {s['text'][:220]}\n        ↳ {s['where']}")
    for line in out["comments"]:
        print(line)


def add_parsers(sub) -> None:
    sp = sub.add_parser("trace", help="every Unit's decision about one paper, citation key, query, collision (X0001), gap "
                                      "(GAP_001) or question (Q_001)")
    sp.add_argument("research_dir")
    sp.add_argument("item")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_trace)
