"""LitSearch Mode A eval: metrics, matching, subset freeze, offline Step 2 / A3."""
from __future__ import annotations

from pathlib import Path

import pytest

from evaluation.step02.data import stratified_table7
from evaluation.step02.fixtures import mode_a_config, timeframe_for
from evaluation.step02.ids import build_gold_id_map
from evaluation.step02.match import match_gold
from evaluation.step02.metrics import set_recall
from evaluation.step02.runner import eval_config, run_mode_a, run_mode_b, score_question, session_id_for
from evaluation.step03.runner import run_mode_a3
from tests.fakes import FakeHttpx, PAPERS


def test_set_recall():
    assert set_recall(["a", "b"], ["a", "c"]) == 0.5
    assert set_recall(["a"], []) == 0.0
    assert set_recall([], ["a"]) == 0.0


def test_match_gold_doi_s2_title():
    papers = [
        {"id": "paper_001", "doi": "10.1000/A", "semantic_scholar_id": "s2A", "arxiv_id": None, "title": PAPERS["A"]["title"]},
        {"id": "paper_002", "doi": None, "semantic_scholar_id": "s2Z", "arxiv_id": "99.9", "title": "unrelated work on widgets"},
    ]
    p, m = match_gold({"doi": "10.1000/a", "paperId": "nope", "title": "x"}, papers)
    assert p["id"] == "paper_001" and m == "doi"
    p, m = match_gold({"doi": None, "paperId": "s2A", "title": "x"}, papers)
    assert p["id"] == "paper_001" and m == "s2"
    p, m = match_gold({"doi": None, "paperId": None, "title": PAPERS["A"]["title"]}, papers)
    assert p["id"] == "paper_001" and m == "title"
    p, m = match_gold({"doi": None, "paperId": None, "title": "zzzz not a paper"}, papers)
    assert p is None and m is None


def test_lost_at_from_trace_first_gate():
    from evaluation.step02.match import lost_at_from_trace

    assert lost_at_from_trace(None) == "not_in_step2_set"
    assert lost_at_from_trace({"provider_raw": {}, "year_filtered_raw": False, "after_dedup": False}) == "provider_miss"
    assert lost_at_from_trace({"provider_raw": {"openalex": True}, "year_filtered_raw": True, "after_dedup": False}) == "year_filter"
    assert lost_at_from_trace({"provider_raw": {"semantic_scholar": True}, "year_filtered_raw": False, "after_dedup": False}) == "dedup_merge"
    assert lost_at_from_trace({"provider_raw": {}, "snowball_drop_reason": "overlap", "after_dedup": False}) == "snowball_overlap"


def test_table7_subset_is_80_specific_40_40():
    queries = []
    for qs, n, spec in (
        ("inline_acl", 100, 1),
        ("inline_acl", 30, 0),
        ("manual_acl", 80, 1),
        ("manual_iclr", 40, 1),
        ("manual_acl", 10, 0),
    ):
        for i in range(n):
            queries.append(
                {
                    "query_set": qs,
                    "query": f"{qs} q{i:03d} about transformers",
                    "specificity": spec,
                    "quality": 1 if i % 3 else 2,
                    "corpusids": [1000 + i],
                }
            )
    rows = stratified_table7(queries, seed=20260924)
    assert len(rows) == 80
    assert all(r["specificity"] == 1 for r in rows)
    assert sum(r["split"] == "inline" for r in rows) == 40
    assert sum(r["split"] == "author" for r in rows) == 40
    assert len({r["qid"] for r in rows}) == 80
    assert all(r["qid"].startswith("ls_") for r in rows)
    assert {r["quality"] for r in rows} <= {1, 2}


def test_timeframe_covers_gold_year():
    assert timeframe_for([2018]) == "2013-2026"
    assert timeframe_for([]) == "1990-2026"
    sc = mode_a_config("ls_001", "Which paper proposed prefix-tuning?", [2018], "20260924001", "2026-09-24T00:00:00+08:00")
    assert sc.field_type == "cs_engineering"
    assert sc.queries[0].id == "Q1" and "prefix-tuning" in sc.queries[0].query
    assert sc.year_range()[0] <= 2018 <= sc.year_range()[1]
    assert sc.engine.llm_model == "none"
    assert session_id_for("ls_007") == "20260924007"


