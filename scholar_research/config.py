"""Engine configuration: research.toml + environment variables.

Precedence (highest first): CLI flags → environment → research.toml → defaults.
Model IDs are pinned in the *session* config at ``new`` time so later runs never
silently pick up a different model.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


CacheMode = Literal["read-write", "read-only", "refresh", "off"]


class LLMConfig(BaseModel):
    model: str = "claude-sonnet-5"
    # "anthropic" (Messages API) or "ollama" (local server, e.g. model = "qwen3.8")
    provider: Literal["anthropic", "ollama"] = "anthropic"
    base_url: str = "http://127.0.0.1:11434"  # ollama only
    num_ctx: int = 32768  # ollama only: context window to allocate
    think: bool = False  # ollama only: let thinking models reason before the JSON (slower)
    request_timeout: float = 1800.0  # ollama only: local generation can take minutes
    temperature: float = 0.0
    max_tokens: int = 8192
    max_retries: int = 3
    # structured output validation retries (LLM returned schema-invalid JSON)
    validation_retries: int = 2
    # Steps 6/9 long-context strategy (see plan §9): "full" or "summary"
    context_strategy: Literal["full", "summary"] = "summary"
    per_paper_char_budget: int = 12000


class SearchConfig(BaseModel):
    sources: list[str] = Field(default_factory=lambda: ["semantic_scholar", "openalex", "pubmed", "arxiv"])
    results_per_query: int = 30
    snowball_seeds: int = 5
    snowball_refs_per_seed: int = 50
    snowball_min_overlap: float = 0.15  # token overlap with PICO terms to keep a snowball ref
    title_match_threshold: float = 0.85
    hub_in_degree: int = 3
    request_timeout: float = 30.0
    max_attempts: int = 4


class ScreeningConfig(BaseModel):
    threshold_include: float = 3.5
    threshold_borderline: float = 3.0
    small_collection_size: int = 20
    small_collection_threshold: float = 3.0
    weights: dict[str, float] = Field(
        default_factory=lambda: {"relevance": 0.50, "quality": 0.30, "recency_impact": 0.20}
    )
    tier_bounds: list[float] = Field(default_factory=lambda: [4.5, 4.0])  # tier1 >=4.5, tier2 >=4.0, tier3 >= threshold
    batch_size: int = 12


class GapsConfig(BaseModel):
    weights: dict[str, float] = Field(
        default_factory=lambda: {"severity": 0.40, "novelty": 0.30, "feasibility": 0.30}
    )
    max_gaps: int = 3


class FulltextConfig(BaseModel):
    translate: bool = False  # bilingual _zh.md via LLM (expensive); off by default
    min_chars_full: int = 8000  # below this a "full text" is flagged suspicious
    min_sections_full: int = 4
    prefer_published: bool = True


class APIConfig(BaseModel):
    semantic_scholar_key: str | None = None
    ncbi_api_key: str | None = None
    openalex_mailto: str | None = None
    unpaywall_email: str | None = None
    anthropic_api_key: str | None = None


class PathsConfig(BaseModel):
    research_root: str = "10_Research"
    vault_root: str | None = None  # for canvas file paths relative to an Obsidian vault


class Config(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    screening: ScreeningConfig = Field(default_factory=ScreeningConfig)
    gaps: GapsConfig = Field(default_factory=GapsConfig)
    fulltext: FulltextConfig = Field(default_factory=FulltextConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    cache_mode: CacheMode = "read-write"

    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls, path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> "Config":
        data: dict[str, Any] = {}
        candidate = Path(path) if path else Path("research.toml")
        if candidate.exists():
            with open(candidate, "rb") as fh:
                data = tomllib.load(fh)
        cfg = cls.model_validate(data)
        cfg._apply_env()
        if overrides:
            cfg = cfg.model_copy(update=overrides, deep=True)
        return cfg

    def _apply_env(self) -> None:
        env = os.environ
        self.api.anthropic_api_key = env.get("ANTHROPIC_API_KEY") or self.api.anthropic_api_key
        self.api.semantic_scholar_key = env.get("S2_API_KEY") or env.get("SEMANTIC_SCHOLAR_API_KEY") or self.api.semantic_scholar_key
        self.api.ncbi_api_key = env.get("NCBI_API_KEY") or self.api.ncbi_api_key
        self.api.openalex_mailto = env.get("OPENALEX_MAILTO") or self.api.openalex_mailto
        self.api.unpaywall_email = env.get("UNPAYWALL_EMAIL") or self.api.unpaywall_email
        if env.get("SCHOLAR_RESEARCH_ROOT"):
            self.paths.research_root = env["SCHOLAR_RESEARCH_ROOT"]
        if env.get("SCHOLAR_LLM_MODEL"):
            self.llm.model = env["SCHOLAR_LLM_MODEL"]
        if env.get("SCHOLAR_LLM_PROVIDER"):
            self.llm.provider = env["SCHOLAR_LLM_PROVIDER"]  # type: ignore[assignment]
        if env.get("SCHOLAR_LLM_BASE_URL"):
            self.llm.base_url = env["SCHOLAR_LLM_BASE_URL"]

    def public_dict(self) -> dict[str, Any]:
        """Config without secrets — safe to embed in the run manifest."""
        d = self.model_dump()
        d["api"] = {k: ("<set>" if v else None) for k, v in d["api"].items()}
        return d
