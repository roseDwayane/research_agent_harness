"""A3 screen - the Units that decide, per candidate paper, whether it belongs (rules: references/search/A3-screen.md).

  A3.b  bibliometrics  per paper: type, retraction, language, citations (field- and year-normalised percentile,
                       velocity), venue (Scopus SNIP, OpenAlex 2-year mean citedness), citations inside the collection
                       -> the computed impact axis                                      -> step3_bibliometrics.json
  A3.g  gate           mechanical exclusions: retracted, not research, not in the protocol's languages
                                                                                        -> step3_gate.json
  A3    scoring        evidence first, then relevance and quality, by subagents in batches, blind to venue and
                       citations; exclusions name the criterion they violate             -> screening_scores.json
                       build (screen-build): composite, inclusion, tiers, reading roles  -> step3_shortlist.json,
                                                                                           step3_screening_results.md

Network: `mcp_bridge.py bibliometrics <RD>` (OpenAlex + the scholar server's Scopus venue tool). Offline:
  ideate_tools.py screen-gate  <RD>                       A3.g
  ideate_tools.py screen-plan  <RD> [--size 60]           A3: the brief and the batches for the subagents
  ideate_tools.py screen-merge <RD>                       A3: batch answers -> screening_scores.json
  ideate_tools.py screen-amend <RD> amendment.json        A3: a criterion amendment, with its reason
  ideate_tools.py screen-rescue <RD> <id> --reason R      A3: a second, blind reading of one excluded paper
  ideate_tools.py screen-build <RD> screening_scores.json A3: composite, inclusion, tiers, roles -> the shortlist
  ideate_tools.py a3-check     <RD> [--unit A3.b|A3.g|A3|all] [--json]
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

from it_common import (die, http_json, now_iso, preflight_says, quote, read_json, require_protocol, sha256_file,
                       write_json, write_json_stable, write_text)

BIB_SCHEMA = "ideate-bibliometrics/1"
SCORES_SCHEMA = "ideate-scores/2"
SHORTLIST_SCHEMA = "ideate-shortlist/2"
WEIGHTS = {"relevance": 0.50, "quality": 0.30, "recency_impact": 0.20}
INCLUDE_AT = 3.0                  # recall first: the 3.00-3.49 band is included as tier 4
FLOOR_RELEVANCE = 3               # snowball and dense-only additions
SOFT_RELEVANCE_CAP = 2            # a paper violating only soft EX criteria (A1.e E6) that would be included without them:
                                  # kept as tier 4, its composite computed on rel <= 2
# OpenAlex work types that are not research reports. Kept on purpose: article, preprint, review, book-chapter,
# book, dissertation, report, dataset, standard, other - recall first.
GATE_TYPES = {"editorial", "erratum", "retraction", "paratext", "letter", "peer-review", "grant",
              "supplementary-materials", "libguides", "reference-entry"}
GATE_CODES = {"X-RET": "retracted", "X-TYPE": "not a research report", "X-LANG": "not in the protocol's languages"}
W_CIT, W_LOCAL = 0.7, 0.3        # impact = field-normalised citation percentile + citations inside the collection
COLD_YEARS = 2                    # papers this young lean on the venue prior; it fades out in year 3
EVIDENCE_KEYS = ("problem", "method", "data", "code")
NOT_STATED = "not stated"
BATCH_SIZE = 60
LOW_SEM_PCT = 25                  # a bulk rule may only touch papers in the bottom quarter by sem_sim
ROLE_ORDER = ("foundational", "core-method", "emerging", "survey", "supporting")


def F(level, code, unit, msg):
    return {"level": level, "code": code, "unit": unit, "msg": msg}


def errors(fs):
    return [f for f in fs if f["level"] == "ERROR"]


def _cfg(rd: Path) -> dict:
    p = Path(rd) / "step0_session_config.json"
    if not p.exists():
        die(f"{p} not found", 2)
    return read_json(p)


def candidates(rd: Path, filled: bool = True) -> list[dict]:
    """The search's and the snowball's papers. `filled`: a record without an abstract carries the one A3.b found
    (`abstract_fill` in step3_bibliometrics.json, §15 G3) and `abstract_filled_by` - scoring, its checks and the shortlist
    read that text; the step2 files are never changed."""
    papers = list(read_json(Path(rd) / "step2_raw_papers.json")["papers"])
    sb = Path(rd) / "step2b_snowball_papers.json"
    if sb.exists():
        papers += read_json(sb)["papers"]
    bp = Path(rd) / "step3_bibliometrics.json"
    if filled and bp.exists():
        fills = {pid: r["abstract_fill"] for pid, r in (read_json(bp).get("papers") or {}).items()
                 if isinstance(r, dict) and r.get("abstract_fill")}
        if fills:
            papers = [{**x, "abstract": fills[x["id"]]["text"], "abstract_filled_by": fills[x["id"]]["source"],
                       "abstract_raw": x.get("abstract")}                 # what an earlier scorer may have quoted
                      if x["id"] in fills and not has_abstract(x) else x for x in papers]
    return papers


def text_sha(p: dict) -> str:
    """The text a scorer saw (title + abstract, normalised): an entry whose paper reads differently now was scored on
    less than there is."""
    return hashlib.sha256(_norm(f"{p.get('title') or ''} {p.get('abstract') or ''}").encode()).hexdigest()[:16]


def _openalex_abstract(inv) -> str:
    if not isinstance(inv, dict) or not inv:
        return ""
    pos = sorted((i, w) for w, idx in inv.items() for i in idx or [])
    return " ".join(w for _, w in pos)


S2_ABSTRACT_CHUNK = 100


async def fill_abstracts(server, rd: Path, papers: list[dict], works: dict, prev: dict) -> tuple[dict, dict, list]:
    """§15 G3: an abstract for the records that have none, before anyone scores them - OpenAlex's own (already in the
    works A3.b fetched), then Semantic Scholar's by DOI or S2 id. Only text that passes `has_abstract` is kept. A fill
    from an earlier A3.b run is kept as it was (no second request). Returns ({id: {text, source}}, counts, caveats)."""
    fills, queue, caveats = {}, [], []
    lacking = [p for p in papers if not has_abstract(p)]
    for p in lacking:
        old = (prev.get(p["id"]) or {}).get("abstract_fill")
        if old and has_abstract({**p, "abstract": old.get("text")}):    # an earlier fill, still an abstract today
            fills[p["id"]] = old
            continue
        t = _openalex_abstract((works.get(p["id"]) or {}).get("abstract_inverted_index"))
        if t and has_abstract({**p, "abstract": t}):
            fills[p["id"]] = {"text": t, "source": "openalex"}
        elif p.get("doi") or p.get("semantic_scholar_id"):
            queue.append(p)
    asked = 0
    if queue and server is not None and (preflight_says(rd, "semantic_scholar") or (True, ""))[0] is not False:
        for i in range(0, len(queue), S2_ABSTRACT_CHUNK):
            chunk = queue[i:i + S2_ABSTRACT_CHUNK]
            ids = {p["id"]: (f"DOI:{p['doi']}" if p.get("doi") else str(p["semantic_scholar_id"])) for p in chunk}
            r = await server.call("scholar_abstracts", {"paper_ids": list(ids.values())})
            if not (isinstance(r, dict) and isinstance(r.get("abstracts"), dict)):
                caveats.append({"code": "abstract-fill-partial", "text": "Semantic Scholar abstracts unavailable "
                                f"after {asked} of {len(queue)} record(s): {str((r or {}).get('_text') or r)[:120]}",
                                "must_disclose": False})
                break
            asked += len(chunk)
            for p in chunk:
                t = r["abstracts"].get(ids[p["id"]])
                if t and has_abstract({**p, "abstract": t}):
                    fills[p["id"]] = {"text": t, "source": "semantic_scholar"}
    elif queue:
        caveats.append({"code": "abstract-fill-partial", "text": f"{len(queue)} record(s) without an abstract were not "
                        "looked up on Semantic Scholar (no scholar server, or preflight says it is down)",
                        "must_disclose": False})
    counts = {"lacking": len(lacking), "openalex": sum(1 for f in fills.values() if f["source"] == "openalex"),
              "semantic_scholar": sum(1 for f in fills.values() if f["source"] == "semantic_scholar"),
              "still_missing": len(lacking) - len(fills)}
    return fills, counts, caveats


def basis_shas(rd: Path) -> dict:
    return {"raw": sha256_file(Path(rd) / "step2_raw_papers.json"),
            "snowball": sha256_file(Path(rd) / "step2b_snowball_papers.json")}


def pct(x, values) -> float:
    """Percentile of x among values (ties count half), 0-100."""
    vs = [v for v in values if v is not None]
    if x is None or not vs:
        return None
    return round(100 * (sum(1 for v in vs if v < x) + 0.5 * sum(1 for v in vs if v == x)) / len(vs), 1)


# ============================================================================================== A3.b bibliometrics
EN_WORDS = {"the", "of", "and", "in", "to", "with", "for", "is", "are", "we", "this", "that", "on", "by", "from"}


def english_abstract(text) -> bool:
    """An abstract written in English (>= 5 common English function words). OpenAlex's `language` describes the full
    text: a Dutch or Chinese journal article with an English abstract is tagged nl / zh, yet its abstract already says
    what was done - prior work a novelty claim must face."""
    words = re.findall(r"[a-z]+", str(text or "").lower())
    return sum(1 for w in words if w in EN_WORDS) >= 5


def _year_now() -> int:
    return date.today().year


def _velocity(counts_by_year) -> float | None:
    """Mean citations per year over the last two complete years."""
    if not counts_by_year:
        return None
    y = _year_now()
    by = {int(c["year"]): int(c.get("cited_by_count") or 0) for c in counts_by_year}
    return round((by.get(y - 1, 0) + by.get(y - 2, 0)) / 2, 2)


def impact_value(rec: dict) -> float | None:
    """0-1. Article part = field- and year-normalised citation percentile (OpenAlex; else the paper's citations per
    year as a percentile of the collection) blended with its citations inside the collection. A paper younger than
    COLD_YEARS leans on its venue's percentile (neutral when the venue has none: preprints and conferences are never
    penalised); the venue's share fades out in the third year. None = no metadata at all (scored neutral)."""
    cit = rec.get("cit_pct")
    if cit is None:
        cit = (rec.get("cit_pct_local") or 0) / 100 if rec.get("cit_pct_local") is not None else None
    if cit is None:
        return None
    art = W_CIT * cit + W_LOCAL * ((rec.get("in_pct") or 0) / 100)
    venue = (rec.get("venue_pct") / 100) if rec.get("venue_pct") is not None else 0.5
    age = rec.get("age")
    if age is not None and age < COLD_YEARS:
        return round(0.5 * art + 0.5 * venue, 4)
    if age is not None and age == COLD_YEARS:
        return round(0.75 * art + 0.25 * venue, 4)
    return round(art, 4)


def impact_score(rec: dict) -> float:
    v = impact_value(rec)
    return 3.0 if v is None else round(1 + 4 * v, 1)


