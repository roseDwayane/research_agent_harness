"""Semantic Scholar helpers for IdeaBench target + reference collection."""
from __future__ import annotations

from typing import Any, Callable

from scholar_research.providers.base import HttpClient
from scholar_research.providers.semantic_scholar import BASE, REF_FIELDS, SemanticScholar

# IdeaBench: drop non-primary research labelled by Semantic Scholar.
NON_PRIMARY_TYPES = frozenset(
    {
        "Review",
        "Editorial",
        "LettersAndComments",
        "Letter",
        "Book",
        "BookSection",
        "News",
    }
)

DEFAULT_VENUES = (
    "Nature,Science,Cell,The Lancet,JAMA,New England Journal of Medicine,"
    "Nature Medicine,Nature Biotechnology,BMJ,PLOS Medicine"
)

# Soft venue allow-list. Empty = keep any venue.
DEFAULT_VENUE_NEEDLES = (
    "nature",
    "science",
    "cell",
    "lancet",
    "jama",
    "new england journal",
    "bmj",
    "plos medicine",
)

Say = Callable[[str], None]


def _venue_ok(venue: str | None, needles: tuple[str, ...] = DEFAULT_VENUE_NEEDLES) -> bool:
    if not needles:
        return True
    v = (venue or "").lower()
    if not v:
        return False
    compact = " ".join(v.replace("&", " and ").replace("-", " ").split())
    for n in needles:
        n = n.lower()
        if n == "science":
            if compact == "science" or compact.startswith("science "):
                return True
            continue
        if n == "cell":
            if compact == "cell" or compact.startswith("cell "):
                return True
            continue
        if n == "jama":
            if compact == "jama" or compact.startswith("jama "):
                return True
            continue
        if n == "bmj":
            if compact == "bmj" or compact.startswith("bmj "):
                return True
            continue
        if n == "nature":
            if compact == "nature" or compact.startswith("nature "):
                return True
            continue
        if n in compact:
            return True
    return False


def search_biomed_targets(
    http: HttpClient,
    *,
    target_start: str,
    target_end: str,
    need: int,
    venues: str | None = None,
    venue_needles: tuple[str, ...] | None = DEFAULT_VENUE_NEEDLES,
    query: str = "biology OR medicine OR clinical OR biomedical",
    api_key: str | None = None,
    say: Say | None = None,
) -> list[dict[str, Any]]:
    """Fetch peer-reviewed biomedical targets in ``publicationDateOrYear`` window.

    Multi-venue ``venue=`` queries often return empty on Semantic Scholar, so we
    query **one venue at a time** (from ``venues`` CSV or a short default list),
    then keep papers with abstracts and without arXiv-only IDs.
    """
    log = say or (lambda _m: None)
    headers = {"x-api-key": api_key} if api_key else None
    http.limiter.intervals["api.semanticscholar.org"] = 1.1 if api_key else 3.1
    fields = "paperId,title,abstract,venue,year,publicationDate,externalIds,citationCount,publicationTypes,url"
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    date_range = f"{target_start}:{target_end}"
    venue_list = [v.strip() for v in (venues or DEFAULT_VENUES).split(",") if v.strip()]
    if not venue_list:
        venue_list = [""]  # one unscoped pass
    needles = venue_needles if venue_needles is not None else DEFAULT_VENUE_NEEDLES
    per_venue_limit = min(100, max(need * 2, 10))

    def _keep(p: dict[str, Any]) -> bool:
        pid = p.get("paperId")
        if not pid or pid in seen:
            return False
        ext = p.get("externalIds") or {}
        if ext.get("ArXiv") and not ext.get("DOI"):
            return False
        if not (p.get("abstract") or "").strip():
            return False
        if not (p.get("title") or "").strip():
            return False
        if needles and not _venue_ok(p.get("venue"), needles):
            return False
        return True

    for venue in venue_list:
        if len(out) >= need:
            break
        offset = 0
        while len(out) < need:
            params: dict[str, Any] = {
                "query": query,
                "publicationDateOrYear": date_range,
                "limit": per_venue_limit,
                "offset": offset,
                "fields": fields,
            }
            # fieldsOfStudy + venue together often returns empty on S2; omit FoS for venue passes.
            if not venue:
                params["fieldsOfStudy"] = "Medicine,Biology"
            if venue:
                params["venue"] = venue
            r = http.get(f"{BASE}/paper/search", params=params, headers=headers)
            if not r.ok:
                log(f"  S2 search venue={venue!r} HTTP {r.status}; skip")
                break
            batch = r.json().get("data") or []
            if not batch:
                log(f"  S2 venue={venue!r} exhausted (have {len(out)}/{need})")
                break
            added = 0
            for p in batch:
                if not _keep(p):
                    continue
                seen.add(p["paperId"])
                out.append(p)
                added += 1
                if len(out) >= need:
                    break
            offset += len(batch)
            log(f"  S2 venue={venue!r} offset={offset} +{added} kept={len(out)}/{need}")
            if len(batch) < per_venue_limit:
                break
    return out[:need]


