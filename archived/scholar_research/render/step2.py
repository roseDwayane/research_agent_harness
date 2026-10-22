from __future__ import annotations

from collections import Counter

from ..schemas.paper import RawPapers
from ..schemas.session_config import SessionConfig
from ..utils import frontmatter, last_name, md_cell


def render_search_summary(sc: SessionConfig, raw: RawPapers, date: str, sources: list[str], per_query_raw: Counter, overlap_count: int, recovered: int) -> str:
    sm = raw.search_summary
    n = sm.final_count
    lines = [
        frontmatter({"session_id": sc.session_id, "topic": sc.topic, "date": date, "step": 2}),
        "",
        "# Search Summary",
        "",
        f"> Topic: {sc.topic}",
        f"> Sources: {', '.join(sources)}",
        f"> Date: {date}",
        "",
        "## Results",
        "",
        "| Query | Strategy | Raw | Unique |",
        "|-------|----------|-----|--------|",
    ]
    for q in sc.queries:
        lines.append(f"| {q.id} | {md_cell(q.strategy)} | {per_query_raw.get(q.id, 0)} | {sm.queries.get(q.id, 0)} |")
    lines += [
        f"| Snowball | Top-cited references | — | {sm.snowball_additions} |",
        f"| **Total** | | **{sm.total_raw_results}** | **{n}** |",
        "",
        f"DOI coverage: {sm.doi_coverage} ({recovered} recovered by the recovery pass)",
        f"Source overlap rate: {round(100 * overlap_count / n) if n else 0}%",
        "",
        "### Per source",
        "",
        "| Source | Unique |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v} |" for k, v in sm.sources.items()]
    if sm.source_failures:
        lines += ["", "### Source failures", ""] + [f"- {f}" for f in sm.source_failures]
    lines += ["", "## Hub Papers", ""]
    pid = {p.id: p for p in raw.papers}
    hubs = sorted((pid[h] for h in sm.hub_papers), key=lambda p: (-p.citation_network.in_degree, p.id))
    if hubs:
        for i, p in enumerate(hubs, 1):
            fa = last_name(p.authors[0]) if p.authors else "Unknown"
            lines.append(f"{i}. \"{md_cell(p.title)}\" ({fa}, {p.year}) — in_degree: {p.citation_network.in_degree} — cited by {p.citation_network.in_degree} papers in this collection")
    else:
        lines.append("No hub papers (in_degree ≥ 3) detected.")
    lines += ["", "## Citation Clusters", ""]
    if sm.clusters:
        for c in sm.clusters:
            lines.append(f"- **{c.name}** ({len(c.paper_ids)} papers) — top terms: {c.theme}{c.theme}")
    else:
        lines.append("- No internal citation clusters detected.")
    if n < 20:
        en = f"Low yield: only {n} unique papers. Consider broadening the weakest queries, extending the timeframe, or dropping population/outcome constraints; the topic may genuinely be under-explored."
    elif n > 80:
        en = f"High yield: {n} unique papers. Screening in Step 3 will filter; expect a larger borderline set at Checkpoint 2."
    else:
        en = f"Yield within the expected 30–60 range ({n} papers) after deduplication across {len(sources)} sources with {sm.snowball_additions} snowball additions."
    lines += ["", "## Yield Assessment", "", en, "", "---", "", "Files: `step2_raw_papers.json`", "Next step: `/research-screen`"]
    return "\n".join(lines)
