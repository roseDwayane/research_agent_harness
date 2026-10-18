"""Prompts for metasyn_eval.py.

OFFICIAL_* are copied verbatim from MetaSyn (https://github.com/THUIR/MetaSyn,
src/metasyn/llm_client.py, MIT License, Copyright (c) THUIR) so the official direction and
holistic insight scores can be reported next to ours. The other prompts are ours.
"""
from __future__ import annotations

# --------------------------------------------------------------------------- #
# MetaSyn, verbatim
# --------------------------------------------------------------------------- #
OFFICIAL_EXTRACT_PROMPT = """Background: This is a systematic review/meta-analysis report. Extract the main conclusion direction and key insights.

Requirements:
1. Conclusion direction must be exactly one of: "Positive", "Negative", or "Mixed"
   - "Positive": The report gives a positive or affirmative answer relative to the review question
   - "Negative": The report gives a negative or opposite answer relative to the review question
   - "Mixed": The report is null, inconclusive, conflicting, heterogeneous, descriptive, or gives no single direction
2. Key insights must be EXACT word-for-word quotes from the report - do NOT paraphrase
3. Each insight should be a complete sentence or phrase as written in the report
4. Look for sections titled "Conclusion", "Discussion", "Key Findings", "Results", "Summary"
5. If insights are found, return them as a list of strings
6. If no insights are found, return an empty list []
7. Return ONLY valid JSON - no markdown, no explanations

JSON Format:
{{
    "conclusion_direction": "Positive",
    "key_insights": ["exact quote 1", "exact quote 2", ...]
}}

Example output:
{{
    "conclusion_direction": "Positive",
    "key_insights": ["The intervention significantly improved outcomes compared to control", "Subgroup analysis showed consistent benefits across populations"]
}}

Report text:
---
{report_text}
---

Extract conclusion and insights now:
"""

OFFICIAL_INSIGHTS_PROMPT = """Task: Evaluate how well the extracted key insights from a systematic review/meta-analysis report match the ground truth key insights.

Score the coverage on a scale of 0.0 to 1.0.

Scoring Guidelines:
- 1.0 = Perfect coverage: All ground truth insights are covered by extracted insights
- 0.8 = Good coverage: Most ground truth insights (75%+) are covered
- 0.6 = Fair coverage: Some ground truth insights (50-74%) are covered
- 0.4 = Poor coverage: Few ground truth insights (25-49%) are covered
- 0.2 = Very poor coverage: Very few ground truth insights (<25%) are covered
- 0.0 = No coverage: Extracted insights are completely different, irrelevant, or empty

Consider semantic similarity, not just exact word matching. An extracted insight "covers" a ground truth insight if they convey the same finding or conclusion.

Ground Truth Insights:
---
{gt_text}
---

Extracted Insights:
---
{extracted_text}
---

JSON Format:
{{
    "consistency_score": 0.8,
    "reason": "One sentence explaining the score based on coverage"
}}

Evaluate now:
"""

# --------------------------------------------------------------------------- #
# ours
# --------------------------------------------------------------------------- #
CLASSIFY_PROMPT = """You are preparing a reference answer for evaluating literature reviews.

A published meta-analysis answered this review question:
{question}

Below is ONE key insight from that meta-analysis. The review being evaluated is a narrative synthesis written from the same individual studies: it can describe each study's results, compare studies, and draw qualitative conclusions, but it does NOT pool data, so it cannot produce pooled estimates or meta-analytic statistics.

Classify the insight into exactly one category:
- "synthesis": a finding, comparison, conclusion or limitation that a careful narrative synthesis of the individual studies could state. This holds even when the insight quotes pooled numbers, as long as it also carries a qualitative claim (a direction, a comparison, a judgement).
- "pooled_estimate": it only reports a pooled or aggregate number (a rate, effect size, prevalence, confidence interval) and says nothing beyond that number's value.
- "meta_analysis_specific": it is about the meta-analysis's own procedures or statistics: heterogeneity, moderator, subgroup or sensitivity analyses, outlier detection, publication bias, prediction intervals.
- "external": it depends on evidence outside the included studies, such as comparisons with other treatments' literature or with guidelines.
- "generic": a limitation of the evidence or a call for more research phrased so that it would be true of most clinical research fields (high risk of bias, small samples, short follow-up, need for larger or better RCTs), without naming anything specific to this question.

For "synthesis", also restate the insight as a claim WITHOUT the pooled numbers, keeping its direction and comparison. For the other categories, set "claim" to "".

Insight:
{insight}

Return ONLY valid JSON:
{{"category": "synthesis", "claim": "...", "reason": "one sentence"}}
"""

COVERAGE_PROMPT = """You are checking whether a literature review states a specific finding.

Review question of the expert meta-analysis:
{question}

Finding (from that meta-analysis):
{claim}

Only statements about the same intervention or exposure, population and outcomes as this question count. A statement about a different topic is "not_covered", however similar its wording.

The finding may quote pooled numbers that only the meta-analysis computed; the review cannot have those. Ignore the numbers and judge the finding's direction, comparison and strength of judgement.

Decide how the review below treats this finding:
- "covered": the review states this finding as one of its own overall findings or conclusions, with the same direction and a similar strength of judgement.
- "partial": the review states only part of it, states it in a clearly weaker or hedged form, or mentions it only as one side of a debate while its own conclusion leans elsewhere.
- "contradicted": the review's own overall finding or conclusion states the opposite.
- "not_covered": the review does not address it.

A single study's result (for example one row of a results table) does not count as the review stating an overall finding; it is at most "partial". Judge meaning, not wording.

Statistical uncertainty in the finding:
- If the finding is non-significant, only a trend, of low or very low certainty, or borderline (p close to 0.05, a confidence interval touching or crossing no effect), then a review saying "no clear difference", "comparable", "inconsistent" or "not consistently" is compatible with it: use "covered" or "partial", never "contradicted".
- If the finding allows several outcomes ("no difference or a reduction"), a review stating any one of them is compatible with it.
- Use "contradicted" only when the review asserts, as its own conclusion, a direction the finding rules out: the opposite direction of a clear effect, a clear effect where the finding reports no effect or no evidence, or no difference where the finding reports a clear, certain difference.

Quote the sentence of the review that decided your verdict, copied exactly from the review (never from the finding); use "" for "not_covered".

Review:
---
{text}
---

Return ONLY valid JSON:
{{"verdict": "covered", "quote": "...", "reason": "one sentence"}}
"""

DIGEST_PROMPT = """You are checking whether the evidence for a finding is present in per-paper notes.

Finding (from a published expert meta-analysis):
{claim}

The finding may quote pooled numbers that only the meta-analysis computed; ignore them and look for evidence of its direction and comparison.

Below are notes on each paper that a literature review was given. Decide whether these notes contain evidence that would let a careful reader state the finding (its direction and comparison, not its exact pooled numbers):
- "supported": the notes contain enough evidence to state the finding.
- "partial": the notes contain some relevant evidence, but not enough to state the finding on their own.
- "not_supported": the notes contain no relevant evidence.

List the citation keys of the papers whose notes provide the evidence.

Notes:
---
{text}
---

Return ONLY valid JSON:
{{"verdict": "supported", "keys": ["Key2020"], "reason": "one sentence"}}
"""
