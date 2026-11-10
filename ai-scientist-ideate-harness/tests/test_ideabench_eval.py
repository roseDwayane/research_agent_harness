from __future__ import annotations

import csv
import json
from pathlib import Path

from ideabench_eval.adapter import import_official, load_tasks
from ideabench_eval.client import ModelConfig, ScriptedClient
from ideabench_eval.ranking import insight_score
from ideabench_eval.runner import run
from ideabench_eval.pipeline import run_p2 as prompt_fixture_p2
from ideabench_eval.new_pipeline import prepare_research_dir
from ideate_v2.ledger import unit_states
from ideate_v2.registry import Registry


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_official_adapter_keeps_gold_separate(tmp_path):
    source, out = tmp_path / "official", tmp_path / "dataset"
    source.mkdir()
    pid = "target-1"
    _write_csv(source / "target_papers.csv", ["paperId", "abstract_summary"],
               [{"paperId": pid, "abstract_summary": "GOLD IDEA ONLY"}])
    refs = [{"targetPaperId": pid, "paperId": f"r{i}", "title": f"Reference {i}",
             "abstract": f"Abstract {i}", "year": "2020", "venue": "Journal"} for i in range(1, 7)]
    _write_csv(source / "filtered_references.csv", list(refs[0]), refs)
    (source / "ideabench_clustering.json").write_text(json.dumps({"Health & Medicine": [pid]}), encoding="utf-8")
    manifest = import_official(source, out)
    assert manifest["count"] == 1
    task = load_tasks(out)[0]
    assert len(task["references"]) == 5
    assert "GOLD IDEA ONLY" not in (out / manifest["tasks"][0]["references"]).read_text(encoding="utf-8")
    assert task["gold_path"].read_text(encoding="utf-8").strip() == "GOLD IDEA ONLY"


def test_insight_score_is_fraction_of_generated_ideas_above_gold():
    assert insight_score(1, 3) == 0.0
    assert insight_score(2, 3) == 1 / 3
    assert insight_score(4, 3) == 1.0


def test_new_pipeline_adapter_freezes_five_refs_and_opens_fusion_boundary(tmp_path):
    refs = [{"paperId": f"r{i}", "title": f"R{i}", "abstract": f"Evidence {i}", "year": 2020}
            for i in range(1, 6)]
    contract = prepare_research_dir(tmp_path, refs, max_questions=3)
    assert contract["online_search"] is False
    assert contract["resume_boundary"] == "STEP-F1/A7.D"
    states = unit_states(Registry.load(), tmp_path)
    assert all(states[unit]["state"] == "done" for unit in ("A4.k", "A4.b", "A6.d", "A6.c"))
    frozen = (tmp_path / "_state" / "ideabench" / "frozen_references.json").read_text(encoding="utf-8")
    assert all(ref["paperId"] in frozen for ref in refs)


def test_full_offline_order_and_gold_blinding(tmp_path):
    dataset, out = tmp_path / "dataset", tmp_path / "run"
    (dataset / "tasks" / "t1").mkdir(parents=True)
    (dataset / "gold").mkdir()
    refs = [{"paperId": f"r{i}", "title": f"R{i}", "abstract": f"Evidence {i}", "year": 2020}
            for i in range(1, 6)]
    (dataset / "tasks" / "t1" / "references.json").write_text(
        json.dumps({"paperId": "t1", "count": 5, "references": refs}), encoding="utf-8")
    marker = "SECRET_GOLD_MARKER"
    (dataset / "gold" / "t1.txt").write_text(marker, encoding="utf-8")
    (dataset / "manifest.json").write_text(json.dumps({
        "low_k": 5, "tasks": [{"paperId": "t1", "references": "tasks/t1/references.json", "gold": "gold/t1.txt"}]
    }), encoding="utf-8")
    final_idea = {
        "Name": "test", "Title": "A testable study", "Short Hypothesis": "Hypothesis: treatment changes outcome.",
        "Related Work": "References 1 and 2 motivate the test.", "Abstract": "We propose a controlled study.",
        "Experiments": "Run a controlled experiment.", "Risk Factors and Limitations": "Limited sample size.",
    }
    generator = ScriptedClient([
        {"questions": [{"id": "Q_001", "gap": "Unresolved mechanism", "question": "Does X change Y?", "evidence": [1, 2]}]},
        {"hypothesis": "X changes Y", "derivation": "References disagree", "rivals": ["confounding"]},
        {"operational_definitions": ["X", "Y"], "experiments": ["controlled test"], "controls": ["negative control"],
         "decision_rule": "effect excludes zero", "feasibility": "available assay"},
        {"nodes": [{"test": "controlled test", "positive": "supports", "negative": "refutes",
                    "uninformative": "repeat"}], "publishable_if_null": True},
        {"targets": [{"reference": 1, "claim": "claim", "weakness": "not controlled", "test": "experiment",
                      "if_miss": "concede"}]},
        final_idea,
        {"idea": "Hypothesis: a direct baseline will test a distinct mechanism."},
    ])
    judge = ScriptedClient([{"order": [1, 2], "rationale": "ranked"} for _ in range(8)])
    gen_cfg = ModelConfig("http://generator", "qwen")
    judge_cfg = ModelConfig("http://judge", "judge-model")
    def fixture_runner(folder, frozen_refs, _config, *, max_questions, say):
        return prompt_fixture_p2(folder, frozen_refs, generator, max_questions=max_questions, say=say)

    result = run(dataset, out, generator, judge, generator_config=gen_cfg, judge_config=judge_cfg,
                 max_questions=1, p2_runner=fixture_runner)
    assert result["status"] == "complete"
    assert result["m_paired"] == 1
    assert json.loads((out / "tasks" / "t1" / "generation_summary.json").read_text())["n_i"] == 1
    assert all(marker not in call["prompt"] for call in generator.calls)
    assert any(marker in call["prompt"] for call in judge.calls)

