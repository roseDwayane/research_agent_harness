"""A5 snowball - fill the keyword search's blind spots along the citation graph (rules: references/search/A5-snowball.md).

  backward     works outside the collection that many included papers cite (A3.b's reference lists: every included
               paper is a seed, no network for the counting)
  co-citation  works outside the collection that the papers citing two or more seeds also cite (their own reference
               lists) - a pool of its own, with its own threshold and cap
  forward      papers that cite two or more seeds (OpenAlex `cites:`; seeds = the foundational and core-method roles)
  similar      Semantic Scholar's embedding neighbours of the core-method and emerging papers (skipped without access)
                                                                    -> step2b_snowball_papers.json
New papers enter A3 (bibliometrics, gate, scoring, build) and need relevance >= 3 there, like every snowball addition.

  mcp_bridge.py snowball <RD> [--round 2]       refuses before A3 passes
  ideate_tools.py a5-check <RD> [--json]
"""

from __future__ import annotations

import json
import math
import re
import asyncio
from collections import Counter
from pathlib import Path

from it_common import (die, http_json, norm_title, now_iso, preflight_says, quote, read_json, replaying,
                       require_protocol, sha256_file, smoke_cap, write_json)

SCHEMA = "ideate-snowball/2"
BACKWARD_MIN, BACKWARD_SHARE, BACKWARD_CAP = 3, 0.02, smoke_cap(40)    # cited by >= max(3, 2% of the included papers); <= 40
COCITE_CAP = smoke_cap(20)               # co-cited by >= max(3, 2% of the citers of two or more seeds); <= 20, a pool of its own
FORWARD_SEEDS, FORWARD_PER_SEED, FORWARD_MIN, FORWARD_CAP = 10, 200, 2, smoke_cap(40)
SIMILAR_SEEDS, SIMILAR_CAP = 10, smoke_cap(30)
SIMILAR_RETRY_WAIT = 120          # seconds before the one retry of recommendations after a 429 (§15 G4)
ROUND2_GROWTH = 0.10          # a second round only when the first grew the included set by >= 10%
SELECT = ("id,doi,title,publication_year,publication_date,authorships,primary_location,cited_by_count,type,"
          "abstract_inverted_index,referenced_works,ids")


def F(level, code, unit, msg):
    return {"level": level, "code": code, "unit": unit, "msg": msg}


def errors(fs):
    return [f for f in fs if f["level"] == "ERROR"]


def _short(x) -> str:
    return str(x or "").rsplit("/", 1)[-1]


def _paper_from_openalex(w: dict) -> dict:
    src = (w.get("primary_location") or {}).get("source") or {}
    inv = w.get("abstract_inverted_index") or {}
    abstract = " ".join(t for _, t in sorted((i, t) for t, ps in inv.items() for i in ps)) if inv else None
    ids = w.get("ids") or {}
    pmid = str(ids.get("pmid") or "").rsplit("/", 1)[-1] or None
    return {"title": w.get("title"), "authors": [((a.get("author") or {}).get("display_name"))
                                                 for a in w.get("authorships") or [] if (a.get("author") or {}).get("display_name")],
            "year": w.get("publication_year"), "journal": src.get("display_name"),
            "doi": str(w.get("doi") or "").lower().removeprefix("https://doi.org/") or None,
            "url": w.get("doi") or w.get("id"), "abstract": abstract, "citation_count": w.get("cited_by_count"),
            "sources_found_in": ["openalex"], "openalex_id": _short(w.get("id")), "pubmed_id": pmid,
            "arxiv_id": None, "has_abstract": bool(abstract)}


def threshold(n_included: int) -> int:
    """max(3, 2 % of the population counted): the included papers for backward, the two-seed citers for co-citation."""
    return max(BACKWARD_MIN, math.ceil(BACKWARD_SHARE * n_included))


def fallback_threshold(answered: int) -> int:
    """Only <= 10 seeds answer in the Semantic Scholar fallback: a reference shared by a quarter of them (at least 2)."""
    return max(2, math.ceil(answered / 4))


def seeds_for(sl: dict, roles: tuple, cap: int) -> list[dict]:
    pool = [p for p in sl["papers"] if p.get("found_via") not in ("snowball",) and set(p.get("roles") or []) & set(roles)]
    return sorted(pool, key=lambda p: -p["screening"]["composite"])[:cap]


