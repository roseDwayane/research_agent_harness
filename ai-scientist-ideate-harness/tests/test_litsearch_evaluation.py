from __future__ import annotations

from evaluation.litsearch.adapter import prepare_step3, scored_papers, verify_frozen, write_json
from evaluation.litsearch.metrics import ranking_metrics
from evaluation.litsearch.cli import _canonical_ids
from evaluation.step03.scoring import composite_score, rank_papers
from ideate_v2.ledger import unit_states
from ideate_v2.registry import Registry


def test_prepare_step3_opens_current_s3_boundary_without_gold(tmp_path):
    task = {"qid": "q1", "query": "biomedical mechanism", "corpusids": ["gold"]}
    candidates = [{"id": str(i), "title": f"Paper {i}", "abstract": f"Abstract {i}"} for i in range(3)]
    contract = prepare_step3(tmp_path, task, candidates)
    assert contract["gold_is_hidden"] is True
    assert "gold" not in (tmp_path / "step2_raw_papers.json").read_text(encoding="utf-8")
    states = unit_states(Registry.load(), tmp_path)
    assert all(states[u]["state"] == "done" for u in ("A2.s", "A2.m", "A2.c"))
    verify_frozen(tmp_path)


def test_current_step3_artifacts_are_normalized_and_ranked(tmp_path):
    task = {"qid": "q1", "query": "query", "corpusids": ["2"]}
    candidates = [{"id": str(i), "title": f"P{i}", "abstract": f"A{i}"} for i in range(1, 4)]
    prepare_step3(tmp_path, task, candidates)
    write_json(tmp_path / "screening_scores.json", {"scores": {
        "1": {"relevance": 2, "quality": 4, "recency_impact": 5},
        "2": {"relevance": 5, "quality": 4, "recency_impact": 3},
        "3": {"relevance": 1, "quality": 3, "recency_impact": 2}}})
    write_json(tmp_path / "step3_shortlist.json", {"papers": [{"id": "2"}], "summary": {"included": 1}})
    rows = scored_papers(tmp_path)
    ranked = [p["id"] for p in sorted(rows, key=lambda p: -p["screening"]["relevance"])]
    assert ranked[0] == "2"
    assert ranking_metrics(task["corpusids"], ranked)["MRR"] == 1.0


def test_live_provider_ids_map_back_to_litsearch_corpus_ids():
    papers = [{"id": "internal", "paperId": "semantic-scholar-id", "doi": "10.1/example"}]
    mapping = {"42": {"ok": True, "paperId": "semantic-scholar-id", "doi": "10.1/example"}}
    assert _canonical_ids(papers, mapping) == ["42"]


def test_step3_composite_and_ranking_contract():
    assert composite_score(5, 4, 3) == 4.3
    papers = [
        {"id": "b", "screening": {"relevance": 4, "composite": 4.2}},
        {"id": "a", "screening": {"relevance": 4, "composite": 4.2}},
        {"id": "c", "screening": {"relevance": 4, "composite": 4.5}},
        {"id": "d", "screening": {"relevance": 5, "composite": 4.0}},
    ]
    assert [p["id"] for p in rank_papers(papers, "relevance")] == ["d", "c", "a", "b"]
    assert [p["id"] for p in rank_papers(papers, "composite")] == ["c", "a", "b", "d"]
