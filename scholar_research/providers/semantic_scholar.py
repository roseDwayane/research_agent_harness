from __future__ import annotations

from typing import Any

from .base import HttpClient
from .records import Hit

BASE = "https://api.semanticscholar.org/graph/v1"
SEARCH_FIELDS = "title,authors,year,abstract,externalIds,citationCount,journal,venue,url,publicationTypes,publicationVenue"
REF_FIELDS = "title,authors,year,abstract,externalIds,citationCount,journal,venue,url,publicationTypes"


class SemanticScholar:
    name = "semantic_scholar"

    def __init__(self, http: HttpClient, api_key: str | None = None):
        self.http = http
        self.api_key = api_key
        # ~100 req / 5 min without key → 3 s spacing; 1 rps with key
        http.limiter.intervals["api.semanticscholar.org"] = 1.1 if api_key else 3.1

    def _headers(self) -> dict[str, str] | None:
        return {"x-api-key": self.api_key} if self.api_key else None

    # ------------------------------------------------------------------ #
    def search(self, query: str, query_id: str, year_from: int, year_to: int, limit: int = 30) -> list[Hit]:
        r = self.http.get(f"{BASE}/paper/search", params={"query": query, "fields": SEARCH_FIELDS, "limit": limit, "year": f"{year_from}-{year_to}"}, headers=self._headers())
        if not r.ok:
            raise RuntimeError(f"semantic_scholar search HTTP {r.status}")
        data = r.json().get("data") or []
        return [self._to_hit(p, query_id) for p in data if p.get("title")]

    def references(self, paper_id: str, limit: int = 50) -> list[Hit]:
        r = self.http.get(f"{BASE}/paper/{paper_id}/references", params={"fields": REF_FIELDS, "limit": limit}, headers=self._headers())
        if not r.ok:
            raise RuntimeError(f"semantic_scholar references HTTP {r.status}")
        out = []
        for row in r.json().get("data") or []:
            p = row.get("citedPaper") or {}
            if p.get("paperId") and p.get("title"):
                out.append(self._to_hit(p, "snowball"))
        return out

    def reference_ids(self, paper_id: str, limit: int = 500) -> list[str]:
        r = self.http.get(f"{BASE}/paper/{paper_id}/references", params={"fields": "paperId", "limit": limit}, headers=self._headers())
        if not r.ok:
            return []
        return [row["citedPaper"]["paperId"] for row in r.json().get("data") or [] if (row.get("citedPaper") or {}).get("paperId")]

    def lookup(self, ident: str) -> dict[str, Any] | None:
        """ident = 'ARXIV:2401.12345' | 'DOI:10...' | 'PMID:...' | paperId."""
        r = self.http.get(f"{BASE}/paper/{ident}", params={"fields": "externalIds,paperId,title,year,citationCount"}, headers=self._headers())
        if not r.ok:
            return None
        return r.json()

    def match_title(self, title: str) -> dict[str, Any] | None:
        r = self.http.get(f"{BASE}/paper/search/match", params={"query": title, "fields": "externalIds,paperId,title,year"}, headers=self._headers())
        if not r.ok:
            return None
        data = r.json().get("data") or []
        return data[0] if data else None

    # ------------------------------------------------------------------ #
    @staticmethod
    def _to_hit(p: dict[str, Any], query_id: str) -> Hit:
        ext = p.get("externalIds") or {}
        journal = (p.get("journal") or {}).get("name") or p.get("venue") or None
        jr = p.get("journal") or {}
        types = p.get("publicationTypes") or []
        venue_type = None
        if "Conference" in types:
            venue_type = "conference"
        elif "JournalArticle" in types:
            venue_type = "journal"
        elif ext.get("ArXiv") and not ext.get("DOI"):
            venue_type = "preprint"
        return Hit(
            source="semantic_scholar",
            query_id=query_id,
            title=p.get("title") or "",
            authors=[a.get("name", "") for a in p.get("authors") or [] if a.get("name")],
            year=p.get("year"),
            journal=journal,
            doi=ext.get("DOI"),
            url=p.get("url"),
            abstract=p.get("abstract"),
            citation_count=p.get("citationCount"),
            semantic_scholar_id=p.get("paperId"),
            pubmed_id=str(ext["PubMed"]) if ext.get("PubMed") else None,
            pmc_id=str(ext["PubMedCentral"]) if ext.get("PubMedCentral") else None,
            arxiv_id=ext.get("ArXiv"),
            venue_type=venue_type,
            volume=str(jr["volume"]) if jr.get("volume") else None,
            pages=str(jr["pages"]).replace(" ", "") if jr.get("pages") else None,
        )