def _batch(rd, filt_key, ids, select, fetch, mailto, per=40):
    out = []
    for i in range(0, len(ids), per):
        chunk = ids[i:i + per]
        url = (f"https://api.openalex.org/works?filter={quote(filt_key + ':' + '|'.join(chunk))}&per-page=50"
               f"&mailto={quote(mailto)}&select={select}")
        try:
            out += fetch(url, rd).get("results") or []
        except Exception:  # noqa: BLE001 - counted by the caller as missing metadata
            pass
    return out


async def _run_bibliometrics(server, cfg: dict, rd: Path, mailto: str, fetch=http_json) -> dict:
    rd = Path(rd)
    papers = candidates(rd, filled=False)
    select = ("id,doi,type,is_retracted,language,cited_by_count,fwci,citation_normalized_percentile,counts_by_year,"
              "referenced_works,publication_year,publication_date,primary_location,authorships,abstract_inverted_index")
    dois = sorted({str(p["doi"]).lower() for p in papers if p.get("doi")})
    works = _batch(rd, "doi", dois, select, fetch, mailto)
    oa_ids = sorted({str(p["openalex_id"]) for p in papers if p.get("openalex_id") and not p.get("doi")})
    works += _batch(rd, "openalex", oa_ids, select, fetch, mailto)
    by_doi = {str(w.get("doi") or "").lower().removeprefix("https://doi.org/"): w for w in works if w.get("doi")}
    by_oa = {str(w.get("id") or "").rsplit("/", 1)[-1]: w for w in works}
    # venues: OpenAlex source stats, then Scopus SNIP by ISSN
    src_ids = sorted({((w.get("primary_location") or {}).get("source") or {}).get("id", "").rsplit("/", 1)[-1]
                      for w in works} - {""})
    sources = {}
    for i in range(0, len(src_ids), 50):
        chunk = src_ids[i:i + 50]
        url = (f"https://api.openalex.org/sources?filter={quote('openalex:' + '|'.join(chunk))}&per-page=50"
               f"&mailto={quote(mailto)}&select=id,display_name,type,issn_l,issn,summary_stats")
        try:
            for s in fetch(url, rd).get("results") or []:
                sources[str(s["id"]).rsplit("/", 1)[-1]] = s
        except Exception:  # noqa: BLE001
            pass
    issns = sorted({s.get("issn_l") for s in sources.values() if s.get("issn_l")})
    snip = {}
    caveats = []
    for i in range(0, len(issns), 25):
        r = await server.call("scholar_venues", {"issns": issns[i:i + 25]}) if server is not None else {}
        if isinstance(r, dict) and isinstance(r.get("venues"), dict):
            snip.update(r["venues"])
        elif server is not None:
            caveats.append({"code": "snip-unavailable", "text": str((r or {}).get("_text") or r)[:160], "must_disclose": False})
            break
    y = _year_now()
    recs = {}
    for p in papers:
        w = by_doi.get(str(p.get("doi") or "").lower()) or by_oa.get(str(p.get("openalex_id") or ""))
        year = p.get("year") or (w or {}).get("publication_year")
        rec = {"openalex_id": None, "type": None, "is_retracted": None, "language": None,
               "abstract_english": english_abstract(p.get("abstract")), "cites": p.get("citation_count"),
               "fwci": None, "cit_pct": None, "velocity": None, "year": year,
               "age": max(0, y - int(year)) if year else None, "venue": None, "refs": [], "metadata": "none",
               "authors_full": None, "publication_date": None, "counts_by_year": []}
        if w:
            src = (w.get("primary_location") or {}).get("source") or {}
            sid = str(src.get("id") or "").rsplit("/", 1)[-1]
            s = sources.get(sid) or {}
            sn = snip.get(s.get("issn_l") or "") or {}
            rec.update({"openalex_id": str(w.get("id") or "").rsplit("/", 1)[-1], "type": w.get("type"),
                        "is_retracted": bool(w.get("is_retracted")), "language": w.get("language"),
                        "cites": w.get("cited_by_count", p.get("citation_count")), "fwci": w.get("fwci"),
                        "cit_pct": (w.get("citation_normalized_percentile") or {}).get("value"),
                        "velocity": _velocity(w.get("counts_by_year")),
                        "refs": [str(x).rsplit("/", 1)[-1] for x in w.get("referenced_works") or []],
                        "venue": {"id": sid or None, "name": src.get("display_name"), "type": src.get("type"),
                                  "issn_l": s.get("issn_l"), "snip": sn.get("snip"), "sjr": sn.get("sjr"),
                                  "two_yr": ((s.get("summary_stats") or {}).get("2yr_mean_citedness"))} if sid else None,
                        "metadata": "openalex",
                        # A4 mints citation keys from the most complete author list (Scopus gives only the first)
                        "authors_full": [((x.get("author") or {}).get("display_name")) for x in w.get("authorships") or []
                                         if (x.get("author") or {}).get("display_name")] or None,
                        "publication_date": w.get("publication_date"),
                        "counts_by_year": [{"year": c.get("year"), "cited_by_count": c.get("cited_by_count")}
                                           for c in w.get("counts_by_year") or []]})
        recs[p["id"]] = rec
    # citations inside the collection
    oa_to_id = {r["openalex_id"]: pid for pid, r in recs.items() if r["openalex_id"]}
    for pid, r in recs.items():
        r["out_degree"] = len({oa_to_id[x] for x in r["refs"] if x in oa_to_id} - {pid})
        r["in_degree"] = 0
    for pid, r in recs.items():
        for x in r["refs"]:
            q = oa_to_id.get(x)
            if q and q != pid:
                recs[q]["in_degree"] += 1
    ins = [r["in_degree"] for r in recs.values()]
    outs = [r["out_degree"] for r in recs.values()]
    vel = [r["velocity"] for r in recs.values() if r["velocity"] is not None]
    vmetric = lambda r: (r["venue"] or {}).get("snip") if (r["venue"] or {}).get("snip") is not None else None
    snips = [vmetric(r) for r in recs.values() if vmetric(r) is not None]
    two = [(r["venue"] or {}).get("two_yr") for r in recs.values() if (r["venue"] or {}).get("two_yr") is not None]
    cpy = {pid: (r["cites"] / (r["age"] + 1)) if r["cites"] is not None and r["age"] is not None else None
           for pid, r in recs.items()}
    for pid, r in recs.items():
        r["in_pct"] = pct(r["in_degree"], ins)
        r["out_pct"] = pct(r["out_degree"], outs)
        r["velocity_pct"] = pct(r["velocity"], vel)
        v = r["venue"] or {}
        r["venue_pct"] = pct(v.get("snip"), snips) if v.get("snip") is not None else \
            (pct(v.get("two_yr"), two) if v.get("two_yr") is not None and v.get("type") == "journal" else None)
        r["cit_pct_local"] = pct(cpy[pid], [x for x in cpy.values() if x is not None]) if r["cit_pct"] is None else None
        r["impact"] = impact_score(r)
        # `refs` stays: A5 counts the references the collection shares, and the report reads its graph from here
    prev_p = Path(rd) / "step3_bibliometrics.json"
    prev = (read_json(prev_p).get("papers") or {}) if prev_p.exists() else {}
    work_of = {p["id"]: by_doi.get(str(p.get("doi") or "").lower()) or by_oa.get(str(p.get("openalex_id") or ""))
               for p in papers}
    fills, fill_counts, fill_caveats = await fill_abstracts(server, rd, papers, work_of, prev)
    for pid, f in fills.items():
        recs[pid]["abstract_fill"] = f
        recs[pid]["abstract_english"] = english_abstract(f["text"])
    caveats += fill_caveats
    if fill_counts["lacking"]:
        caveats.append({"code": "abstract-fill", "text": f"{fill_counts['lacking']} record(s) had no abstract: "
                        f"{fill_counts['openalex']} filled from OpenAlex, {fill_counts['semantic_scholar']} from Semantic "
                        f"Scholar, {fill_counts['still_missing']} judged on the title", "must_disclose": False})
    missing = sum(1 for r in recs.values() if r["metadata"] == "none")
    if missing:
        caveats.append({"code": "no-metadata", "text": f"{missing} candidate(s) have no OpenAlex record: impact scored "
                        "neutral (3.0)", "must_disclose": False})
    out = {"schema": BIB_SCHEMA, "at": now_iso(), "basis": basis_shas(rd), "weights": {"citation": W_CIT, "local": W_LOCAL},
           "cold_years": COLD_YEARS, "venues_with_snip": len(snip), "abstract_fill": fill_counts, "papers": recs,
           "caveats": caveats}
    write_json_stable(rd / "step3_bibliometrics.json", out)
    return out


# ======================================================================================================= A3.g gate
def gate_decisions(cfg: dict, bib: dict) -> list[dict]:
    langs = [str(x).lower() for x in (cfg.get("protocol") or {}).get("languages") or ["en"]]
    out = []
    for pid, r in sorted(bib["papers"].items()):
        if r.get("is_retracted"):
            out.append({"id": pid, "code": "X-RET", "detail": "OpenAlex marks the work as retracted"})
        elif r.get("type") in GATE_TYPES:
            out.append({"id": pid, "code": "X-TYPE", "detail": f"OpenAlex type: {r['type']}"})
        elif r.get("language") and str(r["language"]).lower() not in langs and not ("en" in langs and r.get("abstract_english")):
            out.append({"id": pid, "code": "X-LANG", "detail": f"language {r['language']} not in {langs}, and the abstract is not English"})
    return out


def _cmd_gate(a):
    rd = Path(a.research_dir)
    cfg = _cfg(rd)
    bpath = rd / "step3_bibliometrics.json"
    if not bpath.exists():
        die("no step3_bibliometrics.json: run `mcp_bridge.py bibliometrics <RD>` (A3.b) first", 2)
    bib = read_json(bpath)
    exc = gate_decisions(cfg, bib)
    write_json_stable(rd / "step3_gate.json", {"schema": "ideate-gate/1", "at": now_iso(), "bib_sha": sha256_file(bpath),
                                               "excluded": exc, "passed": len(bib["papers"]) - len(exc)})
    c = Counter(e["code"] for e in exc)
    print(f"A3.g: {len(exc)} excluded mechanically ({dict(c) or 'none'}), {len(bib['papers']) - len(exc)} go to scoring")


