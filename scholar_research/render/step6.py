from __future__ import annotations

from ..schemas.llm_outputs import S6Sota
from ..utils import frontmatter, md_cell

LEGEND = [("1", "🔴 Red", "experimental", "Experimental / 實驗研究"), ("2", "🟠 Orange", "computational", "Computational / 計算方法"), ("3", "🟡 Yellow", "review", "Review / 文獻回顧"), ("4", "🟢 Green", "observational", "Observational / 觀察研究"), ("5", "🔵 Cyan", "engineering", "Engineering / 工程設計"), ("6", "🟣 Purple", "theoretical", "Theoretical / 理論研究")]


def render_sota_review(sc, sota: S6Sota, papers, key_of, date: str, n_full: int, abstract_only: bool) -> str:
    n = len(papers)
    fm = {"session_id": sc.session_id, "topic": sc.topic, "date": date, "step": 6, "total_papers": n, "themes": len(sota.themes), "full_text_papers": n_full, "abstract_only_papers": n - n_full}
    if abstract_only:
        fm["abstract_only"] = True
    lines = [frontmatter(fm), ""]
    if abstract_only:
        lines += ["> [!warning] Abstract-Only Synthesis / 僅摘要綜整", "> This review is based on abstracts only — full texts were not available (`step5_full_text/` not found). Synthesis depth is limited: claims cannot be verified against full methodology sections, and quantitative results may be incomplete. Run `/research-fulltext` first for a deeper review.", "> 本綜述僅基於摘要——全文不可用（`step5_full_text/` 未找到）。綜整深度有限：無法根據完整方法學章節驗證論點，定量結果可能不完整。建議先執行 `/research-fulltext` 以獲得更深入的綜述。", ""]
    lines += ["# State-of-the-Art Review / 研究現況綜述", "", f"> Topic / 研究主題: {sc.topic}", f"> Papers synthesized / 綜整論文數: {n}", f"> Themes identified / 主題數: {len(sota.themes)}", f"> Date / 日期: {date}", "", "## Executive Summary / 總覽摘要", "", sota.executive_summary_en, "", sota.executive_summary_zh, "", "## Methodology Legend / 方法學圖例", "", "| Color / 顏色 | Methodology / 方法學 | Count / 數量 |", "|-------------|---------------------|-------------|"]
    counts = {m: sum(1 for x in sota.paper_map if x.methodology == m) for _, _, m, _ in LEGEND}
    lines += [f"| {c} | {label} | {counts[m]} |" for _, c, m, label in LEGEND]
    lines += ["", "---"]
    for t in sorted(sota.themes, key=lambda t: t.number):
        lines += ["", f"## Theme {t.number}: {t.title_en} / {t.title_zh}", "", f"**Papers / 論文:** {', '.join(t.paper_keys)}", "", "### Consensus / 共識", "", t.consensus_en, "", t.consensus_zh, "", "### Debates / 爭議", "", t.debates_en, "", t.debates_zh, "", "### Dominant Methods / 主流方法", "", t.methods_en, "", t.methods_zh, "", "### Key Results / 關鍵發現", "", t.key_results_en, "", t.key_results_zh, "", "---"]
    lines += ["", "## Cross-Theme Analysis / 跨主題分析", "", "### Methodological Trends Over Time / 方法學時間趨勢", "", sota.trends_en, "", sota.trends_zh, "", "### Converging Findings / 匯聚發現", "", sota.converging_en, "", sota.converging_zh, "", "### Diverging Findings / 分歧發現", "", sota.diverging_en, "", sota.diverging_zh, "", "### Theme Interactions / 主題交互", "", sota.interactions_en, "", sota.interactions_zh, "", "---", "", "## Paper–Theme Mapping / 論文主題對照", "", "| Citation Key / 引用鍵 | Theme / 主題 | Methodology / 方法學 | Bridge? / 跨主題? |", "|----------------------|-------------|---------------------|------------------|"]
    for m in sota.paper_map:
        lines.append(f"| `{m.citation_key}` | theme_{m.theme_number} | {m.methodology} | {'Yes' if m.is_bridge else '—'} |")
    lines += ["", "---", "", "Files / 檔案: `step6_sota_review.md`, `step6_knowledge_graph.canvas`", "Next step / 下一步: `/research-gaps`"]
    return "\n".join(lines)
