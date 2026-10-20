"""Step 3 ranking metrics on top of a Mode A/B Step 2 set."""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Sequence

from .metrics import (
    TABLE7,
    expected_mrr,
    expected_ndcg_at_k,
    expected_recall_at_k,
    mean,
    mrr,
    ndcg_at_k,
    recall_at_k,
)


def sort_ids(papers: Sequence[dict[str, Any]], *, by: str) -> tuple[list[str], list[float]]:
    """Return (ids in rank order, primary scores aligned with that order).

    Deterministic tie-break: paper.id ascending.
    composite: (-composite, id)
    relevance: (-relevance, -composite, id)
    """

    def rec(p: dict[str, Any]) -> dict[str, Any]:
        return p.get("screening") or {}

    decorated: list[tuple[tuple, str, float]] = []
    for p in papers:
        sc = rec(p)
        pid = str(p.get("id") or "")
        rel = int(sc.get("relevance") or 0)
        comp = float(sc.get("composite") or 0.0)
        if by == "relevance":
            key: tuple = (-rel, -comp, pid)
            primary = float(rel)
        else:
            key = (-comp, pid)
            primary = comp
        decorated.append((key, pid, primary))
    decorated.sort()
    return [d[1] for d in decorated], [d[2] for d in decorated]


def _rank_of(pid: str | None, ranked: Sequence[str]) -> int | None:
    if not pid:
        return None
    try:
        return list(ranked).index(pid) + 1
    except ValueError:
        return None


def _lost_at_rank(rank: int | None, *, found: bool, prior: str | None) -> str | None:
    if not found:
        return prior
    if rank is None:
        return prior or "not_in_step2_set"
    if rank <= 5:
        return None  # found_at_k — keep null like Step 2 hits
    if rank <= 20:
        return "rank_gt_5"
    return "rank_gt_20"


def metrics_for(gold_paper_ids: Iterable[str], ranked: Sequence[str], scores: Sequence[float]) -> dict[str, float]:
    g = [x for x in gold_paper_ids if x]
    return {
        "R@5": recall_at_k(g, ranked, 5),
        "R@20": recall_at_k(g, ranked, 20),
        "MRR": mrr(g, ranked),
        "nDCG@10": ndcg_at_k(g, ranked, 10),
        "R@5_expected": expected_recall_at_k(g, ranked, scores, 5),
        "R@20_expected": expected_recall_at_k(g, ranked, scores, 20),
        "MRR_expected": expected_mrr(g, ranked, scores),
        "nDCG@10_expected": expected_ndcg_at_k(g, ranked, scores, 10),
    }


def zeros() -> dict[str, float]:
    return {k: 0.0 for k in ("R@5", "R@20", "MRR", "nDCG@10", "R@5_expected", "R@20_expected", "MRR_expected", "nDCG@10_expected")}


def score_ranking(
    question: dict[str, Any],
    step2_papers: list[dict[str, Any]],
    id_map: dict[str, Any],
    y0: int,
    y1: int,
    screened: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Set recall from Step 2 papers; R@k from Step 3 scores when present."""
    from .runner import score_question

    row = score_question(question, step2_papers, id_map, y0, y1)
    gold_paper_ids: list[str] = []
    for g in row["gold"]:
        pid = g.get("paper_id")
        if g.get("found") and pid:
            gold_paper_ids.append(str(pid))
        else:
            gold_paper_ids.append(f"__unretrieved_gold__:{g['corpusId']}")

    empty = zeros()
    row["relevance"] = dict(empty)
    row["composite"] = dict(empty)
    row["n_screened"] = len(screened or [])
    row["step3"] = bool(screened)

    if not screened or not gold_paper_ids:
        for g in row["gold"]:
            g["rank_relevance"] = None
            g["rank_composite"] = None
            g["step3_category"] = None
        return row

    rel_ids, rel_scores = sort_ids(screened, by="relevance")
    comp_ids, comp_scores = sort_ids(screened, by="composite")
    by_id = {str(p.get("id")): p for p in screened}

    row["relevance"] = metrics_for(gold_paper_ids, rel_ids, rel_scores)
    row["composite"] = metrics_for(gold_paper_ids, comp_ids, comp_scores)

    for g in row["gold"]:
        pid = str(g["paper_id"]) if g.get("paper_id") else None
        rr = _rank_of(pid, rel_ids)
        rc = _rank_of(pid, comp_ids)
        g["rank_relevance"] = rr
        g["rank_composite"] = rc
        g["step3_category"] = ((by_id.get(pid) or {}).get("screening") or {}).get("category") if pid else None
        g["lost_at"] = _lost_at_rank(rr, found=bool(g.get("found")), prior=g.get("lost_at"))
    return row


def rank_from_step2_miss(step2_row: dict[str, Any]) -> dict[str, Any]:
    """Copy a Step 2 miss/skip into a rank row without running Step 3."""
    row = dict(step2_row)
    empty = zeros()
    row["relevance"] = dict(empty)
    row["composite"] = dict(empty)
    row["n_screened"] = 0
    row["step3"] = False
    row["gold"] = [dict(g, rank_relevance=None, rank_composite=None, step3_category=None) for g in (step2_row.get("gold") or [])]
    return row


def summarise_rank(rows: list[dict[str, Any]], *, mode: str = "A3") -> dict[str, Any]:
    def pack(xs: list[dict[str, Any]]) -> dict[str, Any]:
        def col(kind: str, key: str) -> float:
            return round(mean([float((r.get(kind) or {}).get(key) or 0.0) for r in xs]), 3)

        return {
            "n": len(xs),
            "set_recall": round(mean([float(r.get("set_recall") or 0.0) for r in xs]), 3),
            "mean_set_size": round(mean([float(r.get("set_size") or 0.0) for r in xs]), 1),
            "relevance": {k: col("relevance", k) for k in ("R@5", "R@20", "MRR", "nDCG@10", "R@5_expected", "R@20_expected", "MRR_expected", "nDCG@10_expected")},
            "composite": {k: col("composite", k) for k in ("R@5", "R@20", "MRR", "nDCG@10", "R@5_expected", "R@20_expected", "MRR_expected", "nDCG@10_expected")},
        }

    hits = [r for r in rows if (r.get("set_recall") or 0) > 0]
    lost = Counter()
    for r in rows:
        for g in r.get("gold") or []:
            lost[g.get("lost_at") or "found_at_k"] += 1
    return {
        "n_questions": len(rows),
        "overall": pack(rows),
        "hit_only": pack(hits),
        "by_split": {k: pack([r for r in rows if r.get("split") == k]) for k in ("inline", "author")},
        "by_quality": {str(k): pack([r for r in rows if r.get("quality") == k]) for k in (1, 2)},
        "funnel": dict(lost),
        "table7_commercial_R@5": TABLE7,
        "mode": mode,
        "note": (
            "A3 = Mode A Step 2 set + Step 3 ranks. Headline R@k uses the 80-question denominator "
            "(misses are 0). hit_only is ranking quality given gold already in S. "
            "Main funnel ranks are relevance-only; composite is a contrast. "
            "Deterministic tie-break is paper.id; *_expected is uniform random inside equal primary scores."
        ),
    }
