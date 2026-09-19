"""Step 1 — research-init: topic → PICO + 5 queries (LLM, structured)."""
from __future__ import annotations

from .. import ENGINE_VERSION
from ..render.step1 import render_search_queries
from ..schemas.llm_outputs import S1PicoQueries
from ..schemas.session_config import PICO, EngineInfo, PICOZh, Query, SessionConfig
from ..utils import write_text
from .base import Context, StepOutput


def run(ctx: Context) -> StepOutput:
    s = ctx.session
    topic_original = s.state["topic_original"]
    ts = ctx.ts(1)
    out = ctx.llm.structured("s1_init", S1PicoQueries, {"topic": topic_original, "today": ts[:10]}, step=1)
    cfg = SessionConfig(
        session_id=s.state["session_id"],
        topic=out.topic_en.strip() or topic_original,
        topic_original=topic_original,
        topic_slug=s.state["topic_slug"],
        timestamp=ts,
        current_step=1,
        pico=PICO(population=out.population, intervention=out.intervention, comparison=out.comparison, outcome=out.outcome, setting=out.setting, timeframe=out.timeframe),
        pico_zh=PICOZh(population=out.population_zh, intervention=out.intervention_zh, comparison=out.comparison_zh, outcome=out.outcome_zh, setting=out.setting_zh),
        source_urls=[],
        queries=[Query(id=q.id, strategy=q.strategy, strategy_zh=q.strategy_zh, query=q.query, rationale=q.rationale, rationale_zh=q.rationale_zh) for q in sorted(out.queries, key=lambda q: q.id)],
        field_type=out.field_type,
        engine=EngineInfo(version=ENGINE_VERSION, llm_model=ctx.config.llm.model, llm_temperature=ctx.config.llm.temperature),
    )
    s.save_config(cfg)
    md = render_search_queries(cfg, ts[:10])
    write_text(s.path("step1_search_queries.md"), md)
    return StepOutput(
        files=[s.path("step0_session_config.json"), s.path("step1_search_queries.md")],
        summary={"topic": cfg.topic, "field_type": cfg.field_type, "pico": cfg.pico.model_dump(), "queries": [(q.id, q.query) for q in cfg.queries]},
    )
