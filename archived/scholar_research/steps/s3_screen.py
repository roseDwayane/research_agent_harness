"""Step 3 — research-screen.  Hybrid: LLM emits 1–5 integers; Python owns the arithmetic.

composite = rel×0.50 + qual×0.30 + rec×0.20 (Decimal, half-up to 2 dp)
included ≥ 3.50, borderline 3.00–3.49, excluded < 3.00 — strict, by code.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..render.step3 import render_screening_results
from ..schemas.llm_outputs import S3Batch, S3Criteria
from ..schemas.paper import Paper, RawPapers, ScreenedPaper, Screening, ScreeningConfigOut, ScreeningRecord, Shortlist, ShortlistSummary
from ..utils import dump_json, load_json, round2, truncate, write_text
from .base import Context, StepOutput


def composite_score(relevance: int, quality: int, recency_impact: int, weights: dict[str, float]) -> float:
    """Exact weighted sum, rounded half-up to 2 decimals.  Property: identical axes → identical composite."""
    total = Decimal(str(relevance)) * Decimal(str(weights["relevance"])) + Decimal(str(quality)) * Decimal(str(weights["quality"])) + Decimal(str(recency_impact)) * Decimal(str(weights["recency_impact"]))
    return round2(float(total))


def classify(composite: float, include: float, borderline: float) -> str:
    if composite >= include:
        return "included"
    if composite >= borderline:
        return "borderline"
    return "excluded"


def tier_of(composite: float, bounds: list[float], include: float) -> int | None:
    if composite < include:
        return None
    for i, b in enumerate(bounds, 1):
        if composite >= b:
            return i
    return len(bounds) + 1


def run(ctx: Context) -> StepOutput:
    s, scfg = ctx.session, ctx.config.screening
    sc = s.load_config()
    raw = RawPapers.model_validate(load_json(s.path("step2_raw_papers.json")))
    ts = ctx.ts(3)
    papers = raw.papers
    n = len(papers)
    threshold = scfg.threshold_include
    borderline_t = scfg.threshold_borderline
    small = n < scfg.small_collection_size
    if small:  # keep the borderline band the same width below the lowered threshold
        band = scfg.threshold_include - scfg.threshold_borderline
        threshold = scfg.small_collection_threshold
        borderline_t = round2(threshold - band)
    weights = dict(scfg.weights)

    # ---- criteria (one LLM call) ----
    sample = "\n".join(f"- {truncate(p.title, 110)} ({p.year})" for p in papers[:25])
    pico = sc.pico
    crit = ctx.llm.structured("s3_criteria", S3Criteria, {"topic": sc.topic, "field_type": sc.field_type, "population": pico.population, "intervention": pico.intervention, "comparison": pico.comparison, "outcome": pico.outcome, "setting": pico.setting, "timeframe": pico.timeframe, "n_papers": n, "title_sample": sample}, step=3, tag="criteria")
    inclusion = "\n".join(f"- {c.en}" for c in crit.inclusion)
    exclusion = "\n".join(f"- {c.en}" for c in crit.exclusion)

    # ---- scores (batched LLM calls; batches are deterministic slices) ----
    scores: dict[str, Any] = {}
    for start in range(0, n, scfg.batch_size):
        batch = papers[start : start + scfg.batch_size]
        blob = "\n\n".join(_paper_block(p) for p in batch)
        out = ctx.llm.structured("s3_score", S3Batch, {"topic": sc.topic, "population": pico.population, "intervention": pico.intervention, "comparison": pico.comparison, "outcome": pico.outcome, "inclusion": inclusion, "exclusion": exclusion, "n": len(batch), "papers": blob, "today": ts[:10]}, step=3, tag=f"batch{start // scfg.batch_size + 1}")
        wanted = {p.id for p in batch}
        got = {x.paper_id: x for x in out.scores if x.paper_id in wanted}
        missing = wanted - set(got)
        if missing:  # retry the missing ones once as their own batch
            sub = [p for p in batch if p.id in missing]
            out2 = ctx.llm.structured("s3_score", S3Batch, {"topic": sc.topic, "population": pico.population, "intervention": pico.intervention, "comparison": pico.comparison, "outcome": pico.outcome, "inclusion": inclusion, "exclusion": exclusion, "n": len(sub), "papers": "\n\n".join(_paper_block(p) for p in sub), "today": ts[:10]}, step=3, tag=f"batch{start // scfg.batch_size + 1}-retry")
            got.update({x.paper_id: x for x in out2.scores if x.paper_id in missing})
        scores.update(got)

    screened: list[ScreenedPaper] = []
    for p in papers:
        sc_ = scores.get(p.id)
        if sc_ is None:  # conservative default, flagged
            rel, qual, rec, rationale, excl = 3, 2, 3, "LLM returned no score — conservative default, review manually", None
        else:
            rel, qual, rec, rationale, excl = sc_.relevance, sc_.quality, sc_.recency_impact, sc_.rationale, sc_.exclusion_reason
        comp = composite_score(rel, qual, rec, weights)
        cat = classify(comp, threshold, borderline_t)
        if cat == "excluded" and not excl:
            excl = rationale
        screened.append(ScreenedPaper(**p.model_dump(), screening=Screening(relevance=rel, quality=qual, recency_impact=rec, composite=comp, tier=tier_of(comp, scfg.tier_bounds, threshold), category=cat, rationale=rationale, exclusion_reason=excl if cat == "excluded" else None, no_abstract=not bool(p.abstract))))
    screened.sort(key=lambda x: (-x.screening.composite, x.id))

    # ---- apply Checkpoint 2 decision if it already exists (replay / re-run) ----
    cp = s.load_checkpoints().get(2)
    manual: set[str] = set((cp.decision.get("include") or [])) if cp else set()
    included = [x for x in screened if x.screening.category == "included" or x.id in manual]
    for x in included:
        if x.id in manual and x.screening.category != "included":
            x.manually_included = True
    borderline = [x for x in screened if x.screening.category == "borderline"]
    excluded = [x for x in screened if x.screening.category == "excluded"]

    record = ScreeningRecord(session_id=sc.session_id, criteria_inclusion=[c.model_dump() for c in crit.inclusion], criteria_exclusion=[c.model_dump() for c in crit.exclusion], tier_names=[t.model_dump() for t in sorted(crit.tier_names, key=lambda t: t.tier)], papers=screened)
    dump_json(s.path("step3_screening_all.json"), record.model_dump())
    shortlist = _build_shortlist(sc, ts, threshold, borderline_t, weights, screened, included, borderline, excluded)
    dump_json(s.path("step3_shortlist.json"), shortlist.model_dump())
    md = render_screening_results(sc, record, shortlist, ts[:10], threshold, borderline_t, weights, scfg.tier_bounds, small)
    write_text(s.path("step3_screening_results.md"), md)
    notes = [f"small collection ({n} < {scfg.small_collection_size}): threshold lowered to {threshold}, borderline band {borderline_t}–{round2(threshold - 0.01)}"] if small else []
    return StepOutput(files=[s.path("step3_screening_results.md"), s.path("step3_shortlist.json"), s.path("step3_screening_all.json")], notes=notes, summary={"screened": n, "included": len(included), "borderline": len(borderline), "excluded": len(excluded), "threshold": threshold, "top": [(x.id, truncate(x.title, 70), x.screening.composite) for x in included[:5]], "borderline_ids": [x.id for x in borderline]})


def _build_shortlist(sc, ts, threshold, borderline_t, weights, screened, included, borderline, excluded) -> Shortlist:
    n = len(screened)
    return Shortlist(
        session_id=sc.session_id,
        topic=sc.topic,
        screening_timestamp=ts,
        screening_config=ScreeningConfigOut(threshold=threshold, borderline_threshold=borderline_t, weights=weights),
        summary=ShortlistSummary(total_screened=n, included=len(included), borderline=len(borderline), excluded=len(excluded), inclusion_rate=f"{round(100 * len(included) / n) if n else 0}%", manually_included=sum(1 for x in included if x.manually_included)),
        papers=sorted(included, key=lambda x: (-x.screening.composite, x.id)),
    )


def apply_checkpoint2(ctx: Context, include_ids: list[str]) -> Shortlist:
    """Re-derive step3_shortlist.json from the full record + human decision (no LLM)."""
    s = ctx.session
    sc = s.load_config()
    record = ScreeningRecord.model_validate(load_json(s.path("step3_screening_all.json")))
    old = load_json(s.path("step3_shortlist.json"))
    cfg = old["screening_config"]
    screened = record.papers
    manual = set(include_ids)
    for x in screened:
        x.manually_included = x.id in manual and x.screening.category != "included"
    included = [x for x in screened if x.screening.category == "included" or x.id in manual]
    borderline = [x for x in screened if x.screening.category == "borderline"]
    excluded = [x for x in screened if x.screening.category == "excluded"]
    sl = _build_shortlist(sc, old["screening_timestamp"], cfg["threshold"], cfg["borderline_threshold"], cfg["weights"], screened, included, borderline, excluded)
    dump_json(s.path("step3_shortlist.json"), sl.model_dump())
    scfg = ctx.config.screening
    small = cfg["threshold"] != scfg.threshold_include
    md = render_screening_results(sc, record, sl, old["screening_timestamp"][:10], cfg["threshold"], cfg["borderline_threshold"], cfg["weights"], scfg.tier_bounds, small)
    write_text(s.path("step3_screening_results.md"), md)
    return sl


def _paper_block(p: Paper) -> str:
    hub = f" [HUB: cited by {p.citation_network.in_degree} papers in this collection]" if p.citation_network.is_hub else ""
    ab = p.abstract if p.abstract else "(no abstract available)"
    return f"[{p.id}]{hub}\nTitle: {p.title}\nAuthors: {', '.join(p.authors[:6])}{' et al.' if len(p.authors) > 6 else ''}\nYear: {p.year} | Venue: {p.journal or '?'} | Citations: {p.citation_count if p.citation_count is not None else '?'}\nAbstract: {ab[:2500]}"
