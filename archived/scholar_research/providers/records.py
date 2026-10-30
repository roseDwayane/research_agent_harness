"""Provider-neutral search hit, before dedup/merge into ``Paper``."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..utils import normalize_doi


@dataclass
class Hit:
    source: str
    query_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    journal: str | None = None
    doi: str | None = None
    url: str | None = None
    abstract: str | None = None
    citation_count: int | None = None
    semantic_scholar_id: str | None = None
    openalex_id: str | None = None
    pubmed_id: str | None = None
    pmc_id: str | None = None
    arxiv_id: str | None = None
    venue_type: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    arxiv_primary_class: str | None = None
    language: str | None = None
    # external reference ids for citation network (namespace → ids)
    refs_s2: list[str] = field(default_factory=list)
    refs_openalex: list[str] = field(default_factory=list)
    refs_doi: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.doi = normalize_doi(self.doi)
        self.title = " ".join((self.title or "").split())
        if self.abstract:
            self.abstract = " ".join(self.abstract.split())
