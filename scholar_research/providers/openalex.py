from __future__ import annotations

from typing import Any

from .base import HttpClient
from .records import Hit

BASE = "https://api.openalex.org"


def reconstruct_abstract(inv: dict[str, list[int]] | None) -> str | None:
    if not inv:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions) or None


class OpenAlex:
    name = "openalex"

    def __init__(self, http: HttpClient, mailto: str | None = None):
        self.http = http
        self.mailto = mailto
        http.limiter.intervals["api.openalex.org"] = 0.12

    def search(self, query: str, query_id: str, year_from: int, year_to: int, limit: int = 30) -> list[Hit]:
        params = {
            "search": query,
            "filter": f"from_publication_date:{year_from}-01-01,to_publication_date:{year_to}-12-31",
            "per_page": limit,
            "sort": "relevance_score:desc",
            "mailto": self.mailto,
        }
        r = self.http.get(f"{BASE}/works", params=params)
        if not r.ok:
            raise RuntimeError(f"openalex search HTTP {r.status}")
        return [self._to_hit(w, query_id) for w in r.json().get("results") or [] if w.get("title")]

    def lookup_doi(self, doi: str) -> dict[str, Any] | None:
        r = self.http.get(f"{BASE}/works/https://doi.org/{doi}", params={"mailto": self.mailto})
        return r.json() if r.ok else None

    def lookup_title(self, title: str) -> dict[str, Any] | None:
        r = self.http.get(f"{BASE}/works", params={"filter": f"title.search:{title[:200]}", "per_page": 1, "mailto": self.mailto})
        if not r.ok:
            return None
        res = r.json().get("results") or []
        return res[0] if res else None

    @staticmethod
    def _to_hit(w: dict[str, Any], query_id: str) -> Hit:
        ids = w.get("ids") or {}
        loc = (w.get("primary_location") or {}) or {}
        src = (loc.get("source") or {}) or {}
        pmid = ids.get("pmid")
        pmcid = ids.get("pmcid")
        biblio = w.get("biblio") or {}
        pages = None
        if biblio.get("first_page"):
            pages = biblio["first_page"] + (f"-{biblio['last_page']}" if biblio.get("last_page") and biblio["last_page"] != biblio["first_page"] else "")
        wtype = w.get("type")
        venue_type = None
        if src.get("type") == "conference" or wtype in ("proceedings-article",):
            venue_type = "conference"
        elif wtype in ("article", "review") and src.get("type") == "journal":
            venue_type = "journal"
        elif src.get("type") == "repository" or wtype == "preprint":
            venue_type = "preprint"
        return Hit(
            source="openalex",
            query_id=query_id,
            title=w.get("title") or "",
            authors=[(a.get("author") or {}).get("display_name", "") for a in w.get("authorships") or [] if (a.get("author") or {}).get("display_name")],
            year=w.get("publication_year"),
            journal=src.get("display_name"),
            doi=w.get("doi"),
            url=w.get("doi") or (w.get("id") or None),
            abstract=reconstruct_abstract(w.get("abstract_inverted_index")),
            citation_count=w.get("cited_by_count"),
            openalex_id=(w.get("id") or "").rsplit("/", 1)[-1] or None,
            pubmed_id=pmid.rsplit("/", 1)[-1] if pmid else None,
            pmc_id=pmcid.rsplit("/", 1)[-1] if pmcid else None,
            venue_type=venue_type,
            volume=biblio.get("volume"),
            issue=biblio.get("issue"),
            pages=pages,
            language=w.get("language"),
            refs_openalex=[x.rsplit("/", 1)[-1] for x in w.get("referenced_works") or []],
        )
