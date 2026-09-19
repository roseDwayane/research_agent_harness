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
        lines += ["> [!warning] Abstract-Based Hypothesis / 僅摘要假說", "> This hypothesis is derived from an abstract-only gap analysis and SOTA review. Expected effect sizes and methodological details may be imprecise. Consider running `/research-fulltext` to access full papers before finalizing the study design.", "> 本假說基於僅摘要的缺口分析與文獻綜述。預期效果量和方法學細節可能不夠精確。建議在最終確定研究設計前，先執行 `/research-fulltext` 以取得完整論文。", ""]
    lines += ["# Hypothesis Specification / 假說規格書", "", f"> Topic / 研究主題: {topic}", f"> Selected Gap / 選定缺口: {locked_id} — {gap['title_en']}"]
    if dropped:
        lines.append("> Dropped Gaps / 放棄缺口: " + ", ".join(f"{d} ({by_id[d]['gap']['title_en']})" for d in dropped if d in by_id))
    lines += [f"> Date / 日期: {date}", "", "## Executive Summary / 總覽摘要", "", out.executive_summary_en, "", out.executive_summary_zh, "", "---", "", "## Selected Gap Summary / 選定缺口摘要", "", f"**Gap ID:** {locked_id}", f"**Type / 類型:** {gap['gap_type']}", f"**Priority Score / 優先分數:** {g['composite']:.2f}", "", out.gap_summary_en, "", out.gap_summary_zh, ""]
    if dropped and out.gap_selection_rationale_en:
        lines += ["### Gap Selection Rationale / 缺口選擇理由", "", out.gap_selection_rationale_en, "", out.gap_selection_rationale_zh, ""]
    if constraint:
        lines += ["### Constraint Adaptation / 限制條件調整", "", f"User-specified design constraint: **{constraint}**. RQs, hypotheses and scope below are adapted to this constraint.", f"使用者指定的設計限制：**{constraint}**。以下 RQ、假說與範圍已依此限制調整。", ""]
    lines += ["---", "", "## Research Questions / 研究問題", ""]
    for r in out.research_questions:
        lines += [f"### {r.id}: {r.question_en} / {r.question_zh}", "", r.elaboration_en, "", r.elaboration_zh, ""]
    lines += ["---", "", "## Hypotheses / 假說", ""]
    for i, h in enumerate(out.hypotheses):
        title = "Primary Hypothesis / 主要假說" if i == 0 else f"Secondary Hypothesis {h.id} / 次要假說 {h.id}"
        lines += [f"### {title}", "", "**H0 (Null / 虛無假說):**", "", h.h0_en, "", h.h0_zh, "", f"**{h.id} (Alternative / 對立假說):**", "", h.h1_en, "", h.h1_zh, "", "**Expected Direction & Magnitude / 預期方向與幅度:**", "", h.direction_magnitude_en, "", h.direction_magnitude_zh, "", "**Suggested Statistical Approach / 建議統計方法:**", "", h.statistical_approach_en, "", h.statistical_approach_zh, ""]
    lines += ["---", "", "## Scope Boundaries / 範圍界定", "", "### IN Scope / 範圍內", "", "| Dimension / 維度 | Specification / 規格 |", "|-----------------|---------------------|"]
    lines += [f"| **{md_cell(x.dimension_en)} / {md_cell(x.dimension_zh)}** | {md_cell(x.spec_en)} / {md_cell(x.spec_zh)} |" for x in out.scope_in]
    lines += ["", "### OUT Scope / 範圍外", "", "| Exclusion / 排除項目 | Rationale / 學術理由 |", "|---------------------|---------------------|"]
    lines += [f"| {md_cell(x.exclusion_en)} / {md_cell(x.exclusion_zh)} | {md_cell(x.rationale_en)} / {md_cell(x.rationale_zh)} |" for x in out.scope_out]
    lines += ["", "### Scope Rationale / 範圍邏輯", "", out.scope_rationale_en, "", out.scope_rationale_zh, "", "---", "", "## Conceptual Framework / 概念框架", "", out.conceptual_framework_en, "", out.conceptual_framework_zh, "", "---", "", "## Risk Assessment / 風險評估", "", "| Risk / 風險 | Likelihood / 可能性 | Impact / 影響 | Mitigation / 緩解策略 |", "|------------|-------------------|-------------|---------------------|"]
    lines += [f"| {md_cell(r.risk)} | {r.likelihood} | {r.impact} | {md_cell(r.mitigation)} |" for r in out.risks]
    lines += ["", "---", "", "## Gap-to-Hypothesis Traceability / 缺口到假說追溯", "", "| Element / 元素 | Source / 來源 | Evidence / 證據 |", "|---------------|-------------|----------------|"]
    lines += [f"| {md_cell(t.element)} | {md_cell(t.source)} | {md_cell(t.evidence)} |" for t in out.traceability]
    lines += ["", "---", "", "> **Checkpoint 4: 護城河最終確認**", ">", "> Review the IN/OUT boundaries above. Verify that:", "> 1. Every OUT exclusion has an academically defensible rationale", "> 2. The scope matches your actual time, budget, and resource constraints", "> 3. The hypotheses are testable with your available methods and data", ">", "> 請審核上述 IN/OUT 邊界。確認：", "> 1. 每個 OUT 排除項目都有可在學術上辯護的理由", "> 2. 範圍符合您實際的時間、預算和資源限制", "> 3. 假說可用您現有的方法和數據進行測試", ">", "> To proceed, confirm: \"Scope approved\" — then I'll generate journal recommendations and you can move to manuscript writing.", ">", "> 請確認：「範圍核准」——然後我將生成期刊推薦，您可以進入論文寫作階段。", "", "---", "", "Files / 檔案: `step8_hypothesis_specification.md`", "Next step / 下一步: Review journal recommendations, then `/research-write`"]
    return "\n".join(lines)


