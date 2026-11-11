from __future__ import annotations

import hashlib

from evaluation.litsearch.adapter import prepare_step3, scored_papers, verify_frozen, write_json
from evaluation.litsearch.cli import (_completed, _completion_key, _completion_path, selected_tasks)
from evaluation.litsearch.metrics import ranking_metrics
from evaluation.litsearch.cli import _canonical_ids
from evaluation.step03.scoring import composite_score, rank_papers
from evaluation.step0203.cli import evaluate as evaluate_final, rank_final_papers, screening_audit
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


def test_limit_selects_first_n_frozen_tasks(tmp_path):
    tasks = tmp_path / 'tasks.jsonl'
    tasks.write_text(''.join(f'{{"qid":"q{i}"}}\n' for i in range(5)), encoding='utf-8')
    assert [task['qid'] for task in selected_tasks(tasks, 2)] == ['q0', 'q1']
    import pytest
    with pytest.raises(ValueError, match='positive'):
        selected_tasks(tasks, 0)


def test_completed_step_is_skipped_only_for_matching_successful_run(tmp_path):
    task = {"qid": "q1", "query": "biomedical mechanism"}
    key = _completion_key(task, 2, "qwen3.8", "http://localhost", 32768, 8192, tmp_path)
    write_json(tmp_path / "step2_raw_papers.json", {"papers": []})
    summary = tmp_path / "_state" / "harness" / "run1" / "summary.json"
    write_json(summary, {"failed": False, "steps": [{"step": "STEP-S2", "status": "done"}]})
    write_json(_completion_path(tmp_path, 2), {"key": key,
               "summary": str(summary.relative_to(tmp_path)),
               "outputs": {"step2_raw_papers.json": hashlib.sha256(
                   (tmp_path / "step2_raw_papers.json").read_bytes()).hexdigest()}})
    assert _completed(tmp_path, 2, key)
    assert not _completed(tmp_path, 2, {**key, "query": "changed"})
    summary.unlink()
    assert not _completed(tmp_path, 2, key)


def test_step3_completion_requires_screening_outputs(tmp_path):
    task = {"qid": "q1", "query": "biomedical mechanism"}
    key = _completion_key(task, 3, "qwen3.8", "http://localhost", 32768, 8192, tmp_path)
    summary = tmp_path / "_state" / "harness" / "run1" / "summary.json"
    write_json(summary, {"failed": False, "steps": [{"step": "STEP-S3", "status": "degraded"}]})
    write_json(_completion_path(tmp_path, 3), {"key": key,
               "summary": str(summary.relative_to(tmp_path))})
    assert not _completed(tmp_path, 3, key)
    write_json(tmp_path / "screening_scores.json", {"scores": []})
    write_json(tmp_path / "step3_shortlist.json", {"papers": []})
    write_json(_completion_path(tmp_path, 3), {"key": key,
               "summary": str(summary.relative_to(tmp_path)),
               "outputs": {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
                           for name in ("screening_scores.json", "step3_shortlist.json")}})
    assert _completed(tmp_path, 3, key)


def test_final_screening_audit_uses_production_fields():
    audit = screening_audit(
        {"screening_config": {"include_at": 3.0, "weights": {"relevance": 0.5,
             "quality": 0.3, "recency_impact": 0.2}},
         "summary": {"screened": 10, "included": 4, "excluded": 6}},
        {"summary": {"borderline": 1}, "papers": [{"manually_included": True}, {}]})
    assert audit["threshold"] == 3.5
    assert audit["borderline_threshold"] == 3.0
    assert audit["inclusion_rate"] == 0.4
    assert audit["manually_included"] == 1


def test_final_checkpoint_scores_gold_found_only_by_snowball(tmp_path):
    task = {"qid": "q1", "query": "mechanism", "corpusids": ["gold"], "mode": "inline"}
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(__import__("json").dumps(task) + "\n", encoding="utf-8")
    rd = tmp_path / "sessions" / "q1"
    write_json(rd / "step2_raw_papers.json", {"papers": [{"id": "other"}]})
    write_json(rd / "step2b_snowball_papers.json", {"papers": [{"id": "gold"}]})
    write_json(rd / "screening_scores.json", {"scores": []})
    write_json(rd / "step3_shortlist.json", {"screening_config": {"include_at": 3.0},
               "summary": {"screened": 2, "included": 1, "excluded": 1}, "papers": []})
    write_json(rd / "step3_screening_all.json", {"summary": {"borderline": 0}, "papers": [
        {"id": "gold", "screening": {"relevance": 5, "composite": 4.5}},
        {"id": "other", "screening": {"relevance": None, "composite": None}}]})
    summary = rd / "_state" / "harness" / "run1" / "summary.json"
    write_json(summary, {"failed": False, "steps": [{"step": "STEP-S4", "status": "done"}],
               "gates": [{"gate": "GATE-a5-check", "passed": True}]})
    key = {"qid": "q1", "query": "mechanism", "step": 4}
    outputs = {name: hashlib.sha256((rd / name).read_bytes()).hexdigest() for name in
               ("step2_raw_papers.json", "step2b_snowball_papers.json",
                "screening_scores.json", "step3_shortlist.json", "step3_screening_all.json")}
    write_json(_completion_path(rd, 4), {"key": key,
               "summary": str(summary.relative_to(rd)), "outputs": outputs})
    result = evaluate_final(tasks, tmp_path / "sessions", tmp_path / "out")
    assert result["execution"]["step2_gold_hit"] == 0
    assert result["execution"]["final_gold_hit"] == 1
    assert result["relevance"]["R@5"] == 1.0
    assert [p["id"] for p in rank_final_papers(
        [{"id": "other", "screening": {"relevance": None, "composite": None}},
         {"id": "gold", "screening": {"relevance": 5, "composite": 4.5}}], "relevance")] == ["gold", "other"]


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
