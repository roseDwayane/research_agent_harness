"""Offline run of the evaluation flow: run_batch (batch only) → step06_sota/run_checks → aggregate.

Uses the same fake LLM / fake HTTP as test_e2e_replay. The second topic's Step 6 is made to
fail so the failure-case bookkeeping is exercised too.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean

import pytest

from scholar_research.config import Config
from scholar_research.llm.client import FakeBackend
from tests.fakes import FakeHttpx, fake_llm

EVAL_DIR = Path(__file__).resolve().parent.parent / "evaluation"
sys.path.insert(0, str(EVAL_DIR))
sys.path.insert(0, str(EVAL_DIR / "step06_sota"))

import aggregate  # noqa: E402
import run_batch  # noqa: E402
import run_checks  # noqa: E402
from eval_common import batch_paths, read_json, read_runs, write_json  # noqa: E402


@pytest.fixture
def offline(monkeypatch):
    import scholar_research.providers.base as base

    monkeypatch.setattr(base.httpx, "Client", FakeHttpx)
    monkeypatch.setattr(base.time, "sleep", lambda *_: None)
    FakeHttpx.calls.clear()
    yield


def _failing_second_synthesis():
    calls = {"sota": 0}

    def responder(tool, messages):
        if tool == "emit_sota_review":
            calls["sota"] += 1
            if calls["sota"] > 1:
                raise RuntimeError("simulated Step 6 failure")
        return fake_llm(tool, messages)

    return FakeBackend(responder)


def test_batch_collects_successes_and_failures(tmp_path: Path, offline):
    batch_dir = tmp_path / "runs" / "smoke"
    cfg = run_batch.build_config(None, {"model": "fake-pinned"}, batch_paths(batch_dir)["sessions"])
    cfg.llm.max_retries = 1
    topics = [{"id": "ok_topic", "topic": "EEG neurofeedback for MCI"},
              {"id": "failing_topic", "topic": "EEG neurofeedback for MCI replicate"}]

    run_batch.run_batch(topics, cfg, batch_dir, until=6, backend=_failing_second_synthesis(), echo=False)

    runs = {r["id"]: r for r in read_runs(batch_dir)}
    assert set(runs) == {"ok_topic", "failing_topic"}

    ok = runs["ok_topic"]
    assert ok["pipeline_status"] == "ok" and ok["step6_present"]
    assert [s["status"] for s in ok["steps"]] == ["ok"] * 6
    assert "deterministic" not in ok  # run_batch only produces the batch

    assert run_checks.main(["--batch", str(batch_dir)]) == 0
    det = read_json(batch_paths(batch_dir)["eval"] / "ok_topic" / "step06" / "summary.json")
    assert det["status"] == "ok", det
    assert det["contract"]["integrity_fail"] is False
    assert "numeric_attestation" in det["numeric"]
    assert not (batch_paths(batch_dir)["eval"] / "failing_topic").exists()
    manifest = read_json(batch_paths(batch_dir)["eval"] / "ok_topic" / "step06" / "manifest.json")
    assert manifest["sources"] and manifest["coverage_denominator"] == ["full-text-pdf", "full-text-html"]

    failed = runs["failing_topic"]
    assert failed["pipeline_status"] == "failed" and failed["failed_step"] == 6
    assert "simulated Step 6 failure" in failed["error"]
    assert not failed["step6_present"]

    # a batch is never silently reused
    with pytest.raises(SystemExit):
        run_batch.run_batch(topics, cfg, batch_dir, until=6, backend=_failing_second_synthesis(), echo=False)

    eval_dir = batch_paths(batch_dir)["eval"]
    sys.argv = ["aggregate.py", "--batch", str(batch_dir)]
    assert aggregate.main() == 0
    summary = read_json(eval_dir / "summary.json")
    assert summary["protocol"]["summary"]["same_config"] is True
    assert summary["protocol"]["summary"]["auto_checkpoints_only"] is True
    assert summary["protocol"]["summary"]["step6_untouched"] is True

    m = summary["metrics"]
    assert (m["topics"], m["pipeline_ok"], m["step6_present"]) == (2, 1, 1)
    assert m["deterministic"]["integrity_pass"] == {"all": 0.5, "scored": 1.0, "n_scored": 1, "n_total": 2}
    assert "failing_topic" in (eval_dir / "summary.md").read_text(encoding="utf-8")


def test_hand_edit_is_detected(tmp_path: Path, offline):
    batch_dir = tmp_path / "runs" / "edited"
    cfg = run_batch.build_config(None, {"model": "fake-pinned"}, batch_paths(batch_dir)["sessions"])
    run_batch.run_batch([{"id": "t", "topic": "EEG neurofeedback for MCI"}], cfg, batch_dir, until=6,
                        backend=FakeBackend(fake_llm), echo=False)
    record = read_runs(batch_dir)[0]
    review = batch_dir / record["session_dir"] / "step6_sota_review.md"
    review.write_text(review.read_text(encoding="utf-8") + "\nhand edit\n", encoding="utf-8")

    protocol = aggregate.protocol_checks(read_json(batch_paths(batch_dir)["batch"]), [record], batch_dir)
    assert protocol["summary"]["step6_untouched"] is False


def test_manifest_theme_range_follows_paper_count(tmp_path: Path):
    import make_manifest

    session = tmp_path / "s"
    (session / "step5_full_text").mkdir(parents=True)
    bib = "".join(f"@article{{Key{i}2024,\n title={{T}}\n}}\n" for i in range(12))
    (session / "step4_references.bib").write_text(bib, encoding="utf-8")
    for i in range(12):
        level = "full-text-html" if i % 2 else "abstract-only"
        (session / "step5_full_text" / f"Key{i}2024.md").write_text(
            f"---\ncitation_key: Key{i}2024\naccess_level: {level}\n---\n# T\n", encoding="utf-8")
    m = make_manifest.build_manifest(session, tmp_path / "eval" / "m.json")
    assert (m["theme_count_min"], m["theme_count_max"]) == (4, 6)
    assert len(m["sources"]) == 12 and m["project_dir"] == "../s"
    assert json.dumps(m)  # serialisable


def test_review_sections():
    from autosurvey_common import step6_sections

    review = "\n".join(["# State-of-the-Art Review", "## Executive Summary", "Summary.", "## Methodology Legend", "| a |",
                        "## Theme 1: Alpha", "### Consensus", "c (Key2024)", "## Theme 2: Beta", "b",
                        "## Cross-Theme Analysis", "x", "## Paper–Theme Mapping", "| k |", "## Limitations of This Review", "l"])
    sections = step6_sections(review)
    assert [t for t, _ in sections] == ["Executive Summary", "Theme 1: Alpha", "Theme 2: Beta", "Cross-Theme Analysis"]
    assert sections[1][1] == "## Theme 1: Alpha\n### Consensus\nc (Key2024)\n"


def test_section_damage_is_deterministic():
    import autosurvey_controls as ac

    section = "## Theme 1: A\n\n### Consensus\n\nFirst point (Key2024). Second point.\n\n### Debates\n\nThird point. Fourth point.\n"
    forms = ac.section_forms(section, 1)
    assert list(forms) == ac.SECTION_VARIANTS and forms["original"] == section
    assert "###" not in forms["no_subheadings"] and "First point" in forms["no_subheadings"]
    assert forms["repeated"].count("Third point.") == 2
    assert forms == ac.section_forms(section, 1) and "###" not in forms["shuffled"]
    assert sorted(forms["shuffled"].split("\n\n", 1)[1].replace("\n\n", " ").split(". ")) != forms["shuffled"]  # content kept


def test_judge_agreement_report(tmp_path: Path):
    import metasyn_judge_agreement as ja

    verdicts = {  # judge → per review: coverage verdicts of the 4 Key Insights of step6
        "a": [["covered", "partial", "not_covered", "covered"], ["not_covered", "covered", "partial", "contradicted"]],
        "b": [["covered", "partial", "not_covered", "partial"], ["not_covered", "covered", "partial", "contradicted"]],
        "c": [["covered", "covered", "not_covered", "covered"], ["not_covered", "covered", "not_covered", "not_covered"]],
    }
    for judge, per_review in verdicts.items():
        for rid, vs in zip((1, 2, 3), per_review + [per_review[0]]):
            items = [{"index": i, "verdict": v, "digest": {"verdict": "supported"}} for i, v in enumerate(vs)]
            score = mean(ja.COVERAGE_SCORE[v] for v in vs)
            system = {"items": items, "coverage_all": score, "coverage_answerable": score,
                      "official": {"direction": "Positive" if rid != 2 else "Mixed", "insights_consistency": round(score, 1)}}
            write_json(tmp_path / "eval" / f"review_{rid}" / "metasyn" / ja.judge_file(judge),
                       {"review_id": rid, "systems": {"step6": system, "offtopic": {"items": []}}})

    sys.argv = ["metasyn_judge_agreement.py", "--batch", str(tmp_path), "--judges", "a", "b", "c"]
    assert ja.main() == 0
    report = read_json(tmp_path / "eval" / "judge_agreement.json")
    assert report["systems"] == ["step6"]  # damaged control forms are excluded
    cov = report["agreement"]["coverage"]
    assert cov["n_units"] == 12 and cov["pairs"]["a | b"]["exact"] == round(10 / 12, 4)
    assert report["agreement"]["direction"]["pairs"]["a | c"] == {"n": 3, "exact": 1.0, "kappa": 1.0}
    assert report["agreement"]["digest"]["pairs"]["a | b"]["exact"] == 1.0
    assert "fleiss_kappa" in cov and "mean of judges" in report["convergent"]
    rho = report["convergent"]["a"]["correlations"]["coverage_all / step6"]["spearman"]
    assert rho == 1.0  # insights_consistency was built from the same score
