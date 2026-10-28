"""A2 search - the three Units that turn A1's strategy into a candidate collection (rules: references/search/A2-search.md).

  A2.s  retrieval     one instance per query (plus the dense instance D1): each source gets the form it parses -
                      Boolean, Boolean without truncation (OpenAlex), arXiv syntax, or flat - and every attempt is
                      recorded                                        -> step2_queries/<id>@<hash>.json
  A2.m  merge         all instances -> one collection: DOI / arXiv-id / fuzzy / exact-title merge, found_by[] kept,
                      ids from an append-only registry, DOI + OpenAlex enrichment, PRISMA identification counts
                                                                      -> step2_raw_papers.json, step2_search_summary.md,
                                                                         _state/paper_ids.jsonl (A2.m's entries)
  A2.c  relevance     tool signals per query, then the model's verdict per query (ok / replan / accept-weak)
                                                                      -> step2_relevance_check.{json,md}
                      (a replan goes through `frame query-revise`; a missing synonym through `frame add-terms`)

Network runs (`mcp_bridge.py search` / `merge`) call `run_search` / `run_merge` with the bridge's Server; everything
else is offline:
  ideate_tools.py search-check   <RD> [--json]          A2.c signals (writes _state/A2c/signals_r{n}.json)
  ideate_tools.py relevance-set  <RD> verdicts.json     A2.c verdicts, one round
  ideate_tools.py a2-check       <RD> [--unit A2.s|A2.m|A2.c|all] [--json]   exit 1 on any ERROR
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from pathlib import Path

from it_common import (append_jsonl, content_words, die, http_json, norm_title, now_iso, preflight_says, quote,
                       read_json, read_jsonl, require_protocol, scholar_key, sha256_file, sha256_json, with_legacy,
                       write_json, write_text, smoke_cap)
import it_legacy

RAW_SCHEMA = "ideate-raw/2"
LIMIT = smoke_cap(50)                        # per source per query (IDEATE_SMOKE_CAP: it_common.smoke_cap)
# Which form each source parses: PubMed, Scopus, IEEE and WoS take
# the Boolean form; OpenAlex takes Boolean but refuses truncation on its stemmed field (so `*` is dropped and its
# stemming does the work); arXiv needs its own field syntax; Semantic Scholar's search parses no Boolean.
SOURCE_FORM = {"pubmed": "boolean", "scopus": "boolean", "ieee": "boolean", "wos": "boolean",
               "openalex": "boolean-nostar", "arxiv": "arxiv", "semantic_scholar": "flat"}
# Variant -> the sources its literature lives in. Unlisted variants use every chosen source. A query's own
# `sources` (A1.q) overrides this.
ROUTES = {"recent": ["arxiv", "openalex", "semantic_scholar"]}
# The order each source returns its first `limit` results in, as the scholar server asks for it: a capped query is a
# sample of the source's total, and the order decides which sample. Recorded on every attempt; part of the instance
# hash, so an instance fetched in another order is stale.
SOURCE_ORDER = {"pubmed": "relevance", "scopus": "relevance", "ieee": "relevance", "wos": "relevance",
                "openalex": "relevance", "arxiv": "relevance", "semantic_scholar": "relevance"}
DENSE_ID = "D1"
DENSE_LIMIT = smoke_cap(50)
SEM_HIGH_PCT = 75                             # "semantically close" = top quarter of the collection by sem_sim
SEM_LOW_PCT = 25                              # "semantically far" = bottom quarter
PULL_MIN, PULL_SHARE = 5, 0.5                 # a term whose own catch is >= 5 papers, half of them far: ambiguous
ANCHOR_MIN = 0.5                              # on-anchor share below which a query cannot be judged ok
MAX_ROUNDS = 3                                # r0 + two re-plan rounds
SATURATED = 0.05                              # a re-plan round adding fewer new papers than this ends re-planning
VERDICTS = ("ok", "replan", "accept-weak")
TRANSIENT = re.compile(r"\b(429|50[0-4])\b|rate limit|timed? ?out", re.I)
PREPRINT_HINT = re.compile(r"arxiv|biorxiv|medrxiv|ssrn|preprint|research square|techrxiv", re.I)
CODE_HINT = re.compile(r"(https?://)?(github\.com|gitlab\.com|zenodo\.org|osf\.io|bitbucket\.org)/[^\s)\]]+|"
                       r"code (?:is|are) (?:publicly |freely )?available|open[- ]source (?:code|implementation)", re.I)
STOP = {"a", "an", "the", "of", "for", "and", "or", "in", "on", "to", "with", "by", "from", "under", "via", "using",
        "is", "are", "we", "this", "that", "these", "as", "at", "be", "can", "our", "it", "its", "was", "were", "which"}


def F(level, code, unit, msg):
    return {"level": level, "code": code, "unit": unit, "msg": msg}


def errors(fs):
    return [f for f in fs if f["level"] == "ERROR"]


# =================================================================================================== A2.s retrieval
def _strip_star(t: str) -> str:
    return str(t).replace("*", "").strip()


def _arxiv_term(t: str) -> str:
    t = _strip_star(t)
    return f'all:"{t}"' if (" " in t or "-" in t) else f"all:{t}"


def render(protocol: dict, q: dict, form: str) -> str:
    """The string sent to a source of this form. A query without axes is sent as written."""
    from it_frame import _quote, selected_terms
    if not q.get("axes"):
        return str(q.get("query") or "")
    if form == "flat":
        return str(q.get("flat_query") or q.get("query") or "")
    parts = []
    for terms in selected_terms(protocol, q).values():
        if form == "arxiv":
            alts = [_arxiv_term(t) for t in terms]
        elif form == "boolean-nostar":
            alts = list(dict.fromkeys(_quote(_strip_star(t)) for t in terms))
        else:
            alts = [_quote(t) for t in terms]
        parts.append(f"({' OR '.join(alts)})" if len(alts) > 1 else alts[0])
    return " AND ".join(parts)


def query_sources(cfg: dict, q: dict) -> list[str]:
    base = list(cfg.get("sources") or [])
    if q.get("sources"):
        return [s for s in q["sources"] if s in SOURCE_FORM]
    route = ROUTES.get(q.get("strategy"))
    if route:
        hit = [s for s in base if s in route] or [s for s in route if s in SOURCE_FORM]
        return hit
    return base


def query_year(cfg: dict, q: dict) -> str | None:
    """The protocol's timeframe; a `recent` variant narrows it to the last twelve months."""
    from datetime import date
    tf = str((cfg.get("protocol") or {}).get("timeframe") or "")
    m = re.findall(r"\d{4}", tf)
    if q.get("year") == "last-12-months":
        y = date.today().year
        return f"{y - 1}-{y}"
    return f"{m[0]}-{m[1]}" if len(m) >= 2 else (m[0] if m else None)


def plan(cfg: dict, q: dict) -> dict:
    """{form: {"query": sent string, "sources": [...]}} - one scholar_search call per form."""
    p = cfg.get("protocol") or {}
    groups: dict[str, dict] = {}
    for src in query_sources(cfg, q):
        form = SOURCE_FORM.get(src, "flat")
        groups.setdefault(form, {"query": render(p, q, form), "sources": []})["sources"].append(src)
    return groups


def instance_hash(cfg: dict, q: dict, limit: int = LIMIT) -> str:
    pl = plan(cfg, q)
    order = {s: SOURCE_ORDER.get(s) for g in pl.values() for s in g["sources"]}
    return sha256_json({"plan": pl, "year": query_year(cfg, q), "limit": limit, "order": order})[:8]


def query_dir(rd: Path) -> Path:
    return Path(rd) / "step2_queries"


def instance_path(rd: Path, qid: str, h: str) -> Path:
    return query_dir(rd) / f"{qid}@{h}.json"


def shorten(query: str, n: int = 4) -> str:
    return " ".join(content_words(query)[:n])


async def _call(server, sent, sources, limit, year, qid):
    return await server.call("scholar_search", {"query": sent, "sources": sources, "limit": limit, "year": year,
                                                "found_via": qid})


def _absorb(rec: dict, form: str, sent: str, sources: list, r: dict, at: str, year, limit):
    """Fold one scholar_search answer into an instance record: one attempt per source, papers appended."""
    papers = r.get("papers") if isinstance(r, dict) else None
    errs = (r or {}).get("source_errors") or {}
    skipped = (r or {}).get("sources_skipped") or {}
    for src in sources:
        ps = rec["per_source"].setdefault(src, {"form": form, "attempts": []})
        att = {"sent_query": sent, "at": at, "filters": {"year": year, "limit": limit}, "order": SOURCE_ORDER.get(src)}
        if papers is None:
            att["error"] = str((r or {}).get("_text") or r)[:300]
        elif src in skipped:
            att["skipped"] = skipped[src]
        elif src in errs:
            att["error"] = str(errs[src])[:300]
        else:
            att["returned"] = ((r.get("returned") or {}).get(src)
                               if r.get("returned") is not None else sum(1 for p in papers if src in (p.get("sources_found_in") or [])))
            att["total"] = (r.get("totals") or {}).get(src)
        ps["attempts"].append(att)
    for p in papers or []:
        p = dict(p)
        p["found_via"] = rec["id"]
        rec["papers"].append(p)


def _final(ps: dict) -> dict:
    """The decisive attempt of a source: the last one that answered, else the last one."""
    ok = [a for a in ps["attempts"] if "returned" in a]
    return ok[-1] if ok else ps["attempts"][-1]


def source_status(rec: dict) -> dict:
    out = {}
    for src, ps in rec.get("per_source", {}).items():
        a = _final(ps)
        out[src] = ("ok" if "returned" in a else "skipped" if "skipped" in a else "error",
                    a.get("returned"), a.get("total"), a.get("error") or a.get("skipped"))
    return out


