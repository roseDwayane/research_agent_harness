import math

import pytest

from evaluation.step02.rescore import evaluate, summarise


def test_partial_multi_gold_keeps_original_denominator_and_excluded_rank():
    question = {"qid": "q", "corpusids": [1, 2, 3]}
    mapping = {"1": {"ok": True, "doi": "10.1/a"}, "2": {"ok": True, "doi": "10.1/b"}}
    papers = [{"id": "p1", "doi": "10.1/a", "found_via": "Q1"}]
    screened = [{**papers[0], "screening": {"relevance": 5, "composite": 2.5, "category": "excluded"}}]
    row = evaluate(question, mapping, {"papers": papers}, {}, screened, [], {},
                   step2_complete=True, step3_complete=True)
    assert row["set_recall"] == pytest.approx(1/3)
    assert row["mapped_only_recall"] == 0.5
    assert row["relevance"]["R@5"] == pytest.approx(1/3)
    assert row["relevance"]["MRR"] == 1
    assert row["relevance"]["nDCG@10"] == pytest.approx(1 / sum(1/math.log2(i+1) for i in range(1,4)))
    assert row["metrics"]["shortlist_recall"]["numerator"] == 0
    assert row["gold_categories"]["excluded"] == 1
    assert row["n_unmapped"] == 1


def test_snowball_gain_and_failed_questions_remain_in_summary():
    q = {"qid": "q", "corpusids": [1]}
    mapping = {"1": {"ok": True, "doi": "10.1/a"}}
    papers = [{"id": "p1", "doi": "10.1/a", "found_via": "snowball"}]
    row = evaluate(q, mapping, {"papers": papers}, {}, None, None, {},
                   step2_complete=True, step3_complete=False)
    failed = evaluate({**q, "qid": "failed"}, mapping, None, {}, None, None, {},
                      step2_complete=False, step3_complete=False)
    assert row["metrics"]["snowball_gain"]["numerator"] == 1
    assert row["metrics"]["gold_retention"]["value"] == 0
    summary = summarise([row, failed])
    assert summary["completion"]["step2"] == {"numerator": 1, "denominator": 2, "value": .5}
    assert summary["metrics"]["final_set_recall"]["macro"]["value"] == .5
    assert summary["overall"]["relevance"]["R@5"] == 0
    assert failed["direct_set_size"] == 0
    assert summary["metrics"]["direct_search_recall"]["macro"]["denominator"] == 2


def test_expected_multi_gold_matches_all_tie_permutations():
    from itertools import permutations
    from evaluation.step02.metrics import expected_mrr, expected_ndcg_at_k, mrr, ndcg_at_k
    ids = ["a", "b", "c"]
    gold = ["a", "b", "missing"]
    orders = list(permutations(ids))
    assert expected_mrr(gold, ids, [5,5,5]) == pytest.approx(sum(mrr(gold,p) for p in orders)/len(orders))
    assert expected_ndcg_at_k(gold, ids, [5,5,5], 2) == pytest.approx(sum(ndcg_at_k(gold,p,2) for p in orders)/len(orders))
