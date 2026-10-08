from __future__ import annotations

from ..utils import frontmatter, md_cell


def render_hypothesis_spec(sc, topic, out, g, locked_id, dropped, by_id, constraint, date, abstract_only):
    fm = {"session_id": sc.session_id, "topic": topic, "date": date, "step": 8, "selected_gap": locked_id}
    if dropped:
        fm["dropped_gaps"] = dropped
    if constraint:
        fm["design_constraint"] = constraint
    fm["research_questions"] = len(out.research_questions)
    fm["hypotheses"] = len(out.hypotheses)
    gap = g["gap"]
    lines = [frontmatter(fm), ""]
    if abstract_only:
        lines += ["> [!warning] Abstract-Based Hypothesis", "> This hypothesis is derived from an abstract-only gap analysis and SOTA review. Expected effect sizes and methodological details may be imprecise. Consider running `/research-fulltext` to access full papers before finalizing the study design.", ""]
    lines += ["# Hypothesis Specification", "", f"> Topic: {topic}", f"> Selected Gap: {locked_id} — {gap['title_en']}"]
    if dropped:
        lines.append("> Dropped Gaps: " + ", ".join(f"{d} ({by_id[d]['gap']['title_en']})" for d in dropped if d in by_id))
    lines += [f"> Date: {date}", "", "## Executive Summary", "", out.executive_summary_en, "", "---", "", "## Selected Gap Summary", "", f"**Gap ID:** {locked_id}", f"**Type:** {gap['gap_type']}", f"**Priority Score:** {g['composite']:.2f}", "", out.gap_summary_en, ""]
    if dropped and out.gap_selection_rationale_en:
        lines += ["### Gap Selection Rationale", "", out.gap_selection_rationale_en, ""]
    if constraint:
        lines += ["### Constraint Adaptation", "", f"User-specified design constraint: **{constraint}**. RQs, hypotheses and scope below are adapted to this constraint.", ""]
    lines += ["---", "", "## Research Questions", ""]
    for r in out.research_questions:
        lines += [f"### {r.id}: {r.question_en}", "", r.elaboration_en, ""]
    lines += ["---", "", "## Hypotheses", ""]
    for i, h in enumerate(out.hypotheses):
        title = "Primary Hypothesis" if i == 0 else f"Secondary Hypothesis {h.id} {h.id}"
        lines += [f"### {title}", "", "**H0 (Null):**", "", h.h0_en, "", f"**{h.id} (Alternative):**", "", h.h1_en, "", "**Expected Direction & Magnitude:**", "", h.direction_magnitude_en, "", "**Suggested Statistical Approach:**", "", h.statistical_approach_en, ""]
    lines += ["---", "", "## Scope Boundaries", "", "### IN Scope", "", "| Dimension | Specification |", "|-----------------|---------------------|"]
    lines += [f"| **{md_cell(x.dimension_en)}** | {md_cell(x.spec_en)} |" for x in out.scope_in]
    lines += ["", "### OUT Scope", "", "| Exclusion | Rationale |", "|---------------------|---------------------|"]
    lines += [f"| {md_cell(x.exclusion_en)} | {md_cell(x.rationale_en)} |" for x in out.scope_out]
    lines += ["", "### Scope Rationale", "", out.scope_rationale_en, "", "---", "", "## Conceptual Framework", "", out.conceptual_framework_en, "", "---", "", "## Risk Assessment", "", "| Risk | Likelihood | Impact | Mitigation |", "|------------|-------------------|-------------|---------------------|"]
    lines += [f"| {md_cell(r.risk)} | {r.likelihood} | {r.impact} | {md_cell(r.mitigation)} |" for r in out.risks]
    lines += ["", "---", "", "## Gap-to-Hypothesis Traceability", "", "| Element | Source | Evidence |", "|---------------|-------------|----------------|"]
    lines += [f"| {md_cell(t.element)} | {md_cell(t.source)} | {md_cell(t.evidence)} |" for t in out.traceability]
    lines += ["", "---", "", "> **Checkpoint 4: Final Scope Confirmation**", ">", "> Review the IN/OUT boundaries above. Verify that:", "> 1. Every OUT exclusion has an academically defensible rationale", "> 2. The scope matches your actual time, budget, and resource constraints", "> 3. The hypotheses are testable with your available methods and data", ">", "> To proceed, confirm: \"Scope approved\" — then I'll generate journal recommendations and you can move to manuscript writing.", "", "---", "", "Files: `step8_hypothesis_specification.md`", "Next step: Review journal recommendations, then `/research-write`"]
    return "\n".join(lines)


def render_journal_recs(sc, topic, out, date):
    h1 = out.hypotheses[0].h1_en if out.hypotheses else ""
    lines = [frontmatter({"session_id": sc.session_id, "topic": topic, "date": date, "step": 8, "journals_recommended": len(out.journals)}), "", "# Journal Recommendations", "", f"> Topic: {topic}", f"> Hypothesis: {h1[:200]}", f"> Date: {date}", "", "## Selection Criteria", "", out.journal_selection_criteria_en, "", "---", "", "## Recommended Journals", ""]
    for i, j in enumerate(out.journals, 1):
        star = " ⭐ Top Recommendation" if i == 1 else ""
        lines += [f"### {i}. {j.name}{star}", "", "| Field | Details |", "|-------------|---------------|", f"| **Impact Factor** | {md_cell(j.impact_factor)} |", f"| **Scope Fit** | {md_cell(j.scope_fit_en)} |", f"| **Review Timeline** | {md_cell(j.review_timeline)} |", f"| **Open Access** | {md_cell(j.open_access)} |", f"| **Why This Journal** | {md_cell(j.why_en)} |", ""]
        if j.papers_from_collection:
            lines += ["**Papers from our collection published here:**"] + [f"- {k} — indicates topic relevance and reviewer familiarity" for k in j.papers_from_collection] + [""]
        lines += ["---", ""]
    lines += ["## Journal Comparison", "", "| Rank | Journal | IF | Scope Fit | Review Time | OA Cost | Strategy |", "|------------|--------------|-----|-------------------|---------------------|-----------------|----------------|"]
    lines += [f"| {i} | {md_cell(j.name)} | {md_cell(j.impact_factor)} | {md_cell(j.scope_fit_en[:40])} | {md_cell(j.review_timeline)} | {md_cell(j.open_access)} | {'⭐ ' if i == 1 else ''}{md_cell(j.strategy_en)} |" for i, j in enumerate(out.journals, 1)]
    lines += ["", "---", "", "## Submission Strategy", "", out.submission_strategy_en, "", "---", "", "Files: `step8_journal_recommendations.md`", "Next step: `/research-write`"]
    return "\n".join(lines)
