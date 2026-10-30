"""Step 8 — research-hypothesis.  Needs Checkpoint 3 (locked gap) in checkpoints.json."""
from __future__ import annotations

import json

from ..render.step8 import render_hypothesis_spec, render_journal_recs
from ..schemas.llm_outputs import S8HypothesisSpec
from ..utils import dump_json, load_json, parse_frontmatter, write_text
from .base import Context, StepOutput


def run(ctx: Context) -> StepOutput:
    s = ctx.session
    sc = s.load_config()
    cp = s.load_checkpoints().get(3)
    if not cp or not cp.decision.get("lock"):
        raise RuntimeError("Checkpoint 3 unresolved: no locked gap (use --decisions file, --auto, or interactive mode)")
    locked_id: str = cp.decision["lock"]
    dropped: list[str] = list(cp.decision.get("drop") or [])
    constraint: str = cp.decision.get("constraint") or ""
    gaps = load_json(s.path("step7_gaps.json"))
    by_id = {g["id"]: g for g in gaps["gaps"]}
    if locked_id not in by_id:
        raise RuntimeError(f"locked gap {locked_id} not found in step7_gaps.json (have {', '.join(by_id)})")
    g = by_id[locked_id]
    sota_md = s.path("step6_sota_review.md").read_text(encoding="utf-8")
    fm = parse_frontmatter(sota_md)
    abstract_only = fm.get("abstract_only") == "true" or fm.get("full_text_papers") == "0"
    gaps_fm = parse_frontmatter(s.path("step7_gap_analysis.md").read_text(encoding="utf-8"))
    topic = gaps_fm.get("topic") or sc.topic
    date = ctx.date(8)
    sl = load_json(s.path("step3_shortlist.json"))
    keys = load_json(s.path("step4_citation_keys.json"))
    venues = "; ".join(f"{keys[p['id']]['key']} → {p.get('journal') or '?'}" for p in sl["papers"] if p["id"] in keys)
    dropped_txt = ", ".join(f"{d} ({by_id[d]['gap']['title_en']}, composite {by_id[d]['composite']:.2f})" for d in dropped if d in by_id) or "none"
    out = ctx.llm.structured("s8_hypothesis", S8HypothesisSpec, {"topic": topic, "population": sc.pico.population, "intervention": sc.pico.intervention, "comparison": sc.pico.comparison, "outcome": sc.pico.outcome, "setting": sc.pico.setting, "locked_id": locked_id, "locked_gap": json.dumps(g, ensure_ascii=False, indent=1), "dropped": dropped_txt, "constraint": constraint or "none", "venues": venues, "sota": sota_md, "abstract_only_note": "\n- The pipeline ran abstract-only: effect sizes are imprecise; say so and frame magnitudes as exploratory." if abstract_only else ""}, step=8)
    dump_json(s.path("step8_hypothesis.json"), {"locked_gap": locked_id, "dropped_gaps": dropped, "design_constraint": constraint or None, "spec": out.model_dump()})
    spec_md = render_hypothesis_spec(sc, topic, out, g, locked_id, dropped, by_id, constraint, date, abstract_only)
    rec_md = render_journal_recs(sc, topic, out, date)
    write_text(s.path("step8_hypothesis_specification.md"), spec_md)
    write_text(s.path("step8_journal_recommendations.md"), rec_md)
    return StepOutput(files=[s.path("step8_hypothesis_specification.md"), s.path("step8_journal_recommendations.md"), s.path("step8_hypothesis.json")], summary={"locked": locked_id, "rqs": [(r.id, r.question_en) for r in out.research_questions], "h1": out.hypotheses[0].h1_en if out.hypotheses else None, "top_journal": out.journals[0].name if out.journals else None})
