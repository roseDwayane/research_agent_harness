"""LitSearch metrics.

Step 2 is a set — only set recall + |S|.
Step 3 produces a ranked list — R@k / MRR / binary nDCG@k.
Integer scores tie; deterministic ranks use a secondary key, expected ranks
assume a uniform random permutation inside each equal-score group.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence


TABLE7 = {
    "Google Search": {"inline": 23.1, "author": 62.5},
    "Google Scholar": {"inline": 20.5, "author": 17.5},
    "Elicit": {"inline": 23.1, "author": 17.5},
}


def set_recall(gold: Iterable[str], retrieved: Iterable[str]) -> float:
    g = {x for x in gold if x}
    if not g:
        return 0.0
    return len(g & set(retrieved)) / len(g)


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def recall_at_k(gold_ids: Iterable[str], ranked_ids: Sequence[str], k: int) -> float:
    g = {x for x in gold_ids if x}
    if not g:
        return 0.0
    return len(g & set(ranked_ids[:k])) / len(g)


def mrr(gold_ids: Iterable[str], ranked_ids: Sequence[str]) -> float:
    """1 / rank of the first gold paper. 0 if none retrieved."""
    g = {x for x in gold_ids if x}
    if not g:
        return 0.0
    for i, pid in enumerate(ranked_ids, 1):
        if pid in g:
            return 1.0 / i
    return 0.0


def ndcg_at_k(gold_ids: Iterable[str], ranked_ids: Sequence[str], k: int = 10) -> float:
    """Binary nDCG@k (relevant=1). LitSearch gold is typically one paper."""
    g = {x for x in gold_ids if x}
    if not g:
        return 0.0
    dcg = 0.0
    for i, pid in enumerate(ranked_ids[:k], 1):
        if pid in g:
            dcg += 1.0 / math.log2(i + 1)
    n_ideal = min(k, len(g))
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, n_ideal + 1))
    return dcg / idcg if idcg else 0.0


def _tie_span(ranked_ids: Sequence[str], scores: Sequence[float], index: int) -> tuple[int, int]:
    """1-indexed [lo, hi] of the equal-score group containing ranked_ids[index]."""
    score = scores[index]
    start = index
    while start > 0 and scores[start - 1] == score:
        start -= 1
    end = index
    while end + 1 < len(ranked_ids) and scores[end + 1] == score:
        end += 1
    return start + 1, end + 1


def expected_recall_at_k(gold_ids: Iterable[str], ranked_ids: Sequence[str], scores: Sequence[float], k: int) -> float:
    """E[R@k] if ties of equal primary score are broken uniformly at random.

    Linearity: each gold has P(rank <= k) = slots_of_its_group_in_top_k / group_size.
    Exact for any number of golds.
    """
    g = [x for x in gold_ids if x]
    if not g:
        return 0.0
    id_to_i = {pid: i for i, pid in enumerate(ranked_ids)}
    hits = 0.0
    for pid in g:
        i = id_to_i.get(pid)
        if i is None:
            continue
        lo, hi = _tie_span(ranked_ids, scores, i)
        size = hi - lo + 1
        if lo > k:
            p = 0.0
        elif hi <= k:
            p = 1.0
        else:
            p = (k - lo + 1) / size
        hits += p
    return hits / len(g)


def expected_mrr(gold_ids: Iterable[str], ranked_ids: Sequence[str], scores: Sequence[float]) -> float:
    """Exact reciprocal rank of the first gold under uniform primary-score ties."""
    g = set(gold_ids)
    first = next((i for i, pid in enumerate(ranked_ids) if pid in g), None)
    if first is None:
        return 0.0
    lo, hi = _tie_span(ranked_ids, scores, first)
    size = hi-lo+1
    hits = sum(pid in g for pid in ranked_ids[lo-1:hi])
    probability = hits / size
    value = 0.0
    for offset in range(1, size-hits+2):
        value += probability / (lo+offset-1)
        if offset < size-hits+1:
            probability *= (size-offset-hits+1) / (size-offset)
    return value


def expected_ndcg_at_k(gold_ids: Iterable[str], ranked_ids: Sequence[str], scores: Sequence[float], k: int = 10) -> float:
    """Exact expected binary nDCG, including unretrieved original gold in IDCG."""
    g = list(set(x for x in gold_ids if x))
    if not g:
        return 0.0
    idcg = sum(1 / math.log2(i+1) for i in range(1, min(k, len(g))+1))
    id_to_i = {pid: i for i, pid in enumerate(ranked_ids)}
    vals: list[float] = []
    for pid in g:
        i = id_to_i.get(pid)
        if i is None:
            vals.append(0.0)
            continue
        lo, hi = _tie_span(ranked_ids, scores, i)
        acc = 0.0
        for r in range(lo, hi + 1):
            if r <= k:
                acc += (1.0 / math.log2(r + 1)) / idcg
        vals.append(acc / (hi - lo + 1))
    return sum(vals)