# ================================================================================================ A3 scoring (fanout)
BRIEF = """# A3 screening brief

You screen candidate papers for a scoping review whose purpose is to find research gaps. For **every** paper in your
batch file, decide whether it belongs - recall first: a missed close paper produces a false novelty claim, an extra
paper costs a few minutes. You see titles and abstracts only, on purpose: no journal, no citation counts.

Read `{batch}` (your papers) and nothing else. Write `{out}`. Judge each paper on the text in the batch only - never on
what you know about the work from elsewhere (its authors, its reputation, a version you have read): another reviewer
must reach your verdict from the same text.

## 1. Evidence first, then the scores

For each paper, before any number, copy **verbatim** from its title or abstract (a phrase of at least two words,
exactly as written; or the literal "not stated"):

- `problem` - the question or task it addresses
- `method` - what it does or proposes
- `data` - the data, population or setting
- `code` - a statement that code or data is available (usually "not stated")

A score of relevance 3 or more needs a quoted `problem` and `method` (a paper with no abstract: a quoted `problem`
from the title is enough). Quotes are checked against the text, ignoring case, punctuation (hyphens too) and spacing: curly or
straight quotes, a non-breaking space or a line break do not matter; copy a hyphenated line break as written
("em- bedded").

If the abstract plainly describes **another** paper than the title (a different subject altogether), add
`"record_problem": "abstract-mismatch"`, and judge the paper on its **title only**: quotes from the title, the
no-abstract rule below (a rationale starting `no abstract:` that says the abstract is of another paper).

## 2. The criteria (fixed before the search)

{criteria}

A paper that violates an exclusion criterion: `"violates": ["EX1"]`; one that plainly meets no inclusion criterion:
the inclusion criteria it fails, `"violates": ["IN1"]` (not a low relevance score). Either way a rationale that says
how - no scores needed.

A criterion marked **soft** rests on one reading of a word in the topic that has another plausible reading (given
after it); a criterion marked **linked** holds the same word and is read the same way. For every soft or linked
criterion a paper fails under the protocol's reading, judge the other reading too:

- it **meets** the criterion under the other reading: the paper is not excluded for it. Give evidence and scores as if
  the criterion were absent and add `"soft_violates": {{"EX1": "<how it meets the other reading>"}}`. If it would be
  included without it, it is kept as borderline.
- it **fails both** readings: the criterion is violated like any other, `"violates": ["EX1"]`; when every criterion in
  `violates` is soft or linked, add `"both_readings": {{"EX1": "<why the other reading excludes it too>"}}`.

Either way name the criterion with a reason of a few words; an entry without it is refused. A paper excluded by any
criterion that is neither soft nor linked is simply `violates` - it carries no `soft_violates`.

## 3. Scores (each 1-5)

**Relevance to the protocol** - read against every slot and outcome below, not only the first idea you have:
5 same population, anchor concept and outcome · 4 most components, one minor mismatch · 3 shares the anchor concept or
the population but not both, or a closely related question · 2 same broad field, different focus · 1 keywords only.

{scope}

**Methodological quality** - what the abstract reveals: 5 rigorous evaluation on established benchmarks with strong
baselines and ablations · 4 several datasets, clear methodology · 3 single benchmark or thin baselines · 2 inadequate
evaluation · 1 no method discernible. Reviews are judged on systematic rigour. Preprints are not penalised.

A paper flagged NO-ABSTRACT that is clearly on topic from its title: relevance 4, quality 3, rationale starting
`no abstract:`. One whose title may be on topic but does not settle it: relevance 3, quality 3, `"needs_text": true`,
rationale starting `no abstract: the title does not settle` - its full text is read first, later. Any NO-ABSTRACT
paper with relevance 3 or more has a rationale starting `no abstract:`. A record that is not a paper (an organisation
name, a cover page): relevance 1, quality 1, rationale `not a paper`, evidence all "not stated".

## 4. Rationale

One specific sentence per paper, in your own words for **that** paper ("population mismatch: rodent recordings"),
never shared with another paper and never "not relevant".

## 5. Duplicates

Two records of the same paper: score one, mark the other `{{"id": "...", "duplicate_of": "paper_xxx"}}`; if the dropped
copy is an open-access preprint, add `"carry": {{"arxiv_id": "..."}}` so the kept record keeps the route to the text.

## Output - exactly one JSON object

```json
{{"model": "the model you are",
 "scores": [{{"id": "paper_001", "evidence": {{"problem": "…", "method": "…", "data": "…", "code": "not stated"}},
             "rel": 4, "qual": 3, "rationale": "…"}},
            {{"id": "paper_002", "violates": ["EX1"], "rationale": "…"}},
            {{"id": "paper_004", "evidence": {{…}}, "rel": 4, "qual": 3,
             "soft_violates": {{"EX2": "meets it under the other reading: …"}}, "rationale": "…"}},
            {{"id": "paper_005", "violates": ["EX2"], "both_readings": {{"EX2": "…"}}, "rationale": "…"}},
            {{"id": "paper_003", "duplicate_of": "paper_001"}}]}}
```
"""


VENUE_TEXT = re.compile(r"\b(Proceedings of|Conference on|Workshop on|Association for Computational Linguistics|"
                        r"Transactions of|Annual Meeting)\b", re.I)


NAME_PARTICLES = {"and", "et", "al", "de", "van", "von", "der", "den", "la", "le", "da", "di", "del", "dos", "du",
                  "y", "e", "jr"}


def _no_prose(text: str) -> bool:
    """Text with (almost) no lower-case words is not an abstract: a list of names, "International audience" (HAL),
    "status: Published", a book's table of contents. Text mostly in another script (CJK ...) is left to the scorer."""
    text = re.sub(r"https?://\S+|\bdoi:\s*\S+|\b10\.\d{4,}/\S+", " ", text)    # a link is not a word
    latin = [w for w in re.findall(r"[^\W\d_][\w'\-]*", text) if all(c <= "ɏ" for c in w)]   # "Pérez" is one word
    other = len(re.findall(r"[^\x00-ɏ\s\W\d_]", text))
    if not latin and not other:
        return True                                   # punctuation, digits, a lone "," - no words at all
    if not latin or other > len("".join(latin)):
        return False
    lower = [w for w in latin if w[0].islower() and w.lower() not in NAME_PARTICLES and len(w) > 2]
    return len(lower) < max(3, 0.15 * len(latin))


def has_abstract(p: dict) -> bool:
    """An abstract the scorer can quote. Some records carry something else in the abstract field - the citation (the
    authors and the venue, OpenAlex for ACL Anthology papers), a bare author list, repository boilerplate, a table of
    contents - which is no abstract: the paper is screened as NO-ABSTRACT, on its title."""
    text = str(p.get("abstract") or "").strip()
    if not text or _no_prose(text):
        return False
    words = text.split()
    if len(words) >= 60 or not VENUE_TEXT.search(text):
        return True
    head = " ".join(words[:25]).lower()
    surnames = {str(a).replace(",", " ").split()[-1].lower() for a in p.get("authors") or [] if str(a).strip()}
    names_list = len(re.findall(r"\b[A-Z][a-z]+ [A-Z][a-z]+,", text[:300])) >= 2
    return not (any(n in head for n in surnames if len(n) > 2) or names_list)


def _flags(p, bibrec) -> list[str]:
    f = []
    if p.get("anchor_match") is False:
        f.append("NO-ANCHOR")
    if not has_abstract(p):
        f.append("NO-ABSTRACT")
    if p.get("is_hub"):
        f.append("HUB")
    return f


def scores_path(rd: Path) -> Path:
    return Path(rd) / "screening_scores.json"


def load_scores(rd: Path) -> dict:
    p = scores_path(rd)
    return read_json(p) if p.exists() else {"schema": SCORES_SCHEMA, "bulk": [], "criteria_amendments": [], "scores": []}


def reconcile(rd: Path, scores: dict) -> tuple[int, int]:
    """After A5 redid a round: an entry for a work the snowball no longer holds moves to `withdrawn` (kept, never
    deleted); a withdrawn work that is a candidate again gets its earlier reading back. A search paper never
    vanishes this way - C01 still names it. Returns (withdrawn, restored)."""
    cand = {p["id"] for p in candidates(rd)}
    raw = {p["id"] for p in read_json(Path(rd) / "step2_raw_papers.json")["papers"]}
    gone = [e for e in scores.get("scores") or [] if e.get("id") not in cand and e.get("id") not in raw]
    have = {e.get("id") for e in scores.get("scores") or []}
    back = [w for w in scores.get("withdrawn") or [] if w.get("id") in cand and w.get("id") not in have]
    if not gone and not back:
        return 0, 0
    keep = [w for w in scores.get("withdrawn") or [] if w not in back]
    scores["withdrawn"] = keep + [{**e, "withdrawn": {"at": now_iso(), "why": "no longer a candidate: A5 redid "
                                                      "the round that brought it in"}} for e in gone]
    scores["scores"] = [e for e in scores.get("scores") or [] if e not in gone] + \
        [{k: v for k, v in w.items() if k != "withdrawn"} for w in back]
    return len(gone), len(back)


def _soft(rd: Path) -> dict:
    from it_frame import soft_criteria
    return soft_criteria(rd)


def _soft_sets(rd: Path) -> tuple[set, set]:
    """(the soft criteria, the criteria linked to them)."""
    soft = _soft(rd)
    return set(soft), {x for s in soft.values() for x in s.get("linked") or []}


SOFT_SHARE_WARN = 0.25     # a3-check C20: more of the shortlist than this kept only by a soft criterion
BRIEF_VERSION = 2          # §15: soft and linked criteria judged under both readings; `no abstract:`; needs_text


def _criteria_text(cfg: dict, scores: dict, soft: dict | None = None) -> str:
    crit = (cfg.get("protocol") or {}).get("criteria") or {}
    soft = soft or {}

    links = {lid: (cid, s_) for cid, s_ in soft.items() for lid in s_.get("linked") or []}

    def line(c):
        s_ = soft.get(c["id"])
        mark = (f" **(soft: \"{s_.get('word')}\" in the topic may also mean {s_.get('alt_reading')})**" if s_ else "")
        if c["id"] in links:
            cid, ls = links[c["id"]]
            mark += f" **(linked to soft {cid}: read \"{ls.get('word')}\" here the same way)**"
        return f"- {c['id']}: {c['text']}{mark}"
    lines = ["Inclusion:"] + [line(c) for c in crit.get("inclusion") or []]
    lines += ["Exclusion:"] + [line(c) for c in crit.get("exclusion") or []]
    for a in scores.get("criteria_amendments") or []:
        lines.append(f"- amendment: {a['change']} ({a['reason']})")
    return "\n".join(lines)


def _scope_text(cfg: dict) -> str:
    p = cfg.get("protocol") or {}
    fw = p.get("framework") or {}
    lines = [f"Framework {fw.get('name')}:"] + [f"- {s['slot']}: {s['value']}" for s in fw.get("slots") or []]
    lines += [f"- outcome {o['id']}: {o['text']}" for o in p.get("outcomes") or []]
    return "\n".join(lines)


