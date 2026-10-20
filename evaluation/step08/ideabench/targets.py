"""IdeaBench targets from PubMed / OpenAlex (S2 search was rate-limited / empty for 2026 venues)."""
from __future__ import annotations

from typing import Any, Callable

from scholar_research.providers.base import HttpClient
from scholar_research.providers.openalex import BASE as OA_BASE
from scholar_research.providers.openalex import OpenAlex
from scholar_research.providers.pubmed import BASE as PM_BASE
from scholar_research.providers.pubmed import PubMed
from .s2 import DEFAULT_VENUE_NEEDLES, _venue_ok, target_card

Say = Callable[[str], None]

# PubMed [Journal] phrases that map onto the IdeaBench-style venue allow-list.
PUBMED_JOURNAL_TERMS = (
    "Nature[Journal]",
    "Science[Journal]",
    "Cell[Journal]",
    "Lancet[Journal]",
    "JAMA[Journal]",
    '"N Engl J Med"[Journal]',
    '"Nat Med"[Journal]',
    '"Nat Biotechnol"[Journal]',
    "BMJ[Journal]",
    '"PLoS Med"[Journal]',
)

OA_NON_PRIMARY = frozenset(
    {
        "review",
        "editorial",
        "letter",
        "book",
        "book-chapter",
        "paratext",
        "peer-review",
        "erratum",
        "retraction",
    }
)


def _pmid_date_term(start: str, end: str) -> str:
    """YYYY-MM-DD → PubMed date range on Date - Publication."""
    a = start.replace("-", "/")
    b = end.replace("-", "/")
    return f'("{a}"[Date - Publication] : "{b}"[Date - Publication])'


def search_pubmed_targets(
    http: HttpClient,
    *,
    target_start: str,
    target_end: str,
    need: int,
    api_key: str | None = None,
    say: Say | None = None,
) -> list[dict[str, Any]]:
    """Peer-reviewed journal articles with abstracts in the date window (PubMed)."""
    log = say or (lambda _m: None)
    pm = PubMed(http, api_key=api_key)
    journal_or = " OR ".join(PUBMED_JOURNAL_TERMS)
    term = (
        f"({journal_or}) AND {_pmid_date_term(target_start, target_end)} "
        f'AND hasabstract[text] AND "journal article"[Publication Type] '
        f'NOT (review[Publication Type] OR editorial[Publication Type] OR letter[Publication Type])'
    )
    # Over-fetch then keep those with abstracts (efetch already preferred).
    retmax = min(200, max(need * 10, 30))
    log(f"  PubMed esearch retmax={retmax}")
    r = http.get(
        f"{PM_BASE}/esearch.fcgi",
        params={
            "db": "pubmed",
            "term": term,
            "retmax": retmax,
            "retmode": "json",
            "sort": "pub_date",
            "api_key": api_key,
        },
    )
    if not r.ok:
        raise RuntimeError(f"pubmed esearch HTTP {r.status}")
    ids = (r.json().get("esearchresult") or {}).get("idlist") or []
    log(f"  PubMed idlist={len(ids)}")
    if not ids:
        return []
    hits = pm.fetch(ids, "ideabench")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for h in hits:
        if not (h.abstract or "").strip() or not (h.title or "").strip():
            continue
        if not _venue_ok(h.journal, DEFAULT_VENUE_NEEDLES):
            continue
        pid = f"pmid:{h.pubmed_id}" if h.pubmed_id else (f"doi:{h.doi}" if h.doi else None)
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append(
            {
                "paperId": pid,
                "title": h.title,
                "abstract": h.abstract,
                "year": h.year,
                "publicationDate": None,
                "venue": h.journal,
                "citationCount": h.citation_count,
                "publicationTypes": ["JournalArticle"],
                "externalIds": {
                    **({"DOI": h.doi} if h.doi else {}),
                    **({"PubMed": h.pubmed_id} if h.pubmed_id else {}),
                    **({"PubMedCentral": h.pmc_id} if h.pmc_id else {}),
                },
                "doi": h.doi,
                "pmid": h.pubmed_id,
                "url": h.url,
                "source": "pubmed",
            }
        )
        if len(out) >= need:
            break
    log(f"  PubMed kept={len(out)}/{need}")
    return out[:need]


