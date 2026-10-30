"""step2_raw_papers.json and step3_shortlist.json records."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CitationNetwork(BaseModel):
    in_degree: int = 0
    out_degree: int = 0
    is_hub: bool = False
    cluster: str | None = None


class Paper(BaseModel):
    id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    journal: str | None = None
    doi: str | None = None
    url: str | None = None
    abstract: str | None = None
    citation_count: int | None = None
    sources_found_in: list[str] = Field(default_factory=list)
    semantic_scholar_id: str | None = None
    openalex_id: str | None = None
    pubmed_id: str | None = None
    pmc_id: str | None = None
    arxiv_id: str | None = None
    references: list[str] = Field(default_factory=list)
    cited_by: list[str] = Field(default_factory=list)
    is_seed_paper: bool = False
    found_via: str = ""
    language: str | None = None
    venue_type: str | None = None  # journal | conference | preprint (best effort from sources)
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    arxiv_primary_class: str | None = None
    citation_network: CitationNetwork = Field(default_factory=CitationNetwork)
    # raw provider ids of referenced works (external) — used only for network mapping
    external_refs: dict[str, list[str]] = Field(default_factory=dict, exclude=True)


class Cluster(BaseModel):
    name: str
    paper_ids: list[str]
    theme: str


class SearchSummary(BaseModel):
    total_raw_results: int
    after_dedup: int
    snowball_additions: int
    final_count: int
    sources: dict[str, int]
    queries: dict[str, int]
    doi_coverage: str
    hub_papers: list[str]
    clusters: list[Cluster]
    source_failures: list[str] = Field(default_factory=list)


class RawPapers(BaseModel):
    session_id: str
    topic: str
    search_timestamp: str
    search_summary: SearchSummary
    papers: list[Paper]


class Screening(BaseModel):
    relevance: int = Field(ge=1, le=5)
    quality: int = Field(ge=1, le=5)
    recency_impact: int = Field(ge=1, le=5)
    composite: float
    tier: int | None = None
    category: str = "included"  # included | borderline | excluded
    rationale: str = ""
    exclusion_reason: str | None = None
    no_abstract: bool = False


class ScreenedPaper(Paper):
    screening: Screening
    manually_included: bool = False


class ScreeningConfigOut(BaseModel):
    threshold: float
    borderline_threshold: float
    weights: dict[str, float]


class ShortlistSummary(BaseModel):
    total_screened: int
    included: int
    borderline: int
    excluded: int
    inclusion_rate: str
    manually_included: int = 0


class Shortlist(BaseModel):
    session_id: str
    topic: str
    screening_timestamp: str
    screening_config: ScreeningConfigOut
    summary: ShortlistSummary
    papers: list[ScreenedPaper]


class ScreeningRecord(BaseModel):
    """Full record of every paper's scores (included + borderline + excluded).

    Written to ``step3_screening_all.json`` so Checkpoint 2 and replay have the
    complete decision table without re-parsing markdown.
    """

    session_id: str
    criteria_inclusion: list[dict[str, str]]
    criteria_exclusion: list[dict[str, str]]
    tier_names: list[dict[str, Any]]
    papers: list[ScreenedPaper]