def _cmd_plan(a):
    rd = Path(a.research_dir)
    cfg = _cfg(rd)
    if not (rd / "step3_gate.json").exists():
        die("no step3_gate.json: run `ideate_tools.py screen-gate <RD>` (A3.g) first", 2)
    gate = {e["id"] for e in read_json(rd / "step3_gate.json")["excluded"]}
    scores = load_scores(rd)
    gone, back = reconcile(rd, scores)
    if gone or back:
        write_json(scores_path(rd), scores)
        print(f"A3: {gone} entr(y/ies) withdrawn (the snowball no longer holds them), {back} restored")
    done = {s["id"] for s in scores.get("scores") or []}
    cand = candidates(rd)
    todo = [p for p in cand if p["id"] not in gate and p["id"] not in done]
    fan = rd / "_state" / "fanout" / "A3"
    fan.mkdir(parents=True, exist_ok=True)
    existing = sorted(fan.glob("batch_*.in.json"))
    start = len(existing)
    batches = [(todo[i:i + a.size], None) for i in range(0, len(todo), a.size)]
    taken = {p["id"] for p in todo}
    for kind in a.rescore or []:
        again = [p for p in rescore_targets(rd, scores, cand, gate, kind) if p["id"] not in taken]
        taken |= {p["id"] for p in again}                    # one new reading per paper, whatever asked for it
        batches += [(again[i:i + a.size], {"reason": RESCORE_REASONS[kind], "kind": kind})
                    for i in range(0, len(again), a.size)]
        print(f"A3: {len(again)} entr(y/ies) to read again ({kind}): {RESCORE_REASONS[kind]}")
    for k, (chunk, rescore) in enumerate(batches, start=start):
        write_json(fan / f"batch_{k:02d}.in.json", {
            "batch": k, "brief": BRIEF_VERSION, "ids": [p["id"] for p in chunk], "out": f"batch_{k:02d}.out.json",
            **({"rescore": rescore} if rescore else {}),
            "papers": [{"id": p["id"], "title": p.get("title"), "abstract": p.get("abstract"), "year": p.get("year"),
                        "flags": _flags(p, None)} for p in chunk]})
    write_text(fan / "brief.md", BRIEF.format(batch="<this batch's .in.json>", out="<the matching .out.json>",
                                              criteria=_criteria_text(cfg, scores, _soft(rd)), scope=_scope_text(cfg)))
    print(f"A3: {sum(len(c) for c, _ in batches)} paper(s) to score in {len(batches)} batch(es) of <= {a.size} -> {fan}")
    for k in range(start, start + len(batches)):
        print(f"  subagent {k}: read {fan / 'brief.md'} and {fan / f'batch_{k:02d}.in.json'}; write {fan / f'batch_{k:02d}.out.json'}")


RESCORE_REASONS = {
    "soft": "scored before brief 2: a soft or linked criterion was not judged under its other reading (§15 G1)",
    "filled": "scored on other text than the record has now: A3.b found its abstract, or dropped one that was no abstract (§15 G3)",
}


def rescore_targets(rd: Path, scores: dict, cand: list[dict], gate: set, kind: str) -> list[dict]:
    """Entries to read again under the current brief (`screen-plan --rescore`). soft: an entry from before brief 2
    with soft_violates, or excluded on soft or linked criteria only. filled: an entry scored on less text than the
    paper has now (its text_sha differs; an older entry without one: the paper's abstract came from A3.b's fill). A
    paper already waiting in an unanswered rescore batch is not batched twice."""
    papers = {p["id"]: p for p in cand}
    soft, linked = _soft_sets(rd)
    fan = Path(rd) / "_state" / "fanout" / "A3"
    waiting = set()
    for f in fan.glob("batch_*.in.json") if fan.is_dir() else []:
        bi = read_json(f)
        if bi.get("rescore") and not (fan / bi["out"]).exists():
            waiting |= set(bi["ids"])
    out = []
    for e in scores.get("scores") or []:
        pid = e.get("id")
        if pid not in papers or pid in gate or pid in waiting or "duplicate_of" in e:
            continue
        if kind == "soft":
            hit = (e.get("brief") or 1) < 2 and (bool(e.get("soft_violates")) or
                                                 bool(e.get("violates")) and set(e["violates"]) <= soft | linked)
        else:
            hit = e.get("text_sha") != text_sha(papers[pid]) if e.get("text_sha") else \
                bool(papers[pid].get("abstract_filled_by"))
        if hit:
            out.append(papers[pid])
    return out


def _cmd_rescue(a):
    """Stage B found that an excluded paper may bear on its angle: dispatch a one-paper batch for a second, blind
    reading. The answer supersedes the earlier entry at the next screen-merge; the earlier entry is kept."""
    rd = Path(a.research_dir)
    cfg = _cfg(rd)
    require_protocol(cfg, rd)
    reason = str(a.reason or "").strip()
    if not reason:
        die("--reason is required: why a later step needs this paper read again", 2)
    papers = {p["id"]: p for p in candidates(rd)}
    pid = a.paper_id
    if pid not in papers:
        die(f"{pid} is not a candidate of this collection", 2)
    gate = {e["id"]: e for e in read_json(rd / "step3_gate.json")["excluded"]} if (rd / "step3_gate.json").exists() else {}
    if pid in gate:
        die(f"{pid} was excluded mechanically ({gate[pid]['code']}): a retraction, a record type or a language is a "
            "fact, not a judgement to read again", 2)
    if (rd / "step3_shortlist.json").exists() and pid in {p["id"] for p in read_json(rd / "step3_shortlist.json")["papers"]}:
        die(f"{pid} is already in the shortlist", 2)
    scores = load_scores(rd)
    cur = next((e for e in scores.get("scores") or [] if e.get("id") == pid), None)
    if cur and "duplicate_of" in cur:
        die(f"{pid} is a duplicate of {cur['duplicate_of']}: rescue that paper instead", 2)
    fan = rd / "_state" / "fanout" / "A3"
    fan.mkdir(parents=True, exist_ok=True)
    existing = sorted(fan.glob("batch_*.in.json"))
    for f in existing:
        bi = read_json(f)
        if bi.get("rescue") and pid in bi["ids"] and not (cur and cur.get("batch") == bi["batch"]) \
                and not (fan / bi["out"]).exists():
            die(f"a rescue of {pid} is already waiting for its answer: {f}", 2)
    k = len(existing)
    p = papers[pid]
    write_json(fan / f"batch_{k:02d}.in.json", {
        "batch": k, "brief": BRIEF_VERSION, "ids": [pid], "out": f"batch_{k:02d}.out.json",
        "rescue": {"reason": reason, "by": a.by or "", "at": now_iso(), "supersedes": (cur or {}).get("batch", "bulk")},
        "note": "A later step asks for a second reading of this paper. Judge it against the protocol exactly like any "
                "other paper; the earlier reading is not shown. Reason given: " + reason,
        "papers": [{"id": pid, "title": p.get("title"), "abstract": p.get("abstract"), "year": p.get("year"),
                    "flags": _flags(p, None)}]})
    write_text(fan / "brief.md", BRIEF.format(batch="<this batch's .in.json>", out="<the matching .out.json>",
                                              criteria=_criteria_text(cfg, scores, _soft(rd)), scope=_scope_text(cfg)))
    print(f"A3 rescue: {pid} in batch {k}")
    print(f"  subagent: read {fan / 'brief.md'} and {fan / f'batch_{k:02d}.in.json'}; write {fan / f'batch_{k:02d}.out.json'}")
    print("  then: screen-merge, screen-build, export, mcp_bridge.py bibliography, fulltext-status")


def cmd_merge(a):
    rd = Path(a.research_dir)
    fan = rd / "_state" / "fanout" / "A3"
    scores = load_scores(rd)
    gone, back = reconcile(rd, scores)
    papers = {p["id"]: p for p in candidates(rd)}
    cand = set(papers)
    ex_ids = criteria_ids(_cfg(rd))
    soft, linked = _soft_sets(rd)
    refused = []

    def admissible(e, batch, brief=None):
        if "duplicate_of" in e or e.get("id") not in papers:
            return True
        probs = entry_problems(e, papers[e["id"]], ex_ids, soft, linked, brief)
        if probs:
            refused.append({"id": e["id"], "batch": batch, "problems": [f"{c}: {m}" for c, m in probs]})
        return not probs
    scores["scores"] = [e for e in scores.get("scores") or [] if admissible(e, e.get("batch"))]
    have = {s["id"] for s in scores["scores"]}
    added, missing_all = 0, []
    for fin in sorted(fan.glob("batch_*.in.json")):
        bi = read_json(fin)
        fout = fan / bi["out"]
        if not fout.exists():
            missing_all.append((bi["batch"], bi["ids"], "no answer file"))
            continue
        ans = read_json(fout)
        model = ans.get("model") or "unknown"
        stamp = {"brief": bi["brief"]} if bi.get("brief") else {}       # the rules this answer was written under
        ids = set(bi["ids"])
        got = {}
        for e in ans.get("scores") or []:
            if e.get("id") not in ids:
                die(f"batch {bi['batch']}: answer for {e.get('id')!r}, which is not in the batch", 2)
            if e["id"] in got:
                die(f"batch {bi['batch']}: {e['id']} answered twice", 2)
            got[e["id"]] = e
        for pid in bi["ids"]:
            if pid not in cand:
                continue                                         # an earlier batch's work the snowball dropped
            seen = {"text_sha": text_sha(papers[pid])} if stamp else {}  # what the scorer read (brief 2 on)
            again = bi.get("rescue") or bi.get("rescore")
            if again and pid in got:
                cur = next((e for e in scores["scores"] if e.get("id") == pid), None)
                if cur and cur.get("batch") == bi["batch"]:
                    continue                                     # merged on an earlier run
                if not admissible({**got[pid], **seen}, bi["batch"], bi.get("brief") or 1):
                    continue                                     # refused: the earlier entry stays, the refusal is listed
                key = "rescue" if bi.get("rescue") else "rescore"
                mark = bi["rescue"] if key == "rescue" else \
                    {"reason": bi["rescore"]["reason"], "supersedes": (cur or {}).get("batch", "bulk")}
                if cur:
                    scores.setdefault("superseded", []).append({**cur, "superseded_by": bi["batch"]})
                    scores["scores"] = [e for e in scores["scores"] if e is not cur]
                scores["scores"].append({**got[pid], "batch": bi["batch"], "model": model, key: mark, **stamp, **seen})
                have.add(pid)
                added += 1
                continue
            if pid in have:
                continue
            if pid in got and admissible({**got[pid], **seen}, bi["batch"], bi.get("brief") or 1):
                scores["scores"].append({**got[pid], "batch": bi["batch"], "model": model, **stamp, **seen})
                have.add(pid)
                added += 1
        missing_all.append((bi["batch"], [pid for pid in bi["ids"] if pid in cand], "not answered or refused"))
    missing_all = [(b, [i for i in ids if i not in have], why) for b, ids, why in missing_all]
    missing_all = [m for m in missing_all if m[1]]                           # a later batch may have answered it
    known = {(r["id"], r["batch"]) for r in scores.get("refused") or []}
    refused = [r for r in refused if (r["id"], r["batch"]) not in known]      # an old refusal is not news
    scores["refused"] = list(scores.get("refused") or []) + refused
    scores["schema"] = SCORES_SCHEMA
    scores["basis"] = {**basis_shas(rd), "gate": sha256_file(rd / "step3_gate.json")}
    write_json(scores_path(rd), scores)
    print(f"A3: merged {added} new entr(y/ies) -> screening_scores.json ({len(scores['scores'])} in all)"
          + (f"; {gone} withdrawn, {back} restored" if gone or back else ""))
    for r in refused:
        print(f"  refused {r['id']} (batch {r['batch']}): {'; '.join(r['problems'])[:160]}")
    if missing_all:
        print("  missing - re-dispatch only these (`screen-plan` puts them in new batches):")
        for b, ids, why in missing_all:
            print(f"   batch {b}: {len(ids)} {why}: {ids[:8]}")


