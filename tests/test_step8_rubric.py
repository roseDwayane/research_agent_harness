"""Step 8 absolute rubric: metrics, judge independence, offline runner."""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from scholar_research.cli import main
from scholar_research.config import Config, JudgeLLMConfig, LLMConfig
from evaluation.step08.metrics import METRICS, anchors_for, excerpt_json, metric_by_id
from evaluation.step08.runner import run_step8_rubric
from scholar_research.llm.client import FakeBackend
from scholar_research.schemas.session_config import EngineInfo, PICO, SessionConfig
from scholar_research.session import Session
from scholar_research.utils import dump_json


def _minimal_spec() -> dict:
    dims = [
        "Population",
        "Intervention / Method",
        "Comparison / Control",
        "Primary Outcome",
        "Secondary Outcome",
        "Setting",
        "Design",
        "Timeframe",
    ]
    return {
        "executive_summary_en": "Home NF for MCI WM.",
        "executive_summary_zh": "摘要",
        "gap_summary_en": "No trial tracked effects beyond 3 months.",
        "gap_summary_zh": "缺口",
        "gap_selection_rationale_en": "chosen",
        "gap_selection_rationale_zh": "選",
        "research_questions": [
            {
                "id": "RQ1",
                "focus": "Feasibility",
                "question_en": "Can home NF be delivered?",
                "question_zh": "可行嗎",
                "elaboration_en": "e",
                "elaboration_zh": "說",
            }
        ],
        "hypotheses": [
            {
                "id": "H1",
                "label_en": "Primary",
                "label_zh": "主要",
                "h0_en": "No difference",
                "h0_zh": "無",
                "h1_en": "Home NF improves WM by >=10%",
                "h1_zh": "將改善",
                "direction_magnitude_en": "based on LeeEtAl2023",
                "direction_magnitude_zh": "依據",
                "statistical_approach_en": "paired t-test, alpha=.05",
                "statistical_approach_zh": "配對 t",
            }
        ],
        "scope_in": [{"dimension_en": d, "dimension_zh": "維", "spec_en": "spec", "spec_zh": "規"} for d in dims],
        "scope_out": [{"exclusion_en": f"ex{i}", "exclusion_zh": "排", "rationale_en": "why", "rationale_zh": "理"} for i in range(3)],
        "scope_rationale_en": "r",
        "scope_rationale_zh": "邏",
        "conceptual_framework_en": "A -> B",
        "conceptual_framework_zh": "框架",
        "risks": [{"risk": f"r{i}", "likelihood": "Medium", "impact": "High", "mitigation": "m"} for i in range(3)],
        "traceability": [{"element": "RQ1", "source": "GAP_001", "evidence": "e"}],
        "journals": [],
        "journal_selection_criteria_en": "c",
        "journal_selection_criteria_zh": "準",
        "submission_strategy_en": "s",
        "submission_strategy_zh": "策",
    }


def _seed_session(root: Path) -> Session:
    cfg = Config(llm=LLMConfig(model="generator-model"), judge=JudgeLLMConfig(model="judge-model"))
    s = Session.create(root, "EEG NF MCI", cfg, session_id="20260101")
    sc = SessionConfig(
        session_id="20260101",
        topic="EEG NF MCI",
        topic_original="EEG NF MCI",
        topic_slug="eeg-nf-mci",
        timestamp="2026-01-01T00:00:00+08:00",
        pico=PICO(
            population="MCI",
            intervention="EEG NF",
            comparison="sham",
            outcome="WM",
            setting="home",
            timeframe="2020-2026",
        ),
        field_type="biomedical",
        engine=EngineInfo(version="0.1.0", llm_model="generator-model"),
    )
    s.save_config(sc)
    dump_json(
        s.path("step8_hypothesis.json"),
        {"locked_gap": "GAP_001", "dropped_gaps": ["GAP_002"], "design_constraint": None, "spec": _minimal_spec()},
    )
    dump_json(
        s.path("step7_gaps.json"),
        {
            "gaps": [
                {
                    "id": "GAP_001",
                    "rank": 1,
                    "composite": 4.1,
                    "gap": {
                        "title_en": "Long-term follow-up",
                        "title_zh": "缺口",
                        "gap_type": "temporal",
                        "description_en": "No study beyond 3 months.",
                        "description_zh": "無",
                        "why_it_matters_en": "matters",
                        "why_it_matters_zh": "重要",
                        "supporting_evidence": [],
                        "severity": 4,
                        "novelty": 4,
                        "feasibility": 3,
                    },
                }
            ]
        },
    )
    dump_json(
        s.path("step3_shortlist.json"),
        {
            "papers": [
                {
                    "id": "paper_001",
                    "title": "Home neurofeedback for MCI",
                    "year": 2024,
                    "abstract": "A pilot RCT of home EEG NF improved working memory.",
                }
            ]
        },
    )
    dump_json(
        s.path("step6_sota.json"),
        {
            "executive_summary_en": "NF shows moderate WM gains in lab settings.",
            "trends_en": "home delivery rising",
            "converging_en": "theta protocols",
            "diverging_en": "transfer measures",
            "themes": [
                {
                    "number": 1,
                    "title_en": "Clinical trials",
                    "consensus_en": "short-term gains",
                    "methods_en": "RCT",
                }
            ],
        },
    )
    return s