def forward_seeds(rd: Path, sl: dict) -> tuple[list[dict], list[dict]]:
    """The forward seeds: the rule (foundational + core-method, top 10 by composite), then a person's seed overrides
    (`_human/search_overrides.json`, kind seed: add a shortlisted paper, or remove one). Returns (seeds, applied)."""
    from it_overrides import entries as overrides
    seeds = seeds_for(sl, ("foundational", "core-method"), FORWARD_SEEDS)
    by_id = {p["id"]: p for p in sl["papers"]}
    applied = []
    for e in overrides(rd, "seed"):
        pid = e.get("id")
        if e.get("action") == "remove" and any(p["id"] == pid for p in seeds):
            seeds = [p for p in seeds if p["id"] != pid]
            applied.append({"id": pid, "action": "remove", "reason": e.get("reason")})
        elif e.get("action") == "add" and pid in by_id and all(p["id"] != pid for p in seeds):
            seeds.append(by_id[pid])
            applied.append({"id": pid, "action": "add", "reason": e.get("reason")})
    return seeds, applied


def _known(rd: Path, prev: dict | None) -> tuple[set, set, set]:
    """openalex ids, DOIs and normalised titles already in the collection: the search's papers and the earlier
    rounds' (`prev`, as preflight returns it - a round being redone does not count its own earlier additions)."""
    papers = list(read_json(rd / "step2_raw_papers.json")["papers"]) + list((prev or {}).get("papers") or [])
    ids = {p["id"] for p in papers}
    bib = read_json(rd / "step3_bibliometrics.json")["papers"]
    oa = {r.get("openalex_id") for i, r in bib.items() if i in ids and r.get("openalex_id")} | \
        {p.get("openalex_id") for p in papers if p.get("openalex_id")}
    return oa, {str(p.get("doi") or "").lower() for p in papers if p.get("doi")}, {norm_title(p.get("title")) for p in papers}


def _fetch_works(rd, ids, mailto, fetch, select=SELECT):
    out = {}
    for i in range(0, len(ids), 40):
        chunk = ids[i:i + 40]
        url = (f"https://api.openalex.org/works?filter={quote('openalex:' + '|'.join(chunk))}&per-page=50"
               f"&mailto={quote(mailto)}&select={select}")
        try:
            for w in fetch(url, rd).get("results") or []:
                out[_short(w.get("id"))] = w
        except Exception:  # noqa: BLE001
            pass
    return out


async def _s2_backward(server, seeds, known_doi, known_title) -> tuple[dict, int]:
    """References of each seed from Semantic Scholar, counted by normalised title. Returns ({key: {n, by, rec}}, the
    number of seeds that answered)."""
    out, answered = {}, 0
    for sp in seeds:
        pid = f"DOI:{sp['doi']}" if sp.get("doi") else (f"ARXIV:{sp['arxiv_id']}" if sp.get("arxiv_id") else None)
        if not pid:
            continue
        r = await server.call("scholar_snowball", {"paper_id": pid, "limit": 80})
        if not isinstance(r, dict) or not r.get("references"):
            continue                  # an empty list is no answer: it would only raise the threshold
        answered += 1
        for ref in r["references"]:
            k = norm_title(ref.get("title"))
            doi = str(ref.get("doi") or "").lower()
            if len(k) < 12 or k in known_title or (doi and doi in known_doi) or not ref.get("authors"):
                continue
            e = out.setdefault(f"s2t:{k}", {"n": 0, "by": [], "rec": {
                **{f: ref.get(f) for f in ("title", "authors", "year", "journal", "doi", "url", "abstract",
                                           "citation_count", "semantic_scholar_id", "arxiv_id", "pubmed_id")},
                "doi": doi or None, "sources_found_in": ["semantic_scholar"]}})
            e["n"] += 1
            e["by"].append(sp["id"])
    return out, answered


def _directions(k, back, cocite, t, t_co) -> list[str]:
    return [d for d, ok in (("backward", back.get(k, 0) >= t), ("cocitation", cocite.get(k, 0) >= t_co)) if ok]


def _finish(cfg: dict, p: dict, round_no: int) -> None:
    from it_search import CODE_HINT
    anchors = [str(x).lower() for x in cfg.get("anchor_terms") or []]
    blob = f"{p.get('title') or ''} {p.get('abstract') or ''}".lower()
    p["anchor_match"] = any(x in blob for x in anchors) if anchors else None
    p["has_abstract"] = bool(str(p.get("abstract") or "").strip())
    m = CODE_HINT.search(str(p.get("abstract") or ""))
    p["code_hint"] = m.group(0) if m else None
    p["retired_only"] = False
    p["round"] = round_no