def cmd_amend(a):
    rd = Path(a.research_dir)
    am = read_json(Path(a.input_json))
    if set(am) - {"change", "reason", "refs"} or not str(am.get("change", "")).strip() or not str(am.get("reason", "")).strip():
        die("an amendment is {change, reason, refs?}: what changes and why (it goes into the protocol's deviation log)", 2)
    scores = load_scores(rd)
    scores.setdefault("criteria_amendments", []).append({**am, "by": "A3", "at": now_iso()})
    write_json(scores_path(rd), scores)
    print("A3: criteria amendment recorded (score the affected papers under it; earlier batches may need a re-check)")


# ========================================================================================================== checks
def _norm(s) -> str:
    """Case, punctuation (hyphens too: "Prompt-Tuning" = "prompt tuning") and spacing are ignored; %, . and + stay,
    so a number or a percentage is still checked."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s%.+]|_", " ", str(s or "").lower())).strip()


def evidence_problems(e: dict, paper: dict) -> list[str]:
    out = []
    ev = e.get("evidence")
    if not isinstance(ev, dict) or set(ev) != set(EVIDENCE_KEYS):
        return [f"evidence must have exactly {EVIDENCE_KEYS}"]
    mismatch = e.get("record_problem") == "abstract-mismatch"
    text = _norm(paper.get("title") if mismatch else
                 f"{paper.get('title') or ''} {paper.get('abstract') or ''} {paper.get('abstract_raw') or ''}")
    for k in EVIDENCE_KEYS:
        v = str(ev.get(k) or "").strip()
        if v.lower() == NOT_STATED:
            continue
        if len(_norm(v).split()) < 2 or _norm(v) not in text:          # "ParaNMT-Small" is two words
            out.append(f"evidence.{k} is not a verbatim phrase of the {'title (abstract-mismatch: title only)' if mismatch else 'title or abstract'}: {v[:60]!r}")
    # an entry its scorer wrote before A3.b found the abstract is judged on the text it saw: the title alone
    seen_less = bool(paper.get("abstract_filled_by")) and e.get("text_sha") != text_sha(paper)
    no_abs = mismatch or not has_abstract(paper) or seen_less
    if (e.get("rel") or 0) >= 3:
        need = ("problem",) if no_abs else ("problem", "method")
        for k in need:
            if str(ev.get(k) or "").strip().lower() == NOT_STATED:
                out.append(f"relevance {e['rel']} needs a quoted {k}")
    return out


def check_bib(cfg, rd) -> list[dict]:
    U = "A3.b"
    p = Path(rd) / "step3_bibliometrics.json"
    if not p.exists():
        return [F("ERROR", "B01", U, "no step3_bibliometrics.json: run `mcp_bridge.py bibliometrics <RD>`")]
    bib = read_json(p)
    fs = []
    ids = {c["id"] for c in candidates(rd)}
    lack = sorted(ids - set(bib.get("papers") or {}))
    if lack:
        fs.append(F("ERROR", "B01", U, f"{len(lack)} candidate(s) have no bibliometric record: {lack[:6]}"))
    for pid, r in (bib.get("papers") or {}).items():
        if r.get("impact") != impact_score(r):
            fs.append(F("ERROR", "B02", U, f"{pid}: impact {r.get('impact')} != {impact_score(r)} recomputed (edited by hand?)"))
            break
    if bib.get("basis") != basis_shas(rd):
        fs.append(F("ERROR", "B03", U, "STALE: the candidate collection changed after the bibliometrics: run it again"))
    return fs


def check_gate(cfg, rd) -> list[dict]:
    U = "A3.g"
    p = Path(rd) / "step3_gate.json"
    bp = Path(rd) / "step3_bibliometrics.json"
    if not p.exists():
        return [F("ERROR", "G01", U, "no step3_gate.json: run `ideate_tools.py screen-gate <RD>`")]
    g = read_json(p)
    fs = []
    if g.get("bib_sha") != sha256_file(bp):
        fs.append(F("ERROR", "G01", U, "STALE: the bibliometrics changed after the gate: run screen-gate again"))
    for e in g.get("excluded") or []:
        if e.get("code") not in GATE_CODES or not str(e.get("detail", "")).strip():
            fs.append(F("ERROR", "G02", U, f"{e.get('id')}: gate exclusion needs a code in {sorted(GATE_CODES)} and a detail"))
            break
    if bp.exists() and [(e["id"], e["code"]) for e in g.get("excluded") or []] != \
            [(e["id"], e["code"]) for e in gate_decisions(cfg, read_json(bp))]:
        fs.append(F("ERROR", "G03", U, "the gate differs from its recomputation (edited by hand?)"))
    return fs


def criteria_ids(cfg: dict) -> set:
    crit = (cfg.get("protocol") or {}).get("criteria") or {}
    return {c["id"] for c in crit.get("exclusion") or []} | {c["id"] for c in crit.get("inclusion") or []}


RECORD_PROBLEMS = {"abstract-mismatch"}


def _reasons(d) -> bool:
    return isinstance(d, dict) and bool(d) and all(isinstance(v, str) and len(v.split()) >= 3 for v in d.values())


def entry_problems(e: dict, paper: dict, ex_ids: set, soft: set = frozenset(), linked: set = frozenset(),
                   brief: int | None = None) -> list[tuple[str, str]]:
    """What is wrong with one scorer's entry on its own (C02, C03, C05, C16, C17, C18) - screen-merge refuses such an
    entry, so the paper is batched again, and a3-check reports one that got in. `brief` = the brief version the entry
    answered (`e["brief"]` once merged): an entry from a batch before brief 2 (§15) keeps the rules it was written
    under - a list of soft criteria, no reasons, no `no abstract:` rule."""
    out = []
    v2 = (brief if brief is not None else e.get("brief") or 1) >= 2
    softish = set(soft) | (set(linked) if v2 else set())
    if "record_problem" in e and e["record_problem"] not in RECORD_PROBLEMS:
        out.append(("C17", f"record_problem must be one of {sorted(RECORD_PROBLEMS)} (got {e['record_problem']!r})"))
    if "violates" in e:
        bad = [x for x in e.get("violates") or [] if x not in ex_ids]
        if not e.get("violates") or bad or not str(e.get("rationale", "")).strip():
            out.append(("C05", f"violates must name criteria of the protocol (got {bad or e.get('violates')}) with a rationale"))
        elif set(e["violates"]) <= softish and not v2:
            out.append(("C16", f"{e['violates']} are soft criteria only: score the paper and put them in soft_violates"))
        elif set(e["violates"]) <= softish:
            br = e.get("both_readings")
            if not _reasons(br) or set(br) != set(e["violates"]):
                out.append(("C16", f"{e['violates']} are soft or linked only: a paper that meets one under the other "
                                   "reading goes to soft_violates; one that fails both readings needs both_readings "
                                   "{criterion: why} for each of them"))
        if "both_readings" in e and not set(e.get("both_readings") or {}) <= softish:
            out.append(("C16", f"both_readings may only name soft or linked criteria ({sorted(softish) or 'none'})"))
        if "soft_violates" in e:
            out.append(("C16", "an excluded paper (violates) has no soft_violates"))
        return out
    if "both_readings" in e:
        out.append(("C16", "both_readings belongs to an excluded paper (violates)"))
    if "soft_violates" in e:
        sv = e.get("soft_violates")
        if v2:
            if not _reasons(sv) or set(sv) - softish:
                out.append(("C16", f"soft_violates must be {{criterion: how the paper meets it under the other reading}} "
                                   f"for soft or linked criteria of this topic ({sorted(softish) or 'none'}), got {sv!r}"))
        elif not isinstance(sv, list) or not sv or set(sv) - soft:
            out.append(("C16", f"soft_violates must name soft criteria of this topic ({sorted(soft) or 'none'}), got {sv!r}"))
    if "needs_text" in e and e["needs_text"] is not True:
        out.append(("C18", "needs_text is true or absent"))
    seen_less = bool(paper.get("abstract_filled_by")) and e.get("text_sha") != text_sha(paper)
    if v2 and (e.get("rel") or 0) >= 3 and (e.get("record_problem") == "abstract-mismatch" or not has_abstract(paper)
                                             or seen_less) \
            and not str(e.get("rationale", "")).strip().lower().startswith("no abstract:"):
        out.append(("C18", "a NO-ABSTRACT paper at relevance 3+ is judged on its title: the rationale starts "
                           "`no abstract:` (and never rests on what is known about the work from elsewhere)"))
    for ax in ("rel", "qual"):
        if not isinstance(e.get(ax), int) or not 1 <= e[ax] <= 5:
            out.append(("C02", f"{ax} must be an integer 1-5"))
    r = str(e.get("rationale", "")).strip()
    if not r or r.lower() in ("not relevant", "relevant", "off-topic"):
        out.append(("C02", "the rationale must be specific"))
    out += [("C03", msg) for msg in evidence_problems(e, paper)]
    return out


def check_scores(cfg, rd, scores: dict | None = None) -> list[dict]:
    U = "A3"
    fs = []
    scores = scores if scores is not None else (read_json(scores_path(rd)) if scores_path(rd).exists() else None)
    if scores is None:
        return [F("ERROR", "C01", U, "no screening_scores.json: screen-plan, the subagents, screen-merge")]
    papers = {p["id"]: p for p in candidates(rd)}
    gate = {e["id"] for e in read_json(Path(rd) / "step3_gate.json")["excluded"]} if (Path(rd) / "step3_gate.json").exists() else set()
    entries = list(scores.get("scores") or [])
    seen = Counter(e.get("id") for e in entries)
    bulk_ids = bulk_targets(scores, papers, gate, entries_only=True)
    covered = set(seen) | set(bulk_ids)
    need = set(papers) - gate
    lack = sorted(need - covered)
    if lack:
        fs.append(F("ERROR", "C01", U, f"{len(lack)} paper(s) have no entry (no paper may vanish): {lack[:8]}"))
    twice = sorted(i for i, n in seen.items() if n > 1)
    if twice:
        fs.append(F("ERROR", "C01", U, f"scored twice: {twice[:6]}"))
    unknown = sorted(set(seen) - set(papers))
    if unknown:
        fs.append(F("ERROR", "C01", U, f"entries for unknown papers: {unknown[:6]}"))
    raw = {p["id"] for p in read_json(Path(rd) / "step2_raw_papers.json")["papers"]}
    hidden = sorted(w.get("id") for w in scores.get("withdrawn") or [] if w.get("id") in papers or w.get("id") in raw)
    if hidden:
        fs.append(F("ERROR", "C15", U, f"withdrawn, yet a candidate or a search paper: {hidden[:6]} (only screen-plan / "
                                      "screen-merge withdraw, and only works the snowball dropped)"))
    ex_ids = criteria_ids(cfg)
    soft, linked = _soft_sets(rd)
    rationales = Counter(str(e.get("rationale", "")).strip() for e in entries if (e.get("rel") or 0) >= 3)
    fan = Path(rd) / "_state" / "fanout" / "A3"
    batch_ids = {}
    for f in fan.glob("batch_*.in.json") if fan.is_dir() else []:
        bi = read_json(f)
        batch_ids[bi["batch"]] = set(bi["ids"])
    for e in entries:
        pid = e.get("id")
        if pid not in papers:
            continue
        if "duplicate_of" in e:
            tgt = next((x for x in entries if x.get("id") == e["duplicate_of"]), None)
            if e["duplicate_of"] not in papers or tgt is None or "duplicate_of" in tgt:
                fs.append(F("ERROR", "C10", U, f"{pid}: duplicate_of must name a scored, non-duplicate paper"))
            if set(e.get("carry") or {}) - {"arxiv_id", "doi", "alt_dois", "oa_url"}:
                fs.append(F("ERROR", "C10", U, f"{pid}: carry may only move identifiers (arxiv_id, doi, alt_dois, oa_url)"))
        else:
            fs += [F("ERROR", code, U, f"{pid}: {msg}") for code, msg in entry_problems(e, papers[pid], ex_ids, soft, linked)]
            r = str(e.get("rationale", "")).strip()
            if "violates" not in e and (e.get("rel") or 0) >= 3 and rationales.get(r, 0) > 1:
                fs.append(F("ERROR", "C04", U, f"{pid}: rationale shared word for word with another included-range paper "
                                              f"(a template, not a judgement): {r[:60]!r}"))
        if "batch" not in e or "model" not in e:
            fs.append(F("ERROR", "C07", U, f"{pid}: entry without batch / model (write entries through screen-merge)"))
        elif batch_ids and pid not in batch_ids.get(e["batch"], set()):
            fs.append(F("ERROR", "C07", U, f"{pid}: entry claims batch {e['batch']}, which never contained it"))
    current = {e.get("id"): e for e in entries}
    for e in entries:
        rs = e.get("rescue") or e.get("rescore")
        if rs is None:
            continue
        if not str(rs.get("reason", "")).strip():
            fs.append(F("ERROR", "C12", U, f"{e.get('id')}: a rescue / rescore without a reason"))
        if rs.get("supersedes") != "bulk" and not any(x.get("id") == e.get("id") and x.get("batch") == rs.get("supersedes")
                                                      for x in scores.get("superseded") or []):
            fs.append(F("ERROR", "C12", U, f"{e.get('id')}: the rescued paper's earlier entry (batch {rs.get('supersedes')}) "
                                          "is not kept under `superseded`"))
    # a paper read again twice leaves a chain: each superseded entry points at a rescue / rescore that replaced it
    # (the current entry, or a later superseded one)
    again_batches = {}
    for x in list(scores.get("superseded") or []) + entries:
        if x.get("rescue") or x.get("rescore"):
            again_batches.setdefault(x.get("id"), set()).add(x.get("batch"))
    gone = {w.get("id") for w in scores.get("withdrawn") or []} - set(current)
    for x in scores.get("superseded") or []:
        if x.get("id") in gone:
            continue                                     # a work an A5 redo dropped: its readings are kept, unjudged
        cur = current.get(x.get("id"))
        if not cur or not (cur.get("rescue") or cur.get("rescore")) or \
                x.get("superseded_by") not in again_batches.get(x.get("id"), set()):
            fs.append(F("ERROR", "C12", U, f"{x.get('id')}: a superseded entry no rescue / rescore points at (entries are "
                                          "replaced only through screen-rescue or screen-plan --rescore, then screen-merge)"))
    for rule in scores.get("bulk") or []:
        if rule.get("rel", 1) > 2:
            fs.append(F("ERROR", "C06", U, f"bulk rule /{rule.get('title_regex')}/: rel must be <= 2"))
    for a in scores.get("criteria_amendments") or []:
        if not str(a.get("reason", "")).strip():
            fs.append(F("ERROR", "C09", U, "a criteria amendment without a reason"))
    b = scores.get("basis") or {}
    if b and (b.get("raw") != basis_shas(rd)["raw"] or b.get("gate") != sha256_file(Path(rd) / "step3_gate.json")):
        fs.append(F("ERROR", "C11", U, "STALE: the candidates or the gate changed after these scores were merged"))
    later = rescore_targets(rd, scores, list(papers.values()), gate, "filled")
    if later:
        fs.append(F("WARN", "C19", U, f"{len(later)} entr(y/ies) were scored on less text than the paper has now (A3.b "
                                     f"found the abstract later): `screen-plan --rescore filled` reads them again "
                                     f"({[x['id'] for x in later[:6]]})"))
    return fs


def bulk_targets(scores: dict, papers: dict, gate: set, entries_only=False) -> dict:
    """Papers a bulk rule scores: no explicit entry, title matches, and no anchor term and in the bottom
    quarter by sem_sim (when sem_sim exists). A rule never admits a paper (rel <= 2)."""
    explicit = {e.get("id") for e in scores.get("scores") or []}
    out = {}
    for rule in scores.get("bulk") or []:
        try:
            rx = re.compile(rule["title_regex"], re.I)
        except (KeyError, re.error):
            continue
        for pid, p in papers.items():
            if pid in explicit or pid in gate or pid in out or not rx.search(str(p.get("title") or "")):
                continue
            if p.get("anchor_match") is not False:
                continue
            if p.get("sem_pct") is not None and p["sem_pct"] >= LOW_SEM_PCT:
                continue
            out[pid] = {"id": pid, "rel": min(int(rule.get("rel", 1)), 2), "qual": int(rule.get("qual", 3)),
                        "rationale": "bulk: " + str(rule.get("rationale", "")).strip(), "bulk": True}
    return out


# ================================================================================================= build (A3 + A3.r)
def _novelty(rd: Path, included: list[dict]) -> dict:
    """1 - the highest cosine to any paper ranked above it (SPECTER2 vectors from A2.m's cache); None without vectors."""
    from it_search import _cos
    files = sorted((Path(rd) / "_state" / "embeddings").glob("specter2_base@*.jsonl"))
    if not files:
        return {}
    cache = {}
    for line in files[-1].read_text().splitlines():
        if line.strip():
            k, v = json.loads(line)
            cache[k] = v
    vecs = {}
    for p in included:
        k = hashlib.sha1(f"{p.get('title') or ''}. {p.get('abstract') or ''}".encode("utf-8")).hexdigest()
        if k in cache:
            vecs[p["id"]] = cache[k]
    out, seen = {}, []
    for p in included:
        v = vecs.get(p["id"])
        if v is None:
            continue
        out[p["id"]] = round(1 - max((_cos(v, u) for u in seen), default=0.0), 4) if seen else None
        seen.append(v)
    return out


def _apply_human(rd, papers, entries, bib, gate, included, excluded) -> None:
    """A person's include / exclude overrides (it_overrides), applied after the scores: final, marked, counted apart."""
    from it_overrides import entries as overrides
    human = {}
    for e in overrides(rd):
        if e.get("kind") in ("include", "exclude") and e.get("id") in papers and str(e.get("reason", "")).strip():
            human[e["id"]] = e                                   # the last entry for a paper wins
    for pid, e in human.items():
        who = e.get("by") or "a person"
        inc = next((q for q in included if q["id"] == pid), None)
        if e["kind"] == "exclude" and inc is not None:
            included.remove(inc)
            excluded.append((papers[pid], inc["screening"], "HUMAN", f"excluded by {who}: {e['reason']}"))
        elif e["kind"] == "include" and inc is None and (gate.get(pid) or {}).get("code") != "X-RET":
            for x in [x for x in excluded if x[0]["id"] == pid]:
                excluded.remove(x)
            ent = entries.get(pid) or {}
            imp = (bib.get(pid) or {}).get("impact")
            q = dict(papers[pid])
            if isinstance(ent.get("rel"), int) and isinstance(ent.get("qual"), int) and imp is not None:
                comp = round(ent["rel"] * 0.5 + ent["qual"] * 0.3 + imp * 0.2, 2)
                q["screening"] = {"relevance": ent["rel"], "quality": ent["qual"], "recency_impact": imp, "composite": comp,
                                  "tier": tier_of(comp), "arithmetic": f"{ent['rel']} × 0.50 + {ent['qual']} × 0.30 + "
                                  f"{imp} × 0.20 = {comp:.2f}", "rationale": ent.get("rationale"),
                                  "evidence": ent.get("evidence"), "batch": ent.get("batch"), "model": ent.get("model")}
            else:                                                # no score to show: placed at the borderline tier
                q["screening"] = {"relevance": None, "quality": None, "recency_impact": imp, "composite": INCLUDE_AT,
                                  "tier": 4, "arithmetic": "a person's decision (no score)", "rationale": ent.get("rationale")}
            q["screening"].update({"decided_by": "human", "human_reason": e["reason"], "human_by": who})
            q["impact"] = {k: (bib.get(pid) or {}).get(k) for k in ("type", "cites", "fwci", "cit_pct", "velocity",
                                                                    "velocity_pct", "in_degree", "in_pct", "out_degree",
                                                                    "venue", "venue_pct", "age")}
            included.append(q)


def roles_for(p: dict, imp: dict, nov_pct) -> list[str]:
    s = p["screening"]
    rel, qual = s["relevance"] or 0, s["quality"] or 0
    age = imp.get("age")
    roles = []
    if rel >= 4 and ((imp.get("in_pct") or 0) >= 80 or ((imp.get("cit_pct") or 0) >= 0.9 and (age or 0) >= 3)):
        roles.append("foundational")
    code = str((s.get("evidence") or {}).get("code") or NOT_STATED).lower() != NOT_STATED or bool(p.get("code_hint"))
    if rel >= 4 and (qual >= 4 or (code and qual >= 3)):
        roles.append("core-method")
    if rel >= 4 and age is not None and age <= COLD_YEARS and ((imp.get("velocity_pct") or 0) >= 70 or (nov_pct or 0) >= 80):
        roles.append("emerging")
    if imp.get("type") == "review" or ((imp.get("out_degree") or 0) >= 5 and (imp.get("out_pct") or 0) >= 90):
        roles.append("survey")
    return roles or ["supporting"]


def tier_of(c: float) -> int:
    return 1 if c >= 4.5 else 2 if c >= 4.0 else 3 if c >= 3.5 else 4


def is_included(rel, comp, paper=None) -> bool:
    """composite >= INCLUDE_AT; a paper no query matched (a snowball or dense-only addition) also needs relevance >=
    FLOOR_RELEVANCE, because a high composite from quality and impact alone admits widely cited toolboxes."""
    if comp < INCLUDE_AT:
        return False
    if (paper or {}).get("found_via") in ("snowball", "dense"):
        return rel >= FLOOR_RELEVANCE
    return True


def build(rd: Path, scores_file: Path) -> dict:
    """screen-build for a protocol topic. Refuses (writes nothing) unless every A3.b / A3.g / A3 check passes."""
    from it_common import last_name
    rd = Path(rd)
    cfg = _cfg(rd)
    scores = read_json(scores_file)
    fs = check_bib(cfg, rd) + check_gate(cfg, rd) + check_scores(cfg, rd, scores) + _check_overrides(rd)
    for f in fs:
        print(f"  {f['level']:<5} {f['code']} [{f['unit']}] {f['msg']}")
    if errors(fs):
        die(f"{len(errors(fs))} problem(s); nothing was written", 2)
    papers = {p["id"]: p for p in candidates(rd)}
    bib = read_json(rd / "step3_bibliometrics.json")["papers"]
    gate = {e["id"]: e for e in read_json(rd / "step3_gate.json")["excluded"]}
    entries = {e["id"]: e for e in scores["scores"]}
    entries.update(bulk_targets(scores, papers, set(gate)))
    prev = {}
    if (rd / "step3_shortlist.json").exists():
        prev = {p["id"]: p for p in read_json(rd / "step3_shortlist.json").get("papers", [])}
    included, excluded = [], []
    carry = {}
    for pid, e in entries.items():
        if "duplicate_of" in e:
            carry.setdefault(e["duplicate_of"], {}).update(e.get("carry") or {})
    for pid, p in papers.items():
        if pid in gate:
            excluded.append((p, None, gate[pid]["code"], gate[pid]["detail"]))
            continue
        e = entries[pid]
        if "duplicate_of" in e:
            excluded.append((p, None, "DUP", f"duplicate of {e['duplicate_of']}"))
            continue
        if "violates" in e:
            code = "+".join(e["violates"])
            if e.get("record_problem"):                  # judged on the title alone: A6's full text can rescue it
                excluded.append((p, None, "X-REC", f"{e['record_problem']}, judged on the title: {code}: {e['rationale']}"))
            else:
                excluded.append((p, None, code, e["rationale"]))
            continue
        imp = bib[pid]["impact"]
        soft_v = list(e.get("soft_violates") or [])
        rel = min(e["rel"], SOFT_RELEVANCE_CAP) if soft_v else e["rel"]   # §14: kept, at the borderline, ranked low
        comp = round(rel * 0.5 + e["qual"] * 0.3 + imp * 0.2, 2)
        arith = (f"{rel} × 0.50 + {e['qual']} × 0.30 + {imp} × 0.20 = {rel * 0.5:.2f} + {e['qual'] * 0.3:.2f} + "
                 f"{imp * 0.2:.2f} = {comp:.2f}" + (f" (relevance {e['rel']} capped at {SOFT_RELEVANCE_CAP}: violates "
                                                    f"soft {'+'.join(soft_v)})" if soft_v else ""))
        q = dict(p)
        q["screening"] = {"relevance": e["rel"], "quality": e["qual"], "recency_impact": imp, "composite": comp,
                          "tier": 4 if soft_v else tier_of(comp), "arithmetic": arith, "rationale": e["rationale"],
                          "evidence": e.get("evidence"), "batch": e.get("batch"), "model": e.get("model"),
                          "bulk": bool(e.get("bulk"))}
        if soft_v:
            q["screening"]["soft_violates"] = e["soft_violates"]          # {criterion: how it meets the other reading}
        if e.get("record_problem"):
            q["screening"]["record_problem"] = e["record_problem"]
        if e.get("needs_text"):
            q["screening"]["needs_text"] = True                           # the title did not settle it: A6 reads it first
        q["impact"] = {k: bib[pid].get(k) for k in ("type", "cites", "fwci", "cit_pct", "velocity", "velocity_pct",
                                                     "in_degree", "in_pct", "out_degree", "venue", "venue_pct", "age")}
        comp_free = round(e["rel"] * 0.5 + e["qual"] * 0.3 + imp * 0.2, 2)   # as if the soft criteria were absent
        if (soft_v and is_included(e["rel"], comp_free, q)) or (not soft_v and is_included(e["rel"], comp, q)):
            for k, v in carry.get(pid, {}).items():
                if not q.get(k):
                    q[k] = v
            if "access_level" in prev.get(pid, {}):            # A6's field; citation keys are projected by A4.k
                q["access_level"] = prev[pid]["access_level"]
            included.append(q)
        else:
            code = "FLOOR" if comp_free >= INCLUDE_AT else "SCORE"
            why = (f"{p.get('found_via')} paper with relevance {e['rel']} < 3: " if code == "FLOOR" else "") + e["rationale"]
            if e.get("record_problem"):
                code, why = "X-REC", f"{e['record_problem']}, judged on the title: {code}: {why}"
            excluded.append((p, q["screening"], code, why))
    _apply_human(rd, papers, entries, bib, gate, included, excluded)
    included.sort(key=lambda p: -p["screening"]["composite"])
    nov = _novelty(rd, included)
    nov_vals = [v for v in nov.values() if v is not None]
    for q in included:
        n = nov.get(q["id"])
        q["novelty"] = n
        q["novelty_pct"] = pct(n, nov_vals) if n is not None else None
        q["roles"] = roles_for(q, bib[q["id"]], q["novelty_pct"])
    tiers = {k: sum(1 for p in included if p["screening"]["tier"] == k) for k in (1, 2, 3, 4)}
    reasons = Counter(code for _, _, code, _ in excluded)
    gate_n = sum(n for c, n in reasons.items() if c in GATE_CODES)     # X-REC is a screening decision
    summary = {"candidates": len(papers), "gate_excluded": gate_n, "screened": len(papers) - gate_n,
               "included": len(included), "excluded": len(excluded), "excluded_by_reason": dict(reasons), "tiers": tiers,
               "decided_by_human": sum(1 for q in included if q["screening"].get("decided_by") == "human"),
               "soft_kept": sum(1 for q in included if q["screening"].get("soft_violates")),
               "record_problems": sum(1 for e in entries.values() if e.get("record_problem")),
               "needs_text": sum(1 for q in included if q["screening"].get("needs_text")),
               "abstract_filled": sum(1 for q in included if q.get("abstract_filled_by")),
               "roles": dict(Counter(r for p in included for r in p["roles"])), "basis": scores.get("basis")}
    out = {"topic": cfg.get("topic"), "schema": SHORTLIST_SCHEMA,
           "screening_config": {"include_at": INCLUDE_AT, "weights": WEIGHTS, "impact": "computed by A3.b",
                                "snowball_and_dense_min_relevance": 3, "soft_criteria": _soft(rd),
                                "soft_relevance_cap": SOFT_RELEVANCE_CAP},
           "summary": summary, "papers": included}
    write_json(rd / "step3_shortlist.json", out)
    write_text(rd / "step3_screening_results.md", render_results(cfg, scores, out, excluded, last_name))
    return out


def _cmd_build(a):
    from it_search import screen_gate
    rd = Path(a.research_dir)
    cfg = _cfg(rd)
    gate = screen_gate(cfg, rd)
    if gate:
        for f in gate[:12]:
            print(f"  {f['code']} [{f['unit']}] {f['msg']}")
        die(f"A2 is not done ({len(gate)} error(s)): `ideate_tools.py a2-check {rd}`", 2)
    out = build(rd, Path(a.scores_json))
    s = out["summary"]
    print(f"screen-build: {s['candidates']} candidates -> {s['included']} included {s['tiers']}, {s['excluded']} excluded "
          f"{s['excluded_by_reason']}; roles {s['roles']}")
    if s["included"] < 10:
        print("  WARNING: fewer than 10 papers survived - treat every gap and idea from this base as preliminary")
    if s["tiers"][1] >= 20:
        print("  WARNING: 20+ Tier 1 papers - the relevance anchors are probably too lenient; recalibrate")


def render_results(cfg, scores, out, excluded, last_name) -> str:
    s = out["summary"]
    crit = (cfg.get("protocol") or {}).get("criteria") or {}
    L = ["<!-- generated by `ideate_tools.py screen-build` (A3) - do not edit -->", "# Screening results", "",
         f"Topic: {cfg.get('topic')}  ",
         f"Candidates {s['candidates']} · mechanically excluded {s['gate_excluded']} · screened {s['screened']} · "
         f"included **{s['included']}** · excluded {s['excluded']}  ",
         "composite = relevance × 0.50 + quality × 0.30 + impact × 0.20 (impact computed from citations, the "
         "collection's own citation network and the venue; the scorer never saw them); included when composite >= 3.00; "
         "snowball and dense-only papers also need relevance >= 3", "",
         "## Criteria (A1.p)", "", "**Inclusion**", ""] + [f"- {c['id']} {c['text']}" for c in crit.get("inclusion") or []]
    L += ["", "**Exclusion**", ""] + [f"- {c['id']} {c['text']}" for c in crit.get("exclusion") or []]
    soft = (out.get("screening_config") or {}).get("soft_criteria") or {}
    if soft:
        L += ["", "**Soft criteria (A1.e E6)** - a paper violating only these is kept at tier 4, its composite computed on "
                  f"relevance <= {SOFT_RELEVANCE_CAP} ({s.get('soft_kept', 0)} kept)", ""]
        L += [f"- {k}: \"{v.get('word')}\" may also mean {v.get('alt_reading')}"
              + (f" (linked: {', '.join(v['linked'])} read the same way)" if v.get("linked") else "")
              for k, v in sorted(soft.items())]
    if s.get("abstract_filled") or s.get("needs_text"):
        L += ["", f"**Text**: {s.get('abstract_filled', 0)} included paper(s) were scored on an abstract A3.b found "
                  f"(OpenAlex / Semantic Scholar); {s.get('needs_text', 0)} have no abstract and a title that did not "
                  "settle them (`needs_text`): A6 reads their full text first"]
    if s.get("record_problems"):
        L += ["", f"**Records judged on the title only** (abstract of another paper): {s['record_problems']}; excluded ones "
                  "carry code X-REC"]
    if scores.get("criteria_amendments"):
        L += ["", "**Amendments (A3)**", ""] + [f"- {a['change']} — {a['reason']}" for a in scores["criteria_amendments"]]
    L += ["", "## Exclusions by reason (PRISMA screening)", "", "| Reason | Papers |", "|---|---|"]
    L += [f"| {c} | {n} |" for c, n in sorted(s["excluded_by_reason"].items())]
    L += ["", "## Reading roles", "", " · ".join(f"{r}: {s['roles'].get(r, 0)}" for r in ROLE_ORDER), ""]
    names = {1: "Tier 1 - core (>= 4.50)", 2: "Tier 2 - strong supporting (4.00-4.49)", 3: "Tier 3 - contextual (3.50-3.99)",
             4: "Tier 4 - borderline, auto-included (3.00-3.49)"}
    for k in (1, 2, 3, 4):
        rows = [p for p in out["papers"] if p["screening"]["tier"] == k]
        L += [f"## {names[k]} — {len(rows)} papers", "", "| ID | Title | First author | Year | Roles | Arithmetic | Rationale |",
              "|---|---|---|---|---|---|---|"]
        for p in rows:
            au = p.get("authors") or []
            L.append(f"| {p['id']} | {str(p.get('title'))[:80]} | {last_name(au[0]) if au else '-'} | {p.get('year')} | "
                     f"{', '.join(p['roles'])} | {p['screening']['arithmetic']} | "
                     + (f"**{p['screening'].get('human_by')}:** {p['screening'].get('human_reason')} · "
                        if p['screening'].get('decided_by') == 'human' else "")
                     + f"{str(p['screening']['rationale']).replace('|', '/')} |")
        L.append("")
    resc = [e for e in scores.get("scores") or [] if e.get("rescue")]
    if resc:
        inc = {p["id"] for p in out["papers"]}
        L += [f"## Read again on request — {len(resc)} papers", "", "| ID | Asked by | Reason | Result |", "|---|---|---|---|"]
        L += [f"| {e['id']} | {e['rescue'].get('by') or '-'} | {str(e['rescue'].get('reason')).replace('|', '/')[:140]} | "
              f"{'included' if e['id'] in inc else 'excluded'} |" for e in resc]
        L.append("")
    L += [f"## Excluded — {len(excluded)} papers", "", "| ID | Title | Year | Reason | Detail |", "|---|---|---|---|---|"]
    L += [f"| {p['id']} | {str(p.get('title'))[:80]} | {p.get('year')} | {code} | {str(why).replace('|', '/')[:140]} |"
          for p, _, code, why in excluded]
    return "\n".join(L) + "\n"


def _check_overrides(rd) -> list[dict]:
    import it_overrides
    papers = {p["id"]: p for p in candidates(rd)} if (Path(rd) / "step2_raw_papers.json").exists() else None
    gate = {e["id"]: e for e in read_json(Path(rd) / "step3_gate.json")["excluded"]} if (Path(rd) / "step3_gate.json").exists() else {}
    return [f for f in it_overrides.check(rd, papers, gate) if f["unit"] == "A3"]


def check_shortlist(cfg, rd) -> list[dict]:
    fs = _shortlist_errors(cfg, rd)
    p = Path(rd) / "step3_shortlist.json"
    sl = read_json(p) if p.exists() else {}
    papers = sl.get("papers") or [] if sl.get("schema") == SHORTLIST_SCHEMA else []
    kept = [q["id"] for q in papers if (q.get("screening") or {}).get("soft_violates")]
    if papers and len(kept) > SOFT_SHARE_WARN * len(papers):
        fs.append(F("WARN", "C20", "A3", f"{len(kept)} of {len(papers)} included papers are kept only by a soft "
                                        f"criterion (> {SOFT_SHARE_WARN:.0%}): look at a few - is the other reading the "
                                        f"topic's, or should the protocol say so? ({kept[:6]})"))
    return fs


def _shortlist_errors(cfg, rd) -> list[dict]:
    U = "A3"
    p = Path(rd) / "step3_shortlist.json"
    if not p.exists():
        return [F("ERROR", "C08", U, "no step3_shortlist.json: run screen-build")]
    sl = read_json(p)
    if sl.get("schema") != SHORTLIST_SCHEMA:
        return [F("ERROR", "C08", U, "step3_shortlist.json was not written by screen-build")]
    bib = read_json(Path(rd) / "step3_bibliometrics.json")["papers"] if (Path(rd) / "step3_bibliometrics.json").exists() else {}
    from it_overrides import entries as overrides
    human = {e["id"]: e for e in overrides(rd) if e.get("kind") in ("include", "exclude") and e.get("id")}
    gate = {e["id"]: e for e in read_json(Path(rd) / "step3_gate.json")["excluded"]} if (Path(rd) / "step3_gate.json").exists() else {}
    ids = {q["id"] for q in sl["papers"]}
    for q in sl["papers"]:
        if (q["screening"].get("decided_by") == "human") != ((human.get(q["id"]) or {}).get("kind") == "include"):
            return [F("ERROR", "C14", U, f"{q['id']}: a person's decision in the shortlist that no include override backs "
                                         "(or an include override not applied: run screen-build)")]
    for pid, e in human.items():
        if e["kind"] == "exclude" and pid in ids:
            return [F("ERROR", "C14", U, f"{pid}: a person's exclusion not applied: run screen-build")]
        if e["kind"] == "include" and pid not in ids and (gate.get(pid) or {}).get("code") != "X-RET":
            return [F("ERROR", "C14", U, f"{pid}: a person's inclusion not applied: run screen-build")]
    for q in sl["papers"]:
        s = q["screening"]
        if s.get("decided_by") == "human" and s.get("relevance") is None:
            if s["composite"] != INCLUDE_AT or s["tier"] != 4:
                return [F("ERROR", "C08", U, f"{q['id']}: an unscored inclusion by a person sits at {INCLUDE_AT}, tier 4")]
            continue
        soft_v = bool(s.get("soft_violates"))                         # recomputed as build does: rel capped, tier 4
        rel = min(s["relevance"], SOFT_RELEVANCE_CAP) if soft_v else s["relevance"]
        comp = round(rel * 0.5 + s["quality"] * 0.3 + s["recency_impact"] * 0.2, 2)
        tier = 4 if soft_v else tier_of(comp)
        if comp != s["composite"] or s["tier"] != tier or s["recency_impact"] != (bib.get(q["id"]) or {}).get("impact"):
            return [F("ERROR", "C08", U, f"{q['id']}: composite / tier / impact differ from their recomputation "
                                         "(the shortlist was edited by hand)")]
        if q.get("roles") != roles_for(q, bib.get(q["id"]) or {}, q.get("novelty_pct")):
            return [F("ERROR", "C08", U, f"{q['id']}: roles differ from their recomputation")]
    if (sl.get("summary") or {}).get("basis") != (read_json(scores_path(rd)).get("basis") if scores_path(rd).exists() else None):
        return [F("ERROR", "C08", U, "STALE: the scores changed after the shortlist was built: run screen-build")]
    return []


def run_checks(cfg, rd, unit="all") -> list[dict]:
    require_protocol(cfg, rd)
    fs = []
    if unit in ("all", "A3.b"):
        fs += check_bib(cfg, rd)
    if unit in ("all", "A3.g"):
        fs += check_gate(cfg, rd)
    if unit in ("all", "A3"):
        fs += check_scores(cfg, rd) + check_shortlist(cfg, rd) + _check_overrides(rd)
    return fs


def export_gate(cfg, rd) -> list[dict]:
    """What A4 requires of A3 before it may export (protocol topics only)."""
    return errors(run_checks(cfg, rd))


def cmd_a3_check(a):
    rd = Path(a.research_dir)
    fs = run_checks(_cfg(rd), rd, a.unit)
    if a.json:
        print(json.dumps(fs, indent=2, ensure_ascii=False))
    else:
        for f in fs:
            print(f"  {f['level']:<5} {f['code']} [{f['unit']}] {f['msg']}")
        print("OK" if not errors(fs) else f"{len(errors(fs))} error(s)")
    raise SystemExit(1 if errors(fs) else 0)


# ---------------------------------------------------------------------------------------------- ledger boundaries
async def run_bibliometrics(server, cfg: dict, rd: Path, *args, **kw) -> dict:
    from it_ledger import degraded_codes, run_unit
    with run_unit(rd, "A3.b", check=lambda: check_bib(_cfg(Path(rd)), Path(rd)), degraded=lambda: degraded_codes(rd, "A3.b")):
        return await _run_bibliometrics(server, cfg, rd, *args, **kw)


def cmd_gate(a):
    from it_ledger import run_unit
    rd = Path(a.research_dir)
    with run_unit(rd, "A3.g", check=lambda: check_gate(_cfg(rd), rd)):
        _cmd_gate(a)


def _human_rereads(rd: Path) -> None:
    """A person's `reread` overrides become rescue batches (once each), before the unscored papers are batched."""
    from types import SimpleNamespace
    from it_ledger import note
    from it_overrides import entries as overrides
    scores = load_scores(rd)
    fan = rd / "_state" / "fanout" / "A3"
    sl = {q["id"] for q in read_json(rd / "step3_shortlist.json")["papers"]} if (rd / "step3_shortlist.json").exists() else set()
    for e in overrides(rd, "reread"):
        pid, who = e.get("id"), e.get("by") or "a person"
        if not pid or pid in sl or not str(e.get("reason", "")).strip():
            continue
        done_ = any(x.get("id") == pid and (x.get("rescue") or {}).get("reason") == e["reason"] for x in scores.get("scores") or [])
        waiting = any(pid in read_json(f)["ids"] and read_json(f).get("rescue", {}).get("reason") == e["reason"]
                      for f in fan.glob("batch_*.in.json")) if fan.is_dir() else False
        if done_ or waiting:
            continue
        _cmd_rescue(SimpleNamespace(research_dir=str(rd), paper_id=pid, reason=e["reason"], by=who))
        note(rd, "A3", "override", kind="reread", id=pid, by=who)


def cmd_plan(a):
    """A3 begins with the batches (a person's rereads first); screen-build closes it."""
    from it_ledger import begin
    _human_rereads(Path(a.research_dir))
    _cmd_plan(a)
    begin(a.research_dir, "A3")


def cmd_rescue(a):
    from it_ledger import begin
    _cmd_rescue(a)
    begin(a.research_dir, "A3")


def cmd_build(a):
    from it_ledger import _begin_event, _events, begin, degraded_codes, done
    rd = Path(a.research_dir)
    if _begin_event(_events(rd), "A3", "-")[1] is None:
        begin(rd, "A3")
    try:
        _cmd_build(a)
    except BaseException as e:  # noqa: BLE001
        from it_ledger import fail
        fail(rd, "A3", f"{type(e).__name__}: {str(e)[:160]}")
        raise
    done(rd, "A3", degraded=degraded_codes(rd, "A3"))


def add_parsers(sub) -> None:
    sp = sub.add_parser("screen-gate", help="A3.g: mechanical exclusions (references/search/A3-screen.md#a3g)")
    sp.add_argument("research_dir")
    sp.set_defaults(fn=cmd_gate)
    sp = sub.add_parser("screen-plan", help="A3: the brief and the batches for the scoring subagents")
    sp.add_argument("research_dir")
    sp.add_argument("--size", type=int, default=BATCH_SIZE)
    sp.add_argument("--rescore", action="append", choices=sorted(RESCORE_REASONS),
                    help="also batch entries to read again: soft (scored before brief 2 on a soft or linked criterion), "
                         "filled (scored before A3.b found the abstract); the answer supersedes the earlier entry")
    sp.set_defaults(fn=cmd_plan)
    sp = sub.add_parser("screen-merge", help="A3: merge the subagents' answers into screening_scores.json")
    sp.add_argument("research_dir")
    sp.set_defaults(fn=cmd_merge)
    sp = sub.add_parser("screen-amend", help="A3: record a criteria amendment with its reason")
    sp.add_argument("research_dir")
    sp.add_argument("input_json")
    sp.set_defaults(fn=cmd_amend)
    sp = sub.add_parser("screen-rescue", help="A3: a second, blind reading of one excluded paper (asked for by Stage B)")
    sp.add_argument("research_dir")
    sp.add_argument("paper_id")
    sp.add_argument("--reason", required=True, help="why a later step needs this paper read again")
    sp.add_argument("--by", default="", help="who asks, e.g. gen_3")
    sp.set_defaults(fn=cmd_rescue)
    sp = sub.add_parser("screen-build", help="A3: composite, inclusion, tiers, roles -> step3_shortlist.json")
    sp.add_argument("research_dir")
    sp.add_argument("scores_json")
    sp.set_defaults(fn=cmd_build)
    sp = sub.add_parser("a3-check", help="A3 handoff checks (A3.b, A3.g, A3)")
    sp.add_argument("research_dir")
    sp.add_argument("--unit", default="all", choices=["all", "A3.b", "A3.g", "A3"])
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_a3_check)