# ----------------------------- metrics -------------------------------- #
def test_ten_unique_metrics():
    ids = [m.id for m in METRICS]
    assert len(ids) == 10
    assert len(set(ids)) == 10
    assert {m.category for m in METRICS} == {"Problem", "Method"}
    for cat in ("Problem", "Method"):
        assert sum(1 for m in METRICS if m.category == cat) == 5


def test_anchors_split_by_field_and_excerpt_nonempty():
    bio = anchors_for("problem.clarity", "biomedical")
    cs = anchors_for("problem.clarity", "cs_engineering")
    assert bio != cs
    assert "Do NOT default to 4–5" in bio
    spec = _minimal_spec()
    for m in METRICS:
        excerpt = excerpt_json(m, spec)
        assert excerpt.strip().startswith("{")
        assert len(excerpt) > 20
    assert metric_by_id("method.generalizability").name == "Generalizability"
    with pytest.raises(KeyError):
        metric_by_id("experiment.validity")
    with pytest.raises(KeyError):
        anchors_for("experiment.validity", "biomedical")
    with pytest.raises(KeyError):
        metric_by_id("nope")


# ----------------------------- judge config --------------------------- #
def test_resolve_judge_requires_distinct_model():
    cfg = Config(llm=LLMConfig(model="same"), judge=JudgeLLMConfig(model=None))
    with pytest.raises(RuntimeError, match="judge.model is not set"):
        cfg.resolve_judge_llm()
    cfg.judge.model = "same"
    with pytest.raises(RuntimeError, match="equals"):
        cfg.resolve_judge_llm()
    got = cfg.resolve_judge_llm(allow_same_model=True)
    assert got.model == "same"
    cfg.judge.model = "other-judge"
    assert cfg.resolve_judge_llm().model == "other-judge"


def test_judge_env_override(monkeypatch):
    monkeypatch.setenv("SCHOLAR_JUDGE_MODEL", "env-judge")
    monkeypatch.setenv("SCHOLAR_JUDGE_PROVIDER", "ollama")
    cfg = Config.load(None)
    assert cfg.judge.model == "env-judge"
    assert cfg.judge.provider == "ollama"


# ----------------------------- runner --------------------------------- #
def test_runner_writes_scores_with_fake_judge(tmp_path: Path):
    s = _seed_session(tmp_path / "10_Research")
    cfg = Config(llm=LLMConfig(model="generator-model"), judge=JudgeLLMConfig(model="judge-model", provider="ollama"))
    calls: list[str] = []

    def responder(tool, messages):
        assert tool == "emit_s8_rubric_rating"
        user = messages[0]["content"]
        calls.append(user)
        # rating cycles 2..4 so means are not all 5
        rating = 2 + (len(calls) % 3)
        return {"review": f"evidence in excerpt ({rating})", "feedback": "add detail", "rating": rating}

    payload = run_step8_rubric(s, cfg, judge_backend=FakeBackend(responder), say=lambda _m: None)
    assert len(calls) == 10
    assert len(payload["ratings"]) == 10
    assert set(payload['means']['by_category']) == {'Problem', 'Method'}
    assert payload["meta"]["feeds_pipeline"] is False
    assert payload["meta"]["judge_model"] == "judge-model"
    assert payload["meta"]["generator_model"] == "generator-model"
    assert 1.0 <= payload["means"]["overall"] <= 5.0
    assert (s.dir / "step8_rubric_scores.json").is_file()
    report = (s.dir / "step8_rubric_report.md").read_text(encoding="utf-8")
    assert "problem.clarity" in report and "Overall" in report
    assert 'Experiment' not in report and 'experiment.' not in report
    # prompt must force single-metric focus + anchors
    assert "METRIC UNDER REVIEW" in calls[0]
    assert "CRITERIA" in calls[0] or "Do NOT default to 4–5" in calls[0] or "Likert" in calls[0] or "1 Vague" in calls[0]


def test_runner_only_subset(tmp_path: Path):
    s = _seed_session(tmp_path / "10_Research")
    cfg = Config(llm=LLMConfig(model="generator-model"), judge=JudgeLLMConfig(model="judge-model"))
    n = {"n": 0}

    def responder(tool, messages):
        n["n"] += 1
        return {"review": "ok", "feedback": "none", "rating": 3}

    payload = run_step8_rubric(
        s,
        cfg,
        only=["problem.clarity", "method.validity"],
        judge_backend=FakeBackend(responder),
    )
    assert n["n"] == 2
    assert [r["id"] for r in payload["ratings"]] == ["problem.clarity", "method.validity"]


# ----------------------------- CLI ------------------------------------ #
def test_cli_list_metrics_and_rubric(tmp_path: Path, monkeypatch):
    # Isolate from repo .env (which may set SCHOLAR_JUDGE_MODEL).
    for key in ("SCHOLAR_JUDGE_MODEL", "SCHOLAR_JUDGE_PROVIDER", "SCHOLAR_JUDGE_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)

    r = CliRunner()
    out = r.invoke(main, ["eval", "step8-rubric", "--list-metrics"])
    assert out.exit_code == 0, out.output
    assert "problem.clarity" in out.output
    assert "method.generalizability" in out.output
    assert "experiment." not in out.output

    s = _seed_session(tmp_path / "10_Research")
    out = r.invoke(main, ["eval", "step8-rubric", "--root", str(tmp_path / "10_Research"), "--session", s.name])
    assert out.exit_code != 0
    assert "judge.model" in out.output