def fetch_references(s2: SemanticScholar, paper_id: str, limit: int = 500) -> list[dict[str, Any]]:
    """Return reference dicts (not Hits) with fields needed for filtering."""
    r = s2.http.get(
        f"{BASE}/paper/{paper_id}/references",
        params={"fields": REF_FIELDS, "limit": limit},
        headers=s2._headers(),
    )
    if not r.ok:
        raise RuntimeError(f"S2 references HTTP {r.status} for {paper_id}")
    out: list[dict[str, Any]] = []
    for row in r.json().get("data") or []:
        p = row.get("citedPaper") or {}
        if p.get("paperId") and p.get("title"):
            out.append(p)
    return out


def is_non_primary(publication_types: list[str] | None) -> bool:
    types = set(publication_types or [])
    return bool(types & NON_PRIMARY_TYPES)


def filter_references(
    refs: list[dict[str, Any]],
    *,
    min_citations: int = 5,
    require_abstract: bool = True,
) -> list[dict[str, Any]]:
    """IdeaBench filters 1–2 (+ abstract). Background-section filter is optional elsewhere."""
    kept: list[dict[str, Any]] = []
    for p in refs:
        cites = p.get("citationCount")
        if cites is None or int(cites) < min_citations:
            continue
        if is_non_primary(p.get("publicationTypes")):
            continue
        if require_abstract and not (p.get("abstract") or "").strip():
            continue
        kept.append(p)
    return kept


def pick_low_resource(refs: list[dict[str, Any]], k: int = 5, *, seed: int = 0) -> list[dict[str, Any]]:
    """Deterministic sample of ``k`` filtered refs (sorted by paperId, then stride)."""
    if k <= 0 or not refs:
        return []
    ordered = sorted(refs, key=lambda p: p.get("paperId") or "")
    if len(ordered) <= k:
        return list(ordered)
    # Stable pseudo-sample: rotate by seed then take evenly spaced.
    rot = seed % len(ordered)
    rotated = ordered[rot:] + ordered[:rot]
    if k == 1:
        return [rotated[0]]
    step = (len(rotated) - 1) / (k - 1)
    idxs = sorted({int(round(i * step)) for i in range(k)})
    while len(idxs) < k:
        for j in range(len(rotated)):
            if j not in idxs:
                idxs.append(j)
                break
        idxs = sorted(set(idxs))[:k]
    return [rotated[i] for i in idxs[:k]]


def ref_card(p: dict[str, Any]) -> dict[str, Any]:
    ext = p.get("externalIds") or {}
    return {
        "paperId": p.get("paperId"),
        "title": p.get("title"),
        "abstract": p.get("abstract"),
        "year": p.get("year"),
        "venue": (p.get("journal") or {}).get("name") if isinstance(p.get("journal"), dict) else p.get("venue"),
        "citationCount": p.get("citationCount"),
        "publicationTypes": p.get("publicationTypes") or [],
        "doi": ext.get("DOI"),
        "url": p.get("url"),
    }


def target_card(p: dict[str, Any]) -> dict[str, Any]:
    ext = p.get("externalIds") or {}
    return {
        "paperId": p.get("paperId"),
        "title": p.get("title"),
        "abstract": p.get("abstract"),
        "year": p.get("year"),
        "publicationDate": p.get("publicationDate"),
        "venue": p.get("venue"),
        "citationCount": p.get("citationCount"),
        "publicationTypes": p.get("publicationTypes") or [],
        "doi": ext.get("DOI"),
        "pmid": str(ext["PubMed"]) if ext.get("PubMed") else None,
        "url": p.get("url"),
    }
