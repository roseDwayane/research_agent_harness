"""Step 2 — research-search.  **Pure code**: no LLM anywhere.

Phases (mirrors SKILL.md): multi-source search → dedup + DOI recovery →
snowball → citation network → save.  Determinism: every external response is
cached; ID assignment and every sort use stable keys (never citation counts
alone, which drift between API snapshots).
"""
from __future__ import annotations

import re
import time
from collections import Counter, defaultdict
from typing import Any

from evaluation.step02.match import as_match_record, match_gold
from ..providers.arxiv import ArXiv
from ..providers.openalex import OpenAlex
from ..providers.pubmed import PubMed
from ..providers.records import Hit
from ..providers.semantic_scholar import SemanticScholar
from ..render.step2 import render_search_summary
from ..schemas.paper import CitationNetwork, Cluster, Paper, RawPapers, SearchSummary
from ..schemas.session_config import SessionConfig
from ..utils import dump_json, last_name, normalize_title, title_tokens, word_overlap, write_text
from .base import Context, StepOutput

STOPWORDS = set("a an the of for and or in on with to from by via using based towards toward into at as is are be its their this that these those study analysis approach method methods review systematic new novel effect effects evidence data model models".split())
SOURCE_ORDER = ["semantic_scholar", "openalex", "pubmed", "arxiv"]


def plain_query(q: str) -> str:
    """Boolean/MeSH query → plain keyword string for S2 / OpenAlex."""
    q = re.sub(r"\[[^\]]*\]", " ", q)
    q = re.sub(r"\b(AND|OR|NOT)\b", " ", q)
    q = re.sub(r"[\"()?*]", " ", q)
    return " ".join(q.split())


# --------------------------------------------------------------------------- #
class Collection:
    """Deterministic merge of hits into papers."""

    def __init__(self, title_threshold: float):
        self.papers: list[dict[str, Any]] = []
        self.by_doi: dict[str, int] = {}
        self.by_key: dict[str, int] = {}  # "s2:..", "oa:..", "pm:..", "ax:.."
        self.title_threshold = title_threshold
        self.raw_count = 0
        self.per_source_unique: Counter[str] = Counter()
        self.per_query_unique: Counter[str] = Counter()

    def _keys(self, h: Hit) -> list[str]:
        ks = []
        if h.semantic_scholar_id:
            ks.append(f"s2:{h.semantic_scholar_id}")
        if h.openalex_id:
            ks.append(f"oa:{h.openalex_id}")
        if h.pubmed_id:
            ks.append(f"pm:{h.pubmed_id}")
        if h.arxiv_id:
            ks.append(f"ax:{h.arxiv_id}")
        return ks

    def find(self, h: Hit) -> int | None:
        if h.doi and h.doi in self.by_doi:
            return self.by_doi[h.doi]
        for k in self._keys(h):
            if k in self.by_key:
                return self.by_key[k]
        # fuzzy title
        ln = last_name(h.authors[0]).lower() if h.authors else ""
        for i, p in enumerate(self.papers):
            if word_overlap(h.title, p["title"]) >= self.title_threshold:
                pln = last_name(p["authors"][0]).lower() if p["authors"] else ""
                same_author = (not ln or not pln) or ln == pln
                same_year = h.year is None or p["year"] is None or abs(h.year - p["year"]) <= 1
                if same_author and same_year:
                    return i
        return None

    def add(self, h: Hit, count_raw: bool = True) -> tuple[int, bool]:
        if count_raw:
            self.raw_count += 1
        idx = self.find(h)
        if idx is None:
            p = self._new(h)
            self.papers.append(p)
            idx = len(self.papers) - 1
            self.per_source_unique[h.source] += 1
            self.per_query_unique[h.query_id] += 1
            created = True
        else:
            p = self.papers[idx]
            if h.source not in p["sources_found_in"]:
                self.per_source_unique[h.source] += 1
            self._merge(p, h)
            created = False
        self._index(idx, h)
        return idx, created

    def _index(self, idx: int, h: Hit) -> None:
        if h.doi:
            self.by_doi.setdefault(h.doi, idx)
        for k in self._keys(h):
            self.by_key.setdefault(k, idx)

    @staticmethod
    def _new(h: Hit) -> dict[str, Any]:
        return {
            "title": h.title,
            "authors": list(h.authors),
            "year": h.year,
            "journal": h.journal,
            "doi": h.doi,
            "url": h.url,
            "abstract": h.abstract,
            "citation_count": h.citation_count,
            "sources_found_in": [h.source],
            "semantic_scholar_id": h.semantic_scholar_id,
            "openalex_id": h.openalex_id,
            "pubmed_id": h.pubmed_id,
            "pmc_id": h.pmc_id,
            "arxiv_id": h.arxiv_id,
            "found_via": h.query_id,
            "language": h.language,
            "venue_type": h.venue_type,
            "volume": h.volume,
            "issue": h.issue,
            "pages": h.pages,
            "arxiv_primary_class": h.arxiv_primary_class,
            "refs_s2": list(h.refs_s2),
            "refs_openalex": list(h.refs_openalex),
            "_abstract_src": h.source if h.abstract else None,
            "_cc_src": h.source if h.citation_count is not None else None,
        }

    def _merge(self, p: dict[str, Any], h: Hit) -> None:
        if h.source not in p["sources_found_in"]:
            p["sources_found_in"].append(h.source)
            p["sources_found_in"].sort(key=lambda s: SOURCE_ORDER.index(s) if s in SOURCE_ORDER else 99)
        # richest metadata: S2 abstract preferred, OpenAlex citation count preferred
        if h.abstract and (not p["abstract"] or (h.source == "semantic_scholar" and p["_abstract_src"] != "semantic_scholar") or len(h.abstract) > len(p["abstract"]) * 1.2 and p["_abstract_src"] != "semantic_scholar"):
            p["abstract"], p["_abstract_src"] = h.abstract, h.source
        if h.citation_count is not None and (p["citation_count"] is None or (h.source == "openalex" and p["_cc_src"] != "openalex")):
            p["citation_count"], p["_cc_src"] = h.citation_count, h.source
        for k in ("doi", "journal", "url", "year", "semantic_scholar_id", "openalex_id", "pubmed_id", "pmc_id", "arxiv_id", "language", "venue_type", "volume", "issue", "pages", "arxiv_primary_class"):
            v = getattr(h, k)
            if v and not p.get(k):
                p[k] = v
        if h.venue_type and h.source in ("openalex", "semantic_scholar") and p.get("venue_type") == "preprint" and h.venue_type != "preprint":
            p["venue_type"] = h.venue_type
        if len(h.authors) > len(p["authors"]):
            p["authors"] = list(h.authors)
        p["refs_s2"] = sorted(set(p["refs_s2"]) | set(h.refs_s2))
        p["refs_openalex"] = sorted(set(p["refs_openalex"]) | set(h.refs_openalex))


