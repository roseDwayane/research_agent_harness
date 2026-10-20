"""Run ResearchAgent-style absolute rubric on an existing Step 8 hypothesis.

Does **not** modify ``s8_hypothesis.py`` or feed scores into Steps 8/9.
Writes ``step8_rubric_scores.json`` + ``step8_rubric_report.md`` beside the spec.
"""
from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable

from scholar_research.config import Config
from scholar_research.llm.client import Backend, LLMClient
from scholar_research.llm.prompts import load_prompt
from scholar_research.schemas.llm_outputs import S8RubricRating
from scholar_research.session import Session, now_iso
from scholar_research.utils import dump_json, load_json, write_text
from .metrics import METRICS, MetricDef, anchors_for, excerpt_json, metric_by_id
from .render import render_rubric_report

PROMPT_NAME = "s8_rubric"
SCORES_FILE = "step8_rubric_scores.json"
REPORT_FILE = "step8_rubric_report.md"
ABSTRACT_BUDGET = 600
SOTA_BUDGET = 4000


def _mean(vals: list[int]) -> float:
    if not vals:
        return 0.0
    total = sum(Decimal(v) for v in vals) / Decimal(len(vals))
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _truncate(text: str | None, n: int) -> str:
    t = (text or "").strip().replace("\n", " ")
    if len(t) <= n:
        return t
    return t[: n - 1] + "…"


def _related_papers(session: Session, limit: int = 12) -> str:
    if not session.has("step3_shortlist.json"):
        return "(shortlist unavailable)"
    papers = load_json(session.path("step3_shortlist.json")).get("papers") or []
    lines: list[str] = []
    for i, p in enumerate(papers[:limit], 1):
        title = p.get("title") or "?"
        year = p.get("year") or "?"
        abs_ = _truncate(p.get("abstract"), ABSTRACT_BUDGET)
        lines.append(f"{i}. {title} ({year})\n   Abstract: {abs_ or '(none)'}")
    return "\n".join(lines) if lines else "(empty shortlist)"


def _sota_context(session: Session) -> str:
    if session.has("step6_sota.json"):
        sota = load_json(session.path("step6_sota.json"))
        parts = [
            f"Executive summary: {sota.get('executive_summary_en') or ''}",
            f"Trends: {sota.get('trends_en') or ''}",
            f"Converging: {sota.get('converging_en') or ''}",
            f"Diverging: {sota.get('diverging_en') or ''}",
        ]
        for th in sota.get("themes") or []:
            parts.append(
                f"Theme {th.get('number')}: {th.get('title_en')} — "
                f"consensus: {_truncate(th.get('consensus_en'), 240)}; "
                f"methods: {_truncate(th.get('methods_en'), 160)}"
            )
        return _truncate("\n".join(parts), SOTA_BUDGET)
    if session.has("step6_sota_review.md"):
        return _truncate(session.path("step6_sota_review.md").read_text(encoding="utf-8"), SOTA_BUDGET)
    return "(SOTA unavailable)"


def _locked_gap_blob(session: Session, locked_id: str | None) -> str:
    if not locked_id or not session.has("step7_gaps.json"):
        return "(locked gap unavailable)"
    gaps = load_json(session.path("step7_gaps.json")).get("gaps") or []
    by_id = {g.get("id"): g for g in gaps}
    g = by_id.get(locked_id)
    if not g:
        # gaps may nest under "gap" without top-level id in older shapes
        for row in gaps:
            if row.get("id") == locked_id or (row.get("gap") or {}).get("id") == locked_id:
                g = row
                break
    if not g:
        return f"(gap {locked_id} not found in step7_gaps.json)"
    return json.dumps(g, ensure_ascii=False, indent=2)


def build_context(session: Session) -> dict[str, Any]:
    sc = session.load_config()
    hyp = load_json(session.path("step8_hypothesis.json"))
    spec = hyp.get("spec") or hyp
    locked_id = hyp.get("locked_gap")
    return {
        "session_config": sc,
        "hyp_meta": hyp,
        "spec": spec,
        "locked_id": locked_id or "unknown",
        "locked_gap": _locked_gap_blob(session, locked_id),
        "related_papers": _related_papers(session),
        "sota_context": _sota_context(session),
        "field_type": sc.field_type or "biomedical",
    }


