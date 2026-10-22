from __future__ import annotations

from ..schemas.session_config import SessionConfig
from ..utils import frontmatter

STRATEGY_HEADINGS = {
    "Q1": "Core Terms + Population",
    "Q2": "Synonyms + MeSH Terms",
    "Q3": "Mechanism + Theoretical Basis",
    "Q4": "Methodology + Study Design",
    "Q5": "Cross-Disciplinary",
}


def render_search_queries(cfg: SessionConfig, date: str) -> str:
    p = cfg.pico
    lines = [
        frontmatter({"session_id": cfg.session_id, "topic": cfg.topic, "date": date}),
        "",
        "# Search Queries",
        "",
        f"> Topic: {cfg.topic}",
        f"> Generated: {date}",
        "",
        "## PICO Framework",
        "",
        "| Component | Description |",
        "|-----------|-------------|",
        f"| **P** Population | {p.population} |",
        f"| **I** Intervention | {p.intervention} |",
        f"| **C** Comparison | {p.comparison} |",
        f"| **O** Outcome | {p.outcome} |",
        f"| Setting | {p.setting} |",
        f"| Timeframe | {p.timeframe} |",
        "",
        "## Queries",
        "",
    ]
    for q in cfg.queries:
        heading = STRATEGY_HEADINGS.get(q.id, q.strategy)
        lines += [
            f"### {q.id}: {heading}",
            f"**Query:** `{q.query}`",
            f"**Rationale:** {q.rationale}",
            "",
        ]
    lines += [
        "---",
        "",
        "> **Checkpoint 1: Initial Direction Approval**",
        "> Please review the PICO framework and search queries above.",
        "> - Are the PICO components accurate?",
        "> - Any missing keywords or synonyms?",
        "> - Any off-target dimensions to remove?",
        "> ",
        "> When ready, greenlight to proceed to `/research-search`.",
    ]
    return "\n".join(lines)
