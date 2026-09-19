"""Pydantic models for every *LLM* structured output (plan §4.2).

The LLM only ever produces judgement: text, 1-5 integers, labels.  All
arithmetic, sorting, thresholds and formatting happen in Python.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, conint

Score = conint(ge=1, le=5)


# ----------------------------- Step 1 ---------------------------------- #
class S1PicoQueries(BaseModel):
    topic_en: str = Field(description="English topic used downstream (translate if input was Chinese)")
    field_type: Literal["biomedical", "cs_engineering", "other"]
    population: str
    intervention: str
    comparison: str
    outcome: str
    setting: str
    timeframe: str = Field(description="e.g. '2019-2026'")
    population_zh: str
    intervention_zh: str
    comparison_zh: str
    outcome_zh: str
    setting_zh: str
    queries: list["S1Query"] = Field(min_length=5, max_length=5)


class S1Query(BaseModel):
    id: Literal["Q1", "Q2", "Q3", "Q4", "Q5"]
    strategy: str
    strategy_zh: str
    query: str = Field(description="database-ready search string (Boolean ok)")
    rationale: str
    rationale_zh: str


# ----------------------------- Step 3 ---------------------------------- #
class S3Criteria(BaseModel):
    inclusion: list["BilingualItem"] = Field(min_length=3, max_length=8)
    exclusion: list["BilingualItem"] = Field(min_length=3, max_length=8)
    tier_names: list["TierName"] = Field(min_length=3, max_length=3)


class BilingualItem(BaseModel):
    en: str
    zh: str


class TierName(BaseModel):
    tier: conint(ge=1, le=3)
    en: str
    zh: str


class S3PaperScore(BaseModel):
    paper_id: str
    relevance: Score
    quality: Score
    recency_impact: Score
    rationale: str = Field(description="one line, auditable")
    exclusion_reason: str | None = Field(default=None, description="specific reason if the paper is clearly off-target; else null")


class S3Batch(BaseModel):
    scores: list[S3PaperScore]


# ----------------------------- Step 5 ---------------------------------- #
class S5SectionTranslation(BaseModel):
    heading_en: str
    heading_zh: str
    paragraphs_zh: list[str]


class S5Bilingual(BaseModel):
    title_zh: str
    key_points_zh: list[str] = Field(min_length=3, max_length=8)
    sections: list[S5SectionTranslation]


# ----------------------------- Step 6 ---------------------------------- #
Methodology = Literal["experimental", "computational", "review", "observational", "engineering", "theoretical"]


class S6PaperNote(BaseModel):
    """Per-paper structured digest (context_strategy='summary')."""

    citation_key: str
    problem: str
    method: str
    key_results: list[str]
    limitations: list[str]
    future_work: list[str]
    methodology: Methodology
    sample_or_dataset: str = ""


class S6ThemeSection(BaseModel):
    number: int
    title_en: str
    title_zh: str
    paper_keys: list[str]
    consensus_en: str
    consensus_zh: str
    debates_en: str
    debates_zh: str
    methods_en: str
    methods_zh: str
    key_results_en: str = Field(description="markdown table or narrative")
    key_results_zh: str


class S6Edge(BaseModel):
    from_key: str
    to_key: str
    label: str


class S6PaperMap(BaseModel):
    citation_key: str
    theme_number: int
    methodology: Methodology
    is_bridge: bool = False


class S6Sota(BaseModel):
    executive_summary_en: str
    executive_summary_zh: str
    themes: list[S6ThemeSection] = Field(min_length=2, max_length=8)
    trends_en: str
    trends_zh: str
    converging_en: str
    converging_zh: str
    diverging_en: str
    diverging_zh: str
    interactions_en: str
    interactions_zh: str
    paper_map: list[S6PaperMap]
    edges: list[S6Edge]


# ----------------------------- Step 7 ---------------------------------- #
GapType = Literal["methodological", "population", "measurement", "temporal", "integration"]


class S7Evidence(BaseModel):
    citation_key: str
    year: int | None = None
    explanation_en: str
    explanation_zh: str


class S7Gap(BaseModel):
    title_en: str
    title_zh: str
    gap_type: GapType
    secondary_type: GapType | None = None
    description_en: str
    description_zh: str
    supporting_evidence: list[S7Evidence] = Field(min_length=2)
    counter_evidence: list[S7Evidence] = Field(default_factory=list)
    why_it_matters_en: str
    why_it_matters_zh: str
    severity: Score
    novelty: Score
    feasibility: Score
    severity_rationale_en: str
    severity_rationale_zh: str
    novelty_rationale_en: str
    novelty_rationale_zh: str
    feasibility_rationale_en: str
    feasibility_rationale_zh: str


class S7Gaps(BaseModel):
    executive_summary_en: str
    executive_summary_zh: str
    gaps: list[S7Gap] = Field(min_length=1, max_length=4)
    coverage_strength_en: str
    coverage_strength_zh: str
    methodology_distribution_en: str
    methodology_distribution_zh: str
    cross_gap_patterns_en: str
    cross_gap_patterns_zh: str


# ----------------------------- Step 8 ---------------------------------- #
class S8RQ(BaseModel):
    id: str
    focus: str
    question_en: str
    question_zh: str
    elaboration_en: str
    elaboration_zh: str


class S8Hypothesis(BaseModel):
    id: str  # H1 / H2 / H3
    label_en: str
    label_zh: str
    h0_en: str
    h0_zh: str
    h1_en: str
    h1_zh: str
    direction_magnitude_en: str
    direction_magnitude_zh: str
    statistical_approach_en: str
    statistical_approach_zh: str


class S8ScopeIn(BaseModel):
    dimension_en: str
    dimension_zh: str
    spec_en: str
    spec_zh: str


class S8ScopeOut(BaseModel):
    exclusion_en: str
    exclusion_zh: str
    rationale_en: str
    rationale_zh: str


class S8Risk(BaseModel):
    risk: str
    likelihood: Literal["Low", "Medium", "High"]
    impact: Literal["Low", "Medium", "High"]
    mitigation: str


class S8Trace(BaseModel):
    element: str
    source: str
    evidence: str


class S8Journal(BaseModel):
    name: str
    impact_factor: str
    scope_fit_en: str
    scope_fit_zh: str
    review_timeline: str
    open_access: str
    why_en: str
    why_zh: str
    strategy_en: str
    strategy_zh: str
    papers_from_collection: list[str] = Field(default_factory=list)


class S8HypothesisSpec(BaseModel):
    executive_summary_en: str
    executive_summary_zh: str
    gap_summary_en: str
    gap_summary_zh: str
    gap_selection_rationale_en: str = ""
    gap_selection_rationale_zh: str = ""
    research_questions: list[S8RQ] = Field(min_length=1, max_length=4)
    hypotheses: list[S8Hypothesis] = Field(min_length=1, max_length=3)
    scope_in: list[S8ScopeIn] = Field(min_length=5)
    scope_out: list[S8ScopeOut] = Field(min_length=3)
    scope_rationale_en: str
    scope_rationale_zh: str
    conceptual_framework_en: str
    conceptual_framework_zh: str
    risks: list[S8Risk] = Field(min_length=3, max_length=5)
    traceability: list[S8Trace]
    journals: list[S8Journal] = Field(min_length=3, max_length=5)
    journal_selection_criteria_en: str
    journal_selection_criteria_zh: str
    submission_strategy_en: str
    submission_strategy_zh: str


# ----------------------------- Step 9 ---------------------------------- #
class S9Manuscript(BaseModel):
    intro_latex: str = Field(description="body of \\section{Introduction} (no preamble); every citation as \\cite{key}")
    relatedwork_latex: str = Field(description="body of \\section{Related Work}")
    target_journal: str