def add_sem(cfg: dict, rd: Path, papers: list[dict], embedder) -> str:
    """sem_sim of each addition; sem_pct = its percentile among the SEARCH collection's sem_sim (A2.m), so A3's
    bulk-rule guard (sem_pct < 25) means the same thing for a snowball paper as for a searched one."""
    from it_screen import pct
    from it_search import add_sem_sim
    if not papers:
        return "nothing to embed"
    raw = [x.get("sem_sim") for x in read_json(Path(rd) / "step2_raw_papers.json")["papers"] if x.get("sem_sim") is not None]
    if embedder is None or not raw:
        return "not enabled: " + ("allenai/specter2_base is not in the Hugging Face cache" if embedder is None
                                  else "the search collection has no sem_sim")
    note = add_sem_sim(cfg, papers, embedder)
    for x in papers:
        x["sem_pct"] = pct(x["sem_sim"], raw)
    return note + "; sem_pct against the search collection"


_ANNOUNCED: set = set()


def preflight(cfg: dict, rd: Path, round_no: int = 1):
    """Refuse before any network call: A3 must pass, the round must be allowed. Returns the previous snowball file
    (or None) - the bridge runs this before it starts the scholar server, so a refusal is one line, not a traceback."""
    from it_screen import errors as a3_errors, run_checks as a3_checks
    rd = Path(rd)
    if round_no not in (1, 2):
        die("one round; a second only after >= 10% growth of the included set", 2)
    gate = a3_errors(a3_checks(cfg, rd))
    if gate:
        for f in gate[:10]:
            print(f"  {f['code']} [{f['unit']}] {f['msg']}")
        die("A3 is not done: the snowball starts from a current shortlist (`ideate_tools.py a3-check`)", 2)
    sbp = rd / "step2b_snowball_papers.json"
    prev = read_json(sbp) if sbp.exists() else None
    if prev and prev.get("schema") != SCHEMA:
        prev = None                                      # a file another tool wrote is replaced, never extended
    done = {r["round"] for r in (prev or {}).get("rounds") or []}
    if round_no in done:
        from it_ledger import unit_state
        st = unit_state(rd, "A5")
        if st["state"] == "done":
            die(f"round {round_no} already ran and A5 is current", 2)
        if (str(rd), round_no) not in _ANNOUNCED and st["state"] != "running":    # preflight runs up to three times
            _ANNOUNCED.add((str(rd), round_no))
            print(f"A5 is {st['state']} ({st['why']}): round {round_no} is redone, later rounds dropped")
        prev = {**prev, "rounds": [r for r in prev["rounds"] if r["round"] < round_no],
                "caveats": [c for c in prev.get("caveats") or [] if (c.get("round") or 1) < round_no],
                "papers": [x for x in prev.get("papers") or [] if (x.get("round") or 1) < round_no]}
    if round_no == 2:
        g = growth(rd)
        if 1 not in done or g is None or g < ROUND2_GROWTH:
            die(f"no second round: round 1 grew the included set by {(g or 0):.1%} (< {ROUND2_GROWTH:.0%})", 2)
    return prev


