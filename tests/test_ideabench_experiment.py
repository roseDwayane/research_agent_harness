"""Protocol tests: leakage, actual P2 steps, balanced ranks, paired denominators."""
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from scholar_research.config import Config, JudgeLLMConfig, LLMConfig
from evaluation.step08.ideabench.experiment import (
    Ranking, balanced_orders, gap_slots, insight_score, run_experiment, summarize,
)
from scholar_research.llm.client import FakeBackend
from scholar_research.utils import dump_json
from tests.fakes import fake_llm


def dataset(root: Path):
    root.mkdir()
    refs = [{"paperId": f"openalex:W{i}", "title": f"Neurofeedback study {i}",
             "abstract": "Older adults undergo EEG neurofeedback, with cognitive outcomes.",
             "year": 2023, "citationCount": 10, "publicationTypes": ["article"]} for i in range(5)]
    dump_json(root / "refs/openalex_Wtarget/low5.json", {"references": refs})
    (root / "ideas").mkdir()
    (root / "ideas/target.txt").write_text("Hypothesis: SECRET_GOLD future research idea.", encoding="utf-8")
    dump_json(root / "manifest.json", {"low_k": 5})
    (root / "targets.jsonl").write_text(json.dumps({"paperId": "openalex:Wtarget", "idea_path": "ideas/target.txt",
                                        "title": "SECRET_TITLE", "abstract": "SECRET_ABSTRACT"}) + "\n", encoding="utf-8")
    return root


def test_no_repeated_gaps_and_balanced_positions():
    assert gap_slots([{"id": f"G{i}"} for i in range(3)]) == ["G0", "G1", "G2"]
    assert gap_slots([{"id": "G0"}, {"id": "G1"}]) == ["G0", "G1"]
    with pytest.raises(ValueError):
        gap_slots([{"id": "G0"}, {"id": "G0"}])
    orders = balanced_orders(4, 12)
    for idea in range(4):
        assert sorted(order.index(idea) for order in orders) == [0, 1, 2, 3]
    assert insight_score(1, 3) == 0
    assert insight_score(4, 3) == 1
    with pytest.raises(ValueError):
        insight_score(5, 3)
    with pytest.raises(ValidationError):
        Ranking(order=[1, 1, 3, 4], rationale="invalid")


def test_paired_denominator_excludes_incomplete_system():
    records = [{"paperId": "a", "protocol": p, "status": "ok", "n": 2, "scores": {"novelty": s}}
               for p, s in (("P1", 0.2), ("P2", 0.8))]
    records.append({"paperId": "b", "protocol": "P1", "status": "ok", "scores": {"novelty": 1.0}})
    result = summarize(records, ["a", "b"], ["novelty"])
    assert result["m_paired"] == 1
    assert result["insight_scores"]["P1"]["novelty"] == 0.2
    assert result["P2_minus_P1"]["novelty"] == pytest.approx(0.6)
    assert result["status"] == "incomplete"