def test_mode_a_step2_no_llm(tmp_path: Path, monkeypatch):
    import scholar_research.providers.base as base

    monkeypatch.setattr(base.httpx, "Client", FakeHttpx)
    monkeypatch.setattr(base.time, "sleep", lambda *_: None)
    FakeHttpx.calls.clear()

    questions = [
        {
            "qid": "ls_001",
            "split": "inline",
            "query_set": "inline_acl",
            "quality": 2,
            "specificity": 1,
            "query": "EEG neurofeedback training working memory mild cognitive impairment",
            "corpusids": [1001],
        }
    ]
    cache = tmp_path / "cache"
    id_map = build_gold_id_map([1001], cache, api_key=None)
    assert id_map["1001"]["ok"] is True
    assert id_map["1001"]["paperId"] == "s2A"
    cfg = eval_config(tmp_path / "sessions")
    rows = run_mode_a(questions, id_map, tmp_path, cfg, shared_cache=cache, say=lambda *_: None)
    assert len(rows) == 1
    assert rows[0]["set_size"] >= 1
    assert rows[0]["set_recall"] == 1.0
    assert rows[0]["gold"][0]["found"] is True
    session_dirs = list((tmp_path / "sessions").iterdir())
    assert session_dirs
    assert not (session_dirs[0] / "step1_search_queries.md").exists()
    assert (session_dirs[0] / "step2_raw_papers.json").exists()
    assert cfg.search.sources == ["semantic_scholar", "openalex", "arxiv"]
    assert not any("pubmed" in u or "ncbi.nlm.nih.gov" in u for u in FakeHttpx.calls)


def test_score_year_filter_not_a_retrieval_miss():
    papers = [{"id": "paper_001", "doi": "10.9/z", "semantic_scholar_id": "no", "arxiv_id": None, "title": "other"}]
    q = {"qid": "ls_002", "split": "author", "quality": 1, "corpusids": [1]}
    id_map = {"1": {"ok": True, "corpusId": 1, "doi": "10.0/old", "paperId": "old", "title": "BERT", "year": 2018}}
    row = score_question(q, papers, id_map, y0=2019, y1=2026)
    assert row["set_recall"] == 0.0
    assert row["gold"][0]["lost_at"] == "year_filter"


def test_mode_b_step1_then_step2_uses_llm_queries(tmp_path: Path, monkeypatch):
    import scholar_research.providers.base as base
    from scholar_research.llm.client import FakeBackend
    from tests.fakes import fake_llm

    monkeypatch.setattr(base.httpx, "Client", FakeHttpx)
    monkeypatch.setattr(base.time, "sleep", lambda *_: None)
    FakeHttpx.calls.clear()

    questions = [
        {
            "qid": "ls_001",
            "split": "inline",
            "query_set": "inline_acl",
            "quality": 2,
            "specificity": 1,
            "query": "Which paper proposed prefix-tuning for transformers?",
            "corpusids": [1001],
        }
    ]
    cache = tmp_path / "cache"
    id_map = build_gold_id_map([1001], cache, api_key=None)
    cfg = eval_config(tmp_path / "sessions")
    cfg.llm.provider = "ollama"
    rows = run_mode_b(
        questions,
        id_map,
        tmp_path,
        cfg,
        shared_cache=cache,
        say=lambda *_: None,
        llm_backend=FakeBackend(fake_llm),
    )
    assert len(rows) == 1
    assert rows[0].get("error") is None
    assert len(rows[0]["queries"]) == 5
    assert rows[0]["queries"][0]["query"] == "EEG neurofeedback older adults"
    assert rows[0]["field_type"] == "cs_engineering"
    assert rows[0]["timeframe"].startswith("20")
    session_dirs = list((tmp_path / "sessions").iterdir())
    assert (session_dirs[0] / "step1_search_queries.md").exists()
    assert (session_dirs[0] / "step2_raw_papers.json").exists()
    assert not any("pubmed" in u or "ncbi.nlm.nih.gov" in u for u in FakeHttpx.calls)


def test_rank_metrics_and_tie_expectation():
    from evaluation.step02.metrics import expected_recall_at_k, mrr, ndcg_at_k, recall_at_k

    ranked = ["a", "b", "g", "d"]
    assert recall_at_k(["g"], ranked, 2) == 0.0
    assert recall_at_k(["g"], ranked, 3) == 1.0
    assert mrr(["g"], ranked) == 1 / 3
    assert ndcg_at_k(["g"], ranked, 10) > 0
    ids = ["p1", "gold", "p3", "tail"]
    scores = [5.0, 5.0, 5.0, 4.0]
    assert expected_recall_at_k(["gold"], ids, scores, 1) == pytest.approx(1 / 3)
    assert expected_recall_at_k(["gold"], ids, scores, 3) == 1.0
    assert expected_recall_at_k(["gold"], ids, scores, 5) == 1.0
    assert expected_recall_at_k(["missing"], ids, scores, 5) == 0.0