class GoldWatch:
    """Per-gold first-gate log for LitSearch eval. No-op when ``eval_gold`` is empty."""

    def __init__(self, golds: list[dict[str, Any]]):
        self.golds = golds
        self.rows: list[dict[str, Any]] = [
            {
                "corpusId": g.get("corpusId"),
                "provider_raw": {},
                "year_filtered_raw": False,
                "after_dedup": False,
                "snowball_seen": False,
                "snowball_drop_reason": None,
                "snowball_added": False,
                "in_final": False,
            }
            for g in golds
        ]

    def _hits(self, rec: Any) -> list[int]:
        rec = as_match_record(rec)
        found: list[int] = []
        for i, g in enumerate(self.golds):
            p, _ = match_gold(g, [rec])
            if p is not None:
                found.append(i)
        return found

    def note_provider_hit(self, source: str, rec: Any, *, year_ok: bool) -> None:
        for i in self._hits(rec):
            self.rows[i]["provider_raw"][source] = True
            if not year_ok:
                self.rows[i]["year_filtered_raw"] = True

    def mark_after_dedup(self, papers: list[dict[str, Any]]) -> None:
        for i, g in enumerate(self.golds):
            p, _ = match_gold(g, papers)
            self.rows[i]["after_dedup"] = p is not None

    def note_snowball(self, rec: Any, reason: str | None, added: bool) -> None:
        for i in self._hits(rec):
            self.rows[i]["snowball_seen"] = True
            if added:
                self.rows[i]["snowball_added"] = True
                self.rows[i]["snowball_drop_reason"] = None
            elif self.rows[i]["snowball_drop_reason"] is None:
                self.rows[i]["snowball_drop_reason"] = reason

    def mark_final(self, papers: list[Any]) -> None:
        recs = [p.model_dump() if hasattr(p, "model_dump") else p for p in papers]
        for i, g in enumerate(self.golds):
            p, _ = match_gold(g, recs)
            self.rows[i]["in_final"] = p is not None

    def dump(self) -> dict[str, Any]:
        return {"golds": self.rows}