async def run_query(server, cfg: dict, rd: Path, q: dict, limit: int = LIMIT, benched: set | None = None,
                    sleep=asyncio.sleep) -> dict:
    """A2.s for one query: every form group once; a flat source that answered 0 is retried once shortened."""
    benched = benched if benched is not None else set()
    year = query_year(cfg, q)
    rec = {"schema": "ideate-query-instance/1", "kind": "query", "id": q["id"], "strategy": q.get("strategy"),
           "hash": instance_hash(cfg, q, limit), "at": now_iso(), "year": year, "limit": limit,
           "plan": plan(cfg, q), "per_source": {}, "papers": []}
    for form, g in rec["plan"].items():
        live = [s for s in g["sources"] if s not in benched]
        for s in g["sources"]:
            if s in benched:
                rec["per_source"].setdefault(s, {"form": form, "attempts": []})["attempts"].append(
                    {"sent_query": g["query"], "at": now_iso(), "filters": {"year": year, "limit": limit},
                     "error": "benched: rate-limited on earlier queries"})
        if not live:
            continue
        r = await _call(server, g["query"], live, limit, year, q["id"])
        _absorb(rec, form, g["query"], live, r, now_iso(), year, limit)
        if form == "flat":
            zero = [s for s in live if (_final(rec["per_source"][s]).get("returned") == 0)]
            short = shorten(g["query"])
            if zero and short and short != g["query"]:
                await sleep(2)
                r2 = await _call(server, short, zero, limit, year, q["id"])
                _absorb(rec, form, short, zero, r2, now_iso(), year, limit)
        await sleep(1)
    rec["complete"] = True
    write_json(instance_path(rd, q["id"], rec["hash"]), rec)
    return rec


async def run_dense(server, cfg: dict, rd: Path, sleep=asyncio.sleep) -> dict:
    """A2.s dense instance D1: Semantic Scholar's embedding neighbours of the known items the scope probe
    resolved. Recorded like a query; a failure (no key, rate limit) is recorded as `skipped`, never fatal."""
    seeds = [f"DOI:{k['doi']}" for k in ((cfg.get("scope_probe") or {}).get("known_items") or [])
             if k.get("resolved") and k.get("doi")]
    h = sha256_json({"seeds": seeds, "limit": DENSE_LIMIT})[:8]
    rec = {"schema": "ideate-query-instance/1", "kind": "dense", "id": DENSE_ID, "strategy": "dense", "hash": h,
           "at": now_iso(), "seeds": seeds, "limit": DENSE_LIMIT, "per_source": {}, "papers": []}
    att = {"sent_query": f"recommendations of {len(seeds)} known item(s)", "at": now_iso(),
           "filters": {"limit": DENSE_LIMIT}}
    pf = preflight_says(rd, "semantic_scholar")
    if not seeds:
        att["skipped"] = "no resolved known item with a DOI to seed from"
    elif pf is not None and not pf[0]:
        att["skipped"] = f"preflight: Semantic Scholar recommendations unavailable ({pf[1][:120]})"
    else:
        r = await server.call("scholar_recommend", {"paper_ids": seeds, "limit": DENSE_LIMIT})
        if isinstance(r, dict) and isinstance(r.get("papers"), list):
            att["returned"], att["total"] = len(r["papers"]), None
            for p in r["papers"]:
                rec["papers"].append({**p, "found_via": DENSE_ID})
        else:
            att["skipped"] = f"Semantic Scholar recommendations unavailable: {str((r or {}).get('_text') or r)[:200]}"
    rec["per_source"]["semantic_scholar"] = {"form": "dense", "attempts": [att]}
    rec["complete"] = True
    write_json(instance_path(rd, DENSE_ID, h), rec)
    return rec


def latest_instance(rd: Path, qid: str) -> Path | None:
    files = sorted(query_dir(rd).glob(f"{qid}@*.json"), key=lambda f: f.stat().st_mtime)
    return files[-1] if files else None


async def _run_search(server, cfg: dict, rd: Path, only: list | None = None, limit: int = LIMIT, dense: bool = True,
                     force: bool = False, sleep=asyncio.sleep) -> list[dict]:
    """A2.s over the active queries (or `only`), resuming: an instance whose file for the current hash is complete is
    not re-run. A source rate-limited on two queries running is benched; benched and transient failures get one
    delayed retry at the end."""
    from it_common import replaying
    if replaying():                      # a replay waits for nothing
        async def sleep(_):
            return None
    active = [q for q in cfg.get("queries") or [] if q.get("status", "active") == "active"]
    todo = [q for q in active if not only or q["id"] in only]
    if only and not todo:
        die(f"--only {only}: no active query with that id", 2)
    benched, streak, recs = set(), Counter(), []
    for q in todo:
        path = instance_path(rd, q["id"], instance_hash(cfg, q, limit))
        if path.exists() and not force and read_json(path).get("complete"):
            print(f"  {q['id']}: already run ({path.name})", flush=True)
            recs.append(read_json(path))
            continue
        if path.exists() and read_json(path).get("complete"):        # --force: the earlier answer is history, not
            keep = path.with_name(f"{path.stem}r{len(list(query_dir(rd).glob(path.stem + 'r*.json'))) + 1}.json")
            path.rename(keep)                                            # a draft - kept as a superseded instance, so
            print(f"  {q['id']}: earlier instance kept as {keep.name}", flush=True)   # no paper it found vanishes (M01)
        rec = await run_query(server, cfg, rd, q, limit, benched, sleep)
        for src, (st, n, tot, err) in source_status(rec).items():
            if st == "error" and err and TRANSIENT.search(str(err)):
                streak[src] += 1
                if streak[src] >= 2:
                    benched.add(src)
            elif st == "ok":
                streak[src] = 0
        print(f"  {q['id']} [{q.get('strategy')}]: " + "  ".join(
            f"{s}={n if st == 'ok' else st}" + (f"/{tot}" if tot is not None else "")
            for s, (st, n, tot, err) in source_status(rec).items()), flush=True)
        recs.append(rec)
        await sleep(2)
    # one delayed retry for transient failures
    retry = [(rec, s) for rec in recs for s, (st, n, tot, err) in source_status(rec).items()
             if st == "error" and err and (TRANSIENT.search(str(err)) or str(err).startswith("benched"))]
    if retry:
        wait = 15 if only else 45
        print(f"  {len(retry)} (query, source) pair(s) failed transiently; waiting {wait}s and retrying once", flush=True)
        await sleep(wait)
        by_q = {q["id"]: q for q in active}
        for rec, src in retry:
            q = by_q.get(rec["id"])
            if q is None:
                continue
            form = rec["per_source"][src]["form"]
            sent = rec["plan"][form]["query"]
            r = await _call(server, sent, [src], rec["limit"], rec["year"], rec["id"])
            _absorb(rec, form, sent, [src], r, now_iso(), rec["year"], rec["limit"])
            write_json(instance_path(rd, rec["id"], rec["hash"]), rec)
            await sleep(2)
    if dense and not only and cfg.get("depth") != "quick":
        seeds = [f"DOI:{k['doi']}" for k in ((cfg.get("scope_probe") or {}).get("known_items") or [])
                 if k.get("resolved") and k.get("doi")]
        dp = instance_path(rd, DENSE_ID, sha256_json({"seeds": seeds, "limit": DENSE_LIMIT})[:8])
        if dp.exists() and not force and read_json(dp).get("complete"):    # like a query: a complete instance is
            print(f"  {DENSE_ID}: already run ({dp.name})", flush=True)  # not asked again (a re-run only rewrote
            return recs                                                    # its stamps and staled the merge)
        d = await run_dense(server, cfg, rd, sleep)
        st = source_status(d)["semantic_scholar"]
        print(f"  {DENSE_ID} [dense]: " + (f"{st[1]} papers" if st[0] == "ok" else f"skipped - {st[3]}"), flush=True)
    return recs


# ======================================================================================================= A2.m merge
def _arxiv_of(p: dict) -> str | None:
    a = p.get("arxiv_id")
    if a:
        return re.sub(r"v\d+$", "", re.sub(r"(?i)^arxiv:", "", str(a))).strip().lower()
    for doi in [p.get("doi")] + list(p.get("alt_dois") or []):
        m = re.search(r"10\.48550/arxiv\.(\d{4}\.\d{4,5})", str(doi or ""), re.I)
        if m:
            return m.group(1)
    return None


def _dois(p: dict) -> set:
    return {str(d).lower() for d in [p.get("doi")] + list(p.get("alt_dois") or []) if d}


def _tokens(title) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", str(title or "").lower()) if len(w) > 2}


def _surname(p: dict) -> str:
    """First author's family name in the three shapes the sources use ("Family, Given", "Given Family", Scopus
    "Family I.") - the same parser that makes the citation keys."""
    from it_common import ascii_fold, split_name
    au = (p.get("authors") or [None])[0]
    return re.sub(r"[^a-z]", "", ascii_fold(split_name(str(au))[0]).lower()) if au else ""


class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[max(a, b)] = min(a, b)
            return True
        return False