def _select_metrics(only: list[str] | None) -> list[MetricDef]:
    if not only:
        return list(METRICS)
    out: list[MetricDef] = []
    for mid in only:
        out.append(metric_by_id(mid))
    return out


def run_step8_rubric(
    session: Session,
    config: Config,
    *,
    only: list[str] | None = None,
    allow_same_model: bool = False,
    judge_backend: Backend | None = None,
    say: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Score ``step8_hypothesis.json`` with an independent judge client."""
    log = say or (lambda _m: None)
    if not session.has("step8_hypothesis.json"):
        raise FileNotFoundError(f"{session.dir}: missing step8_hypothesis.json — run Step 8 first")

    judge_cfg = config.resolve_judge_llm(allow_same_model=allow_same_model)
    judge = LLMClient(
        judge_cfg,
        session.cache,
        session.ledger,
        backend=judge_backend,
        api_key=config.api.anthropic_api_key,
    )
    ctx = build_context(session)
    sc = ctx["session_config"]
    metrics = _select_metrics(only)
    prompt = load_prompt(PROMPT_NAME)
    ratings: list[dict[str, Any]] = []

    for m in metrics:
        log(f"  rubric {m.id} …")
        variables = {
            "topic": sc.topic,
            "field_type": ctx["field_type"],
            "population": sc.pico.population,
            "intervention": sc.pico.intervention,
            "comparison": sc.pico.comparison,
            "outcome": sc.pico.outcome,
            "setting": sc.pico.setting or "",
            "locked_id": ctx["locked_id"],
            "locked_gap": ctx["locked_gap"],
            "related_papers": ctx["related_papers"],
            "sota_context": ctx["sota_context"],
            "category": m.category,
            "metric_name": m.name,
            "metric_id": m.id,
            "metric_definition": m.definition,
            "primary_fields": ", ".join(m.primary_fields),
            "criteria": anchors_for(m.id, ctx["field_type"]),
            "spec_excerpt": excerpt_json(m, ctx["spec"]),
        }
        out: S8RubricRating = judge.structured(
            PROMPT_NAME,
            S8RubricRating,
            variables,
            step=8,
            tag=f"rubric:{m.id}",
        )
        ratings.append(
            {
                "id": m.id,
                "category": m.category,
                "name": m.name,
                "definition": m.definition,
                "primary_fields": list(m.primary_fields),
                "review": out.review,
                "feedback": out.feedback,
                "rating": int(out.rating),
            }
        )

    by_cat: dict[str, list[int]] = {m.category: [] for m in metrics}
    for r in ratings:
        by_cat[r["category"]].append(r["rating"])
    all_scores = [r["rating"] for r in ratings]
    means = {
        "by_category": {k: _mean(v) for k, v in by_cat.items()},
        "overall": _mean(all_scores),
    }

    gen_model = None
    if sc.engine:
        gen_model = sc.engine.llm_model
    gen_model = gen_model or config.llm.model

    payload = {
        "meta": {
            "session": session.name,
            "locked_gap": ctx["locked_id"],
            "field_type": ctx["field_type"],
            "generator_model": gen_model,
            "judge_model": judge_cfg.model,
            "judge_provider": judge_cfg.provider,
            "prompt": PROMPT_NAME,
            "prompt_version": prompt.version,
            "metric_ids": [m.id for m in metrics],
            "scored_at": now_iso(),
            "feeds_pipeline": False,
        },
        "means": means,
        "ratings": ratings,
    }
    old_path = session.path(SCORES_FILE)
    if old_path.exists():
        old = load_json(old_path)
        if set(old.get('meta', {}).get('metric_ids', [])) != {m.id for m in metrics}:
            dump_json(session.path('step8_rubric_scores.previous_metrics.json'), old)
            if session.has(REPORT_FILE):
                write_text(session.path('step8_rubric_report.previous_metrics.md'), session.path(REPORT_FILE).read_text(encoding='utf-8'))
    dump_json(old_path, payload)
    write_text(session.path(REPORT_FILE), render_rubric_report(payload))
    log(f"wrote {SCORES_FILE} + {REPORT_FILE} (overall {means['overall']:.2f})")
    return payload
