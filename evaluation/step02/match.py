"""Map LitSearch S2ORC corpusIds onto Step 2 papers."""
from __future__ import annotations

from typing import Any

from scholar_research.utils import normalize_doi, word_overlap

TITLE_THRESHOLD = 0.85


def match_gold(gold: dict[str, Any], papers: list[dict[str, Any]], threshold: float = TITLE_THRESHOLD) -> tuple[dict[str, Any] | None, str | None]:
    """Return (paper, method) where method is doi | s2 | arxiv | title. Unmapped gold is not a miss."""
    g_doi = normalize_doi(gold.get("doi"))
    g_s2 = gold.get("paperId") or gold.get("semantic_scholar_id")
    g_ax = (gold.get("arxiv_id") or gold.get("ArXiv") or "") or None
    if g_ax:
        g_ax = str(g_ax).lower()
    g_title = gold.get("title")
    for p in papers:
        if g_doi and normalize_doi(p.get("doi")) == g_doi:
            return p, "doi"
        if g_s2 and p.get("semantic_scholar_id") == g_s2:
            return p, "s2"
        ax = (p.get("arxiv_id") or "")
        if g_ax and ax and ax.lower() == g_ax:
            return p, "arxiv"
    if g_title:
        best, best_s = None, 0.0
        for p in papers:
            s = word_overlap(g_title, p.get("title"))
            if s > best_s:
                best, best_s = p, s
        if best is not None and best_s >= threshold:
            return best, "title"
    return None, None


def as_match_record(obj: Any) -> dict[str, Any]:
    """Hit or paper-like object → dict for ``match_gold``."""
    if isinstance(obj, dict):
        return obj
    return {
        "doi": getattr(obj, "doi", None),
        "semantic_scholar_id": getattr(obj, "semantic_scholar_id", None),
        "arxiv_id": getattr(obj, "arxiv_id", None),
        "title": getattr(obj, "title", None),
    }


def lost_at_from_trace(trace: dict[str, Any] | None) -> str:
    """First gate the gold failed. ``provider_miss`` = no raw hit from any source."""
    if not trace:
        return "not_in_step2_set"
    if trace.get("in_final") or trace.get("after_dedup") or trace.get("snowball_added"):
        return "not_in_step2_set"
    raw = trace.get("provider_raw") or {}
    saw_provider = any(raw.values())
    if trace.get("year_filtered_raw") and not trace.get("after_dedup"):
        return "year_filter"
    if saw_provider and not trace.get("after_dedup"):
        return "dedup_merge"
    reason = trace.get("snowball_drop_reason")
    if reason:
        return f"snowball_{reason}"
    if not saw_provider:
        return "provider_miss"
    return "not_in_step2_set"