def merge_records(records: list[dict], threshold: float = 0.85) -> tuple[list[dict], dict]:
    """Deterministic merge. Each input record carries found_via (its instance id). Order of rules: shared DOI (incl.
    alt_dois) -> shared arXiv id -> fuzzy title (Jaccard >= threshold, same first-author surname or none, year +-1) ->
    identical normalised title. Returns (papers, merge counts by rule)."""
    n = len(records)
    uf = _UF(n)
    counts = Counter()
    keymaps = {"doi": {}, "arxiv": {}, "exact": {}}
    for i, r in enumerate(records):
        for kind, keys in (("doi", _dois(r)), ("arxiv", {_arxiv_of(r)} - {None}),
                           ("exact", {norm_title(r.get("title"))} if len(norm_title(r.get("title"))) >= 12 else set())):
            for k in keys:
                j = keymaps[kind].setdefault(k, i)
                if j != i and uf.union(i, j):
                    counts[kind] += 1
    toks = [_tokens(r.get("title")) for r in records]
    for i in range(n):
        if not toks[i]:
            continue
        for j in range(i):
            if uf.find(i) == uf.find(j) or not toks[j]:
                continue
            jac = len(toks[i] & toks[j]) / len(toks[i] | toks[j])
            if jac < threshold:
                continue
            si, sj = _surname(records[i]), _surname(records[j])
            yi, yj = records[i].get("year"), records[j].get("year")
            if (not si or not sj or si == sj) and (yi is None or yj is None or abs(int(yi) - int(yj)) <= 1):
                if uf.union(i, j):
                    counts["fuzzy"] += 1
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)
    papers = []
    for root in sorted(groups):
        members = [records[i] for i in groups[root]]
        base = sorted(members, key=lambda r: (bool(PREPRINT_HINT.search(str(r.get("journal") or ""))), not r.get("doi"),
                                              -len(str(r.get("abstract") or ""))))[0]
        m = dict(base)
        for r in members:
            for k, v in r.items():
                if m.get(k) in (None, "", []) and v not in (None, "", []):
                    m[k] = v
        m["sources_found_in"] = sorted({s for r in members for s in r.get("sources_found_in") or []})
        m["citation_count"] = max((r.get("citation_count") or 0) for r in members) or base.get("citation_count")
        m["abstract"] = max((str(r.get("abstract") or "") for r in members), key=len) or None
        alt = sorted(_dois(m) | {d for r in members for d in _dois(r)} - {str(m.get("doi") or "").lower()})
        if alt:
            m["alt_dois"] = alt
        order = []
        for r in members:
            if r.get("found_via") not in order:
                order.append(r.get("found_via"))
        m["found_by"] = order
        m["merged_from"] = len(members)
        alt = sorted({norm_title(r.get("title")) for r in members} - {norm_title(m.get("title")), ""})
        if alt:
            m["alt_titles"] = alt                         # the other titles it absorbed (a subtitle, another version)
        m.pop("found_via", None)
        papers.append(m)
    return papers, dict(counts)


# ----------------------------------------------------------------------------------------------- id registry
def registry_path(rd: Path) -> Path:
    return Path(rd) / "_state" / "paper_ids.jsonl"


def load_registry(rd: Path) -> list[dict]:
    return read_jsonl(registry_path(rd))


def assign_ids(rd: Path, papers: list[dict], minted_by: str = "A2.m") -> int:
    """Known papers keep their id (matched by DOI, then arXiv id, then normalised title); new ones get the next free
    number. The registry is append-only and each entry names who minted it; an id is never reused."""
    reg = load_registry(rd)
    by = {"doi": {}, "arxiv": {}, "title": {}}
    top = 0
    for e in reg:
        for d in e.get("dois") or []:
            by["doi"].setdefault(d, e["id"])
        if e.get("arxiv"):
            by["arxiv"].setdefault(e["arxiv"], e["id"])
        if e.get("title"):
            by["title"].setdefault(e["title"], e["id"])
        m = re.fullmatch(r"paper_(\d+)", e["id"])
        top = max(top, int(m.group(1)) if m else 0)
    new = []
    taken = set()
    for p in papers:
        pid = next((by["doi"][d] for d in sorted(_dois(p)) if d in by["doi"]), None) \
            or by["arxiv"].get(_arxiv_of(p) or "") or by["title"].get(norm_title(p.get("title")))
        if pid in taken:            # two merged papers matching one old id: the second is a new paper
            pid = None
        if pid is None:
            top += 1
            pid = f"paper_{top:03d}"
            new.append({"id": pid, "minted_by": minted_by, "at": now_iso(), "dois": sorted(_dois(p)),
                        "arxiv": _arxiv_of(p), "title": norm_title(p.get("title"))})
        p["id"] = pid
        taken.add(pid)
    # A paper that matches two registered ids (an arXiv preprint and its published version, now known to be one):
    # the id it did not take is absorbed - recorded, so it is a merge, not a paper that vanished (M01).
    aliased = {e["id"] for e in reg if e.get("merged_into")}
    every = {"doi": {}, "arxiv": {}, "title": {}}       # every id a DOI, an arXiv id or a title was registered under
    for e in reg:
        for d in e.get("dois") or []:
            every["doi"].setdefault(d, set()).add(e["id"])
        if e.get("arxiv"):
            every["arxiv"].setdefault(e["arxiv"], set()).add(e["id"])
        if e.get("title"):
            every["title"].setdefault(e["title"], set()).add(e["id"])
    for p in papers:
        matched = {i for d in _dois(p) for i in every["doi"].get(d, ())} | \
            {i for a in [_arxiv_of(p)] if a for i in every["arxiv"].get(a, ())} | \
            {i for t in [norm_title(p.get("title"))] + list(p.get("alt_titles") or []) for i in every["title"].get(t, ())}
        for m in sorted(matched - taken - aliased):
            new.append({"id": m, "merged_into": p["id"], "by": minted_by, "at": now_iso()})
            aliased.add(m)
    if new:
        registry_path(rd).parent.mkdir(parents=True, exist_ok=True)
        append_jsonl(registry_path(rd), new)
    return sum(1 for e in new if "minted_by" in e)


# ------------------------------------------------------------------------------------------------ enrichment
def _venue_type(w: dict) -> str | None:
    """The archived engine's venue_type from an OpenAlex work (providers/openalex.py): conference, journal, preprint."""
    src_type = ((w.get("primary_location") or {}).get("source") or {}).get("type")
    if src_type == "conference" or w.get("type") == "proceedings-article":
        return "conference"
    if w.get("type") in ("article", "review") and src_type == "journal":
        return "journal"
    if src_type == "repository" or w.get("type") == "preprint":
        return "preprint"
    return None


def openalex_batch(rd: Path, papers: list[dict], mailto: str, fetch=http_json) -> dict:
    """One OpenAlex request per 40 DOIs (instead of one per paper): abstract when missing, openalex_id, the open-access
    link, and the bibliographic fields the archived engine kept (pmc_id, volume, issue, pages, language, venue_type);
    `refs_in_collection` = the referenced works that are papers of this collection (OpenAlex ids), from which the
    archived citation network is drawn (it_legacy.raw_papers). Recorded under _state/net/http/."""
    got = {"abstracts": 0, "oa_links": 0, "failed_batches": 0, "biblio": 0}
    want = [p for p in papers if p.get("doi")]
    referenced = {}
    for i in range(0, len(want), 40):
        chunk = want[i:i + 40]
        filt = "doi:" + "|".join(str(p["doi"]) for p in chunk)
        url = (f"https://api.openalex.org/works?filter={quote(filt)}&per-page=50&mailto={quote(mailto)}"
               "&select=id,doi,display_name,publication_year,abstract_inverted_index,open_access,best_oa_location,"
               "ids,biblio,language,type,primary_location,referenced_works")
        try:
            res = fetch(url, rd)
        except Exception:  # noqa: BLE001 - enrichment is optional; the failure is counted
            got["failed_batches"] += 1
            continue
        idx = {str(r.get("doi") or "").lower().removeprefix("https://doi.org/"): r for r in res.get("results") or []}
        for p in chunk:
            r = idx.get(str(p["doi"]).lower())
            if not r:
                continue
            p["openalex_id"] = p.get("openalex_id") or str(r.get("id") or "").rsplit("/", 1)[-1] or None
            if not norm_title(p.get("title")) and r.get("display_name"):      # a record that came without a title
                p["title"], p["title_source"] = r["display_name"], "openalex"
                p["year"] = p.get("year") or r.get("publication_year")
            oa = r.get("open_access") or {}
            loc = r.get("best_oa_location") or {}
            link = loc.get("pdf_url") or oa.get("oa_url")
            if link:
                p["oa_url"], got["oa_links"] = link, got["oa_links"] + 1
            p["is_oa"] = oa.get("is_oa")
            if not str(p.get("abstract") or "").strip() and r.get("abstract_inverted_index"):
                inv = r["abstract_inverted_index"]
                p["abstract"] = " ".join(w for _, w in sorted((i, w) for w, ps in inv.items() for i in ps))
                p["abstract_source"] = "openalex"
                got["abstracts"] += 1
            bib = r.get("biblio") or {}
            first, last = bib.get("first_page"), bib.get("last_page")
            pmcid = str((r.get("ids") or {}).get("pmcid") or "").rstrip("/").rsplit("/", 1)[-1]
            found = {"pmc_id": pmcid or None, "volume": bib.get("volume"), "issue": bib.get("issue"),
                     "pages": (first + (f"-{last}" if last and last != first else "")) if first else None,
                     "language": r.get("language"), "venue_type": _venue_type(r)}
            for k, v in found.items():                   # a value the search already gave stays
                if p.get(k) in (None, "") and v not in (None, ""):
                    p[k] = v
            if any(v not in (None, "") for v in found.values()):
                got["biblio"] += 1
            if isinstance(r.get("referenced_works"), list):
                referenced[id(p)] = [str(w).rsplit("/", 1)[-1] for w in r["referenced_works"] if w]
    ours = {p["openalex_id"] for p in papers if p.get("openalex_id")}
    for p in papers:
        if id(p) in referenced:
            p["refs_in_collection"] = sorted({w for w in referenced[id(p)] if w in ours and w != p.get("openalex_id")})
    return got


# ------------------------------------------------------------------------------------------- semantic similarity
def protocol_text(cfg: dict) -> str:
    p = cfg.get("protocol") or {}
    slots = [str(s.get("value") or "") for s in (p.get("framework") or {}).get("slots") or []
             if s.get("operational_role") != "extraction-only"]
    terms = [t for a in p.get("axes") or [] if a.get("kind") == "search" for t in a.get("terms") or []]
    outs = [str(o.get("text") or "") for o in p.get("outcomes") or []]
    return ". ".join([str(cfg.get("topic") or "")] + slots + outs + [", ".join(terms)])