# --------------------------------------------------------------------------- #
def run(ctx: Context) -> StepOutput:
    s, cfg = ctx.session, ctx.config.search
    sc: SessionConfig = s.load_config()
    y0, y1 = sc.year_range()
    ts = ctx.ts(2)
    http = ctx.http
    api = ctx.config.api

    sources = [x for x in SOURCE_ORDER if x in cfg.sources]
    if sc.field_type == "cs_engineering" and "pubmed" in sources:
        sources.remove("pubmed")
    providers: dict[str, Any] = {}
    s2 = SemanticScholar(http, api.semantic_scholar_key)
    for name in sources:
        providers[name] = {"semantic_scholar": s2, "openalex": OpenAlex(http, api.openalex_mailto, api.openalex_api_key), "pubmed": PubMed(http, api.ncbi_api_key), "arxiv": ArXiv(http)}[name]

    # ---------------- Phase 1: multi-source search ---------------- #
    col = Collection(cfg.title_match_threshold)
    watch = GoldWatch(list(s.state.get("eval_gold") or []))
    failures: list[str] = []
    per_query_raw: Counter[str] = Counter()
    provider_queries: list[dict[str, Any]] = []
    n_q = len(sc.queries)
    for name in sources:
        prov = providers[name]
        ctx.say(f"  [{name}] searching {n_q} queries")
        for i, q in enumerate(sc.queries, 1):
            qs = q.query if name == "pubmed" else (q.query if name == "arxiv" else plain_query(q.query))
            ctx.say(f"  [{name}] {q.id} ({i}/{n_q}) …")
            tq = time.time()
            try:
                hits = prov.search(qs, q.id, y0, y1, cfg.results_per_query)
            except Exception as e:  # noqa: BLE001 — one flaky source must not block the search
                provider_queries.append({"provider": name, "query_id": q.id, "success": False, "error": type(e).__name__})
                failures.append(f"{name}/{q.id}: {type(e).__name__}: {str(e)[:120]}")
                ctx.say(f"  [{name}] {q.id} FAIL {type(e).__name__}: {str(e)[:80]}  {time.time() - tq:.0f}s")
                continue
            per_query_raw[q.id] += len(hits)
            provider_queries.append({"provider": name, "query_id": q.id, "success": True, "returned_hits": len(hits)})
            for h in hits:
                year_ok = h.year is None or (y0 <= h.year <= y1)
                watch.note_provider_hit(name, h, year_ok=year_ok)
                if not year_ok:
                    continue
                col.add(h)
            ctx.say(f"  [{name}] {q.id} ok n={len(hits)} unique={len(col.papers)}  {time.time() - tq:.0f}s")
    after_dedup = len(col.papers)
    watch.mark_after_dedup(col.papers)
    ctx.say(f"  raw unique={after_dedup}  (DOI recovery…)")

    # ---------------- Phase 2b: DOI recovery ---------------- #
    recovered = 0
    doi_lookups = 0
    max_doi_lookups = 40
    for p in col.papers:
        if p["doi"]:
            continue
        if doi_lookups >= max_doi_lookups:
            break
        doi_lookups += 1
        ctx.say(f"  doi-recovery {doi_lookups}/{max_doi_lookups}  {p['title'][:50]}")
        rec = None
        try:
            if p["arxiv_id"]:
                rec = s2.lookup(f"ARXIV:{p['arxiv_id']}")
            elif p["pubmed_id"]:
                rec = s2.lookup(f"PMID:{p['pubmed_id']}")
            elif p["semantic_scholar_id"]:
                rec = s2.lookup(p["semantic_scholar_id"])
            else:
                rec = s2.match_title(p["title"])
                if rec and word_overlap(rec.get("title"), p["title"]) < cfg.title_match_threshold:
                    rec = None
        except Exception as e:  # noqa: BLE001
            failures.append(f"doi-recovery/{p['title'][:40]}: {type(e).__name__}")
        ext = (rec or {}).get("externalIds") or {}
        doi = ext.get("DOI")
        if not doi and "openalex" in providers:
            try:
                w = providers["openalex"].lookup_title(p["title"])
                if w and word_overlap(w.get("title"), p["title"]) >= cfg.title_match_threshold and w.get("doi"):
                    doi = w["doi"]
                    p["openalex_id"] = p["openalex_id"] or (w.get("id") or "").rsplit("/", 1)[-1]
            except Exception:  # noqa: BLE001
                pass
        if doi:
            from ..utils import normalize_doi

            p["doi"] = normalize_doi(doi)
            recovered += 1
        if rec and rec.get("paperId") and not p["semantic_scholar_id"]:
            p["semantic_scholar_id"] = rec["paperId"]
        if ext.get("ArXiv") and not p["arxiv_id"]:
            p["arxiv_id"] = ext["ArXiv"]
        if ext.get("PubMed") and not p["pubmed_id"]:
            p["pubmed_id"] = str(ext["PubMed"])

    ctx.say(f"  doi recovered={recovered}  (snowball…)")

    # ---------------- Phase 3: snowball ---------------- #
    direct_papers = [dict(p) for p in col.papers]
    for g, t in zip(watch.golds, watch.rows):
        t["direct_before_snowball"] = match_gold(g, direct_papers)[0] is not None
    pico_terms = _pico_terms(sc)
    ranked = sorted(range(len(col.papers)), key=lambda i: (-(col.papers[i]["citation_count"] or 0), normalize_title(col.papers[i]["title"])))
    seeds = [i for i in ranked if col.papers[i]["semantic_scholar_id"] or col.papers[i]["doi"]][: cfg.snowball_seeds]
    snowball_added = 0
    for si, i in enumerate(seeds, 1):
        p = col.papers[i]
        p["is_seed_paper"] = True
        ident = p["semantic_scholar_id"] or f"DOI:{p['doi']}"
        ctx.say(f"  snowball seed {si}/{len(seeds)} {ident[:40]}")
        try:
            refs = s2.references(ident, cfg.snowball_refs_per_seed)
        except Exception as e:  # noqa: BLE001
            failures.append(f"snowball/{ident}: {type(e).__name__}")
            ctx.say(f"  snowball seed {si} FAIL {type(e).__name__}")
            continue
        p["refs_s2"] = sorted(set(p["refs_s2"]) | {r.semantic_scholar_id for r in refs if r.semantic_scholar_id})
        for r in refs:
            if r.year is None or not (y0 <= r.year <= y1):
                watch.note_snowball(r, "year", False)
                continue
            if not r.abstract:
                watch.note_snowball(r, "no_abstract", False)
                continue
            if _overlap(pico_terms, r.title, r.abstract) < cfg.snowball_min_overlap:
                watch.note_snowball(r, "overlap", False)
                continue
            if col.find(r) is not None:
                watch.note_snowball(r, "already_in_set", False)
                continue
            col.add(r, count_raw=False)
            watch.note_snowball(r, None, True)
            snowball_added += 1

    ctx.say(f"  snowball +{snowball_added}  (citation network…)")

    # ---------------- assign stable ids ---------------- #
    order = sorted(range(len(col.papers)), key=lambda i: (_qrank(col.papers[i]["found_via"]), normalize_title(col.papers[i]["title"])))
    papers: list[Paper] = []
    for n, i in enumerate(order, 1):
        p = col.papers[i]
        papers.append(Paper(id=f"paper_{n:03d}", **{k: v for k, v in p.items() if k in Paper.model_fields and k not in ("id", "references", "cited_by", "citation_network", "is_seed_paper")}, is_seed_paper=bool(p.get("is_seed_paper"))))
        papers[-1].external_refs = {"s2": p["refs_s2"], "openalex": p["refs_openalex"]}
    watch.mark_final(papers)

    # ---------------- Phase 4: citation network ---------------- #
    by_s2 = {p.semantic_scholar_id: p.id for p in papers if p.semantic_scholar_id}
    by_oa = {p.openalex_id: p.id for p in papers if p.openalex_id}
    # Extra S2 /references on every non-seed paper is 1 rps × |S|. Mode B |S|~400 + 429 backoff hung ls_009 for hours.
    extra_ref = 0
    extra_ref_cap = 8 if len(papers) > 60 else len(papers)
    for p in papers:
        if extra_ref >= extra_ref_cap:
            break
        if not p.external_refs.get("openalex") and not p.is_seed_paper and p.semantic_scholar_id and cfg.snowball_refs_per_seed:
            try:
                ctx.say(f"  ref-lookup {extra_ref + 1}/{extra_ref_cap} {p.semantic_scholar_id[:12]}")
                p.external_refs["s2"] = sorted(set(p.external_refs.get("s2", [])) | set(s2.reference_ids(p.semantic_scholar_id)))
                extra_ref += 1
            except Exception:  # noqa: BLE001
                extra_ref += 1
    pid = {p.id: p for p in papers}
    for p in papers:
        targets = set()
        for rid in p.external_refs.get("s2", []):
            if rid in by_s2 and by_s2[rid] != p.id:
                targets.add(by_s2[rid])
        for wid in p.external_refs.get("openalex", []):
            if wid in by_oa and by_oa[wid] != p.id:
                targets.add(by_oa[wid])
        p.references = sorted(targets)
        for t in targets:
            pid[t].cited_by.append(p.id)
    for p in papers:
        p.cited_by = sorted(set(p.cited_by))
        p.citation_network = CitationNetwork(in_degree=len(p.cited_by), out_degree=len(p.references), is_hub=len(p.cited_by) >= cfg.hub_in_degree)
    clusters = _clusters(papers)
    hubs = [p.id for p in papers if p.citation_network.is_hub]

    # ---------------- Phase 5: save ---------------- #
    with_doi = sum(1 for p in papers if p.doi)
    summary = SearchSummary(
        total_raw_results=col.raw_count,
        after_dedup=after_dedup,
        snowball_additions=snowball_added,
        final_count=len(papers),
        sources={k: col.per_source_unique.get(k, 0) for k in sources},
        queries={**{q.id: col.per_query_unique.get(q.id, 0) for q in sc.queries}, "snowball": snowball_added},
        doi_coverage=f"{with_doi}/{len(papers)} ({round(100 * with_doi / len(papers)) if papers else 0}%)",
        hub_papers=hubs,
        clusters=clusters,
        source_failures=failures,
    )
    raw = RawPapers(session_id=sc.session_id, topic=sc.topic, search_timestamp=ts, search_summary=summary, papers=papers)
    dump_json(s.path("step2_raw_papers.json"), raw.model_dump())
    dump_json(s.path("step2_gold_trace.json"), {**watch.dump(), "direct_papers": direct_papers, "provider_queries": provider_queries, "schema_version": 2})
    overlap = sum(1 for p in papers if len(p.sources_found_in) > 1)
    md = render_search_summary(sc, raw, ts[:10], sources, per_query_raw, overlap, recovered)
    write_text(s.path("step2_search_summary.md"), md)
    notes = [f"DOI recovered for {recovered} papers"] + [f"source failure: {f}" for f in failures]
    for g in watch.rows:
        src = ",".join(k for k, v in (g.get("provider_raw") or {}).items() if v) or "none"
        ctx.say(f"  gold {g.get('corpusId')} providers={src} after_dedup={g.get('after_dedup')} snowball={g.get('snowball_drop_reason') or ('added' if g.get('snowball_added') else '-')} final={g.get('in_final')}")
    return StepOutput(files=[s.path("step2_raw_papers.json"), s.path("step2_search_summary.md"), s.path("step2_gold_trace.json")], notes=notes, summary={"raw": col.raw_count, "unique": after_dedup, "snowball": snowball_added, "final": len(papers), "doi_coverage": summary.doi_coverage, "hubs": len(hubs), "clusters": len(clusters), "failures": failures})