def render_journal_recs(sc, topic, out, date):
    h1 = out.hypotheses[0].h1_en if out.hypotheses else ""
    lines = [frontmatter({"session_id": sc.session_id, "topic": topic, "date": date, "step": 8, "journals_recommended": len(out.journals)}), "", "# Journal Recommendations / 目標期刊推薦", "", f"> Topic / 研究主題: {topic}", f"> Hypothesis / 假說: {h1[:200]}", f"> Date / 日期: {date}", "", "## Selection Criteria / 選擇標準", "", out.journal_selection_criteria_en, "", out.journal_selection_criteria_zh, "", "---", "", "## Recommended Journals / 推薦期刊", ""]
    for i, j in enumerate(out.journals, 1):
        star = " ⭐ Top Recommendation / 首選推薦" if i == 1 else ""
        lines += [f"### {i}. {j.name}{star}", "", "| Field / 欄位 | Details / 詳細 |", "|-------------|---------------|", f"| **Impact Factor / 影響因子** | {md_cell(j.impact_factor)} |", f"| **Scope Fit / 範圍契合** | {md_cell(j.scope_fit_en)} / {md_cell(j.scope_fit_zh)} |", f"| **Review Timeline / 審稿時程** | {md_cell(j.review_timeline)} |", f"| **Open Access / 開放取用** | {md_cell(j.open_access)} |", f"| **Why This Journal / 推薦原因** | {md_cell(j.why_en)} / {md_cell(j.why_zh)} |", ""]
        if j.papers_from_collection:
            lines += ["**Papers from our collection published here / 我們文獻中發表於此刊的論文:**"] + [f"- {k} — indicates topic relevance and reviewer familiarity" for k in j.papers_from_collection] + [""]
        lines += ["---", ""]
    lines += ["## Journal Comparison / 期刊比較", "", "| Rank / 排名 | Journal / 期刊 | IF | Scope Fit / 契合度 | Review Time / 審稿時間 | OA Cost / OA費用 | Strategy / 策略 |", "|------------|--------------|-----|-------------------|---------------------|-----------------|----------------|"]
    lines += [f"| {i} | {md_cell(j.name)} | {md_cell(j.impact_factor)} | {md_cell(j.scope_fit_en[:40])} | {md_cell(j.review_timeline)} | {md_cell(j.open_access)} | {'⭐ ' if i == 1 else ''}{md_cell(j.strategy_en)} / {md_cell(j.strategy_zh)} |" for i, j in enumerate(out.journals, 1)]
    lines += ["", "---", "", "## Submission Strategy / 投稿策略", "", out.submission_strategy_en, "", out.submission_strategy_zh, "", "---", "", "Files / 檔案: `step8_journal_recommendations.md`", "Next step / 下一步: `/research-write`"]
    return "\n".join(lines)