def load_embedder(rd: Path | None = None):
    """The fixed local model (allenai/specter2_base), only if it is already downloaded - never fetched from
    here. Runs on the CPU so the same text always gives the same vector (A2.m is a script: same input, same output),
    and caches vectors under <RD>/_state/embeddings/ so a re-merge embeds only new papers.
    Returns (name@revision, fn(list[str]) -> list[list[float]]) or None."""
    import hashlib
    import os
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub" / "models--allenai--specter2_base"
    snaps = sorted((hub / "snapshots").glob("*")) if hub.exists() else []
    if not snaps or not any((s_ / "pytorch_model.bin").exists() or list(s_.glob("*.safetensors")) for s_ in snaps):
        return None
    rev = snaps[-1].name[:8]
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
        tok = AutoTokenizer.from_pretrained("allenai/specter2_base", local_files_only=True)
        model = AutoModel.from_pretrained("allenai/specter2_base", local_files_only=True).eval()
    except Exception:  # noqa: BLE001
        return None
    name = f"allenai/specter2_base@{rev}"
    cache_file = (Path(rd) / "_state" / "embeddings" / f"specter2_base@{rev}.jsonl") if rd else None
    cache = {}
    if cache_file and cache_file.exists():
        for k, v in read_jsonl(cache_file):
            cache[k] = v

    def fn(texts):
        keys = [hashlib.sha1(t.encode("utf-8")).hexdigest() for t in texts]
        todo = [i for i, k in enumerate(keys) if k not in cache]
        new = []
        with torch.no_grad():
            for j in range(0, len(todo), 16):
                idx = todo[j:j + 16]
                enc = tok([texts[i] for i in idx], padding=True, truncation=True, max_length=512, return_tensors="pt")
                vecs = model(**enc).last_hidden_state[:, 0, :].tolist()
                for i, v in zip(idx, vecs):
                    cache[keys[i]] = [round(x, 6) for x in v]
                    new.append((keys[i], cache[keys[i]]))
        if cache_file and new:
            append_jsonl(cache_file, [[k, v] for k, v in new])
        return [cache[k] for k in keys]
    return name, fn


def _cos(a, b):
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def add_sem_sim(cfg: dict, papers: list[dict], embedder) -> str:
    """sem_sim = cosine between the paper (title + abstract) and a description of the protocol; sem_pct = its
    percentile in this collection. The raw cosine of a BERT-type model sits in a narrow band (0.8-0.95 here), so every
    rule reads the percentile, never a fixed cosine."""
    if embedder is None:
        return "not enabled: allenai/specter2_base is not in the Hugging Face cache"
    name, fn = embedder
    texts = [f"{p.get('title') or ''}. {p.get('abstract') or ''}" for p in papers]
    vecs = fn([protocol_text(cfg)] + texts)
    q, rest = vecs[0], vecs[1:]
    for p, v in zip(papers, rest):
        p["sem_sim"] = round(_cos(q, v), 4)
    order = sorted(range(len(papers)), key=lambda i: papers[i]["sem_sim"])
    for rank, i in enumerate(order):
        papers[i]["sem_pct"] = round(100 * rank / max(1, len(papers) - 1), 1)
    return f"enabled: {name} (cpu)"


# ------------------------------------------------------------------------------------------------- merge driver
def instance_files(rd: Path, cfg: dict) -> list[Path]:
    """The latest instance of every query in step0 (active or retired) and of the dense instance."""
    ids = [q["id"] for q in cfg.get("queries") or []] + [DENSE_ID]
    return [f for f in (latest_instance(rd, i) for i in ids) if f is not None]


def superseded_files(rd: Path, cfg: dict) -> list[Path]:
    """The earlier complete instances of those queries: a query asked again under another rendering or result order.
    What they found stays in the collection (no paper vanishes); `found_by` names them `<id>@<hash>`."""
    latest = set(instance_files(rd, cfg))
    ids = [q["id"] for q in cfg.get("queries") or []]
    out = []
    for i in ids:
        for f in sorted(query_dir(rd).glob(f"{i}@*.json"), key=lambda f: f.stat().st_mtime):
            if f not in latest and read_json(f).get("complete"):
                out.append(f)
    return out


def merge_files(rd: Path, cfg: dict) -> list[Path]:
    return instance_files(rd, cfg) + superseded_files(rd, cfg)


def computed_fields(cfg: dict, p: dict, retired: set) -> None:
    anchors = [str(x).lower() for x in cfg.get("anchor_terms") or []]
    blob = f"{p.get('title') or ''} {p.get('abstract') or ''}".lower()
    p["anchor_match"] = any(x in blob for x in anchors) if anchors else None
    p["has_abstract"] = bool(str(p.get("abstract") or "").strip())
    m = CODE_HINT.search(str(p.get("abstract") or ""))
    p["code_hint"] = m.group(0) if m else None
    lexical = [f for f in p["found_by"] if f != DENSE_ID]
    current = [f for f in lexical if "@" not in f]                  # "<id>@<hash>" = a superseded instance
    p["superseded_only"] = bool(lexical) and not current
    p["retired_only"] = bool(current) and all(f in retired for f in current)
    p["found_via"] = (current or lexical)[0] if lexical else "dense"   # dense-only papers face A3's relevance floor


async def _run_merge(server, cfg: dict, rd: Path, mailto: str, fetch=http_json, embedder="auto") -> dict:
    latest = instance_files(rd, cfg)
    if not latest:
        die("no query instances under step2_queries/: run `mcp_bridge.py search` first", 2)
    files = merge_files(rd, cfg)
    insts = [read_json(f) for f in files]
    old = {f.stem for f in files[len(latest):]}
    records = [p if f.stem not in old else {**p, "found_via": f.stem}
               for f, r in zip(files, insts) for p in r.get("papers") or []]
    insts_now = insts[:len(latest)]                     # caveats describe the search as it stands
    blank = lambda r: not norm_title(r.get("title")) and not r.get("doi") and not _arxiv_of(r)
    untitled = sum(1 for r in records if blank(r))
    records = [r for r in records if not blank(r)]      # no title, no DOI, no arXiv id: not a paper (a DOI without a
                                                        # title stays; the OpenAlex enrichment below names it)
    # An arXiv record without a DOI: the published version's DOI from Semantic Scholar - only with a key (keyless, one
    # rate-limited lookup per record stalled a merge for 20+ minutes) - and otherwise its own DataCite DOI
    # 10.48550/arxiv.<id>, which OpenAlex resolves for the enrichment below. Done on the records, before the merge,
    # so a recovered DOI joins the arXiv record to its published version instead of leaving two papers with one DOI.
    has_doi = {_arxiv_of(r) for r in records if _arxiv_of(r) and r.get("doi")}
    need_ax = sorted({_arxiv_of(r) for r in records if _arxiv_of(r) and not r.get("doi")} - has_doi)
    pf = preflight_says(rd, "semantic_scholar")
    s2_ok = bool(scholar_key("SEMANTIC_SCHOLAR_API_KEY")) and not (pf and not pf[0])
    found = {}
    if need_ax and server is not None and s2_ok:
        rep = {}
        for r in records:
            ax = _arxiv_of(r)
            if ax in need_ax and ax not in rep:
                rep[ax] = r
        ask = [rep[ax] for ax in need_ax]
        rec = await server.call("scholar_recover_dois", {"papers": ask})
        if isinstance(rec, dict) and isinstance(rec.get("papers"), list) and len(rec["papers"]) == len(ask):
            found = {ax: str(r["doi"]).lower() for ax, r in zip(need_ax, rec["papers"]) if r.get("doi")}
        # A recovered DOI that another work already holds under a different arXiv id (a conference paper and its
        # journal extension, or a title search that returned a neighbour) would join two works: not used.
        held = {}
        for r in records:
            for d in _dois(r):
                if _arxiv_of(r):
                    held.setdefault(d, set()).add(_arxiv_of(r))
        claims = {}
        for ax, d in found.items():
            claims.setdefault(d, set()).add(ax)
        found = {ax: d for ax, d in found.items() if not (held.get(d, set()) - {ax}) and len(claims[d]) == 1}
    for r in records:
        ax = _arxiv_of(r)
        if ax in need_ax and not r.get("doi"):
            r["doi"], r["doi_source"] = ((found[ax], "semantic_scholar") if ax in found
                                         else (f"10.48550/arxiv.{ax}", "arxiv"))
    arxiv_doi, need = sum(1 for ax in need_ax if ax not in found), need_ax
    papers, merges = merge_records(records)
    enrich = openalex_batch(rd, papers, mailto, fetch)
    minted = assign_ids(rd, papers)
    retired = {q["id"] for q in cfg.get("queries") or [] if q.get("status") == "retired"}
    for p in papers:
        computed_fields(cfg, p, retired)
    sem = add_sem_sim(cfg, papers, load_embedder(rd) if embedder == "auto" else embedder)
    papers.sort(key=lambda p: (p["anchor_match"] is False, -len(p.get("sources_found_in") or []), -(p.get("citation_count") or 0)))
    # PRISMA identification: records per database, as returned and as the database reports for the query
    per_db = {}
    for r in insts:
        for src, (st, n, tot, err) in source_status(r).items():
            d = per_db.setdefault(src, {"retrieved": 0, "reported_total_sum": 0, "queries": 0, "errors": 0})
            if st == "ok":
                d["retrieved"] += n or 0
                d["reported_total_sum"] += tot or 0
                d["queries"] += 1
            elif st == "error":
                d["errors"] += 1
    caveats = []
    for r in insts_now:
        for src, (st, n, tot, err) in source_status(r).items():
            if st == "error":
                caveats.append({"code": "source-failed", "text": f"{src} failed on {r['id']}: {str(err)[:120]}",
                                "must_disclose": False})
    if need and not s2_ok:
        caveats.append({"code": "doi-recovery-skipped", "must_disclose": False,
                        "text": f"{arxiv_doi} arXiv record(s) keep their arXiv DOI: the published versions' DOIs were not "
                                "looked up (no Semantic Scholar key, or the preflight found it down)"})
    dense = next((r for r in insts_now if r.get("kind") == "dense"), None)
    if dense and source_status(dense)["semantic_scholar"][0] != "ok":
        caveats.append({"code": "dense-skipped", "text": "dense retrieval (S2 recommendations) did not run: "
                        + str(source_status(dense)["semantic_scholar"][3]), "must_disclose": False})
    answered = {src for r in insts_now for src, v in source_status(r).items() if v[0] == "ok"}
    dead = [s for s in per_db if s not in answered]
    if dead:
        caveats.append({"code": "source-dead", "text": f"no query got an answer from {dead}", "must_disclose": True})
    summary = {
        "instances": [{"file": f.name, "sha": sha256_file(f)} for f in files],
        "total_raw_results": len(records), "after_dedup": len(papers), "merges": merges,
        "identification": per_db, "minted_ids": minted, "enrichment": enrich, "sem_sim": sem,
        "doi_coverage": f"{sum(1 for p in papers if p.get('doi'))}/{len(papers)}",
        "abstracts_missing": sum(1 for p in papers if not p["has_abstract"]),
        "anchor_terms": cfg.get("anchor_terms"), "without_anchor_term": sum(1 for p in papers if p["anchor_match"] is False),
        "dense_only": sum(1 for p in papers if p["found_by"] == [DENSE_ID]), "retired_only": sum(1 for p in papers if p["retired_only"]),
        "superseded_only": sum(1 for p in papers if p["superseded_only"]), "untitled_records": untitled,
        "caveats": caveats,
    }
    out = {"schema": RAW_SCHEMA, "topic": cfg.get("topic"), "search_timestamp": now_iso(), "search_summary": summary,
           "papers": papers}
    rp = Path(rd) / "step2_raw_papers.json"
    out = with_legacy(rp, out)                                     # compared as written: with the archived fields
    if rp.exists() and _same_collection(read_json(rp), out):      # an unchanged merge keeps the file as it was (its
        out = read_json(rp)                                        # stamp and minted-id count included), so nothing
    else:                                                          # downstream goes stale
        write_json(rp, out)
    write_text(Path(rd) / "step2_search_summary.md",
               it_legacy.search_summary_md(render_summary(cfg, out, insts_now), cfg, out, insts_now))
    return out