# --------------------------------------------------------------------------- #
def _qrank(qid: str) -> int:
    return 99 if qid == "snowball" else int(qid[1:]) if qid[1:].isdigit() else 50


def _pico_terms(sc: SessionConfig) -> set[str]:
    text = " ".join([sc.topic, sc.pico.population, sc.pico.intervention, sc.pico.outcome] + [plain_query(q.query) for q in sc.queries])
    return {t for t in title_tokens(text) if t not in STOPWORDS}


def _overlap(terms: set[str], title: str | None, abstract: str | None) -> float:
    toks = title_tokens((title or "") + " " + (abstract or "")[:600])
    if not terms or not toks:
        return 0.0
    return len(terms & toks) / len(terms)


def _clusters(papers: list[Paper]) -> list[Cluster]:
    adj: dict[str, set[str]] = defaultdict(set)
    for p in papers:
        for r in p.references:
            adj[p.id].add(r)
            adj[r].add(p.id)
    seen: set[str] = set()
    comps: list[list[str]] = []
    for p in papers:
        if p.id in seen or p.id not in adj:
            continue
        stack, comp = [p.id], []
        seen.add(p.id)
        while stack:
            n = stack.pop()
            comp.append(n)
            for m in sorted(adj[n]):
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        if len(comp) >= 2:
            comps.append(sorted(comp))
    comps.sort(key=lambda c: (-len(c), c[0]))
    pid = {p.id: p for p in papers}
    out: list[Cluster] = []
    for i, comp in enumerate(comps):
        name = f"cluster_{chr(ord('A') + i)}" if i < 26 else f"cluster_{i}"
        words: Counter[str] = Counter()
        for x in comp:
            words.update(t for t in title_tokens(pid[x].title) if t not in STOPWORDS)
        top = [w for w, _ in sorted(words.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
        theme = " / ".join(top) if top else "connected component"
        for x in comp:
            pid[x].citation_network.cluster = name
        out.append(Cluster(name=name, paper_ids=comp, theme=theme))
    return out
