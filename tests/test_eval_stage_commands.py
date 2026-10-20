"""Stage boundaries: real engine with fake providers/model, not live services."""
import json
from pathlib import Path

import pytest

from evaluation.step02.data import dump_subset
from evaluation.step02.ids import build_gold_id_map, dump_map
from evaluation.step02.run import run as run_step2
from evaluation.step03.run import run_from_step2
from scholar_research.config import Config
from scholar_research.llm.client import FakeBackend
from tests.fakes import FakeHttpx, fake_llm


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def benchmark(tmp_path, monkeypatch):
    import scholar_research.providers.base as base
    monkeypatch.setattr(base.httpx, "Client", FakeHttpx)
    monkeypatch.setattr(base.time, "sleep", lambda *_: None)
    FakeHttpx.calls.clear()
    questions = [{"qid": f"ls_{i:03}", "query": "EEG neurofeedback training working memory mild cognitive impairment",
                  "split": "inline", "quality": 2, "specificity": 1,
                  "query_set": "inline_acl", "corpusids": [cid]}
                 for i, cid in [(1, 1001), (2, 9999)]]
    subset, mapping = tmp_path / "subset.json", tmp_path / "mapping.json"
    dump_subset(subset, questions)
    gold = build_gold_id_map([1001], tmp_path / "map_cache", api_key=None)
    gold["9999"] = {"ok": False, "corpusId": 9999}
    dump_map(mapping, gold)
    cfg = Config()
    cfg.llm.provider = "ollama"
    cfg.search.sources = ["semantic_scholar"]
    cfg.search.snowball_seeds = 0
    cfg.search.snowball_refs_per_seed = 0
    return subset, mapping, cfg


def test_stages_auto_evaluate_and_score_gold_misses_without_searching_again(tmp_path, benchmark):
    subset, mapping, cfg = benchmark
    source, out = tmp_path / "step02", tmp_path / "step03"
    assert run_step2(source, subset=subset, mapping=mapping, config=cfg, say=lambda *_: None)
    assert read(source / "evaluation/summary.json")["completion"]["step2"]["numerator"] == 2
    before = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
    calls_before = list(FakeHttpx.calls)
    assert run_from_step2(source, out, config=cfg, llm_backend=FakeBackend(fake_llm), say=lambda *_: None)
    assert FakeHttpx.calls == calls_before
    after = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
    assert before == after
    rank = [json.loads(line) for line in (out / "rank.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rank) == 2
    assert rank[1]["set_recall"] == 0
    assert rank[1]["n_screened"] > 0  # No gold-based decision to skip the model.
    assert read(out / "evaluation/summary.json")["completion"]["step3"]["numerator"] == 2

    def must_not_call(**kwargs):
        raise AssertionError("A completed stage must resume without another model request")

    assert run_from_step2(source, out, config=cfg, llm_backend=must_not_call, say=lambda *_: None)
    with pytest.raises(ValueError, match="separate"):
        run_from_step2(source, source, config=cfg)
    raw = next((source / "sessions").glob('*/step2_raw_papers.json'))
    raw.write_text(raw.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Frozen inputs"):
        run_from_step2(source, out, config=cfg)


def test_stage2_failure_is_saved_and_not_removed_from_denominator(tmp_path, benchmark, monkeypatch):
    from evaluation.step02 import run as command
    subset, mapping, cfg = benchmark
    original = command.run_mode_a

    def fail_second(questions, *args, **kwargs):
        if questions[0]["qid"] == "ls_002":
            raise RuntimeError("provider unavailable")
        return original(questions, *args, **kwargs)

    monkeypatch.setattr(command, "run_mode_a", fail_second)
    source = tmp_path / "step02"
    assert not run_step2(source, subset=subset, mapping=mapping, config=cfg, say=lambda *_: None)
    summary = read(source / "evaluation/summary.json")
    assert summary["completion"]["step2"] == {"numerator": 1, "denominator": 2, "value": 0.5}
    assert not run_from_step2(source, tmp_path / "step03", config=cfg,
                             llm_backend=FakeBackend(fake_llm), say=lambda *_: None)
    result = read(tmp_path / "step03/evaluation/summary.json")
    assert result["completion"]["step3"]["numerator"] == 1
    assert result["completion"]["step3"]["denominator"] == 2


def test_bm25_command_automatically_evaluates_selected_tasks_and_returns_failure(tmp_path, monkeypatch):
    from evaluation.step03 import official_bm25
    from evaluation.step03.run import main
    tasks = [{"qid": f"q{i}", "session": f"q{i}", "corpusids": [1], "bm25_top100": [1, 2]}
             for i in (1, 2)]
    (tmp_path / "tasks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tasks), encoding="utf-8")
    # Simulate an interrupted scorer. The real evaluator must still report the
    # requested denominator, zero completion and a nonzero process status.
    monkeypatch.setattr(official_bm25, "score", lambda *args, **kwargs: None)
    assert main(["--source", "bm25", "--out", str(tmp_path), "--limit", "1"]) == 1
    summary = read(tmp_path / "comparison_summary.json")
    assert summary["n"] == 1
    assert summary["completed"] == 0
    assert summary["overall"]["bm25"]["R@5"] == 1