def _same_collection(old: dict, new: dict) -> bool:
    """Two merges of the same instances: equal apart from the merge's own stamp and the ids it minted this time."""
    def strip(d):
        d = json.loads(json.dumps(d, ensure_ascii=False))
        d.pop("search_timestamp", None)
        (d.get("search_summary") or {}).pop("minted_ids", None)
        return d
    return strip(old) == strip(new)


def render_summary(cfg: dict, raw: dict, insts: list[dict]) -> str:
    s = raw["search_summary"]
    L = ["<!-- generated by A2.m (`mcp_bridge.py merge`) - do not edit -->", "# Search summary", "",
         f"Topic: {cfg.get('topic')}", "",
         f"- {s['total_raw_results']} records from {len(s['instances'])} instances -> **{s['after_dedup']} papers** after merging "
         f"(by DOI {s['merges'].get('doi', 0)}, arXiv id {s['merges'].get('arxiv', 0)}, fuzzy title {s['merges'].get('fuzzy', 0)}, "
         f"exact title {s['merges'].get('exact', 0)})",
         f"- DOI coverage {s['doi_coverage']}; abstracts missing {s['abstracts_missing']} (OpenAlex added "
         f"{s['enrichment']['abstracts']}); open-access links {s['enrichment']['oa_links']}",
         f"- Anchor terms {s['anchor_terms']}: {s['without_anchor_term']} papers match none",
         f"- Dense-only papers: {s['dense_only']} · found only by retired queries: {s['retired_only']} · only by superseded "
         f"instances: {s.get('superseded_only', 0)} · semantic similarity: {s['sem_sim']}",
         "", "## Identification (PRISMA)", "", "| Database | Records retrieved | Sum of reported totals | Queries answered | Errors |",
         "|---|---|---|---|---|"]
    L += [f"| {db} | {d['retrieved']} | {d['reported_total_sum']} | {d['queries']} | {d['errors']} |"
          for db, d in sorted(s["identification"].items())]
    L += ["", "## Per query", "", "| Query | Strategy | Source | Form | Sent | Returned / total |", "|---|---|---|---|---|---|"]
    for r in insts:
        for src, ps in r.get("per_source", {}).items():
            a = _final(ps)
            res = f"{a['returned']} / {a.get('total')}" if "returned" in a else (a.get("error") or a.get("skipped") or "")
            L.append(f"| {r['id']} | {r.get('strategy')} | {src} | {ps.get('form')} | `{str(a.get('sent_query'))[:90]}` | "
                     f"{str(res)[:60]} |")
    if s["caveats"]:
        L += ["", "## Caveats", ""] + [f"- **{c['code']}**{' (must disclose)' if c['must_disclose'] else ''}: {c['text']}"
                                       for c in s["caveats"]]
    L += ["", "## First 12 titles", ""] + [f"{i + 1}. ({p.get('year')}) {str(p.get('title'))[:110]}"
                                         for i, p in enumerate(raw["papers"][:12])]
    return "\n".join(L) + "\n"


# ================================================================================================= A2.c relevance
def _paper_text(p):
    return f"{p.get('title') or ''} {p.get('abstract') or ''}".lower()


def _term_in(term: str, text: str) -> bool:
    t = str(term).lower().replace("*", "")
    return bool(t) and t in text


def _when(s) -> float:
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(s)).timestamp()
    except ValueError:
        return 0.0


def epoch(cfg: dict, rel: dict | None) -> dict:
    """The current A2.c epoch (§15 G2). A1.p resetting the protocol after the search started is a new question for the
    relevance check: its rounds, its re-plan limit (R04) and its saturation (R09) start again; the earlier rounds stay
    in the file. A round knows its protocol (`protocol_sha`); an older round without one belongs to the epoch when it
    came after the last such reset. {start, protocol_sha, rounds}."""
    from it_frame import protocol_content_hash
    ph = protocol_content_hash(cfg)
    rounds = list((rel or {}).get("rounds") or [])
    first = _when(rounds[0].get("at")) if rounds else None
    resets = [_when(h.get("at")) for h in ((cfg.get("protocol") or {}).get("history") or [])
              if h.get("by") == "A1.p" and h.get("action") == "reset" and first is not None and _when(h.get("at")) > first]
    start = max(resets) if resets else None
    keep = [r for r in rounds if (r["protocol_sha"] == ph if r.get("protocol_sha") else
                                  start is None or _when(r.get("at")) > start)]
    return {"start": start, "protocol_sha": ph, "rounds": keep}


def query_rounds(cfg: dict, ep: dict | None = None) -> dict:
    """Round in which each query entered: 0 for A1.q's, k for a replacement added by A2.c in round k. In an epoch
    after a protocol reset, a query that came in before the epoch's first round is part of its base (0), and a later
    one entered in the round after the epoch rounds before it."""
    rounds = {q["id"]: 0 for q in cfg.get("queries") or []}
    start = (ep or {}).get("start")
    ep_times = [_when(r.get("at")) for r in (ep or {}).get("rounds") or []]
    for h in cfg.get("queries_history") or []:
        if h.get("action") == "revise" and (h.get("added") or {}).get("id"):
            if start is None:
                rounds[h["added"]["id"]] = int(h.get("round") or 1)
            else:
                at = _when(h.get("at"))
                rounds[h["added"]["id"]] = 0 if at <= start else sum(1 for t in ep_times if t < at)
    return rounds


def signals(cfg: dict, rd: Path) -> dict:
    from it_frame import match_known_items
    raw = read_json(Path(rd) / "step2_raw_papers.json")
    papers = raw.get("papers") or []
    p = cfg.get("protocol") or {}
    axes = {a["id"]: a for a in p.get("axes") or []}
    texts = {x["id"]: _paper_text(x) for x in papers}
    rel = read_json(relevance_path(rd)) if relevance_path(rd).exists() else None
    rounds = query_rounds(cfg, epoch(cfg, rel))
    per_q = {}
    for q in cfg.get("queries") or []:
        mine = [x for x in papers if q["id"] in (x.get("found_by") or [])]
        f = latest_instance(rd, q["id"])
        inst = read_json(f) if f else {}
        st = source_status(inst) if inst else {}
        anchored = [x for x in mine if x.get("anchor_match")]
        named = {}
        if q.get("strategy") == "anchor-methods":
            from it_frame import selected_terms
            sel = selected_terms(p, q)                     # the anchors this query asks, not the whole axis
            for aid in (q.get("axes") or {}):
                if (axes.get(aid) or {}).get("kind") == "anchor":
                    for t in sel.get(aid) or []:
                        named[t] = sum(1 for x in mine if _term_in(t, texts[x["id"]]))
        per_q[q["id"]] = {
            "strategy": q.get("strategy"), "status": q.get("status", "active"), "round": rounds.get(q["id"], 0),
            "instance": f.name if f else None,
            "stale_instance": bool(f) and inst.get("hash") != instance_hash(cfg, q, inst.get("limit", LIMIT)),
            "papers": len(mine), "only_this_query": sum(1 for x in mine if x.get("found_by") == [q["id"]]),
            "on_anchor_share": round(len(anchored) / len(mine), 3) if mine else 0.0,
            "per_source": {s: {"status": v[0], "returned": v[1], "total": v[2], "error": v[3]} for s, v in st.items()},
            "anchor_terms_found": named,
        }
    # outcomes: papers per outcome, through the outcome axes when there are any
    outcomes = {}
    for o in p.get("outcomes") or []:
        terms = [t for a in axes.values() if a.get("outcome") == o["id"] for t in a.get("terms") or []]
        outcomes[o["id"]] = (sum(1 for x in papers if any(_term_in(t, texts[x["id"]]) for t in terms))
                             if terms else None)
    from it_overrides import entries as overrides         # a person's known items count like A1.q's
    extra = [{"title": e.get("title"), "doi": e.get("doi"), "why": e.get("reason"), "added_by": "human"}
             for e in overrides(rd, "known_item") if e.get("title") or e.get("doi")]
    known = match_known_items([k for k in cfg.get("known_items") or []] + extra, papers)
    # saturation: share of papers first found by the queries of the latest re-plan round
    latest = max([r for qid, r in rounds.items()] or [0])
    new_share = None
    if latest > 0:
        newer = {qid for qid, r in rounds.items() if r == latest}
        older_or_dense = lambda fb: any(rounds.get(f, 0) < latest for f in fb if f != DENSE_ID)
        new = [x for x in papers if set(x.get("found_by") or []) & newer and not older_or_dense(x.get("found_by") or [])]
        new_share = round(len(new) / len(papers), 4) if papers else 0.0
    # overlap between active queries (Jaccard of their paper sets), the five largest
    sets = {qid: {x["id"] for x in papers if qid in (x.get("found_by") or [])}
            for qid, v in per_q.items() if v["status"] == "active"}
    pairs = sorted(((len(a & b) / len(a | b), qa, qb) for qa, a in sets.items() for qb, b in sets.items()
                    if qa < qb and (a | b)), reverse=True)[:5]
    # vocabulary feedback: high-similarity papers without any anchor term -> words the axes do not have
    vocab = None
    if any("sem_sim" in x for x in papers):
        known_words = {w for a in axes.values() for t in a.get("terms") or [] for w in re.findall(r"[a-z0-9]+", t.lower())}
        cand = sorted((x for x in papers if x.get("anchor_match") is False and x.get("sem_pct") is not None
                       and x["sem_pct"] >= SEM_HIGH_PCT), key=lambda x: -x["sem_sim"])[:20]
        words = Counter(w for x in cand for w in set(re.findall(r"[a-z][a-z0-9-]{3,}", texts[x["id"]]))
                        if w not in STOP and w not in known_words)
        vocab = {"papers": [{"id": x["id"], "sem_sim": x["sem_sim"], "sem_pct": x["sem_pct"], "title": x.get("title")}
                            for x in cand[:10]],
                 "high_sim_without_anchor": len(cand),
                 "candidate_terms": [w for w, n in words.most_common(15) if n >= 2]}
    dense = [x for x in papers if DENSE_ID in (x.get("found_by") or [])]
    return {"at": now_iso(), "term_pull": term_pull(p, papers, texts), "raw_sha": sha256_file(Path(rd) / "step2_raw_papers.json"), "papers": len(papers),
            "latest_round": latest, "new_share_latest_round": new_share, "queries": per_q, "outcomes": outcomes,
            "known_items": known, "overlap_top": [{"a": a, "b": b, "jaccard": round(j, 3)} for j, a, b in pairs],
            "dense": {"papers": len(dense), "dense_only": sum(1 for x in dense if x.get("found_by") == [DENSE_ID])},
            "vocabulary": vocab, "anchor_min": ANCHOR_MIN, "saturated_below": SATURATED, "max_rounds": MAX_ROUNDS}


