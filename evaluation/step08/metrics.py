"""ResearchAgent-derived 10 Problem/Method rubric metrics + field extractors + Likert anchors.

The judge sees only the excerpt for the metric under review. Anchors differ by
``field_type`` (biomedical vs cs_engineering). ``other`` falls back to biomedical.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Literal

Category = Literal["Problem", "Method"]
FieldType = Literal["biomedical", "cs_engineering", "other"]

Extractor = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class MetricDef:
    id: str  # e.g. problem.clarity
    category: Category
    name: str  # Clarity / Relevance / …
    definition: str
    primary_fields: tuple[str, ...]
    extract: Extractor


def _pick(spec: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: spec[k] for k in keys if k in spec}


def _rq(spec: dict[str, Any]) -> dict[str, Any]:
    return _pick(spec, "research_questions", "gap_summary_en", "gap_summary_zh")


def _gap_sig(spec: dict[str, Any]) -> dict[str, Any]:
    return _pick(
        spec,
        "executive_summary_en",
        "executive_summary_zh",
        "gap_summary_en",
        "gap_summary_zh",
        "gap_selection_rationale_en",
        "gap_selection_rationale_zh",
    )


def _method_core(spec: dict[str, Any]) -> dict[str, Any]:
    return _pick(
        spec,
        "hypotheses",
        "research_questions",
        "conceptual_framework_en",
        "conceptual_framework_zh",
    )


def _method_scope(spec: dict[str, Any]) -> dict[str, Any]:
    return _pick(
        spec,
        "scope_in",
        "scope_out",
        "scope_rationale_en",
        "scope_rationale_zh",
        "hypotheses",
        "conceptual_framework_en",
    )



METRICS: tuple[MetricDef, ...] = (
    MetricDef(
        "problem.clarity",
        "Problem",
        "Clarity",
        "Problem definition is clear, precise, and easy to understand.",
        ("research_questions", "gap_summary_en"),
        _rq,
    ),
    MetricDef(
        "problem.relevance",
        "Problem",
        "Relevance",
        "The problem is relevant and applicable to the current field / PICO.",
        ("research_questions",),
        lambda s: _pick(s, "research_questions", "gap_summary_en", "executive_summary_en"),
    ),
    MetricDef(
        "problem.originality",
        "Problem",
        "Originality",
        "Raises a new challenge or viewpoint that has not been deeply explored.",
        ("gap_summary_en",),
        lambda s: _pick(s, "gap_summary_en", "gap_summary_zh", "gap_selection_rationale_en", "research_questions"),
    ),
    MetricDef(
        "problem.feasibility",
        "Problem",
        "Feasibility",
        "The problem can be investigated or solved under realistic resource constraints.",
        ("research_questions", "risks"),
        lambda s: _pick(s, "research_questions", "risks", "scope_in", "gap_summary_en"),
    ),
    MetricDef(
        "problem.significance",
        "Problem",
        "Significance",
        "Potential impact on the field if the problem is addressed.",
        ("executive_summary_en", "gap_summary_en"),
        _gap_sig,
    ),
    MetricDef(
        "method.clarity",
        "Method",
        "Clarity",
        "Method description is sufficient for others to understand and reproduce the approach.",
        ("hypotheses", "conceptual_framework_en"),
        _method_core,
    ),
    MetricDef(
        "method.validity",
        "Method",
        "Validity",
        "The method addresses and can solve the stated research questions.",
        ("hypotheses", "research_questions"),
        _method_core,
    ),
    MetricDef(
        "method.rigorousness",
        "Method",
        "Rigorousness",
        "Method is systematic, structurally complete, and precise (H0/H1, direction/magnitude).",
        ("hypotheses",),
        lambda s: _pick(s, "hypotheses", "conceptual_framework_en", "traceability"),
    ),
    MetricDef(
        "method.innovativeness",
        "Method",
        "Innovativeness",
        "Introduces techniques or viewpoints that break from convention.",
        ("conceptual_framework_en",),
        lambda s: _pick(s, "conceptual_framework_en", "conceptual_framework_zh", "hypotheses", "gap_summary_en"),
    ),
    MetricDef(
        "method.generalizability",
        "Method",
        "Generalizability",
        "Approach can transfer to other settings, populations, or datasets.",
        ("scope_in", "scope_out"),
        _method_scope,
    ),
)


def metric_by_id(metric_id: str) -> MetricDef:
    for m in METRICS:
        if m.id == metric_id:
            return m
    raise KeyError(f"unknown metric id {metric_id!r}; choose from {[m.id for m in METRICS]}")


# --------------------------------------------------------------------------- #
# Likert anchors (hand-written). Avoid 4–5 without concrete field evidence.
# --------------------------------------------------------------------------- #
_SHARED_FOOTER = (
    "Do NOT default to 4–5. Score 4 only with concrete evidence in the listed fields; "
    "score 5 only when the criterion is fully met with specific, checkable detail. "
    "Vague filler, missing fields, or generic claims → at most 3."
)

_BIO: dict[str, str] = {
    "problem.clarity": (
        "1 Vague or contradictory RQs / gap summary; reader cannot restate the problem.\n"
        "2 Problem sketched but imprecise (who / what / when unclear).\n"
        "3 Understandable problem with minor ambiguity in population, outcome, or timeframe.\n"
        "4 Precise RQs and gap summary; PICO elements named.\n"
        "5 Crystal-clear problem a clinician or trialist could quote; every RQ is unambiguous.\n"
        + _SHARED_FOOTER
    ),
    "problem.relevance": (
        "1 Off-field or ignores the session PICO.\n"
        "2 Same broad disease/domain only; intervention or outcome mismatched.\n"
        "3 Partially aligned with PICO; one major component soft.\n"
        "4 Directly addresses current clinical/biomedical need stated in PICO/SOTA.\n"
        "5 Tight fit to PICO and current practice gap; clearly applicable now.\n"
        + _SHARED_FOOTER
    ),
    "problem.originality": (
        "1 Restates a settled question already answered by shortlist papers.\n"
        "2 Minor rephrasing of well-studied questions.\n"
        "3 Incremental angle (e.g. new subgroup) with limited novelty claim.\n"
        "4 Clear underexplored challenge grounded in the locked gap.\n"
        "5 Genuinely new clinical/methodological challenge with explicit contrast to SOTA.\n"
        + _SHARED_FOOTER
    ),
    "problem.feasibility": (
        "1 Requires infeasible samples, devices, or ethics for a typical lab.\n"
        "2 Severely constrained; risks ignore hard blockers.\n"
        "3 Borderline feasible as a pilot; constraints acknowledged loosely.\n"
        "4 Feasible under stated risks/scope with realistic mitigation.\n"
        "5 Clearly doable with named resources, timeline, and mitigated risks.\n"
        + _SHARED_FOOTER
    ),
    "problem.significance": (
        "1 Cosmetic or redundant if solved.\n"
        "2 Narrow local interest only.\n"
        "3 Meaningful for a niche population or setting.\n"
        "4 Clear field impact argued via why_it_matters / executive summary.\n"
        "5 High-stakes clinical or scientific impact with concrete beneficiaries.\n"
        + _SHARED_FOOTER
    ),
    "method.clarity": (
        "1 Hypotheses / framework unreadable or missing.\n"
        "2 Method named but not explainable to a peer.\n"
        "3 Peer can follow the idea; key steps underspecified.\n"
        "4 Hypotheses + conceptual framework suffice to explain the approach.\n"
        "5 Another lab could outline the protocol from the text alone.\n"
        + _SHARED_FOOTER
    ),
    "method.validity": (
        "1 Method does not address the RQs.\n"
        "2 Loose thematic link only.\n"
        "3 Addresses some RQs; primary RQ weakly covered.\n"
        "4 H1/H0 map cleanly onto RQs.\n"
        "5 Every RQ has a matching, testable hypothesis path.\n"
        + _SHARED_FOOTER
    ),
    "method.rigorousness": (
        "1 Missing H0/H1 or direction; informal wishes only.\n"
        "2 Partial H0/H1 without magnitude or test logic.\n"
        "3 Formal H0/H1 present; magnitude or structure thin.\n"
        "4 Complete H0/H1, direction/magnitude with evidence hook, coherent structure.\n"
        "5 Fully systematic: quantified where evidence allows, traced to sources.\n"
        + _SHARED_FOOTER
    ),
    "method.innovativeness": (
        "1 Standard off-the-shelf design with no new angle.\n"
        "2 Cosmetics-only novelty.\n"
        "3 Modest methodological twist.\n"
        "4 Clear unconventional technique or framing in the conceptual framework.\n"
        "5 Breakthrough-level approach relative to the SOTA shortlist.\n"
        + _SHARED_FOOTER
    ),
    "method.generalizability": (
        "1 Locked to one ungeneralizable quirk; OUT scope empty of transfer logic.\n"
        "2 Narrow IN scope without rationale for boundaries.\n"
        "3 Some transfer plausible; boundaries fuzzy.\n"
        "4 IN/OUT clarify what transfers and what does not.\n"
        "5 Explicit path to other populations/settings/datasets.\n"
        + _SHARED_FOOTER
    ),
}

_CS: dict[str, str] = {
    "problem.clarity": (
        "1 Task/problem statement unusable; no clear input–output.\n"
        "2 Topic named; task boundary fuzzy.\n"
        "3 Understandable ML/systems problem with minor underspecification.\n"
        "4 Precise problem: data, task, metric named in RQs/gap.\n"
        "5 Unambiguous research problem a peer could implement against.\n"
        + _SHARED_FOOTER
    ),
    "problem.relevance": (
        "1 Irrelevant to stated CS/engineering PICO.\n"
        "2 Same broad area only (e.g. 'NLP' without the task).\n"
        "3 Partial match to intervention/outcome.\n"
        "4 Directly attacks the stated systems/ML need vs SOTA.\n"
        "5 Tightly aligned with current bottleneck in the shortlist benchmarks.\n"
        + _SHARED_FOOTER
    ),
    "problem.originality": (
        "1 Rehashes a saturated leaderboard question.\n"
        "2 Tiny variant of a well-known task.\n"
        "3 Incremental setting or dataset shift.\n"
        "4 Clear underexplored challenge relative to locked gap.\n"
        "5 New problem framing or capability gap not covered by related work.\n"
        + _SHARED_FOOTER
    ),
    "problem.feasibility": (
        "1 Needs unrealistic compute, data rights, or hardware.\n"
        "2 Severe resource mismatch; risks ignore it.\n"
        "3 Feasible as a small-scale prototype.\n"
        "4 Doable with stated scope and mitigations.\n"
        "5 Clearly scoped compute/data plan with mitigated risks.\n"
        + _SHARED_FOOTER
    ),
    "problem.significance": (
        "1 No meaningful system or scientific gain.\n"
        "2 Narrow engineering curiosity.\n"
        "3 Useful for a niche benchmark community.\n"
        "4 Clear advance if solved (method, efficiency, or reliability).\n"
        "5 High-impact capability or principled advance argued explicitly.\n"
        + _SHARED_FOOTER
    ),
    "method.clarity": (
        "1 Architecture/algorithm opaque.\n"
        "2 Buzzwords without pipeline.\n"
        "3 Peer grasps the idea; training/inference steps thin.\n"
        "4 Hypotheses + framework describe the method end-to-end.\n"
        "5 Replicable method sketch (modules, losses, baselines).\n"
        + _SHARED_FOOTER
    ),
    "method.validity": (
        "1 Method orthogonal to RQs.\n"
        "2 Thematic link only.\n"
        "3 Covers secondary RQs better than the primary.\n"
        "4 Method is a valid attack on the RQs.\n"
        "5 Each RQ maps to a concrete methodological claim.\n"
        + _SHARED_FOOTER
    ),
    "method.rigorousness": (
        "1 No baselines, ablations, or formal claims.\n"
        "2 Informal claims without H0/H1 structure.\n"
        "3 H0/H1 present; comparison logic incomplete.\n"
        "4 Rigorous claims with direction/magnitude and comparison structure.\n"
        "5 Complete: baselines/ablations implied, claims precise and sourced.\n"
        + _SHARED_FOOTER
    ),
    "method.innovativeness": (
        "1 Off-the-shelf model with default training.\n"
        "2 Cosmetic novelty (hyperparameters only).\n"
        "3 Modest architectural or training twist.\n"
        "4 Clear non-obvious technical idea in the framework.\n"
        "5 Strongly novel method relative to cited SOTA.\n"
        + _SHARED_FOOTER
    ),
    "method.generalizability": (
        "1 One dataset/model with no transfer story.\n"
        "2 Overfit scope; OUT empty.\n"
        "3 Limited transfer hinted.\n"
        "4 IN/OUT define transferable vs instance-specific pieces.\n"
        "5 Explicit multi-domain / multi-benchmark transfer path.\n"
        + _SHARED_FOOTER
    ),
}


def anchors_for(metric_id: str, field_type: str) -> str:
    table = _CS if field_type == "cs_engineering" else _BIO
    if metric_id not in table:
        raise KeyError(metric_id)
    return table[metric_id]


def excerpt_json(metric: MetricDef, spec: dict[str, Any]) -> str:
    return json.dumps(metric.extract(spec), ensure_ascii=False, indent=2)