async def _run_snowball(server, cfg: dict, rd: Path, mailto: str, fetch=http_json, round_no: int = 1,
                       embedder="auto") -> dict:
    from it_search import assign_ids, load_embedder
    rd = Path(rd)
    prev = preflight(cfg, rd, round_no)
    sl = read_json(rd / "step3_shortlist.json")
    bib = read_json(rd / "step3_bibliometrics.json")["papers"]
    sbp = rd / "step2b_snowball_papers.json"
    if round_no == 1:
        citing = [p for p in sl["papers"] if p.get("found_via") != "snowball"]
        seeds, seed_overrides = forward_seeds(rd, sl)
    else:                          # round 2: what round 1 brought in and A3 kept seeds the next step
        r1 = {p["id"] for p in prev["papers"] if p.get("round") == 1}
        citing = sorted([p for p in sl["papers"] if p["id"] in r1], key=lambda p: -p["screening"]["composite"])
        seeds = citing[:FORWARD_SEEDS]
    known_oa, known_doi, known_title = _known(rd, prev)
    t = threshold(len(citing))
    status, caveats = {}, []
    # ---- backward: references the included papers share (no network for the counting)
    with_refs = [p for p in citing if (bib.get(p["id"]) or {}).get("refs")]
    back, back_by = Counter(), {}
    for p in with_refs:
        for x in set(bib[p["id"]]["refs"]) - known_oa:
            back[x] += 1
            back_by.setdefault(x, []).append(p["id"])
    status["backward"] = {"status": "ok" if with_refs else "skipped", "citing_papers_with_refs": len(with_refs),
                          "of": len(citing), "threshold": t}
    s2_back = {}                   # Semantic Scholar only when OpenAlex has no reference list at all
    if not with_refs and server is not None:
        s2_back, answered = await _s2_backward(server, seeds_for(sl, ("foundational", "core-method"), FORWARD_SEEDS)
                                               or citing[:FORWARD_SEEDS], known_doi, known_title)
        t_s2 = fallback_threshold(answered)
        s2_back = {k: v for k, v in s2_back.items() if answered and v["n"] >= t_s2}
        status["backward"] = {"status": "ok" if answered else "skipped", "via": "semantic_scholar (fallback)",
                              "citing_papers_with_refs": answered, "of": len(citing), "threshold": t,
                              "threshold_fallback": t_s2}
        caveats.append({"code": "backward-fallback", "text": f"no included paper has an OpenAlex reference list: backward "
                        f"came from Semantic Scholar references of {answered} seed(s), kept when shared by >= {t_s2}",
                        "must_disclose": False})
    if status["backward"]["status"] == "skipped":
        status["backward"]["why"] = "no included paper has an OpenAlex reference list" + \
            (" and Semantic Scholar answered for no seed" if server is not None else "")
    elif with_refs and len(with_refs) < 0.5 * len(citing):
        caveats.append({"code": "refs-sparse", "text": f"only {len(with_refs)}/{len(citing)} included papers have OpenAlex "
                        "reference lists: backward counts are thin", "must_disclose": False})
    # ---- forward (and the citers' own references, for co-citation)
    seeded = [p for p in seeds if (bib.get(p["id"]) or {}).get("openalex_id")]
    years = re.findall(r"\d{4}", str((cfg.get("protocol") or {}).get("timeframe") or ""))
    span = (f",from_publication_date:{years[0]}-01-01" if years else "") + \
           (f",to_publication_date:{years[1]}-12-31" if len(years) > 1 else "")
    citers, fwd_by, failed = {}, {}, 0
    for seed in seeded:
        s_oa = bib[seed["id"]]["openalex_id"]
        url = (f"https://api.openalex.org/works?filter={quote('cites:' + s_oa + span)}&sort=publication_date:desc"
               f"&per-page={FORWARD_PER_SEED}&mailto={quote(mailto)}&select={SELECT}")
        try:
            res = fetch(url, rd).get("results") or []
        except Exception:  # noqa: BLE001 - counted as a failed seed
            failed += 1
            continue
        for w in res:
            k = _short(w.get("id"))
            citers[k] = w
            fwd_by.setdefault(k, set()).add(seed["id"])
    ok = bool(seeded) and failed < len(seeded)
    status["forward"] = {"status": "ok" if ok else "skipped", "seeds": [p["id"] for p in seeds],
                         "seed_overrides": seed_overrides if round_no == 1 else [],
                         "failed_seeds": failed, "citers_seen": len(citers), "min_seeds": FORWARD_MIN}
    if not ok:
        status["forward"]["why"] = ("no included paper holds the foundational or core-method role" if not seeds else
                                    "no seed has an OpenAlex id" if not seeded else "every OpenAlex `cites:` request failed")
    seed_oa = {bib[p["id"]]["openalex_id"] for p in seeded}

    def new_work(w) -> bool:
        doi = str(w.get("doi") or "").lower().removeprefix("https://doi.org/")
        return _short(w.get("id")) not in known_oa and (not doi or doi not in known_doi) \
            and norm_title(w.get("title")) not in known_title
    fwd = {k: v for k, v in fwd_by.items() if len(v) >= FORWARD_MIN and new_work(citers[k])}
    fwd_ranked = sorted(fwd, key=lambda k: (len(fwd[k]), str(citers[k].get("publication_date") or "")), reverse=True)
    fwd_keep = fwd_ranked[:FORWARD_CAP]
    # co-citation: what the papers citing two or more seeds also cite - works co-cited with the seed set. A citer of
    # one seed may have used one method; counting all citers fills the pool with generic statistics and toolboxes.
    two_seed = [k for k, v in fwd_by.items() if len(v) >= FORWARD_MIN]
    t_co = threshold(len(two_seed))
    cocite = Counter()
    for k in two_seed:
        for x in {_short(r) for r in citers[k].get("referenced_works") or []} - known_oa - seed_oa:
            cocite[x] += 1
    status["cocitation"] = {"status": "ok" if two_seed else "skipped", "counted_from_citers": len(two_seed),
                            "threshold": t_co}
    if not two_seed:
        status["cocitation"]["why"] = "no paper cites two or more seeds" if ok else "no forward citers to count from"
    # ---- two pools, each ranked by its own count, each with its own cap
    back_ranked = sorted((k for k, n in back.items() if n >= t), key=lambda k: (-back[k], k))
    back_keep = back_ranked[:BACKWARD_CAP]
    co_ranked = sorted((k for k, n in cocite.items() if n >= t_co and k not in set(back_keep)), key=lambda k: (-cocite[k], k))
    co_keep = co_ranked[:COCITE_CAP]
    # ---- similar (Semantic Scholar recommendations)
    sim_seeds = seeds_for(sl, ("core-method", "emerging"), SIMILAR_SEEDS)
    sim_ids = [f"DOI:{p['doi']}" for p in sim_seeds if p.get("doi")]
    sim_papers = []
    if not sim_ids:
        status["similar"] = {"status": "skipped", "seeds": [], "why": "no core-method / emerging paper with a DOI"}
    elif server is None:
        status["similar"] = {"status": "skipped", "seeds": [p["id"] for p in sim_seeds], "why": "no scholar server"}
    elif (preflight_says(rd, "semantic_scholar") or (True, ""))[0] is False:
        status["similar"] = {"status": "skipped", "seeds": [p["id"] for p in sim_seeds],
                             "why": "preflight: Semantic Scholar recommendations unavailable "
                                    f"({preflight_says(rd, 'semantic_scholar')[1][:120]})"}
    else:
        r = await server.call("scholar_recommend", {"paper_ids": sim_ids, "limit": SIMILAR_CAP * 2})
        retried = False
        if not (isinstance(r, dict) and isinstance(r.get("papers"), list)) and "429" in str((r or {}).get("_text") or r):
            if not replaying():
                await asyncio.sleep(SIMILAR_RETRY_WAIT)      # §15 G4: the server's own back-off was not enough
            r = await server.call("scholar_recommend", {"paper_ids": sim_ids, "limit": SIMILAR_CAP * 2})
            retried = True
        if isinstance(r, dict) and isinstance(r.get("papers"), list):
            sim_papers = r["papers"]
            status["similar"] = {"status": "ok", "seeds": [p["id"] for p in sim_seeds], "returned": len(sim_papers),
                                 **({"retried": True} if retried else {})}
        else:
            status["similar"] = {"status": "skipped", "seeds": [p["id"] for p in sim_seeds],
                                 "why": f"Semantic Scholar recommendations unavailable: {str((r or {}).get('_text') or r)[:160]}"}
    if status["similar"]["status"] == "skipped":
        caveats.append({"code": "similar-skipped", "text": status["similar"]["why"], "must_disclose": False})
    if status["backward"]["status"] == "skipped" and status["forward"]["status"] == "skipped":
        caveats.append({"code": "snowball-failed", "text": "neither backward nor forward chaining ran: foundational and "
                        "recent citing work were not recovered", "must_disclose": True})
    # ---- metadata for the pooled works, then one record per addition
    meta = _fetch_works(rd, back_keep + co_keep, mailto, fetch)
    adds, seen_titles = {}, set()

    def add(k, p, extra):
        t_ = norm_title(p.get("title"))
        if not p.get("title") or t_ in known_title or (p.get("doi") and str(p["doi"]).lower() in known_doi):
            return
        if k not in adds and t_ in seen_titles:
            return
        seen_titles.add(t_)
        rec = adds.setdefault(k, {**p, "snowball_direction": [], "found_via": "snowball", "found_by": ["snowball"]})
        for d in extra.pop("directions"):
            if d not in rec["snowball_direction"]:
                rec["snowball_direction"].append(d)
        rec.update(extra)
    missing_meta = 0
    for k in back_keep + co_keep:
        if k not in meta:
            missing_meta += 1
            continue
        # a work cut from backward by its cap and taken by the co-citation pool enters on that route only
        dirs = _directions(k, back, cocite, t, t_co) if k in back_keep else ["cocitation"]
        add(k, _paper_from_openalex(meta[k]), {"directions": dirs,
                                               "cocited_by_included": back.get(k, 0), "cocited_with_seeds": cocite.get(k, 0),
                                               "cited_by": sorted(back_by.get(k, []))[:20]})
    for k, v in sorted(s2_back.items(), key=lambda kv: -kv[1]["n"])[:BACKWARD_CAP]:
        add(k, v["rec"], {"directions": ["backward"], "cocited_by_included": v["n"], "cited_by": sorted(v["by"])[:20],
                          "via": "semantic_scholar"})
    for k in fwd_keep:
        add(k, _paper_from_openalex(citers[k]), {"directions": ["forward"], "cites_seeds": sorted(fwd[k])})
    n_sim, sim_cut = 0, 0
    for p in sim_papers:
        rec = {k: p.get(k) for k in ("title", "authors", "year", "journal", "doi", "url", "abstract", "citation_count",
                                      "semantic_scholar_id", "arxiv_id", "pubmed_id")}
        rec["doi"] = str(rec.get("doi") or "").lower() or None
        rec["sources_found_in"] = ["semantic_scholar"]
        k = f"s2:{p.get('semantic_scholar_id') or norm_title(p.get('title'))}"
        if n_sim >= SIMILAR_CAP:          # count what the cap cuts: new to the collection, not added
            t_ = norm_title(rec.get("title"))
            sim_cut += bool(rec.get("title")) and t_ not in known_title and t_ not in seen_titles \
                and not (rec["doi"] and rec["doi"] in known_doi)
            continue
        before = len(adds)
        add(k, rec, {"directions": ["similar"]})
        n_sim += len(adds) > before
    if missing_meta:
        caveats.append({"code": "snowball-no-metadata", "text": f"{missing_meta} pooled work(s) had no OpenAlex record "
                        "and were left out", "must_disclose": False})
    papers = list(adds.values())
    for p in papers:
        _finish(cfg, p, round_no)
    sem = add_sem(cfg, rd, papers, load_embedder(rd) if embedder == "auto" else embedder)
    minted = assign_ids(rd, papers, minted_by="A5")
    truncated = {"backward": max(0, len(back_ranked) - BACKWARD_CAP), "cocitation": max(0, len(co_ranked) - COCITE_CAP),
                 "forward": max(0, len(fwd_ranked) - FORWARD_CAP), "similar": sim_cut}
    rounds = list((prev or {}).get("rounds") or [])
    rounds.append({"round": round_no, "at": now_iso(), "status": status, "threshold": t, "threshold_cocitation": t_co,
                   "truncated": truncated,
                   "basis": {"shortlist": sha256_file(rd / "step3_shortlist.json"),
                             "bibliometrics": sha256_file(rd / "step3_bibliometrics.json")},
                   "added": len(papers), "minted": minted, "included_before": len(citing), "sem_sim": sem,
                   "by_direction": dict(Counter(d for p in papers for d in p["snowball_direction"]))})
    out = {"schema": SCHEMA, "rounds": rounds,
           "thresholds": {"backward": BACKWARD_MIN, "backward_share": BACKWARD_SHARE, "forward_min_seeds": FORWARD_MIN},
           "caps": {"backward": BACKWARD_CAP, "cocitation": COCITE_CAP, "forward": FORWARD_CAP, "similar": SIMILAR_CAP},
           "caveats": list((prev or {}).get("caveats") or []) + [dict(c, round=round_no) for c in caveats],
           "papers": list((prev or {}).get("papers") or []) + papers}
    write_json(sbp, out)
    return out