@pytest.mark.parametrize('gap_count', [2, 3])
def test_full_protocol_leakage_resumption_and_rank_mapping(tmp_path, gap_count):
    data = dataset(tmp_path / "data")
    out = tmp_path / "out"
    cfg = Config(llm=LLMConfig(model="generator", provider="ollama"), judge=JudgeLLMConfig(model="judge"))

    def generate(tool, messages):
        text = messages[0]["content"]
        assert "SECRET_GOLD" not in text and "SECRET_TITLE" not in text and "SECRET_ABSTRACT" not in text
        if tool == "emit_ideabench_context":
            return {"topic": "EEG neurofeedback for MCI", "pico": {"population": "Older adults", "intervention": "EEG neurofeedback", "comparison": "Sham", "outcome": "Cognition"}}
        if tool == "emit_ideabench_ideas":
            assert f'Generate exactly {gap_count}' in text
            return {"ideas": [f"Hypothesis: Direct study {i}." for i in range(gap_count)]}
        if tool == 'emit_gap_analysis':
            value = fake_llm(tool, messages)
            value['gaps'] = value['gaps'][:gap_count]
            return value
        if tool == "emit_hypothesis_spec":
            value = fake_llm(tool, messages)
            gap = re.search(r"LOCKED GAP: (GAP_\d+)", text).group(1)
            value["executive_summary_en"] = gap
            value["hypotheses"][0]["h1_en"] = f"Study testing {gap}"
            return value
        if tool == "emit_ideabench_target_idea":
            gap = re.search(r'"executive_summary_en": "(GAP_\d+)"', text).group(1)
            return {"summary": f"Hypothesis: Proposed study for {gap}."}
        return fake_llm(tool, messages)

    def judge(tool, messages):
        text = messages[0]["content"]
        assert "SECRET_TITLE" not in text and "SECRET_ABSTRACT" not in text
        if tool == "emit_ideabench_coherence":
            return {"failed_ids": [], "rationale": "All intelligible"}
        if tool == "emit_ideabench_ranking":
            # Content-based fixed target-first ranking verifies display mapping.
            gold_id = int(re.search(r"Hypothesis (\d+): Hypothesis: SECRET_GOLD", text).group(1))
            return {"order": [gold_id] + [i for i in range(1, gap_count+2) if i != gold_id], "rationale": "Gold first"}
        if tool == 'emit_s8_rubric_rating':
            assert 'unavailable' not in text and 'SECRET_GOLD' not in text
            assert 'LOCKED GAP (GAP_' in text
            return {'review': 'Evidence from spec', 'feedback': 'Clarify design', 'rating': 3}
        raise AssertionError(tool)

    gen, jdg = FakeBackend(generate), FakeBackend(judge)
    result = run_experiment(data, out, cfg, rubric=True, generator_backend=gen, judge_backend=jdg, say=lambda _: None)
    assert result["m_paired"] == 1 and result["status"] == "complete"
    assert result["insight_scores"] == {p: {q: 0.0 for q in ("novelty", "feasibility")} for p in ("P1", "P2")}
    task = out / "tasks/openalex_Wtarget"
    slots = json.loads((task / "P2/allocation.json").read_text())["slots"]
    assert len(set(slots)) == gap_count
    assert result['n_by_target']['openalex:Wtarget'] == gap_count
    assert result['rubric']['n_specs_scored'] == gap_count
    assert all((task / "P2" / f"spec_{i:02d}/step8_rubric_scores.json").exists() for i in range(1, gap_count+1))
    calls = gen.calls, jdg.calls
    again = run_experiment(data, out, cfg, rubric=True, generator_backend=gen, judge_backend=jdg, say=lambda _: None)
    assert again == result and (gen.calls, jdg.calls) == calls
    with pytest.raises(ValueError, match="contract changed"):
        run_experiment(data, out, cfg, seed=1, rubric=True, generator_backend=gen, judge_backend=jdg)

    # Gate failure must not suppress absolute rubric or sneak into paired scores.
    def fail_gate(tool, messages):
        if tool == 'emit_ideabench_coherence':
            return {'failed_ids': [1], 'rationale': 'Uninterpretable claim'}
        return judge(tool, messages)

    failed = run_experiment(data, tmp_path / 'failed', cfg, rubric=True, generator_backend=gen,
                            judge_backend=FakeBackend(fail_gate), say=lambda _: None)
    assert failed['m_paired'] == 0 and failed['status'] == 'incomplete'
    assert failed['rubric']['n_specs_scored'] == gap_count


def test_generator_judge_alias_rejected_before_network(tmp_path):
    cfg = Config(llm=LLMConfig(model="qwen:latest"), judge=JudgeLLMConfig(model="qwen"))
    with pytest.raises(ValueError, match="must differ"):
        run_experiment(tmp_path / "missing", tmp_path / "out", cfg)
