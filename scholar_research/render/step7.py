from __future__ import annotations

from ..utils import frontmatter, md_cell


def render_gap_analysis(sc, out, ranked, w, date, n_papers, abstract_only, sota_topic):
    topic = sota_topic or sc.topic
    lines = [frontmatter({"session_id": sc.session_id, "topic": topic, "date": date, "step": 7, "gaps_identified": len(ranked), "priority_weights": f"severity={w['severity']:.2f}, novelty={w['novelty']:.2f}, feasibility={w['feasibility']:.2f}"}), ""]
    if abstract_only:
        lines += ["> [!warning] Abstract-Based Gap Analysis", "> This gap analysis is derived from an abstract-only SOTA review. Structural and topical gaps are detectable, but methodological gaps visible only in full-text methods sections may be under-detected. Feasibility is scored conservatively.", ""]
    lines += ["# Gap Analysis", "", f"> Topic: {topic}", f"> Papers analyzed: {n_papers} (from SOTA review)", f"> Gaps identified: {len(ranked)}", f"> Date: {date}", "", "## Executive Summary", "", out.executive_summary_en, "", "---"]
    for r in ranked:
        g = r["gap"]
        typ = g["gap_type"] + (f" ({g['secondary_type']})" if g.get("secondary_type") else "")
        lines += ["", f"## {r['id']}: {g['title_en']}", "", f"**Type:** {typ}", f"**Priority Rank:** #{r['rank']}", "", "### Description", "", g["description_en"], "", "### Supporting Evidence", ""]
        for e in g["supporting_evidence"]:
            y = f" ({e['year']})" if e.get("year") else ""
            lines += [f"- **{e['citation_key']}{y}**: {e['explanation_en']}", ""]
        lines += ["### Counter-Evidence", ""]
        if g["counter_evidence"]:
            for e in g["counter_evidence"]:
                y = f" ({e['year']})" if e.get("year") else ""
                lines += [f"- **{e['citation_key']}{y}**: {e['explanation_en']}", ""]
        else:
            lines += ["> No papers in the collection address this gap, even partially. This suggests a highly novel direction but also warrants caution — the absence may indicate practical barriers not captured in the literature.", ""]
        sev, nov, fea = g["severity"], g["novelty"], g["feasibility"]
        a, b, c = round(sev * w["severity"], 2), round(nov * w["novelty"], 2), round(fea * w["feasibility"], 2)
        lines += ["### Why It Matters", "", g["why_it_matters_en"], "", "### Priority Score", "", "| Axis | Score | Rationale |", "|--------------|-------------|-----------------|", f"| Severity | {sev} | {md_cell(g['severity_rationale_en'])} |", f"| Novelty | {nov} | {md_cell(g['novelty_rationale_en'])} |", f"| Feasibility | {fea} | {md_cell(g['feasibility_rationale_en'])} |", "", f"**Composite:** {sev} × {w['severity']:.2f} + {nov} × {w['novelty']:.2f} + {fea} × {w['feasibility']:.2f} = {a:.2f} + {b:.2f} + {c:.2f} = **{r['composite']:.2f}**", "", "---"]
    lines += ["", "## Priority Ranking", "", "| Rank | Gap ID | Title | Type | Severity | Novelty | Feasibility | **Composite** |", "|------------|--------|-------------|-----------|-----------------|----------------|--------------------|-----------------------|"]
    for r in ranked:
        g = r["gap"]
        lines.append(f"| {r['rank']} | {r['id']} | {md_cell(g['title_en'])} | {g['gap_type']} | {g['severity']} | {g['novelty']} | {g['feasibility']} | **{r['composite']:.2f}** |")
    lines += ["", "---", "", "## Gap Landscape Summary", "", "### Coverage Strength", "", out.coverage_strength_en, "", "### Methodology Distribution", "", out.methodology_distribution_en, "", "### Cross-Gap Patterns", "", out.cross_gap_patterns_en, "", "---", "", "> **Checkpoint 3: Gap Selection**", ">", "> Review the gaps above. Select which gap to pursue based on your lab's capabilities, budget, ethics timeline, and equipment access.", ">", "> To proceed, specify: \"Lock GAP_{N}, drop GAP_{N}\" — then I'll generate a hypothesis from the selected gap.", "", "---", "", "Files: `step7_gap_analysis.md`", "Next step: `/research-hypothesis`"]
    return "\n".join(lines)
