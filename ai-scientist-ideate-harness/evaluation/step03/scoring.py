"""The frozen Step 3 scoring and ranking contract."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

WEIGHTS = (Decimal("0.50"), Decimal("0.30"), Decimal("0.20"))


def _integer(value, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer from 1 to 5")
    number = int(value)
    if number != value or not 1 <= number <= 5:
        raise ValueError(f"{name} must be an integer from 1 to 5, got {value!r}")
    return number


def composite_score(relevance, quality, recency_impact) -> float:
    rel = _integer(relevance, "relevance")
    qual = _integer(quality, "quality")
    rec = _integer(recency_impact, "recency_impact")
    value = WEIGHTS[0] * rel + WEIGHTS[1] * qual + WEIGHTS[2] * rec
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def normalize_screening(paper: dict, score: dict, category: str | None = None) -> dict:
    rel = _integer(score.get("relevance", score.get("relevance_score")), "relevance")
    qual = _integer(score.get("quality", score.get("quality_score")), "quality")
    rec = _integer(score.get("recency_impact", score.get("impact")), "recency_impact")
    composite = composite_score(rel, qual, rec)
    category = category or score.get("category")
    if category not in ("included", "borderline", "excluded"):
        category = "included" if composite >= 3.5 else "borderline" if composite >= 3.0 else "excluded"
    return {**paper, "screening": {**score, "relevance": rel, "quality": qual,
                                    "recency_impact": rec, "composite": composite,
                                    "category": category}}


def rank_papers(papers: list[dict], by: str) -> list[dict]:
    if by == "relevance":
        return sorted(papers, key=lambda p: (-p["screening"]["relevance"],
                                             -p["screening"]["composite"], str(p["id"])))
    if by == "composite":
        return sorted(papers, key=lambda p: (-p["screening"]["composite"], str(p["id"])))
    raise ValueError("ranking must be relevance or composite")