def search_openalex_targets(
    http: HttpClient,
    *,
    target_start: str,
    target_end: str,
    need: int,
    mailto: str | None = None,
    api_key: str | None = None,
    say: Say | None = None,
) -> list[dict[str, Any]]:
    """Journal articles with abstracts in the date window (OpenAlex)."""
    log = say or (lambda _m: None)
    oa = OpenAlex(http, mailto=mailto, api_key=api_key)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    per_page = min(100, max(need * 5, 25))

    def collect(*, strict_venue: bool, page_offset: int = 0) -> None:
        page = 1
        while len(out) < need and page <= 10:
            filt = (
                f"from_publication_date:{target_start},"
                f"to_publication_date:{target_end},"
                f"type:article,"
                f"has_abstract:true,"
                f"is_paratext:false,"
                f"primary_location.source.type:journal"
            )
            params = oa._auth_params(
                {
                    "search": "medicine OR biology OR clinical OR biomedical",
                    "filter": filt,
                    "per_page": per_page,
                    "page": page + page_offset,
                    "sort": "publication_date:desc",
                }
            )
            r = http.get(f"{OA_BASE}/works", params=params)
            if not r.ok:
                raise RuntimeError(f"openalex works HTTP {r.status}: {(r.text or '')[:200]}")
            batch = r.json().get("results") or []
            if not batch:
                log(f"  OpenAlex page={page + page_offset} empty (have {len(out)}/{need})")
                break
            added = 0
            for w in batch:
                hit = OpenAlex._to_hit(w, "ideabench")
                if hit.venue_type == "preprint":
                    continue
                if w.get("type") in OA_NON_PRIMARY:
                    continue
                if not (hit.abstract or "").strip() or not (hit.title or "").strip():
                    continue
                if strict_venue and not _venue_ok(hit.journal, DEFAULT_VENUE_NEEDLES):
                    continue
                wid = hit.openalex_id or ""
                pid = f"openalex:{wid}" if wid else (f"doi:{hit.doi}" if hit.doi else None)
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                out.append(
                    {
                        "paperId": pid,
                        "title": hit.title,
                        "abstract": hit.abstract,
                        "year": hit.year,
                        "publicationDate": w.get("publication_date"),
                        "venue": hit.journal,
                        "citationCount": hit.citation_count,
                        "publicationTypes": ["JournalArticle"],
                        "externalIds": {
                            **({"DOI": hit.doi} if hit.doi else {}),
                            **({"PubMed": hit.pubmed_id} if hit.pubmed_id else {}),
                            **({"OpenAlex": wid} if wid else {}),
                        },
                        "doi": hit.doi,
                        "pmid": hit.pubmed_id,
                        "url": hit.url,
                        "openalex_id": wid or None,
                        "referenced_works": list(hit.refs_openalex or []),
                        "source": "openalex",
                        "venue_filter": "top_venue" if strict_venue else "broad_backfill",
                    }
                )
                added += 1
                if len(out) >= need:
                    break
            mode = "top-venue" if strict_venue else "broad"
            log(f"  OpenAlex {mode} page={page + page_offset} +{added} kept={len(out)}/{need}")
            page += 1
            if len(batch) < per_page:
                break

    collect(strict_venue=True)
    if len(out) < need:
        log(f"  OpenAlex broad backfill (have {len(out)}/{need})")
        collect(strict_venue=False, page_offset=10)
    return out[:need]


def search_targets(
    http: HttpClient,
    *,
    source: str,
    target_start: str,
    target_end: str,
    need: int,
    config_api: Any,
    say: Say | None = None,
) -> list[dict[str, Any]]:
    """``source``: pubmed | openalex | pubmed+openalex | s2."""
    log = say or (lambda _m: None)
    src = (source or "openalex").strip().lower()
    if src == "s2":
        from .s2 import search_biomed_targets

        return search_biomed_targets(
            http,
            target_start=target_start,
            target_end=target_end,
            need=need,
            api_key=config_api.semantic_scholar_key,
            say=say,
        )
    if src == "pubmed":
        return search_pubmed_targets(
            http,
            target_start=target_start,
            target_end=target_end,
            need=need,
            api_key=config_api.ncbi_api_key,
            say=say,
        )
    if src == "openalex":
        return search_openalex_targets(
            http,
            target_start=target_start,
            target_end=target_end,
            need=need,
            mailto=config_api.openalex_mailto,
            api_key=config_api.openalex_api_key,
            say=say,
        )
    if src in ("pubmed+openalex", "openalex+pubmed", "both"):
        # Prefer OpenAlex (richer refs); backfill from PubMed if short.
        a = search_openalex_targets(
            http,
            target_start=target_start,
            target_end=target_end,
            need=need,
            mailto=config_api.openalex_mailto,
            api_key=config_api.openalex_api_key,
            say=say,
        )
        if len(a) >= need:
            return a
        log(f"  backfill PubMed (have {len(a)}/{need})")
        b = search_pubmed_targets(
            http,
            target_start=target_start,
            target_end=target_end,
            need=need - len(a),
            api_key=config_api.ncbi_api_key,
            say=say,
        )
        seen = {p["paperId"] for p in a}
        for p in b:
            if p["paperId"] not in seen:
                a.append(p)
                seen.add(p["paperId"])
            if len(a) >= need:
                break
        return a[:need]
    raise ValueError(f"unknown target source {source!r}; use pubmed|openalex|pubmed+openalex|s2")


