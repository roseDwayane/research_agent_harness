"""Hand-written step0_session_config.json — skip Step 1 LLM."""
from __future__ import annotations

from scholar_research import ENGINE_VERSION
from scholar_research.schemas.session_config import EngineInfo, PICO, Query, SessionConfig
from scholar_research.utils import slugify


def timeframe_for(gold_years: list[int], today_year: int = 2026) -> str:
    """Widen past the gold year so Step 2 year filter is not what we measure."""
    if gold_years:
        y0 = max(1990, min(gold_years) - 5)
        y1 = max(today_year, max(gold_years) + 5)
        return f"{y0}-{y1}"
    return f"1990-{today_year}"


def mode_a_config(qid: str, query: str, gold_years: list[int], session_id: str, timestamp: str) -> SessionConfig:
    q = " ".join(query.split())
    return SessionConfig(
        session_id=session_id,
        topic=q,
        topic_original=q,
        topic_slug=slugify(q),
        timestamp=timestamp,
        current_step=0,
        pico=PICO(
            population=q,
            intervention=q,
            comparison="literature search",
            outcome=q,
            setting="ACL Anthology / ICLR",
            timeframe=timeframe_for(gold_years),
        ),
        queries=[
            Query(
                id="Q1",
                strategy="LitSearch Mode A",
                query=q,
                rationale="verbatim LitSearch question; Step 1 skipped",
            )
        ],
        field_type="cs_engineering",
        engine=EngineInfo(version=ENGINE_VERSION, llm_model="none", llm_temperature=0.0),
    )


def lock_eval_retrieval(sc: SessionConfig, gold_years: list[int]) -> SessionConfig:
    """Keep A vs B about query formulation, not year filter or PubMed."""
    return sc.model_copy(
        update={
            "field_type": "cs_engineering",
            "pico": sc.pico.model_copy(update={"timeframe": timeframe_for(gold_years)}),
        }
    )
