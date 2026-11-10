from __future__ import annotations

import math


def recall_at_k(gold, ranked, k: int) -> float:
    wanted = {str(x) for x in gold}
    return len(wanted & {str(x) for x in ranked[:k]}) / len(wanted) if wanted else 0.0


def mrr(gold, ranked) -> float:
    wanted = {str(x) for x in gold}
    return next((1.0 / i for i, value in enumerate(ranked, 1) if str(value) in wanted), 0.0)


def ndcg_at_k(gold, ranked, k: int) -> float:
    wanted = {str(x) for x in gold}
    dcg = sum(1.0 / math.log2(i + 1) for i, value in enumerate(ranked[:k], 1) if str(value) in wanted)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(wanted), k) + 1))
    return dcg / ideal if ideal else 0.0


def ranking_metrics(gold, ranked) -> dict:
    return {"R@5": recall_at_k(gold, ranked, 5), "R@20": recall_at_k(gold, ranked, 20),
            "R@100": recall_at_k(gold, ranked, 100), "MRR": mrr(gold, ranked),
            "nDCG@10": ndcg_at_k(gold, ranked, 10)}
