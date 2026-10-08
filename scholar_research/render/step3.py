from __future__ import annotations

from ..schemas.paper import ScreenedPaper, ScreeningRecord, Shortlist
from ..schemas.session_config import SessionConfig
from ..utils import frontmatter, last_name, md_cell, truncate


def _row(x: ScreenedPaper, with_hub: bool = False) -> str:
    fa = f"{last_name(x.authors[0])} et al." if len(x.authors) > 1 else (x.authors[0] if x.authors else "—")
    sc = x.screening
    cells = [x.id, md_cell(truncate(x.title, 90)), md_cell(fa), str(x.year or ""), str(sc.relevance), str(sc.quality), str(sc.recency_impact), f"**{sc.composite:.2f}**", md_cell(sc.rationale)]
    if with_hub:
        cells.append("Yes" if x.citation_network.is_hub else "—")
    return "| " + " | ".join(cells) + " |"


def render_screening_results(sc: SessionConfig, record: ScreeningRecord, sl: Shortlist, date: str, threshold: float, borderline_t: float, weights: dict[str, float], tier_bounds: list[float], small: bool) -> str:
    papers = record.papers
    n = len(papers)
    inc = [x for x in papers if x.screening.category == "included"]
    bord = [x for x in papers if x.screening.category == "borderline"]
    exc = [x for x in papers if x.screening.category == "excluded"]
    pct = lambda k: f"{round(100 * k / n) if n else 0}%"  # noqa: E731
    tn = {t["tier"]: t for t in record.tier_names}
    lines = [
        frontmatter({"session_id": sc.session_id, "topic": sc.topic, "date": date, "step": 3, "threshold": threshold, "weights": f"relevance={weights['relevance']:.2f}, quality={weights['quality']:.2f}, recency_impact={weights['recency_impact']:.2f}"}),
        "",
        "# Screening Results",
        "",
        f"> Topic: {sc.topic}",
        f"> Papers screened: {n}",
        f"> Date: {date}",
        f"> Threshold: composite >= {threshold}",
    ]
    if small:
        lines.append(f"> ⚠️ Small collection — threshold lowered to {threshold} to preserve enough papers.")
    lines += ["", "## Screening Criteria", "", "### Inclusion"]
    lines += [f"- {c['en']}" for c in record.criteria_inclusion]
    lines += ["", "### Exclusion"]
    lines += [f"- {c['en']}" for c in record.criteria_exclusion]
    lines += [
        "",
        "## Summary",
        "",
        "| Category | Count | Percentage |",
        "|-----------------|-------------|-------------------|",
        f"| **Included** | **{len(inc)}** | **{pct(len(inc))}** |",
        f"| Borderline | {len(bord)} | {pct(len(bord))} |",
        f"| Excluded | {len(exc)} | {pct(len(exc))} |",
        "",
        f"Composite formula: `composite = relevance × {weights['relevance']:.2f} + quality × {weights['quality']:.2f} + recency_impact × {weights['recency_impact']:.2f}` (computed by code, rounded half-up to 2 dp).",
    ]
    header = "| ID | Title | Authors | Year | Rel | Qual | Rec | **Composite** | Rationale |\n|----|-------|---------|------|-----|------|-----|---------------|-----------|"
    ranges = []
    lo = threshold
    bounds = list(tier_bounds) + [lo]
    for i, b in enumerate(bounds):
        hi = None if i == 0 else bounds[i - 1]
        ranges.append((i + 1, b, hi))
    for tier, b, hi in ranges:
        name = tn.get(tier, {"en": f"Tier {tier}"})
        rng = f"Score >= {b}" if hi is None else f"Score {b}–{round(hi - 0.01, 2)}"
        rows = [x for x in inc if x.screening.tier == tier]
        lines += ["", f"## Tier {tier}: {name['en']} ({rng})", "", header]
        lines += [_row(x) for x in rows] or ["| — | (none) | | | | | | | |"]
    lines += [
        "",
        "---",
        "",
        f"## Borderline Papers (Score {borderline_t}–{round(threshold - 0.01, 2)})",
        "",
        "> **⛳ Checkpoint 2: Borderline Rescue**",
        "> Review the papers below. These scored close to the threshold and may contain relevant work that the scoring missed — especially cross-disciplinary papers using non-standard terminology.",
        ">",
        "> Mark any paper you want to include with `include` and I'll add it to the shortlist.",
        "",
        "| ID | Title | Authors | Year | Rel | Qual | Rec | **Composite** | Rationale | Hub? |",
        "|----|-------|---------|------|-----|------|-----|---------------|-----------|------|",
    ]
    lines += [_row(x, with_hub=True) for x in bord] or ["| — | (none) | | | | | | | | |"]
    lines += [
        "",
        "---",
        "",
        f"## Excluded Papers (Score < {borderline_t})",
        "",
        "| ID | Title | Year | Rel | Qual | Rec | **Composite** | Exclusion Reason |",
        "|----|-------|------|-----|------|-----|---------------|---------------------------|",
    ]
    for x in exc:
        s_ = x.screening
        lines.append(f"| {x.id} | {md_cell(truncate(x.title, 90))} | {x.year or ''} | {s_.relevance} | {s_.quality} | {s_.recency_impact} | **{s_.composite:.2f}** | {md_cell(s_.exclusion_reason or s_.rationale)} |")
    if not exc:
        lines.append("| — | (none) | | | | | | |")
    hubs = [x for x in papers if x.citation_network.is_hub]
    lines += ["", "---", "", "## Hub Paper Summary", "", "| ID | Title | In-Degree | Cluster | Status | Note |", "|----|-------|-----------|---------|--------|------|"]
    for x in hubs:
        st = x.screening.category.capitalize()
        note = f"Hub paper: cited by {x.citation_network.in_degree} papers in this collection"
        if x.screening.category == "borderline":
            note += " — recommend human review for potential inclusion"
        elif x.screening.category == "excluded":
            note += f" — excluded despite structural importance: {x.screening.exclusion_reason}"
        lines.append(f"| {x.id} | {md_cell(truncate(x.title, 80))} | {x.citation_network.in_degree} | {x.citation_network.cluster or '—'} | {st} | {md_cell(note)} |")
    if not hubs:
        lines.append("| — | (no hub papers) | | | | |")
    if sl.summary.manually_included:
        lines += ["", f"Manually included at Checkpoint 2: {sl.summary.manually_included}"]
    lines += ["", "---", "", "Files: `step3_screening_results.md`, `step3_shortlist.json`", "Next step: `/research-export`"]
    return "\n".join(lines)