async def run_snowball(server, cfg: dict, rd: Path, mailto: str, fetch=http_json, round_no: int = 1,
                       embedder="auto") -> dict:
    """A5, one round: refuses before A3 passes (preflight), done once a5-check passes."""
    from it_ledger import degraded_codes, run_unit
    preflight(cfg, rd, round_no)
    with run_unit(rd, "A5", inst=f"r{round_no}", check=lambda: run_checks(cfg, Path(rd)),
                  degraded=lambda: degraded_codes(rd, "A5")):
        return await _run_snowball(server, cfg, rd, mailto, fetch=fetch, round_no=round_no, embedder=embedder)


def seed_basis(rd: Path) -> list | None:
    """What the latest round started from, as the ledger hashes it for A5 (at done, as it reads A5's own file): the
    screening judgements on the papers that round drew its seeds from - the search's papers and, from round 2 on, the
    earlier rounds' additions - and a person's include / exclude of them. A judgement, not the inclusion that follows
    from it: screening A5's own additions moves the composites of the papers they cite (citations inside the
    collection), and that feedback is A5's own loop, not a new input. A person's exclude, a rescue or a re-screen
    changes it."""
    rd = Path(rd)
    if not (rd / "screening_scores.json").exists():
        return None
    from it_overrides import entries as overrides
    sbp = rd / "step2b_snowball_papers.json"
    s = read_json(sbp) if sbp.exists() else {}
    last = max((r["round"] for r in s.get("rounds") or []), default=1)
    ids = {p["id"] for p in read_json(rd / "step2_raw_papers.json")["papers"]} | \
        {x["id"] for x in s.get("papers") or [] if (x.get("round") or 1) < last}
    keys = ("rel", "qual", "violates", "duplicate_of")
    judged = sorted([e["id"], [e.get(k) for k in keys]] for e in read_json(rd / "screening_scores.json").get("scores") or []
                    if e.get("id") in ids)
    human = sorted([e.get("kind"), e.get("id")] for e in overrides(rd) if e.get("kind") in ("include", "exclude")
                   and e.get("id") in ids)
    return [judged, human]


