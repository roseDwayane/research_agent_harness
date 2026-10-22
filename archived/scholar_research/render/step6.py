from __future__ import annotations

from ..schemas.llm_outputs import S6Sota
from ..utils import frontmatter, md_cell

LEGEND = [("1", "🔴 Red", "experimental", "Experimental"), ("2", "🟠 Orange", "computational", "Computational"), ("3", "🟡 Yellow", "review", "Review"), ("4", "🟢 Green", "observational", "Observational"), ("5", "🔵 Cyan", "engineering", "Engineering"), ("6", "🟣 Purple", "theoretical", "Theoretical")]


def render_sota_review(sc, sota: S6Sota, papers, key_of, date: str, n_full: int, abstract_only: bool) -> str:
    n = len(papers)
    fm = {"session_id": sc.session_id, "topic": sc.topic, "date": date, "step": 6, "total_papers": n, "themes": len(sota.themes), "full_text_papers": n_full, "abstract_only_papers": n - n_full}
    if abstract_only:
        fm["abstract_only"] = True
    lines = [frontmatter(fm), ""]
    if abstract_only:
        lines += ["> [!warning] Abstract-Only Synthesis", "> This review is based on abstracts only — full texts were not available (`step5_full_text/` not found). Synthesis depth is limited: claims cannot be verified against full methodology sections, and quantitative results may be incomplete. Run `/research-fulltext` first for a deeper review.", ""]
    lines += ["# State-of-the-Art Review", "", f"> Topic: {sc.topic}", f"> Papers synthesized: {n}", f"> Themes identified: {len(sota.themes)}", f"> Date: {date}", "", "## Executive Summary", "", sota.executive_summary_en, "", "## Methodology Legend", "", "| Color | Methodology | Count |", "|-------------|---------------------|-------------|"]
    counts = {m: sum(1 for x in sota.paper_map if x.methodology == m) for _, _, m, _ in LEGEND}
    lines += [f"| {c} | {label} | {counts[m]} |" for _, c, m, label in LEGEND]
    lines += ["", "---"]
    for t in sorted(sota.themes, key=lambda t: t.number):
        lines += ["", f"## Theme {t.number}: {t.title_en}", "", f"**Papers:** {', '.join(t.paper_keys)}", "", "### Consensus", "", t.consensus_en, "", "### Debates", "", t.debates_en, "", "### Dominant Methods", "", t.methods_en, "", "### Key Results", "", t.key_results_en, "", "---"]
    lines += ["", "## Cross-Theme Analysis", "", "### Methodological Trends Over Time", "", sota.trends_en, "", "### Converging Findings", "", sota.converging_en, "", "### Diverging Findings", "", sota.diverging_en, "", "### Theme Interactions", "", sota.interactions_en, "", "---", "", "## Paper–Theme Mapping", "", "| Citation Key | Theme | Methodology | Bridge? |", "|----------------------|-------------|---------------------|------------------|"]
    for m in sota.paper_map:
        lines.append(f"| `{m.citation_key}` | theme_{m.theme_number} | {m.methodology} | {'Yes' if m.is_bridge else '—'} |")
    lines += ["", "---", "", "Files: `step6_sota_review.md`, `step6_knowledge_graph.canvas`", "Next step: `/research-gaps`"]
    return "\n".join(lines)
