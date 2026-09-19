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
    p, z = cfg.pico, cfg.pico_zh
    zh = z.model_dump() if z else {k: "" for k in ("population", "intervention", "comparison", "outcome", "setting")}
    lines = [
        frontmatter({"session_id": cfg.session_id, "topic": cfg.topic, "date": date}),
        "",
        "# Search Queries / 搜尋策略",
        "",
        f"> Topic / 研究主題: {cfg.topic}",
        f"> Generated / 產生日期: {date}",
        "",
        "## PICO Framework",
        "",
        "| Component | English | 繁體中文 |",
        "|-----------|---------|---------|",
        f"| **P** Population | {p.population} | {zh['population']} |",
        f"| **I** Intervention | {p.intervention} | {zh['intervention']} |",
        f"| **C** Comparison | {p.comparison} | {zh['comparison']} |",
        f"| **O** Outcome | {p.outcome} | {zh['outcome']} |",
        f"| Setting | {p.setting} | {zh['setting']} |",
        f"| Timeframe | {p.timeframe} | {p.timeframe} |",
        "",
        "## Queries",
        "",
    ]
    for q in cfg.queries:
        heading = STRATEGY_HEADINGS.get(q.id, q.strategy)
        lines += [
            f"### {q.id}: {heading}",
            f"**Query:** `{q.query}`",
            f"**Rationale / 策略說明:** {q.rationale} / {q.rationale_zh}",
            "",
        ]
    lines += [
        "---",
        "",
        "> **Checkpoint 1: 初始定向核准**",
        "> Please review the PICO framework and search queries above.",
        "> - Are the PICO components accurate? / PICO 各元素是否正確？",
        "> - Any missing keywords or synonyms? / 有遺漏的關鍵字或同義詞嗎？",
        "> - Any off-target dimensions to remove? / 有需要移除的偏離維度嗎？",
        "> ",
        "> When ready, greenlight to proceed to `/research-search`.",
    ]
    return "\n".join(lines)
