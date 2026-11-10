"""Offline check of evaluation/step06_sota/metasyn_adopt.py on a fake MetaSyn dataset (one review, five articles).

The fake review includes: an article with PMC sections (a full text), an abstract-only article, an article with neither
abstract nor sections and one with no authors (both dropped), and the source review itself among the matched ids
(left out). Its exclusion_criteria holds a finding, as review 173's does in the real data, and its answer fields carry
distinctive sentences that must not reach the research folder.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
EVAL_DIR = REPO / "evaluation"
HARNESS = REPO / "ai-scientist-ideate-harness"
sys.path.insert(0, str(EVAL_DIR))
sys.path.insert(0, str(EVAL_DIR / "step06_sota"))

import metasyn_adopt  # noqa: E402
import metasyn_data  # noqa: E402

KEY_INSIGHT = "Telehealth uptake rose sharply among rural clinics after the second quarter of the study period"
CONCLUSION = "Overall the intervention reduced hospital readmissions across all included studies with moderate certainty"
FINDING_AS_CRITERION = ("The studies included in this review identified a clear reduction in readmissions "
                        "and patterns across registries showed fewer cases overall in the later period of follow up.")


def article(i, title, abstract, authors, sections=None, pmid=""):
    return {"ID": i, "title": title, "abstract": abstract, "authors": authors, "year": "2021", "doi": f"10.1/{i}",
            "pmid": pmid, "pmc_id": "", "journal": "J Test", "sections": sections or []}


@pytest.fixture()
def fake_data(tmp_path):
    data = tmp_path / "metasyn"
    (data / "corpus").mkdir(parents=True)
    arts = [
        article(1, "Telemonitoring after heart failure admission", "Patients received telemonitoring for six months. "
                "Readmissions fell by twelve percent in the intervention group.", ["A Smith", "B Jones"],
                sections=[{"heading": "introduction", "text": "Heart failure readmission is common and costly."},
                          {"heading": "results", "text": "Readmission fell from 31 to 19 percent over six months."}]),
        article(2, "Nurse-led follow up calls", "Nurse-led calls after discharge were compared with usual care.",
                ["C Brown"]),
        article(3, "A title only record", "", ["D White"]),
        article(4, "Remote care without authors", "An abstract that exists but no author list is recorded.", []),
    ]
    pd.DataFrame(arts).to_parquet(data / "corpus" / "part-0.parquet")
    review = {
        "ID": 900, "Title": "A review of telemonitoring", "Abstract": CONCLUSION + ". More text follows here in the abstract.",
        "Topic": "Telemonitoring after heart failure admission",
        "Research_Question": "Does telemonitoring reduce readmissions after heart failure admission?",
        "Population": "adults discharged after a heart failure admission", "Intervention": "telemonitoring or nurse-led follow up calls",
        "Exposure": "None", "Comparison": "usual care without remote follow up", "Outcome": "hospital readmission within six months",
        "Effect_Direction": "Positive", "Statistical_Significance": "Yes", "Effect_Size_Category": "Medium",
        "Conclusion_Summary": CONCLUSION, "Key_Insights": f"- {KEY_INSIGHT}\n- Another long insight about adherence and costs here",
        "Introduction": "Background text of the source review.", "search_start_date": "2015-01-01 00:00:00",
        "search_end_date": "2022-12-31 00:00:00", "inclusion_criteria": "adults; randomised or cohort designs; reports readmission",
        "exclusion_criteria": FINDING_AS_CRITERION, "conclusion_paragraph": "PubMed; Embase", "study_count": "4.0",
        "matched_ref_count": "5", "matched_corpus_ids": [1, 2, 3, 4, 5], "source_review_corpus_ids": [5],
        "extracted_titles": ["Telemonitoring after heart failure admission"], "source": "J Test Reviews",
        "Heterogeneity_Level": "Low", "Total_Sample_Size": "100", "Effect_Size_Type": "RR", "Effect_Size_Value": "0.8",
        "CI_Lower": "0.7", "CI_Upper": "0.9", "P_Value": "0.01", "I2_Value": "10", "Q_Value": "3", "Tau2_Value": "0.1",
    }
    pd.DataFrame([review]).to_parquet(data / "train.parquet")
    arts_with_source = arts + [article(5, "The source review itself", "Source abstract.", ["E Black"])]
    pd.DataFrame(arts_with_source).to_parquet(data / "corpus" / "part-0.parquet")
    return data


def run_ideate(*args):
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, str(HARNESS / "scripts" / "ideate_tools.py"), *map(str, args)], env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def test_adopter_builds_a_folder_the_harness_accepts(fake_data, tmp_path):
    batch = tmp_path / "batch"
    out = metasyn_adopt.adopt_review(900, batch, fake_data, "train", offline=True, depth="standard",
                                     llm_toml=EVAL_DIR / "step06_sota" / "metasyn.toml", harness_dir=HARNESS, force=False)
    rd = batch / "sessions" / "review_900"

    # the papers: two kept, two dropped with a reason, the source review left out
    report = json.loads((batch / "eval" / "review_900" / "input_report.json").read_text(encoding="utf-8"))
    assert out["papers"] == 2 and out["full_text"] == 1
    assert {d["corpus_id"] for d in report["dropped"]} == {3, 4}
    assert report["source_review_ids_excluded"] == [5]

    # every search and full-text unit is done, the adopted ones carry the metasyn-import note, the real ones do not
    events = [json.loads(line) for line in (rd / "_state" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    adopted = {e["unit"] for e in events if e.get("why") == "metasyn-import"}
    assert {"A1.p", "A3", "A5", "A6.d"} <= adopted and not adopted & {"A4.k", "A4.b", "A6.c"}
    status = run_ideate("status", rd, "--block", "search").stdout + run_ideate("status", rd, "--block", "fulltext").stdout
    assert "stale" not in status and "todo" not in status
    assert "OK" in run_ideate("a4-check", rd).stdout

    # a full text only for the paper that has sections; decon-plan reads it, the other paper from its abstract
    md = sorted((rd / "step5_full_text").glob("*.md"))
    assert [p.stem for p in md if not p.name.startswith("_")] == ["smithjones2021"] or len([p for p in md if not p.name.startswith("_")]) == 1
    plan = run_ideate("decon-plan", rd, "--max-chars", "60000").stdout
    assert "(1 full-text, 1 abstract)" in plan

    # nothing the source review says as an answer reached the research folder; the answers are under eval/
    for f in rd.rglob("*"):
        if f.is_file() and f.suffix in {".json", ".md", ".jsonl", ".bib"}:
            text = f.read_text(encoding="utf-8", errors="replace")
            assert KEY_INSIGHT not in text and CONCLUSION not in text and FINDING_AS_CRITERION[:40] not in text, f
    truth = json.loads((batch / "eval" / "review_900" / "ground_truth.json").read_text(encoding="utf-8"))
    assert truth["Effect_Direction"] == "Positive" and KEY_INSIGHT in truth["Key_Insights"]
    # the criteria field that read as a finding was replaced by a derived exclusion criterion
    assert report["protocol_sources"]["exclusion_criteria"].startswith("reads as a finding")
    cfg = json.loads((rd / "step0_session_config.json").read_text(encoding="utf-8"))
    assert all("identified a clear reduction" not in c["text"] for c in cfg["protocol"]["criteria"]["exclusion"])

    # the harness no longer stops at F1 (dry run: no model, no network)
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    copy = tmp_path / "dry"
    import shutil
    shutil.copytree(batch, copy)
    r = subprocess.run([sys.executable, "-m", "harness", "run", str(copy / "topics" / "review_900.md"), "--research-dir",
                        str(copy / "sessions" / "review_900"), "--from", "F1", "--to", "F1", "--dry-run"],
                       cwd=HARNESS, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    text = r.stdout + r.stderr
    at = text.find("UPSTREAM")
    assert at < 0, text[max(0, at - 300):at + 300]
    assert "GATE-a4-check" in text and "A6.c already done" in text and "(dry run) A7.D" in text, text


def test_finding_in_a_criteria_field_is_not_used():
    row = {"Conclusion_Summary": CONCLUSION, "Key_Insights": KEY_INSIGHT, "conclusion_paragraph": "", "Abstract": ""}
    assert metasyn_data.clean_criteria(FINDING_AS_CRITERION, row)[0] is None
    assert metasyn_data.clean_criteria("adults; randomised designs; English language", row)[0] is not None
    assert metasyn_data.clean_criteria("None", row)[0] is None
    assert metasyn_data.clean_criteria("word " * 200, row)[0] is None


def test_leak_check_catches_an_answer_in_the_research_folder(tmp_path):
    rd = tmp_path / "rd"
    rd.mkdir()
    (rd / "step3_shortlist.json").write_text('{"note": "' + CONCLUSION + '"}', encoding="utf-8")
    assert metasyn_adopt.leaked(rd, {"Conclusion_Summary": CONCLUSION})
    assert not metasyn_adopt.leaked(rd, {"Key_Insights": KEY_INSIGHT})