def term_pull(protocol: dict, papers: list, texts: dict) -> list | None:
    """Per axis term, the papers the axis matched through that term alone, and how many of them are semantically far
    (sem_pct < 25, where a quarter of any collection lies). A term flagged here brings in mostly what the protocol
    does not mean ("automated cleaning" -> solar panels): A2.c keeps it with a reason or retires it. None without
    sem_sim. Retired terms are left out."""
    if not any(x.get("sem_pct") is not None for x in papers):
        return None
    out = []
    for a in protocol.get("axes") or []:
        if a.get("kind") not in ("search", "contrast"):
            continue                                   # an anchor term is a named method, revised by its query
        retired = {r.get("term") for r in a.get("retired") or []}
        terms = [t for t in a.get("terms") or [] if t not in retired]
        if len(terms) < 2:
            continue                                   # one term: its catch is the axis itself
        for t in terms:
            own = [x for x in papers if _term_in(t, texts[x["id"]])
                   and not any(_term_in(o, texts[x["id"]]) for o in terms if o != t)]
            scored = [x for x in own if x.get("sem_pct") is not None]
            far = [x for x in scored if x["sem_pct"] < SEM_LOW_PCT]
            share = round(len(far) / len(scored), 3) if scored else 0.0
            by = lambda xs: dict(sorted(Counter(q for x in xs for q in x.get("found_by") or []).items()))
            out.append({"axis": a["id"], "term": t, "own": len(own), "far": len(far), "far_share": share,
                        "flagged": len(scored) >= PULL_MIN and share >= PULL_SHARE,
                        # which queries bring the far and the near ones: a term loose only in a `loosen` variant
                        # (the axis asked without the population) is precise where it is ANDed with it
                        "far_by_query": by(far), "near_by_query": by([x for x in scored if x not in far]),
                        "near_titles": [str(x.get("title"))[:90] for x in sorted(scored, key=lambda x: -x["sem_pct"])
                                        if x not in far][:3],
                        "far_titles": [str(x.get("title"))[:90] for x in sorted(far, key=lambda x: x["sem_pct"])[:3]]})
    return out


def ok_forbidden(sig_q: dict) -> str | None:
    """Why a query may not be judged ok, or None."""
    if sig_q["status"] != "active":
        return None
    if sig_q["papers"] == 0:
        return "it found no paper"
    if sig_q["on_anchor_share"] < ANCHOR_MIN:
        return f"only {sig_q['on_anchor_share']:.0%} of its papers contain an anchor term (< {ANCHOR_MIN:.0%})"
    missing = [t for t, n in (sig_q.get("anchor_terms_found") or {}).items() if n == 0]
    if missing:
        return f"the anchors it names are in no paper: {missing}"
    if sig_q.get("stale_instance"):
        return "its last run used an older rendering (the protocol changed): run it again"
    return None


def relevance_path(rd: Path) -> Path:
    return Path(rd) / "step2_relevance_check.json"


def check_round(cfg: dict, sig: dict, rnd: dict, rounds_before: int, prev: dict | None = None) -> list[dict]:
    U = "A2.c"
    fs = []
    status = {q["id"]: q.get("status", "active") for q in cfg.get("queries") or []}
    for v in (prev or {}).get("verdicts") or []:
        if v.get("verdict") == "replan" and status.get(v.get("query")) == "active":
            fs.append(F("ERROR", "R03", U, f"{v['query']} was judged replan in the previous round but is still active: "
                                          "`frame query-revise` it (and run the replacement) before the next round"))
    active = [qid for qid, v in sig["queries"].items() if v["status"] == "active"]
    vs = {v.get("query"): v for v in rnd.get("verdicts") or [] if isinstance(v, dict)}
    for qid in active:
        if qid not in vs:
            fs.append(F("ERROR", "R01", U, f"no verdict for active query {qid}"))
    for qid, v in vs.items():
        if qid not in sig["queries"]:
            fs.append(F("ERROR", "R01", U, f"verdict for unknown query {qid}"))
            continue
        if v.get("verdict") not in VERDICTS:
            fs.append(F("ERROR", "R01", U, f"{qid}: verdict must be one of {VERDICTS}"))
        if v.get("verdict") in ("replan", "accept-weak") and not str(v.get("reason", "")).strip():
            fs.append(F("ERROR", "R06", U, f"{qid}: a {v.get('verdict')} verdict needs a reason"))
        why = ok_forbidden(sig["queries"][qid])
        if v.get("verdict") == "ok" and why:
            fs.append(F("ERROR", "R02", U, f"{qid} cannot be ok: {why}"))
    n = rounds_before + 1
    if n > MAX_ROUNDS:
        fs.append(F("ERROR", "R04", U, f"{MAX_ROUNDS} rounds already ran; the check is final"))
    final_round = n >= MAX_ROUNDS
    saturated = sig.get("new_share_latest_round") is not None and sig["new_share_latest_round"] < SATURATED
    for qid, v in vs.items():
        if v.get("verdict") == "replan" and final_round:
            fs.append(F("ERROR", "R03", U, f"{qid}: round {n} is the last one - accept-weak with the reason instead of replan"))
        if v.get("verdict") == "replan" and saturated:
            fs.append(F("ERROR", "R09", U, f"{qid}: the last re-plan round added {sig['new_share_latest_round']:.1%} new "
                                          f"papers (< {SATURATED:.0%}): the search is saturated - accept-weak instead"))
    ans = {(a.get("axis"), a.get("term")): a for a in rnd.get("term_pull") or [] if isinstance(a, dict)}
    pulls = {(t["axis"], t["term"]): t for t in sig.get("term_pull") or []}
    for key, t in pulls.items():
        if t["flagged"] and key not in ans:
            fs.append(F("ERROR", "R10", U, f"{t['axis']} {t['term']!r}: {t['far']} of the {t['own']} papers only it brings "
                                          "in are semantically far - keep it with a reason, or retire it"))
    for key, a in ans.items():
        if key not in pulls:
            fs.append(F("ERROR", "R10", U, f"term_pull answer for {key[0]} {key[1]!r}, not a term of that axis"))
        elif a.get("action") not in ("keep", "retire") or not str(a.get("reason", "")).strip():
            fs.append(F("ERROR", "R10", U, f"{key[0]} {key[1]!r}: the answer is keep or retire, with a reason"))
    fs += retire_pending(cfg, prev)
    acts = {a.get("ref"): a for a in rnd.get("known_items") or [] if isinstance(a, dict)}
    for k in sig.get("known_items") or []:
        if not k["resolved"]:
            a = acts.get(k["ref"])
            if not a or not str(a.get("action", "")).strip() or not str(a.get("reason", "")).strip():
                fs.append(F("ERROR", "R05", U, f"known item not in the collection, and no action with a reason: {k['ref']}"))
    return fs


def retire_pending(cfg: dict, rnd: dict | None) -> list[dict]:
    """R11: a term the round decided to retire that the protocol still uses (`frame retire-terms` not run)."""
    axes = {a["id"]: a for a in (cfg.get("protocol") or {}).get("axes") or []}
    fs = []
    for a in (rnd or {}).get("term_pull") or []:
        ax = axes.get(a.get("axis")) or {}
        if a.get("action") == "retire" and a.get("term") not in {r.get("term") for r in ax.get("retired") or []}:
            fs.append(F("ERROR", "R11", "A2.c", f"{a.get('axis')} {a.get('term')!r} was judged retire but the protocol "
                                                "still uses it: `frame retire-terms`, run the affected queries again"))
    return fs


