"""Offline checks of the AutoSurvey-style evaluation (evaluation/step06_sota/autosurvey_*.py, naive_baseline.py)."""
from __future__ import annotations

import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent.parent / "evaluation"
sys.path.insert(0, str(EVAL_DIR))
sys.path.insert(0, str(EVAL_DIR / "step06_sota"))

import autosurvey_eval as ae  # noqa: E402
import naive_baseline  # noqa: E402
from autosurvey_common import step6_survey  # noqa: E402


def test_score_parsing_is_strict():
    assert [ae.parse_score(t) for t in ("4", " **5** ", "Score: 3", "3/5", "2.")] == [4, 5, 3, 3, 2]
    # AutoSurvey would read the first integer of these; they are not scores
    assert ae.parse_score("On a scale of 1-5, I give 4") is None
    assert ae.parse_score("") is None and ae.parse_score("6") is None


def test_step6_survey_drops_generated_parts():
    review = "\n".join([
        "---", "step: 6", "---", "# State-of-the-Art Review", "## Executive Summary", "Summary text here.",
        "## Methodology Legend", "| Color | n |", "|---|---|", "| Red | 1 |",
        "---", "## Theme 1: Alpha", "**Papers:** KeyA2024, KeyB2023", "### Consensus", "Point (KeyA2024).",
        "## Paper–Theme Mapping", "| Paper | Theme |", "|---|---|", "| KeyA2024 | 1 |",
    ])
    text = step6_survey(review)
    assert "## Theme 1: Alpha\n" in text and "Point (KeyA2024)." in text
    assert "Legend" not in text and "Mapping" not in text and "**Papers" not in text


def test_claims_and_citations():
    survey = "\n".join([
        "# T", "## Section",
        "Smith et al. (2024) report gains in memory. Training improved recall in older adults (KeyA2024; KeyB2023).",
        "- Effects faded after six months of follow-up (Ghost2020).",
        "| Study | N | Result |", "|---|---|---|", "| (KeyA2024) | 30 | memory improved by 10 points |",
    ])
    claims = ae.extract_claims(survey, {"KeyA2024", "KeyB2023"})
    by_text = {c["claim"]: c for c in claims}
    assert by_text["Smith et al. (2024) report gains in memory."]["keys"] == []  # "et al." does not split the sentence
    assert by_text["Training improved recall in older adults."]["keys"] == ["KeyA2024", "KeyB2023"]
    assert by_text["Effects faded after six months of follow-up."]["invalid_keys"] == ["Ghost2020"]
    assert by_text["30; memory improved by 10 points"]["kind"] == "table_row"


class FakeCalls:
    """NLI 'Yes' iff the claim's support word appears in the source."""

    def __call__(self, model, prompt, num_predict):
        claim = prompt.split("Claim:\n", 1)[1].split("\n---", 1)[0]
        source = prompt.split("Source: \n", 1)[1].split("\n---", 1)[0]
        return {"text": "Yes" if claim.split()[0] in source else "No"}


def test_citation_quality_follows_autosurvey():
    papers = {"A": {"abstract": "alpha beta", "title": "a"}, "B": {"abstract": "gamma", "title": "b"},
              "C": {"abstract": "alpha", "title": "c"}}
    claims = [
        {"claim": "alpha claim", "keys": ["A", "B"], "invalid_keys": []},   # supported; A relevant, B not
        {"claim": "delta claim", "keys": ["C"], "invalid_keys": []},        # unsupported
        {"claim": "alpha again", "keys": ["A", "C", "X"], "invalid_keys": ["X"]},  # supported; A, C relevant; X invalid
        {"claim": "no citation here", "keys": [], "invalid_keys": []},
    ]
    source = ae.citation_source("abstract", Path("unused"), papers)
    result = ae.citation_quality(FakeCalls(), "m", claims, papers, source)
    assert result["recall"] == round(2 / 3, 4)
    assert result["precision"] == round(3 / 6, 4)  # A, A, C relevant out of A, B, C, A, C, X
    assert result["citation_density"] == 0.75 and result["all_sentence_recall"] == 0.5
    assert result["n_invalid_citations"] == 1
    by_n = result["by_n_citations"]
    assert by_n["1"] == {"n_claims": 1, "recall": 0, "precision": 0.0}
    assert by_n["2"] == {"n_claims": 1, "recall": 1, "precision": 0.5}
    assert by_n["3+"] == {"n_claims": 1, "recall": 1, "precision": round(2 / 3, 4)}

    controls = ae.citation_controls(FakeCalls(), "m", [c for c in claims if c["keys"]], papers, source)
    assert controls["swap"]["n"] == 3 and controls["perturb"]["n"] == 0  # no numbers / direction words to change


def test_fulltext_source_adds_matching_windows(tmp_path: Path):
    import fulltext_retrieval

    body = " ".join(f"filler{i}" for i in range(400)) + " the trial enrolled 482 patients with depression " + \
        " ".join(f"more{i}" for i in range(400))
    (tmp_path / "step5_full_text").mkdir()
    (tmp_path / "step5_full_text" / "K.md").write_text(f"---\ncitation_key: K\n---\n# T\n\n{body}\n", encoding="utf-8")
    source = ae.citation_source("fulltext", tmp_path, {"K": {"abstract": "short abstract", "title": "t"}})
    text = source("A trial of 482 patients with depression", "K")
    assert text.startswith("short abstract\n") and "482 patients" in text
    assert text.count("…") == 2 * fulltext_retrieval.K
    assert ae.perturb("Scores increased by 12.5 points in 2021") == "Scores decreased by 34.1 points in 2021"


def test_naive_prompt_fits_budget():
    papers = {f"Key{i}2024": {"title": "T" * 80, "year": "2024", "abstract": "word " * 600} for i in range(120)}
    prompt, chars = naive_baseline.build_prompt("topic", papers, 2000, input_tokens=24000, max_abstract_chars=1500)
    assert chars < 1500 and len(prompt) / naive_baseline.CHARS_PER_TOKEN < 24000
    assert "[Key0" + "2024]" in prompt and "about 2000 words" in prompt


def test_whole_survey_damage():
    import autosurvey_controls as ac

    survey = "# R\n\n## Executive Summary\n\nS one. S two.\n\n## Theme 1: A\n\n### Consensus\n\nA one. A two.\n\n" \
             "## Theme 2: B\n\nB one.\n\n## Theme 3: C\n\nC one.\n\n## Cross-Theme Analysis\n\nX.\n"
    foreign = "# F\n\n## Theme 1: Zed\n\nZ one.\n"
    forms = ac.damaged_forms(survey, foreign)
    heads = lambda t: __import__("re").findall(r"(?m)^## (.*)$", t)  # noqa: E731
    assert heads(forms["themes_reversed"])[1:4] == ["Theme 3: C", "Theme 2: B", "Theme 1: A"]
    assert heads(forms["theme_repeated"]).count("Theme 1: A") == 2 and heads(forms["theme_repeated"])[-1] == "Cross-Theme Analysis"
    assert heads(forms["half_themes"]) == ["Executive Summary", "Theme 1: A", "Theme 3: C", "Cross-Theme Analysis"]
    assert heads(forms["summary_only"]) == ["Executive Summary"] and heads(forms["all_shuffled"]) == []
    assert "## Theme 2: Zed" in forms["foreign_theme"] and "B one." not in forms["foreign_theme"]
    assert forms == ac.damaged_forms(survey, foreign)  # deterministic
