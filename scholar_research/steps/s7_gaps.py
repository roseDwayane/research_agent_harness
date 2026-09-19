"""Step 7 — research-gaps.  LLM emits gaps + integer scores; Python computes composite and ranks."""
from __future__ import annotations

import json
from decimal import Decimal

from ..render.step7 import render_gap_analysis
from ..schemas.llm_outputs import S7Gaps
from ..utils import dump_json, load_json, parse_frontmatter, round2, write_text
from .base import Context, StepOutput


def gap_composite(severity: int, novelty: int, feasibility: int, w: dict[str, float]) -> float:
    total = Decimal(str(severity)) * Decimal(str(w["severity"])) + Decimal(str(novelty)) * Decimal(str(w["novelty"])) + Decimal(str(feasibility)) * Decimal(str(w["feasibility"]))
    return round2(float(total))


def run(ctx: Context) -> StepOutput:
    s, gcfg = ctx.session, ctx.config.gaps
    sc = s.load_config()
    sota_md = s.path("step6_sota_review.md").read_text(encoding="utf-8")
    fm = parse_frontmatter(sota_md)
    date = ctx.date(7)
    abstract_only = fm.get("abstract_only") == "true" or fm.get("full_text_papers") == "0"
    topic_mismatch = fm.get("topic") and fm.get("topic") != sc.topic
    sota_json = load_json(s.path("step6_sota.json")) if s.has("step6_sota.json") else None
    keys = [m["citation_key"] for m in (sota_json or {}).get("paper_map", [])] or _keys_from_md(sota_md)
    meth = {}
    for m in (sota_json or {}).get("paper_map", []):
        meth[m["methodology"]] = meth.get(m["methodology"], 0) + 1
    graph_stats = "n/a"
    if s.has("step6_knowledge_graph.canvas"):
        cv = json.loads(s.path("step6_knowledge_graph.canvas").read_text(encoding="utf-8"))
        deg: dict[str, int] = {}
        for e in cv.get("edges", []):
            deg[e["fromNode"]] = deg.get(e["fromNode"], 0) + 1
            deg[e["toNode"]] = deg.get(e["toNode"], 0) + 1
        isolated = [n["id"] for n in cv.get("nodes", []) if n.get("type") in ("file", "text") and n["id"] != "overview" and deg.get(n["id"], 0) == 0]
        theme_ids = {n["id"] for n in cv.get("nodes", []) if n.get("type") == "group"}
        graph_stats = f"{len(cv.get('edges', []))} edges across {len(theme_ids)} theme groups; isolated papers: {', '.join(isolated) or 'none'}"
    note = "\n- The SOTA review is abstract-only: methodological gaps visible only in full-text methods may be under-detected; score feasibility conservatively." if abstract_only else ""
    out = ctx.llm.structured("s7_gaps", S7Gaps, {"topic": fm.get("topic") or sc.topic, "population": sc.pico.population, "intervention": sc.pico.intervention, "comparison": sc.pico.comparison, "outcome": sc.pico.outcome, "keys": ", ".join(keys), "methodology": ", ".join(f"{k}={v}" for k, v in sorted(meth.items())) or "unknown", "graph_stats": graph_stats, "sota": sota_md, "abstract_only_note": note}, step=7)
    gaps = out.gaps[: gcfg.max_gaps]
    valid = set(keys)
    scored = []
    for g in gaps:
        g.supporting_evidence = [e for e in g.supporting_evidence if e.citation_key in valid] or g.supporting_evidence
        g.counter_evidence = [e for e in g.counter_evidence if e.citation_key in valid]
        scored.append((g, gap_composite(g.severity, g.novelty, g.feasibility, gcfg.weights)))
    # rank: composite desc, then severity desc, then title (stable)
    scored.sort(key=lambda gc: (-gc[1], -gc[0].severity, gc[0].title_en))
    ranked = [{"id": f"GAP_{i:03d}", "rank": i, "composite": c, "gap": g.model_dump()} for i, (g, c) in enumerate(scored, 1)]
    dump_json(s.path("step7_gaps.json"), {"session_id": sc.session_id, "weights": gcfg.weights, "gaps": ranked, "summary": {"executive_en": out.executive_summary_en, "executive_zh": out.executive_summary_zh, "coverage_en": out.coverage_strength_en, "coverage_zh": out.coverage_strength_zh, "methodology_en": out.methodology_distribution_en, "methodology_zh": out.methodology_distribution_zh, "patterns_en": out.cross_gap_patterns_en, "patterns_zh": out.cross_gap_patterns_zh}})
    md = render_gap_analysis(sc, out, ranked, gcfg.weights, date, len(keys), abstract_only, fm.get("topic") if topic_mismatch else None)
    write_text(s.path("step7_gap_analysis.md"), md)
    notes = []
    if topic_mismatch:
        notes.append(f"topic mismatch: session '{sc.topic}' vs SOTA '{fm.get('topic')}' — used SOTA topic")
    if len(keys) < 10:
        notes.append("small collection (<10 papers): gaps are preliminary")
    return StepOutput(files=[s.path("step7_gap_analysis.md"), s.path("step7_gaps.json")], notes=notes, summary={"gaps": [(r["id"], r["gap"]["title_en"], r["gap"]["gap_type"], r["composite"]) for r in ranked]})


def _keys_from_md(md: str) -> list[str]:
    import re

    return sorted(set(re.findall(r"\| `([A-Za-z][A-Za-z0-9\-]+\d{4}[a-z]?)` \|", md)))