def test_score_ranking_relevance_vs_composite():
    from evaluation.step03.rank import score_ranking

    gold_title = PAPERS["A"]["title"]
    papers = [
        {"id": "paper_001", "doi": "10.1000/a", "semantic_scholar_id": "s2A", "arxiv_id": None, "title": gold_title},
        {"id": "paper_002", "doi": "10.1000/b", "semantic_scholar_id": "s2B", "arxiv_id": None, "title": PAPERS["B"]["title"]},
        {"id": "paper_003", "doi": "10.1000/c", "semantic_scholar_id": "s2C", "arxiv_id": None, "title": PAPERS["C"]["title"]},
    ]
    screened = [
        {"id": "paper_001", "screening": {"relevance": 3, "quality": 2, "recency_impact": 2, "composite": 2.5, "category": "excluded"}},
        {"id": "paper_002", "screening": {"relevance": 5, "quality": 5, "recency_impact": 5, "composite": 5.0, "category": "included"}},
        {"id": "paper_003", "screening": {"relevance": 4, "quality": 4, "recency_impact": 4, "composite": 4.0, "category": "included"}},
    ]
    q = {"qid": "ls_001", "split": "inline", "quality": 2, "corpusids": [1001]}
    id_map = {"1001": {"ok": True, "corpusId": 1001, "doi": "10.1000/a", "paperId": "s2A", "title": gold_title, "year": 2023}}
    row = score_ranking(q, papers, id_map, 2018, 2026, screened)
    assert row["set_recall"] == 1.0
    assert row["gold"][0]["paper_id"] == "paper_001"
    assert row["gold"][0]["rank_relevance"] == 3
    assert row["relevance"]["R@5"] == 1.0
    assert row["gold"][0]["lost_at"] is None  # rank 3 is inside top-5
    assert row["gold"][0]["rank_composite"] == 3
    extra = [{"id": f"paper_{i:03d}", "screening": {"relevance": 5, "quality": 5, "recency_impact": 5, "composite": 5.0, "category": "included"}} for i in range(10, 16)]
    row2 = score_ranking(q, papers, id_map, 2018, 2026, screened + extra)
    assert row2["gold"][0]["rank_relevance"] == 9
    assert row2["relevance"]["R@5"] == 0.0
    assert row2["relevance"]["R@20"] == 1.0
    assert row2["gold"][0]["lost_at"] == "rank_gt_5"


def test_mode_a3_step3_on_existing_hit(tmp_path: Path, monkeypatch):
    import scholar_research.providers.base as base
    from evaluation.step02.runner import _write_results
    from scholar_research.llm.client import FakeBackend
    from tests.fakes import fake_llm

    monkeypatch.setattr(base.httpx, "Client", FakeHttpx)
    monkeypatch.setattr(base.time, "sleep", lambda *_: None)
    FakeHttpx.calls.clear()

    questions = [
        {
            "qid": "ls_001",
            "split": "inline",
            "query_set": "inline_acl",
            "quality": 2,
            "specificity": 1,
            "query": "EEG neurofeedback training working memory mild cognitive impairment",
            "corpusids": [1001],
        },
        {
            "qid": "ls_002",
            "split": "author",
            "query_set": "manual_acl",
            "quality": 1,
            "specificity": 1,
            "query": "a question whose gold is not retrieved",
            "corpusids": [9999],
        },
    ]
    cache = tmp_path / "cache"
    id_map = build_gold_id_map([1001], cache, api_key=None)
    id_map["9999"] = {"ok": True, "corpusId": 9999, "doi": "10.9/missing", "paperId": "nope", "title": "not in collection", "year": 2020}
    cfg = eval_config(tmp_path / "sessions")
    a_rows = run_mode_a(questions[:1], id_map, tmp_path, cfg, shared_cache=cache, say=lambda *_: None)
    assert a_rows[0]["set_recall"] == 1.0
    miss = score_question(questions[1], [], id_map, 2015, 2026)
    miss["mode"] = "A"
    miss["session"] = None
    done = {a_rows[0]["qid"]: a_rows[0], "ls_002": miss}
    _write_results(tmp_path / "results.jsonl", done)

    rows = run_mode_a3(
        questions,
        id_map,
        tmp_path,
        cfg,
        shared_cache=cache,
        say=lambda *_: None,
        llm_backend=FakeBackend(fake_llm),
    )
    by = {r["qid"]: r for r in rows}
    assert by["ls_002"]["step3"] is False
    assert by["ls_002"]["relevance"]["R@5"] == 0.0
    assert by["ls_001"]["step3"] is True
    assert by["ls_001"]["relevance"]["R@5"] == 1.0
    assert by["ls_001"]["relevance"]["MRR"] == 1.0
    assert (tmp_path / "rank.jsonl").exists()
    session_dirs = list((tmp_path / "sessions").iterdir())
    assert (session_dirs[0] / "step3_screening_all.json").exists()
    again = run_mode_a3(questions, id_map, tmp_path, cfg, shared_cache=cache, say=lambda *_: None, llm_backend=FakeBackend(fake_llm))
    assert again[0]["qid"] == "ls_001"