def check_relevance(cfg: dict, rd: Path) -> list[dict]:
    U = "A2.c"
    p = relevance_path(rd)
    if not p.exists():
        return [F("ERROR", "R00", U, "no step2_relevance_check.json: run `ideate_tools.py search-check`, judge each "
                                     "query, store the verdicts with `relevance-set`")]
    ev = read_json(p)
    rounds = ev.get("rounds") or []
    if not rounds:
        return [F("ERROR", "R00", U, "the relevance check has no rounds")]
    last = rounds[-1]
    fs = []
    if last.get("raw_sha") != sha256_file(Path(rd) / "step2_raw_papers.json"):
        fs.append(F("ERROR", "R07", U, "STALE: the collection changed after the last verdicts (a re-run query was "
                                       "merged): run `search-check` and judge again"))
    fs += retire_pending(cfg, last)
    pending = [v["query"] for v in last.get("verdicts") or [] if v.get("verdict") == "replan"]
    if pending:
        fs.append(F("ERROR", "R08", U, f"re-plan pending for {pending}: `frame query-revise`, `mcp_bridge.py search "
                                       "--only <new id>`, then a new round"))
    return fs


# ======================================================================================================= A2.s / A2.m
def check_instances(cfg: dict, rd: Path) -> list[dict]:
    U = "A2.s"
    fs = []
    for q in cfg.get("queries") or []:
        if q.get("status", "active") != "active":
            continue
        f = latest_instance(rd, q["id"])
        if f is None:
            fs.append(F("ERROR", "S01", U, f"{q['id']} has not been run"))
            continue
        rec = read_json(f)
        if not rec.get("complete"):
            fs.append(F("ERROR", "S01", U, f"{q['id']}: the instance {f.name} is incomplete (interrupted): run it again"))
        planned = [s for g in (rec.get("plan") or {}).values() for s in g["sources"]]
        for s in planned:
            if s not in rec.get("per_source", {}):
                fs.append(F("ERROR", "S02", U, f"{q['id']}: source {s} was planned but has no answer, error or skip"))
        for s, ps in rec.get("per_source", {}).items():
            for a in ps.get("attempts") or []:
                if not a.get("sent_query") or not a.get("at") or "filters" not in a:
                    fs.append(F("ERROR", "S03", U, f"{q['id']}/{s}: an attempt without sent_query / at / filters (PRISMA-S)"))
                    break
        if any(p.get("found_via") != q["id"] or not p.get("sources_found_in") for p in rec.get("papers") or []):
            fs.append(F("ERROR", "S04", U, f"{q['id']}: papers must carry found_via {q['id']} and sources_found_in"))
    if cfg.get("depth") != "quick":
        f = latest_instance(rd, DENSE_ID)
        if f is None:
            fs.append(F("WARN", "S05", U, "the dense instance D1 has not run (standard / deep run it with the search)"))
        elif source_status(read_json(f))["semantic_scholar"][0] != "ok":
            fs.append(F("WARN", "S05", U, "dense retrieval skipped: " + str(source_status(read_json(f))["semantic_scholar"][3])))
    return fs


def check_merge(cfg: dict, rd: Path) -> list[dict]:
    U = "A2.m"
    path = Path(rd) / "step2_raw_papers.json"
    if not path.exists():
        return [F("ERROR", "M00", U, "no step2_raw_papers.json: run `mcp_bridge.py merge`")]
    raw = read_json(path)
    if raw.get("schema") != RAW_SCHEMA:
        return [F("ERROR", "M00", U, f"step2_raw_papers.json is not {RAW_SCHEMA}: run `mcp_bridge.py merge`")]
    papers = raw.get("papers") or []
    s = raw.get("search_summary") or {}
    fs = []
    cur = [{"file": f.name, "sha": sha256_file(f)} for f in merge_files(rd, cfg)]
    if cur != s.get("instances"):
        fs.append(F("ERROR", "M05", U, "STALE: query instances changed after the merge: run `mcp_bridge.py merge`"))
    insts = [read_json(query_dir(rd) / i["file"]) for i in s.get("instances") or [] if (query_dir(rd) / i["file"]).exists()]
    titled_only = "untitled_records" in s          # a merge that leaves untitled records out counts only the titled
    n_records = sum(1 for r in insts for x in r.get("papers") or []
                    if not titled_only or norm_title(x.get("title")) or x.get("doi") or _arxiv_of(x))
    if sum(int(p.get("merged_from") or 0) for p in papers) != n_records or s.get("total_raw_results") != n_records:
        fs.append(F("ERROR", "M01", U, f"funnel broken: {n_records} records in the instances, "
                                       f"{sum(int(p.get('merged_from') or 0) for p in papers)} accounted for by the papers"))
    ids = [p.get("id") for p in papers]
    reg = {e["id"]: e for e in load_registry(rd)}
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup or any(i not in reg for i in ids):
        fs.append(F("ERROR", "M02", U, f"ids must be unique and registered: duplicates {dup[:5]}, unregistered "
                                       f"{[i for i in ids if i not in reg][:5]}"))
    minted = {e["id"] for e in load_registry(rd) if e.get("minted_by") == "A2.m"
              and (e.get("title") or e.get("dois") or e.get("arxiv"))}    # an id minted for a blank record is no paper
    absorbed = {e["id"]: e["merged_into"] for e in load_registry(rd) if e.get("merged_into")}
    vanished = sorted(i for i in minted if i not in set(ids) and absorbed.get(i) not in set(ids))
    if vanished:
        fs.append(F("ERROR", "M01", U, f"papers vanished from the collection: {vanished[:8]}"))
    known = {q["id"] for q in cfg.get("queries") or []} | {DENSE_ID} | {f.stem for f in superseded_files(rd, cfg)}
    for p in papers:
        fb = p.get("found_by")
        if not isinstance(fb, list) or not fb or not set(fb) <= known:
            fs.append(F("ERROR", "M03", U, f"{p.get('id')}: found_by must be a non-empty list of query ids, got {fb!r}"))
            break
    seen = {}
    for p in papers:
        for k in list(_dois(p)) + ([f"arxiv:{_arxiv_of(p)}"] if _arxiv_of(p) else []):
            if k in seen and seen[k] != p.get("id"):
                fs.append(F("ERROR", "M04", U, f"{seen[k]} and {p.get('id')} share {k}: one paper, two records"))
            seen[k] = p.get("id")
    retired = {q["id"] for q in cfg.get("queries") or [] if q.get("status") == "retired"}
    for p in papers:
        probe = {k: p.get(k) for k in ("anchor_match", "has_abstract", "code_hint", "retired_only", "found_via")}
        computed_fields(cfg, p, retired)
        if probe != {k: p.get(k) for k in probe}:
            fs.append(F("ERROR", "M06", U, f"{p.get('id')}: computed fields were edited by hand ({probe})"))
            break
    m = re.findall(r"\d{4}", str((cfg.get("protocol") or {}).get("timeframe") or ""))
    if len(m) >= 2:
        lo, hi = int(m[0]), int(m[1])
        out = [p for p in papers if isinstance(p.get("year"), int) and not lo <= p["year"] <= hi and
               not p.get("superseded_only")]
        if out:
            fs.append(F("WARN", "M07", U, f"{len(out)} paper(s) outside the timeframe {lo}-{hi} (a source ignored the "
                                          f"year filter): {[(x['id'], x['year']) for x in out[:5]]}"))
    return fs


def run_checks(cfg: dict, rd: Path, unit: str = "all") -> list[dict]:
    require_protocol(cfg, rd)
    fs = []
    if unit in ("all", "A2.s"):
        fs += check_instances(cfg, rd)
    if unit in ("all", "A2.m"):
        fs += check_merge(cfg, rd)
    if unit in ("all", "A2.c"):
        import it_overrides
        fs += check_relevance(cfg, rd) + [f for f in it_overrides.check(rd) if f["unit"] == "A2.c"]
    return fs


def screen_gate(cfg: dict, rd: Path) -> list[dict]:
    """What A3 requires of A2 before it may screen: A2.s, A2.m and A2.c pass."""
    return errors(run_checks(cfg, rd))


# ========================================================================================================= commands
def _cfg(rd: Path) -> dict:
    p = Path(rd) / "step0_session_config.json"
    if not p.exists():
        die(f"{p} not found", 2)
    return read_json(p)


