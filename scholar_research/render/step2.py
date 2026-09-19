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
        "# Search Summary / 搜尋摘要",
        "",
        f"> Topic / 研究主題: {sc.topic}",
        f"> Sources / 資料來源: {', '.join(sources)}",
        f"> Date / 搜尋日期: {date}",
        "",
        "## Results / 搜尋結果",
        "",
        "| Query | Strategy / 策略 | Raw | Unique / 唯一 |",
        "|-------|----------|-----|--------|",
    ]
    for q in sc.queries:
        lines.append(f"| {q.id} | {md_cell(q.strategy)} / {md_cell(q.strategy_zh)} | {per_query_raw.get(q.id, 0)} | {sm.queries.get(q.id, 0)} |")
    lines += [
        f"| Snowball | Top-cited references / 高引用文獻延伸 | — | {sm.snowball_additions} |",
        f"| **Total / 總計** | | **{sm.total_raw_results}** | **{n}** |",
        "",
        f"DOI coverage / DOI 覆蓋率: {sm.doi_coverage}（recovery pass 補回 {recovered} 筆）",
        f"Source overlap rate / 來源重疊率: {round(100 * overlap_count / n) if n else 0}%",
        "",
        "### Per source / 各來源唯一篇數",
        "",
        "| Source / 來源 | Unique / 唯一 |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v} |" for k, v in sm.sources.items()]
    if sm.source_failures:
        lines += ["", "### Source failures / 來源失敗紀錄", ""] + [f"- {f}" for f in sm.source_failures]
    lines += ["", "## Hub Papers / 核心文獻", ""]
    pid = {p.id: p for p in raw.papers}
    hubs = sorted((pid[h] for h in sm.hub_papers), key=lambda p: (-p.citation_network.in_degree, p.id))
    if hubs:
        for i, p in enumerate(hubs, 1):
            fa = last_name(p.authors[0]) if p.authors else "Unknown"
            lines.append(f"{i}. \"{md_cell(p.title)}\" ({fa}, {p.year}) — in_degree: {p.citation_network.in_degree} — 本集合中被 {p.citation_network.in_degree} 篇引用")
    else:
        lines.append("No hub papers (in_degree ≥ 3) detected. / 未偵測到核心文獻（集合內被引 ≥ 3）。")
    lines += ["", "## Citation Clusters / 引用聚類", ""]
    if sm.clusters:
        for c in sm.clusters:
            lines.append(f"- **{c.name}** ({len(c.paper_ids)} papers) — top terms: {c.theme} / 引用連通子群，關鍵詞：{c.theme}")
    else:
        lines.append("- No internal citation clusters detected. / 未偵測到集合內引用聚類。")
    if n < 20:
        en = f"Low yield: only {n} unique papers. Consider broadening the weakest queries, extending the timeframe, or dropping population/outcome constraints; the topic may genuinely be under-explored."
        zh = f"產量偏低：僅 {n} 篇唯一論文。建議放寬表現最弱的查詢、延長時間範圍或移除族群/結果限制；此主題也可能本身研究稀少。"
    elif n > 80:
        en = f"High yield: {n} unique papers. Screening in Step 3 will filter; expect a larger borderline set at Checkpoint 2."
        zh = f"產量偏高：{n} 篇唯一論文。Step 3 篩選會過濾；Checkpoint 2 的邊緣清單可能較長。"
    else:
        en = f"Yield within the expected 30–60 range ({n} papers) after deduplication across {len(sources)} sources with {sm.snowball_additions} snowball additions."
        zh = f"產量在預期的 30–60 篇範圍內（{n} 篇），來自 {len(sources)} 個來源去重後，含 {sm.snowball_additions} 篇滾雪球補充。"
    lines += ["", "## Yield Assessment / 產量評估", "", en, zh, "", "---", "", "Files / 檔案: `step2_raw_papers.json`", "Next step / 下一步: `/research-screen`"]
    return "\n".join(lines)
