from __future__ import annotations

from ..utils import frontmatter, md_cell


def render_gap_analysis(sc, out, ranked, w, date, n_papers, abstract_only, sota_topic):
    topic = sota_topic or sc.topic
    lines = [frontmatter({"session_id": sc.session_id, "topic": topic, "date": date, "step": 7, "gaps_identified": len(ranked), "priority_weights": f"severity={w['severity']:.2f}, novelty={w['novelty']:.2f}, feasibility={w['feasibility']:.2f}"}), ""]
    if abstract_only:
        lines += ["> [!warning] Abstract-Based Gap Analysis / 僅摘要缺口分析", "> This gap analysis is derived from an abstract-only SOTA review. Structural and topical gaps are detectable, but methodological gaps visible only in full-text methods sections may be under-detected. Feasibility is scored conservatively.", "> 本缺口分析基於僅摘要的文獻綜述。結構性與主題性缺口可被偵測，但僅在全文方法章節可見的方法學缺口可能被低估。可行性採保守評分。", ""]
    lines += ["# Gap Analysis / 研究缺口分析", "", f"> Topic / 研究主題: {topic}", f"> Papers analyzed / 分析論文數: {n_papers} (from SOTA review)", f"> Gaps identified / 已識別缺口: {len(ranked)}", f"> Date / 日期: {date}", "", "## Executive Summary / 總覽摘要", "", out.executive_summary_en, "", out.executive_summary_zh, "", "---"]
    for r in ranked:
        g = r["gap"]
        typ = g["gap_type"] + (f" ({g['secondary_type']})" if g.get("secondary_type") else "")
        lines += ["", f"## {r['id']}: {g['title_en']} / {g['title_zh']}", "", f"**Type / 類型:** {typ}", f"**Priority Rank / 優先排名:** #{r['rank']}", "", "### Description / 描述", "", g["description_en"], "", g["description_zh"], "", "### Supporting Evidence / 支持證據", ""]
        for e in g["supporting_evidence"]:
            y = f" ({e['year']})" if e.get("year") else ""
            lines += [f"- **{e['citation_key']}{y}**: {e['explanation_en']}", "", f"  {e['explanation_zh']}", ""]
        lines += ["### Counter-Evidence / 反面證據", ""]
        if g["counter_evidence"]:
            for e in g["counter_evidence"]:
                y = f" ({e['year']})" if e.get("year") else ""
                lines += [f"- **{e['citation_key']}{y}**: {e['explanation_en']}", "", f"  {e['explanation_zh']}", ""]
        else:
            lines += ["> No papers in the collection address this gap, even partially. This suggests a highly novel direction but also warrants caution — the absence may indicate practical barriers not captured in the literature.", ">", "> 文獻中無論文涉及此缺口。這暗示了一個高度新穎的方向，但也需謹慎——此空白可能反映文獻未記錄的實際障礙。", ""]
        sev, nov, fea = g["severity"], g["novelty"], g["feasibility"]
        a, b, c = round(sev * w["severity"], 2), round(nov * w["novelty"], 2), round(fea * w["feasibility"], 2)
        lines += ["### Why It Matters / 重要性", "", g["why_it_matters_en"], "", g["why_it_matters_zh"], "", "### Priority Score / 優先分數", "", "| Axis / 評估軸 | Score / 分數 | Rationale / 理由 |", "|--------------|-------------|-----------------|", f"| Severity / 嚴重性 | {sev} | {md_cell(g['severity_rationale_en'])} / {md_cell(g['severity_rationale_zh'])} |", f"| Novelty / 新穎性 | {nov} | {md_cell(g['novelty_rationale_en'])} / {md_cell(g['novelty_rationale_zh'])} |", f"| Feasibility / 可行性 | {fea} | {md_cell(g['feasibility_rationale_en'])} / {md_cell(g['feasibility_rationale_zh'])} |", "", f"**Composite / 綜合分:** {sev} × {w['severity']:.2f} + {nov} × {w['novelty']:.2f} + {fea} × {w['feasibility']:.2f} = {a:.2f} + {b:.2f} + {c:.2f} = **{r['composite']:.2f}**", "", "---"]
    lines += ["", "## Priority Ranking / 優先排名", "", "| Rank / 排名 | Gap ID | Title / 標題 | Type / 類型 | Severity / 嚴重性 | Novelty / 新穎性 | Feasibility / 可行性 | **Composite / 綜合分** |", "|------------|--------|-------------|-----------|-----------------|----------------|--------------------|-----------------------|"]
    for r in ranked:
        g = r["gap"]
        lines.append(f"| {r['rank']} | {r['id']} | {md_cell(g['title_en'])} / {md_cell(g['title_zh'])} | {g['gap_type']} | {g['severity']} | {g['novelty']} | {g['feasibility']} | **{r['composite']:.2f}** |")
    lines += ["", "---", "", "## Gap Landscape Summary / 缺口全景", "", "### Coverage Strength / 覆蓋強項", "", out.coverage_strength_en, "", out.coverage_strength_zh, "", "### Methodology Distribution / 方法學分布", "", out.methodology_distribution_en, "", out.methodology_distribution_zh, "", "### Cross-Gap Patterns / 跨缺口模式", "", out.cross_gap_patterns_en, "", out.cross_gap_patterns_zh, "", "---", "", "> **Checkpoint 3: 戰場選擇與價值裁定**", ">", "> Review the gaps above. Select which gap to pursue based on your lab's capabilities, budget, ethics timeline, and equipment access.", ">", "> 請審核上述缺口。根據您實驗室的能力、預算、倫理審查時程與設備，選擇要鎖定的缺口。", ">", "> To proceed, specify: \"Lock GAP_{N}, drop GAP_{N}\" — then I'll generate a hypothesis from the selected gap.", ">", "> 請指示：「鎖定 GAP_{N}，放棄 GAP_{N}」——然後我將根據選定缺口生成假說。", "", "---", "", "Files / 檔案: `step7_gap_analysis.md`", "Next step / 下一步: `/research-hypothesis`"]
    return "\n".join(lines)