def fetch_openalex_references(
    http: HttpClient,
    *,
    openalex_id: str | None,
    referenced_works: list[str] | None,
    doi: str | None,
    mailto: str | None,
    api_key: str | None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Resolve OpenAlex ``referenced_works`` into ref dicts (citationCount + type + abstract)."""
    oa = OpenAlex(http, mailto=mailto, api_key=api_key)
    ref_ids = list(referenced_works or [])
    if not ref_ids and doi:
        w = oa.lookup_doi(doi.replace("https://doi.org/", ""))
        if w:
            ref_ids = [x.rsplit("/", 1)[-1] for x in w.get("referenced_works") or []]
            if not openalex_id:
                openalex_id = (w.get("id") or "").rsplit("/", 1)[-1]
    if not ref_ids and openalex_id:
        r = http.get(f"{OA_BASE}/works/{openalex_id}", params=oa._auth_params({}))
        if r.ok:
            ref_ids = [x.rsplit("/", 1)[-1] for x in (r.json().get("referenced_works") or [])]
    ref_ids = [x for x in ref_ids if x][:limit]
    out: list[dict[str, Any]] = []
    # OpenAlex allows OR filters up to a reasonable batch size.
    chunk = 50
    for i in range(0, len(ref_ids), chunk):
        part = ref_ids[i : i + chunk]
        filt = "|".join(part)
        params = oa._auth_params({"filter": f"openalex_id:{filt}", "per_page": len(part)})
        r = http.get(f"{OA_BASE}/works", params=params)
        if not r.ok:
            continue
        for w in r.json().get("results") or []:
            hit = OpenAlex._to_hit(w, "ref")
            wid = hit.openalex_id or (w.get("id") or "").rsplit("/", 1)[-1]
            out.append(
                {
                    "paperId": f"openalex:{wid}" if wid else (f"doi:{hit.doi}" if hit.doi else wid),
                    "title": hit.title,
                    "abstract": hit.abstract,
                    "year": hit.year,
                    "venue": hit.journal,
                    "citationCount": hit.citation_count,
                    "publicationTypes": [w.get("type") or "article"],
                    "externalIds": {
                        **({"DOI": hit.doi} if hit.doi else {}),
                        **({"PubMed": hit.pubmed_id} if hit.pubmed_id else {}),
                    },
                    "doi": hit.doi,
                    "url": hit.url,
                    "openalex_type": w.get("type"),
                }
            )
    return out


def filter_openalex_references(
    refs: list[dict[str, Any]],
    *,
    min_citations: int = 5,
    require_abstract: bool = True,
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for p in refs:
        cites = p.get("citationCount")
        if cites is None or int(cites) < min_citations:
            continue
        t = (p.get("openalex_type") or (p.get("publicationTypes") or ["article"])[0] or "").lower()
        if t in OA_NON_PRIMARY:
            continue
        if require_abstract and not (p.get("abstract") or "").strip():
            continue
        if not (p.get("title") or "").strip():
            continue
        kept.append(p)
    return kept


def to_target_card(p: dict[str, Any]) -> dict[str, Any]:
    """Normalize PubMed/OpenAlex/S2 target dicts to the shared card schema."""
    if p.get("source") in ("pubmed", "openalex"):
        return {
            "paperId": p["paperId"],
            "title": p.get("title"),
            "abstract": p.get("abstract"),
            "year": p.get("year"),
            "publicationDate": p.get("publicationDate"),
            "venue": p.get("venue"),
            "citationCount": p.get("citationCount"),
            "publicationTypes": p.get("publicationTypes") or [],
            "doi": p.get("doi"),
            "pmid": p.get("pmid"),
            "url": p.get("url"),
            "openalex_id": p.get("openalex_id"),
            "referenced_works": p.get("referenced_works") or [],
            "source": p.get("source"),
            "venue_filter": p.get("venue_filter"),
        }
    card = target_card(p)
    card["source"] = "s2"
    return card