def growth(rd: Path) -> float | None:
    """How much round 1 grew the included set: included snowball papers / included papers before it."""
    sb = Path(rd) / "step2b_snowball_papers.json"
    if not sb.exists():
        return None
    s = read_json(sb)
    r1 = next((r for r in s.get("rounds") or [] if r["round"] == 1), None)
    if not r1 or not r1.get("included_before"):
        return None
    sl = read_json(Path(rd) / "step3_shortlist.json")
    ids = {p["id"] for p in s.get("papers") or [] if p.get("round") == 1}
    return sum(1 for p in sl["papers"] if p["id"] in ids) / r1["included_before"]


# ========================================================================================================== checks
def check(cfg, rd) -> list[dict]:
    from it_search import load_registry
    U = "A5"
    rd = Path(rd)
    p = rd / "step2b_snowball_papers.json"
    if not p.exists():
        return [F("ERROR", "N01", U, "no step2b_snowball_papers.json: run `mcp_bridge.py snowball <RD>`")]
    s = read_json(p)
    if s.get("schema") != SCHEMA:
        return [F("ERROR", "N01", U, "step2b_snowball_papers.json was not written by this snowball: run "
                                     "`mcp_bridge.py snowball <RD>`")]
    fs = []
    raw = read_json(rd / "step2_raw_papers.json")["papers"]
    raw_doi = {str(x.get("doi") or "").lower() for x in raw if x.get("doi")}
    raw_title = {norm_title(x.get("title")) for x in raw}
    reg = {e["id"]: e for e in load_registry(rd)}
    rounds = {r.get("round"): r for r in s.get("rounds") or []}
    ids = Counter(x.get("id") for x in s.get("papers") or [])
    for x in s.get("papers") or []:
        pid = x.get("id")
        if (x.get("doi") and str(x["doi"]).lower() in raw_doi) or norm_title(x.get("title")) in raw_title:
            fs.append(F("ERROR", "N02", U, f"{pid}: already in the search collection"))
        elif (reg.get(pid) or {}).get("minted_by") != "A5" or ids[pid] > 1:
            fs.append(F("ERROR", "N02", U, f"{pid}: not one id minted for A5 by the registry"))
        d = x.get("snowball_direction") or []
        t = (rounds.get(x.get("round")) or {}).get("threshold")
        t_co = (rounds.get(x.get("round")) or {}).get("threshold_cocitation")
        if x.get("round") not in rounds:
            fs.append(F("ERROR", "N03", U, f"{pid}: round {x.get('round')!r} is not recorded"))
        elif not d or not set(d) <= {"backward", "cocitation", "forward", "similar"}:
            fs.append(F("ERROR", "N03", U, f"{pid}: snowball_direction must name its route(s)"))
        elif "backward" in d and x.get("via") == "semantic_scholar" and (x.get("cocited_by_included") or 0) < \
                fallback_threshold((rounds[x["round"]]["status"]["backward"]).get("citing_papers_with_refs") or 0):
            fs.append(F("ERROR", "N03", U, f"{pid}: Semantic Scholar backward below the fallback threshold"))
        elif "backward" in d and x.get("via") != "semantic_scholar" and (x.get("cocited_by_included") or 0) < t:
            fs.append(F("ERROR", "N03", U, f"{pid}: backward, but cited by {x.get('cocited_by_included')} < {t} included papers"))
        elif "cocitation" in d and (t_co is None or (x.get("cocited_with_seeds") or 0) < t_co):
            fs.append(F("ERROR", "N03", U, f"{pid}: co-cited {x.get('cocited_with_seeds')} times by two-seed citers < {t_co}"))
        elif "forward" in d and len(set(x.get("cites_seeds") or [])) < FORWARD_MIN:
            fs.append(F("ERROR", "N03", U, f"{pid}: forward, but cites {len(set(x.get('cites_seeds') or []))} seed(s) < {FORWARD_MIN}"))
    per = Counter((x.get("round"), d) for x in s.get("papers") or [] for d in x.get("snowball_direction") or [])
    for n, r in rounds.items():
        tr = r.get("truncated") or {}
        if any(k not in tr for k in ("backward", "cocitation", "forward", "similar")):
            fs.append(F("ERROR", "N04", U, f"round {n}: truncation per direction is not recorded"))
        mine = [x for x in s.get("papers") or [] if x.get("round") == n]
        n_back = sum(1 for x in mine if "backward" in (x.get("snowball_direction") or []))
        n_co = sum(1 for x in mine if (x.get("snowball_direction") or []) == ["cocitation"])
        if per[(n, "forward")] > FORWARD_CAP or per[(n, "similar")] > SIMILAR_CAP or n_back > BACKWARD_CAP \
                or n_co > COCITE_CAP:
            fs.append(F("ERROR", "N04", U, f"round {n}: more additions than a direction's cap"))
        for d in ("backward", "forward", "similar"):
            st = (r.get("status") or {}).get(d) or {}
            if st.get("status") not in ("ok", "skipped") or (st.get("status") == "skipped" and not st.get("why")):
                fs.append(F("ERROR", "N07", U, f"round {n}: {d} has no status (ok, or skipped with a reason)"))
        if r.get("threshold") != threshold(r.get("included_before") or 0):
            fs.append(F("ERROR", "N03", U, f"round {n}: threshold {r.get('threshold')} != max({BACKWARD_MIN}, "
                                           f"{BACKWARD_SHARE:.0%} of {r.get('included_before')})"))
        n_two = ((r.get("status") or {}).get("cocitation") or {}).get("counted_from_citers") or 0
        if r.get("threshold_cocitation") != threshold(n_two):
            fs.append(F("ERROR", "N03", U, f"round {n}: co-citation threshold {r.get('threshold_cocitation')} != "
                                           f"max({BACKWARD_MIN}, {BACKWARD_SHARE:.0%} of {n_two} two-seed citers)"))
    sl = rd / "step3_shortlist.json"
    r1 = rounds.get(1)
    if r1 and sl.exists() and r1["basis"]["shortlist"] == sha256_file(sl):
        want = [x["id"] for x in forward_seeds(rd, read_json(sl))[0]]
        if want != r1["status"]["forward"].get("seeds"):
            fs.append(F("ERROR", "N05", U, "the forward seeds differ from the rule (foundational + core-method, top 10 by composite)"))
    elif r1 and sl.exists():
        fs.append(F("INFO", "N05", U, "the shortlist was rebuilt after round 1 (expected: A3 screened the additions)"))
    if 2 in rounds:
        g = growth(rd)
        if g is not None and g < ROUND2_GROWTH:
            fs.append(F("ERROR", "N06", U, f"a second round ran although round 1 grew the included set by {g:.1%} < {ROUND2_GROWTH:.0%}"))
    for c in s.get("caveats") or []:
        if c.get("must_disclose"):
            fs.append(F("WARN", "N08", U, c["text"]))
    return fs


def run_checks(cfg, rd, unit="all") -> list[dict]:
    import it_overrides
    require_protocol(cfg, rd)
    sl = Path(rd) / "step3_shortlist.json"
    papers = {p["id"]: p for p in read_json(sl)["papers"]} if sl.exists() else None
    return check(cfg, rd) + [f for f in it_overrides.check(rd, papers) if f["unit"] == "A5"]


def cmd_a5_check(a):
    rd = Path(a.research_dir)
    cfg = read_json(rd / "step0_session_config.json")
    fs = run_checks(cfg, rd)
    if a.json:
        print(json.dumps(fs, indent=2, ensure_ascii=False))
    else:
        for f in fs:
            print(f"  {f['level']:<5} {f['code']} [{f['unit']}] {f['msg']}")
        print("OK" if not errors(fs) else f"{len(errors(fs))} error(s)")
    raise SystemExit(1 if errors(fs) else 0)


def add_parsers(sub) -> None:
    sp = sub.add_parser("a5-check", help="A5 handoff checks (snowball)")
    sp.add_argument("research_dir")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_a5_check)