def _cmd_search_check(a):
    rd = Path(a.research_dir)
    cfg = _cfg(rd)
    require_protocol(cfg, rd)
    sig = signals(cfg, rd)
    rel = read_json(relevance_path(rd)) if relevance_path(rd).exists() else {"rounds": []}
    n = len(rel["rounds"])
    write_json(rd / "_state" / "A2c" / f"signals_r{n}.json", sig)
    if a.json:
        print(json.dumps(sig, indent=2, ensure_ascii=False))
        return
    print(f"A2.c signals, round {n} ({sig['papers']} papers; on-anchor floor {ANCHOR_MIN:.0%}):")
    for qid, v in sig["queries"].items():
        src = " ".join(f"{s}={d['returned'] if d['status'] == 'ok' else d['status']}" + (f"/{d['total']}" if d.get("total") else "")
                       for s, d in v["per_source"].items())
        why = ok_forbidden(v)
        print(f"  {qid:<5} {v['strategy'] or '':<16} {v['status']:<8} papers={v['papers']:<4} only-here={v['only_this_query']:<4} "
              f"on-anchor={v['on_anchor_share']:.0%}  {src}" + (f"   NOT OK: {why}" if why else ""))
    ki = sig["known_items"]
    print(f"  known items in the collection: {sum(1 for k in ki if k['resolved'])}/{len(ki)}"
          + "".join(f"\n   MISSING: {k['ref']}" for k in ki if not k["resolved"]))
    print(f"  outcomes: {sig['outcomes']} · dense: {sig['dense']} · new in latest round: {sig['new_share_latest_round']}")
    if sig["overlap_top"]:
        print("  largest overlaps: " + ", ".join(f"{o['a']}~{o['b']} {o['jaccard']}" for o in sig["overlap_top"]))
    if sig["vocabulary"] and sig["vocabulary"]["high_sim_without_anchor"]:
        print(f"  vocabulary feedback: {sig['vocabulary']['high_sim_without_anchor']} paper(s) in the top "
              f"{100 - SEM_HIGH_PCT}% by sem_sim contain no anchor term; candidate terms: "
              + (", ".join(sig["vocabulary"]["candidate_terms"]) or "(none repeated in 2+ papers)"))
        for x in sig["vocabulary"]["papers"][:5]:
            print(f"     pct {x['sem_pct']:5.1f}  {str(x['title'])[:90]}")
    elif sig["vocabulary"]:
        print(f"  vocabulary feedback: no paper in the top {100 - SEM_HIGH_PCT}% by sem_sim lacks an anchor term - "
              "no missing synonym detected")
    else:
        print("  vocabulary feedback: not available (no sem_sim - the embedding model is not downloaded)")
    flagged = [t for t in sig["term_pull"] or [] if t["flagged"]]
    if flagged:
        print("  ambiguous terms (answer each under `term_pull`: keep or retire, with a reason):")
        for t in flagged:
            print(f"     {t['axis']} {t['term']!r}: {t['far']} of the {t['own']} papers only it brings in are in the bottom "
                  f"{SEM_LOW_PCT}% by sem_sim, e.g. " + " | ".join(t["far_titles"]))
            print(f"       far ones found by {t['far_by_query']}; the near ones by {t['near_by_query']}"
                  + (": " + " | ".join(t["near_titles"]) if t["near_titles"] else ""))
    elif sig["term_pull"] is not None:
        print(f"  ambiguous terms: none (no term's own catch is >= {PULL_MIN} papers with half in the bottom {SEM_LOW_PCT}%)")


def _cmd_relevance_set(a):
    rd = Path(a.research_dir)
    cfg = _cfg(rd)
    rnd = read_json(Path(a.input_json))
    extra = sorted(set(rnd) - {"verdicts", "known_items", "vocabulary", "term_pull", "summary", "model"})
    if extra:
        die(f"verdicts.json has keys A2.c does not own: {extra}", 2)
    rel = read_json(relevance_path(rd)) if relevance_path(rd).exists() else {"schema": "ideate-relevance/1", "rounds": []}
    sig = signals(cfg, rd)
    last = rel["rounds"][-1] if rel["rounds"] else None
    if last and last.get("raw_sha") == sig["raw_sha"] and all(last.get(k) == rnd.get(k) for k in
                                                              ("verdicts", "known_items", "vocabulary", "term_pull",
                                                               "summary", "model")):
        rel["rounds"].pop()                      # the same verdicts stored again (a resumed run): the same round
    ep = epoch(cfg, rel)
    fs = check_round(cfg, sig, rnd, len(ep["rounds"]), ep["rounds"][-1] if ep["rounds"] else None)
    for f in fs:
        print(f"  {f['level']:<5} {f['code']} [{f['unit']}] {f['msg']}")
    if errors(fs):
        die(f"{len(errors(fs))} error(s) in the verdicts; nothing was written", 2)
    rel["rounds"].append({"round": len(rel["rounds"]), "epoch_round": len(ep["rounds"]),
                          "protocol_sha": ep["protocol_sha"], "at": now_iso(), "raw_sha": sig["raw_sha"],
                          # term_pull is a list in every round (empty when nothing was computed); whether it was
                          # computed at all (no sem_sim: not) is term_pull_computed
                          "signals": {**{k: sig[k] for k in ("papers", "new_share_latest_round", "known_items", "outcomes",
                                                             "dense")},
                                      "term_pull": sig["term_pull"] or [],
                                      "term_pull_computed": sig["term_pull"] is not None},
                          **rnd})
    caveats = []
    for v in rnd.get("verdicts") or []:
        if v.get("verdict") == "accept-weak":
            caveats.append({"code": "accept-weak", "text": f"{v['query']}: {v['reason']}", "must_disclose": True})
    for k in rnd.get("known_items") or []:
        if str(k.get("action", "")).startswith("accept-weak"):
            caveats.append({"code": "known-item-missing", "text": f"{k['ref']}: {k['reason']}", "must_disclose": True})
    rel["caveats"] = caveats
    for r in rel["rounds"]:                       # a round stored before term_pull was always a list: the same shape
        sg = r.get("signals")
        if isinstance(sg, dict) and "term_pull_computed" not in sg:
            sg["term_pull_computed"] = sg.get("term_pull") is not None
            sg["term_pull"] = sg.get("term_pull") or []
    write_json(relevance_path(rd), rel)
    write_text(rd / "step2_relevance_check.md", render_relevance(rel))
    for t in rnd.get("term_pull") or []:
        if t.get("action") == "retire":
            print(f"  retire {t['axis']} {t['term']!r}: `frame retire-terms`, then run the affected queries again")
    n_rep = sum(1 for v in rnd.get("verdicts") or [] if v.get("verdict") == "replan")
    if not ep["rounds"] and len(rel["rounds"]) > 1:
        print(f"  the protocol was reset after the search: this is round 0 of a new epoch "
              f"({len(rel['rounds']) - 1} earlier round(s) kept in the file, not counted)")
    print(f"A2.c: round {len(rel['rounds']) - 1} stored - " + (f"{n_rep} re-plan(s): `frame query-revise`, then "
          "`mcp_bridge.py search --only <new id>`, then search-check again" if n_rep else "no re-plan: A2 is done"))


def render_relevance(rel: dict) -> str:
    L = ["<!-- generated by A2.c (`ideate_tools.py relevance-set`) - do not edit -->", "# Relevance check (A2.c)", ""]
    prev_sha = None
    for r in rel.get("rounds") or []:
        if prev_sha and r.get("protocol_sha") and r["protocol_sha"] != prev_sha:
            L += ["**The protocol was revised (A1.p) - a new epoch: rounds, the re-plan limit and saturation start again.**", ""]
        prev_sha = r.get("protocol_sha") or prev_sha
        L += [f"## Round {r['round']} ({r['at']})", "", str(r.get("summary") or ""), "",
              "| Query | Verdict | Reason |", "|---|---|---|"]
        L += [f"| {v.get('query')} | {v.get('verdict')} | {str(v.get('reason', '')).replace('|', '/')} |" for v in r.get("verdicts") or []]
        if r.get("known_items"):
            L += ["", "Known items not found: " + "; ".join(f"{k.get('ref')} → {k.get('action')} ({k.get('reason')})"
                                                          for k in r["known_items"])]
        if r.get("vocabulary"):
            L += ["", "Vocabulary: " + "; ".join(f"{v.get('axis')} {v.get('term')!r} {v.get('action')} ({v.get('reason')})"
                                                 for v in r["vocabulary"])]
        if r.get("term_pull"):
            L += ["", "Ambiguous terms: " + "; ".join(f"{v.get('axis')} {v.get('term')!r} {v.get('action')} ({v.get('reason')})"
                                                      for v in r["term_pull"])]
        L.append("")
    if rel.get("caveats"):
        L += ["## Caveats", ""] + [f"- **{c['code']}**{' (must disclose)' if c['must_disclose'] else ''}: {c['text']}"
                                   for c in rel["caveats"]]
    return "\n".join(L) + "\n"


def cmd_a2_check(a):
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
async def run_search(server, cfg: dict, rd: Path, *args, **kw):
    """A2.s: done once every active query and D1 has a complete instance for its current rendering."""
    from it_ledger import degraded_codes, run_unit
    with run_unit(rd, "A2.s", check=lambda: check_instances(_cfg(Path(rd)), Path(rd)),
                  degraded=lambda: degraded_codes(rd, "A2.s")):
        return await _run_search(server, cfg, rd, *args, **kw)


async def run_merge(server, cfg: dict, rd: Path, *args, **kw):
    """A2.m: done once the merged collection passes its checks."""
    from it_ledger import run_unit
    with run_unit(rd, "A2.m", check=lambda: check_merge(_cfg(Path(rd)), Path(rd))):
        return await _run_merge(server, cfg, rd, *args, **kw)


def cmd_search_check(a):
    """A2.c begins with the signals; relevance-set closes it when no re-plan is pending."""
    from it_ledger import begin
    _cmd_search_check(a)
    begin(a.research_dir, "A2.c")


def cmd_relevance_set(a):
    from it_ledger import _begin_event, _events, begin, degraded_codes, done, pending
    rd = Path(a.research_dir)
    if _begin_event(_events(rd), "A2.c", "-")[1] is None:
        begin(rd, "A2.c")
    try:
        _cmd_relevance_set(a)
    except BaseException as e:  # noqa: BLE001 - a refusal is recorded, then propagates
        __import__("it_ledger").fail(rd, "A2.c", f"{type(e).__name__}: {str(e)[:160]}")
        raise
    errs = errors(check_relevance(_cfg(rd), rd))
    if errs:
        pending(rd, "A2.c", f"{errs[0]['code']}: {errs[0]['msg'][:160]}")
    else:
        done(rd, "A2.c", degraded=degraded_codes(rd, "A2.c"))


def add_parsers(sub) -> None:
    sp = sub.add_parser("search-check", help="A2.c signals per query (references/search/A2-search.md#a2c)")
    sp.add_argument("research_dir")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_search_check)
    sp = sub.add_parser("relevance-set", help="A2.c: store one round of verdicts")
    sp.add_argument("research_dir")
    sp.add_argument("input_json")
    sp.set_defaults(fn=cmd_relevance_set)
    sp = sub.add_parser("a2-check", help="A2 handoff checks (A2.s, A2.m, A2.c)")
    sp.add_argument("research_dir")
    sp.add_argument("--unit", default="all", choices=["all", "A2.s", "A2.m", "A2.c"])
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_a2_check)
