#!/usr/bin/env python3
"""Tests for the question / argument tooling of ideate_tools.py: argument-check (C1-C24), argument-render, env-probe,
power, the claim lines in concept-index, the two extra paths of link-run, and that validate / append-idea are unchanged.

  python3 -m unittest discover -s .claude/skills/ai-scientist-ideate/scripts/tests -v

Only unittest + tempfile + subprocess + shutil. Every fixture is built in code and lives in a temporary directory;
nothing under ai_scientist/ideas/ or experiments/ is written. One class (TestValidationReplay) READS the validation
generation under ai_scientist/ideas/ and works on a temporary copy of it; it is skipped where that folder is absent.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "ideate_tools.py"
# The copy taken before this change. Present in the working repo, absent elsewhere - those comparisons are skipped then.
REPO = Path(__file__).resolve().parents[5]
OLD_SCRIPT = REPO / "_archive" / "ai-scientist-ideate_pre-question-plan_2026-10-04" / "scripts" / "ideate_tools.py"
# The copy taken before the fixes that followed the validation run (power gained flags; old invocations must not move).
PREV_SCRIPT = REPO / "_archive" / "ai-scientist-ideate_pre-validation-fixes_2026-10-04" / "scripts" / "ideate_tools.py"
# The generation the revised flow was validated on. Read-only evidence: tests copy it to a temp dir first.
VALIDATION_GEN = REPO / "ai_scientist" / "ideas" / "EEG_signal_quality_research" / "_work" / "validation_newflow_gen1"


def run(*args, script=SCRIPT):
    p = subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def dump(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# ------------------------------------------------------------------ fixtures
# The id shapes in use: the role tag after the id ("E3 [tests C1] ..."), its bracketed spelling, the bold heading of
# older archives, and "E3: ...".
EXPERIMENTS = [
    "E0 [instrument] Data and units: 109 subjects of a public motor imagery dataset; the subject is the unit.",
    "**E1 Reference operators** - native, common average and linked mastoids, applied to the same epochs.",
    "E2: [tests C1] Mismatch matrix: train under one reference, test under another; report the decoding accuracy "
    "drop under reference mismatch against the matched-reference calibration accuracy.",
    "[E3 · control C1] Negative control: a mismatch-free relabelling of channels that leaves covariance geometry "
    "untouched must not change decoding accuracy; positive control: an injected rank-1 rotation must.",
    "[E4 · descriptive C2] Estimate how far the covariance geometry moves under each reference, with a 95% CI.",
    "[E5 · release] Release the reference operators and the mismatch matrix.",
]


QUESTION = ("Why does a reference mismatch between training and test reduce motor imagery decoding accuracy, "
            "and is the loss explained by covariance geometry?")


def base_idea() -> dict:
    return {
        "Name": "reference_mismatch_geometry",
        "Title": "Why a reference mismatch lowers motor imagery decoding accuracy: a covariance geometry account",
        "Short Hypothesis": QUESTION + " Although re-referencing is treated as harmless, we claim it rotates the "
                            "covariance geometry.",
        "Related Work": "Re-referencing is treated as a harmless preprocessing choice [keya2020]; no study crosses it.",
        "Abstract": " ".join(["word"] * 200),
        "Experiments": list(EXPERIMENTS),
        "Risk Factors and Limitations": ["Single dataset family.", "Reference operators are linear only."],
    }


def base_argument() -> dict:
    rival = lambda t, by: {"type": t, "how": f"how {t} would arise here", "ruled_out_by": by}
    return {
        "schema": "ai-scientist-argument/1", "variant": "cause",
        "idea": "reference_mismatch_geometry", "generation": 1, "gap": "GAP_001", "angle": "reference mismatch",
        "study_sentence": "Within-subject crossover of training and test reference on decoding accuracy in 109 adults.",
        "question": QUESTION,
        "original_question": None,
        "coverage": {"question": "whole", "angle": "whole", "angle_parts": [{"part": "reference mismatch", "by": "C1"}]},
        "external_check": {"synthetic": False, "real_data": "not applicable", "datasets": ["EEGMMIDB", "Lee2019_MI"],
                           "second_dataset": "not applicable",
                           "inventory": ["~/mne_data/MNE-eegbci-data: 109 subjects, imagery runs",
                                         "~/mne_data/MNE-lee2019-mi-data: second site, another amplifier"]},
        "reader_doubts": [],
        "key_terms": ["reference mismatch", "decoding accuracy", "motor imagery", "covariance geometry"],
        "claims": [
            {
                "id": "C1", "hypothesis": "H1", "primary": True, "kind": "cause", "mode": "test",
                "statement": "Although re-referencing is treated as harmless, a reference mismatch lowers motor imagery "
                             "decoding accuracy because it rotates the covariance geometry the decoder was fitted on.",
                "reasons": ["The decoder is fitted in sensor space and a reference change is a linear map of it."],
                "evidence": [
                    {"experiment": "E2", "measure": "decoding accuracy drop relative to matched-reference calibration accuracy",
                     "would_show": "a drop that grows with the rotation angle",
                     "can_fail": "yes: the reference acts on all channels and the decoder reads all channels; the drop may be 0"},
                    {"experiment": "E3", "measure": "accuracy change under a geometry-preserving relabelling",
                     "would_show": "no change",
                     "can_fail": "yes: the relabelled channels are the ones the decoder reads"}],
                "warrant": "When a decoder is fitted on a covariance structure, then rotating that structure degrades it.",
                "warrant_basis": "keya2020",
                "outcomes": {"if_supported": "We learn the loss is geometric and so repairable by re-alignment.",
                             "if_not": "We learn the loss is an information loss that no re-alignment can repair."},
                "negation": {"text": "A reference mismatch does not lower decoding accuracy.", "verdict": "contestable"},
                "expected_direction": {"direction": "a mismatch lowers accuracy",
                                       "basis": "contested: keya2020 treats re-referencing as harmless; a geometric "
                                                "argument says it cannot be"},
                "falsifier": "E2: mean drop < 2 points with a 95% CI that includes 0.",
                "construction": {
                    "predictor_formula": "pair (train reference, test reference); a reference is a linear map R on all 64 channels",
                    "outcome_formula": "drop = acc(matched pair) - acc(mismatched pair) on held-out trials of the same subject",
                    "shared_terms": [],
                    "computable_without_experiment": "no: the drop depends on how the fitted weights meet the rotated "
                                                     "covariance, which no existing table reports",
                    "free_quantity": "the sensitivity of the fitted decoder to the rotation"},
                "rivals": [rival("chance", "E2 permutation test"), dict(rival("bias", "E3"), main=True),
                           rival("reverse-cause", "design: the reference is assigned"), rival("confounding", "E3"),
                           rival("leakage", "subject-wise splits in E2")],
                "controls": {"negative": "channel relabelling (E3)", "positive": "injected rotation (E3)",
                             "negative_can_move": "yes: it permutes the channels the accuracy is computed from",
                             "positive_expected": "a 30 degree rotation gives a drop of about 8 points: the drop is signed "
                                                  "and unclipped, so the planted loss comes through unchanged"},
                "baseline_predictor": "calibration accuracy",
                "comparator": "matched-reference calibration accuracy",
                "scope": {"internal": "linear references on these recordings", "external": "not dry electrodes",
                          "limits": ["one paradigm"]},
                "power": {"unit": "subjects", "n": 109, "clusters": "1 dataset",
                          "min_detectable": "d >= 0.27 @ 80% power, two-sided alpha = 0.05",
                          "literature_effect": "(TBD)", "verdict": "adequate"},
                "precision_target": None,
            },
            {
                "id": "C2", "hypothesis": None, "primary": False, "kind": "fact", "mode": "estimate",
                "statement": "The covariance geometry moves by a measurable angle under each reference operator.",
                "reasons": ["The operators differ in rank."],
                "evidence": [{"experiment": "E4", "measure": "principal angle between covariance subspaces",
                              "would_show": "an angle with its confidence interval"}],
                "warrant": "When two operators differ in rank, then the subspaces they produce differ.",
                "warrant_basis": "keyb2021",
                "outcomes": {"if_supported": "We learn the size of the shift.", "if_not": "We learn it is below resolution."},
                "negation": {"text": "The geometry does not move.", "verdict": "contestable"},
                "estimate_because": "descriptive: the angle has no direction to test, only a size",
                "falsifier": None,
                "rivals": [],
                "controls": None,
                "baseline_predictor": None,
                "scope": {"internal": "these recordings", "external": "linear references", "limits": []},
                "power": None,
                "precision_target": "95% CI total width <= 0.4 SD",
            },
        ],
        "representation": {
            "sample": {"target": "healthy adult BCI users", "accessible": "109 volunteers of one public dataset",
                       "concern": "single site"},
            "predictor": {"phenomenon": "reference mismatch", "variable": "train/test reference pair",
                          "precision": "exact (assigned)", "accuracy": "exact", "validity": "content: spans the operators in use"},
            "outcome": {"phenomenon": "decoding ability", "variable": "held-out accuracy", "precision": "about 2 points",
                        "accuracy": "unbiased under subject-wise splits", "validity": "criterion: the field's primary metric"},
        },
        "experiments": [
            {"id": "E0", "role": "instrument", "claims": []},
            {"id": "E1", "role": "instrument", "claims": []},
            {"id": "E2", "role": "tests", "claims": ["C1"]},
            {"id": "E3", "role": "control", "claims": ["C1"]},
            {"id": "E4", "role": "descriptive", "claims": ["C2"]},
            {"id": "E5", "role": "release", "claims": []},
        ],
        "tradeoffs": [],
    }


def equivalence_claim() -> dict:
    c = copy.deepcopy(base_argument()["claims"][1])
    c.update(id="C3", mode="equivalence", precision_target=None,
             statement="Although one might expect otherwise, the common average and linked mastoids are equivalent.",
             falsifier="E4: the 90% CI of the difference leaves the +/-2 point margin fixed in advance.",
             controls={"negative": None, "positive": "injected rotation is detected by the same pipeline",
                       "positive_expected": "a planted 4 point difference leaves the +/-2 point margin: the CI is of "
                                            "the signed difference"})
    return c


def tradeoff(**kw) -> dict:
    """A complete tradeoffs row; a test overrides the one field it is about."""
    row = {"gate": "compute", "ids": [], "change": "5 seeds -> 3", "because": "compute gate",
           "lost": "nothing: the seeds only narrow the interval", "still_answers_question": True,
           "covers_gap": True, "covers_angle": True, "why": "same design, same contrast"}
    row.update(kw)
    return row


def idea_asking(question: str, **kw) -> dict:
    """base_idea() whose Short Hypothesis opens with `question` (C20 looks for the question there)."""
    return dict(base_idea(), **{"Short Hypothesis": question + " Although re-referencing is treated as harmless, we "
                                                               "claim it rotates the covariance geometry."}, **kw)


STEP7B = "---\ntopic: \"t\"\ngap: GAP_001\nmove: confirm-assumed\n{study}---\n# Problem and question\n\n## 5. Question\nq?\n"
CONTEXT_FILES = ("argument_r1.json", "step7b_problem.md", "step7b_problem_r1.md", "restatement_1.json",
                 "restatement_2.json", "../step0_session_config.json")
RESTATEMENT = {"research_question": "Why does it drop?", "tested_part": "all of it", "primary_claim": "it rotates",
               "falsifying_experiment": "E2", "biggest_doubt": "One site only, and nothing repeats the contrast elsewhere."}


class ArgumentCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.gen = Path(self._tmp.name) / "topic_research" / "gen_1"
        self.gen.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def check(self, arg, idea="default", extra=(), files=None):
        """Run argument-check --json; returns (exit code, result dict). `files` are the other files of the generation
        the check reads when present: name -> dict (written as JSON) or str (written as text)."""
        dump(self.gen / "argument.json", arg)
        for name in ("idea.json", "idea_draft.json") + CONTEXT_FILES:
            (self.gen / name).unlink(missing_ok=True)
        if idea == "default":
            idea = base_idea()
        if idea is not None:
            dump(self.gen / "idea.json", idea)
        for name, content in (files or {}).items():
            self.assertIn(name, CONTEXT_FILES)
            if isinstance(content, str):
                (self.gen / name).write_text(content, encoding="utf-8")
            else:
                dump(self.gen / name, content)
        code, out, err = run("argument-check", self.gen, "--json", *extra)
        self.assertIn(code, (0, 1), err)
        return code, json.loads(out)

    def assert_only(self, arg, check, level, claim=None, **kw):
        """`arg` trips exactly `check`, at `level`, and nothing else."""
        code, res = self.check(arg, **kw)
        hit = {f["check"] for f in res["errors"] + res["warnings"]}
        self.assertEqual(hit, {check}, res)
        self.assertTrue(res["errors" if level == "ERROR" else "warnings"], res)
        self.assertFalse(res["warnings" if level == "ERROR" else "errors"], res)
        self.assertEqual(code, 1 if level == "ERROR" else 0)
        if claim:
            self.assertIn(claim, {f["claim"] for f in res["errors"] + res["warnings"]})
        return res


class TestArgumentCheck(ArgumentCase):
    def test_pass(self):
        code, res = self.check(base_argument())
        self.assertEqual((code, res), (0, {"errors": [], "warnings": [], "notes": []}))

    def test_pass_text_output(self):
        dump(self.gen / "argument.json", base_argument())
        dump(self.gen / "idea.json", base_idea())
        code, out, _ = run("argument-check", self.gen)
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "argument-check: 0 error(s), 0 warning(s) [idea: idea.json] - OK")

    def test_c1_two_primaries(self):
        a = base_argument()
        a["claims"][1]["primary"] = True
        self.assert_only(a, "C1", "ERROR")

    def test_c1_no_primary(self):
        a = base_argument()
        a["claims"][0]["primary"] = False
        self.assert_only(a, "C1", "ERROR")

    def test_c2_test_without_falsifier(self):
        a = base_argument()
        a["claims"][0]["falsifier"] = ""
        self.assert_only(a, "C2", "ERROR", claim="C1")

    def test_c2_estimate_without_precision_target(self):
        a = base_argument()
        a["claims"][1]["precision_target"] = None
        self.assert_only(a, "C2", "ERROR", claim="C2")

    def test_c3_evidence_cites_unknown_experiment(self):
        a = base_argument()
        a["claims"][0]["evidence"][0]["experiment"] = "E9"
        res = self.assert_only(a, "C3", "ERROR", claim="C1")
        self.assertEqual(len(res["errors"]), 2)  # not in experiments[], not in the idea

    def test_c3_experiment_not_in_idea(self):
        a = base_argument()
        a["experiments"].append({"id": "E7", "role": "release", "claims": []})
        self.assert_only(a, "C3", "ERROR")

    def test_c3_evidence_not_listed_in_experiments(self):
        a = base_argument()
        a["experiments"] = [e for e in a["experiments"] if e["id"] != "E3"] + [{"id": "E1", "role": "control", "claims": ["C1"]}]
        a["experiments"] = [e for i, e in enumerate(a["experiments"]) if not (e["id"] == "E1" and e["role"] == "instrument")]
        res = self.assert_only(a, "C3", "ERROR", claim="C1")
        self.assertIn("not listed in experiments[]", res["errors"][0]["text"])

    def test_c4_missing_role(self):
        a = base_argument()
        del a["experiments"][5]["role"]
        self.assert_only(a, "C4", "ERROR")

    def test_c4_control_without_claim(self):
        a = base_argument()
        a["experiments"][5] = {"id": "E5", "role": "control", "claims": []}
        self.assert_only(a, "C4", "ERROR")

    def test_c5_orphan_claim(self):
        a = base_argument()
        a["experiments"][4]["claims"] = []  # descriptive needs no claim (C4), but C2 is now supported by nothing
        self.assert_only(a, "C5", "ERROR", claim="C2")

    def test_c6_same_outcome_both_ways(self):
        a = base_argument()
        a["claims"][0]["outcomes"]["if_not"] = a["claims"][0]["outcomes"]["if_supported"].upper()
        self.assert_only(a, "C6", "ERROR", claim="C1")

    def test_c6_empty_outcome(self):
        a = base_argument()
        a["claims"][0]["outcomes"]["if_not"] = " "
        self.assert_only(a, "C6", "ERROR", claim="C1")

    def test_c7_negation_not_contestable(self):
        for verdict in ("trivial", "obviously-false"):
            a = base_argument()
            a["claims"][0]["negation"]["verdict"] = verdict
            self.assert_only(a, "C7", "ERROR", claim="C1")

    def test_c8_missing_basic_rival(self):
        a = base_argument()
        a["claims"][0]["rivals"] = [r for r in a["claims"][0]["rivals"] if r["type"] != "confounding"]
        res = self.assert_only(a, "C8", "ERROR", claim="C1")
        self.assertIn("confounding", res["errors"][0]["text"])

    def test_c8_no_control_experiment(self):
        a = base_argument()
        a["experiments"][3]["role"] = "tests"
        a["claims"][0]["evidence"][1]["refuted_if"] = "any accuracy change above 1 point"  # else C2: tests without a rule
        self.assert_only(a, "C8", "ERROR", claim="C1")

    def test_c9_equivalence(self):
        ok = base_argument()
        ok["claims"].append(equivalence_claim())
        ok["experiments"][4]["claims"] = ["C2", "C3"]
        self.assertEqual(self.check(ok)[0], 0)
        a = copy.deepcopy(ok)
        a["claims"][2]["controls"]["positive"] = None
        self.assert_only(a, "C9", "ERROR", claim="C3")
        a = copy.deepcopy(ok)
        a["claims"][2]["falsifier"] = None
        self.assert_only(a, "C9", "ERROR", claim="C3")

    def test_c10_key_term_absent(self):
        a = base_argument()
        a["key_terms"][3] = "zebra crossing"
        res = self.assert_only(a, "C10", "WARN")
        self.assertIn("the question, any claim statement, any Experiments entry", res["warnings"][0]["text"])

    def test_c10_stem_and_cjk(self):
        a = base_argument()
        a["key_terms"] = ["reference mismatches", "decoding accuracies", "motor imagery", "幾何"]
        a["question"] += " (共變異幾何)"
        a["claims"][0]["statement"] += " 幾何"
        idea = idea_asking(a["question"])
        idea["Experiments"][4] += " 共變異幾何的位移"
        self.assertEqual(self.check(a, idea=idea), (0, {"errors": [], "warnings": [], "notes": []}))
        a["key_terms"][3] = "拓樸"
        self.assert_only(a, "C10", "WARN", idea=idea)

    def test_c10_term_count(self):
        a = base_argument()
        a["key_terms"] = a["key_terms"][:3]
        self.assert_only(a, "C10", "WARN")

    def test_c11_validity_without_basis(self):
        for text in ("construct", "construct validity", "Criterion validity."):
            a = base_argument()
            a["representation"]["outcome"]["validity"] = text
            self.assert_only(a, "C11", "WARN")

    def test_c10_short_terms_need_word_boundaries(self):
        a = base_argument()
        a["key_terms"] = ["MI", "ICA", "ERP", "SNR"]
        a["angle"] = "practical interpretation"
        a["coverage"]["angle_parts"] = [{"part": "practical interpretation", "by": "C2"}]
        a["claims"][1]["statement"] += " A practical interpretation."
        a["question"] = "How does minimum practical interpretation matter?"
        a["claims"][0]["statement"] = "Although minimum practical interpretation is assumed, it matters because of x."
        idea = idea_asking(a["question"])
        idea["Experiments"][2] += " minimum practical interpretation"
        res = self.assert_only(a, "C10", "WARN", idea=idea)
        self.assertEqual(len(res["warnings"]), 4, res)  # none of the four is "found" inside another word
        a["question"] = "How do MI, ICA, ERPs and SNR interact?"
        idea["Short Hypothesis"] = a["question"] + " Although ICA is routine, we claim otherwise."
        a["claims"][0]["statement"] = "Although ICA is routine, MI ERPs lose SNR because of x."
        idea["Experiments"][2] += " MI ICA ERP SNR"
        self.assertEqual(self.check(a, idea=idea)[0], 0)

    def test_c11_block_missing(self):
        a = base_argument()
        del a["representation"]["sample"]
        self.assert_only(a, "C11", "WARN")

    def test_c12_underpowered_primary(self):
        a = base_argument()
        a["claims"][0]["power"]["verdict"] = "underpowered"
        self.assert_only(a, "C12", "WARN", claim="C1")

    def test_c13_rival_not_addressed(self):
        for text in ("(not addressed)", "Not Addressed", "(NOT ADDRESSED) - no second site"):
            a = base_argument()
            a["claims"][0]["rivals"][4]["ruled_out_by"] = text
            res = self.assert_only(a, "C13", "WARN", claim="C1")
            self.assertIn("leakage", res["warnings"][0]["text"])

    def test_c14_warrant_basis_tbd(self):
        a = base_argument()
        a["claims"][0]["warrant_basis"] = "(TBD)"
        self.assert_only(a, "C14", "WARN", claim="C1")

    def test_c15_baseline_predictor_not_measured(self):
        a = base_argument()
        a["claims"][0]["baseline_predictor"] = "pupil diameter"
        self.assert_only(a, "C15", "ERROR", claim="C1")

    def test_c15_idea_text_alone_does_not_count(self):
        """E2 of the idea names the calibration accuracy, but no evidence row of the claim measures it."""
        a = base_argument()
        a["claims"][0]["evidence"][0]["measure"] = "decoding accuracy drop"
        self.assert_only(a, "C15", "ERROR", claim="C1")

    def test_c15_one_shared_word_is_not_enough(self):
        """'calibration AUC' / 'calibration accuracy' are not measured by a row that only says 'calibration block'."""
        for name in ("calibration AUC", "calibration accuracy"):
            a = base_argument()
            a["claims"][0].update(baseline_predictor=name, comparator=name)
            a["claims"][0]["evidence"][0]["measure"] = "decoding drop on the calibration block and the calibration session"
            res = self.assert_only(a, "C15", "ERROR", claim="C1")
            self.assertEqual(len(res["errors"]), 1)
            self.assertIn("named in no evidence[].measure", res["errors"][0]["text"])

    def test_c15_alias_in_parentheses(self):
        a = base_argument()
        a["claims"][0].update(baseline_predictor="calibration accuracy (M_cal)", comparator="M_cal")
        a["claims"][0]["evidence"][0]["measure"] = "out-of-sample R2 of M_BCR+M_cal versus M_cal"
        self.assertEqual(self.check(a)[0], 0)

    def test_c15_falsifier_against_a_weaker_comparator(self):
        """The H3 of the MI run: calibration accuracy is measured, but the decisive contrast is against generic
        quality and the increment over the baseline is a secondary, two-sided comparison."""
        a = base_argument()
        a["claims"][0].update(
            baseline_predictor="calibration accuracy (M_cal)", comparator="generic quality G (M_G) and resting SMR (M_SMR)",
            falsifier="E2: paired-bootstrap CI of delta R2 (M_BCR - M_G) includes 0. M_BCR+M_cal versus M_cal is a "
                      "pre-declared secondary comparison.")
        a["claims"][0]["evidence"][0]["measure"] = "out-of-sample R2 of M_BCR versus M_G and M_SMR; M_BCR+M_cal versus M_cal"
        res = self.assert_only(a, "C15", "ERROR", claim="C1")
        self.assertIn("does not start with the baseline predictor", res["errors"][0]["text"])
        a["claims"][0]["comparator"] = "generic quality G (M_G); M_cal only as a secondary comparison"
        self.assert_only(a, "C15", "ERROR", claim="C1")
        a["claims"][0]["comparator"] = "calibration accuracy (M_cal), in a nested model; M_G reported as well"
        self.assertEqual(self.check(a)[0], 0)
        a["claims"][0]["comparator"] = None
        res = self.assert_only(a, "C15", "ERROR", claim="C1")
        self.assertIn("comparator is empty", res["errors"][0]["text"])

    def test_c17_can_fail(self):
        a = base_argument()
        del a["claims"][0]["evidence"][1]["can_fail"]
        res = self.assert_only(a, "C17", "ERROR", claim="C1")
        self.assertIn("E3", res["errors"][0]["text"])
        a = base_argument()
        for ev in a["claims"][0]["evidence"]:
            ev["can_fail"] = "no: the measure is computed on the window the noise is injected into"
        res = self.assert_only(a, "C17", "ERROR", claim="C1")
        self.assertIn("fixed by construction", res["errors"][0]["text"])
        a = base_argument()
        a["claims"][0]["evidence"][1]["can_fail"] = "no: outside the decoding set"  # one row that can fail is enough
        self.assertEqual(self.check(a)[0], 0)

    def test_c17_negative_control_that_cannot_move_the_measure(self):
        """The blocker of the MI run: controls that are zero by construction (channels outside the decoding set)."""
        a = base_argument()
        a["claims"][0]["controls"]["negative_can_move"] = "no: the noise is injected into channels the decoder never reads"
        self.assert_only(a, "C17", "ERROR", claim="C1")
        del a["claims"][0]["controls"]["negative_can_move"]
        self.assert_only(a, "C17", "ERROR", claim="C1")

    def test_c17_not_asked_of_secondary_fact_or_estimate_claims(self):
        a = base_argument()
        a["claims"][1].update(mode="test", falsifier="E4: angle CI includes 0", precision_target=None,
                              expected_direction={"direction": "the angle is above zero", "basis": "unknown: no source reports it"})
        self.assertEqual(self.check(a)[0], 0)  # C2: kind fact, not primary, no can_fail

    def test_c18_incorporation_not_addressed(self):
        a = base_argument()
        a["claims"][0]["rivals"].append({"type": "incorporation", "how": "B is computed where the noise is injected",
                                         "ruled_out_by": "(not addressed)"})
        code, res = self.check(a)
        self.assertEqual(code, 1)
        self.assertEqual([(f["check"], f["claim"]) for f in res["errors"]], [("C18", "C1")])
        self.assertEqual([f["check"] for f in res["warnings"]], ["C13"])
        a["claims"][0]["rivals"][-1]["ruled_out_by"] = "E3"
        self.assertEqual(self.check(a)[0], 0)
        a = base_argument()  # on a secondary fact claim it stays a C13 warning
        a["claims"][1]["rivals"].append({"type": "incorporation", "how": "x", "ruled_out_by": "(not addressed)"})
        self.assert_only(a, "C13", "WARN", claim="C2")

    def test_c16_tradeoff_without_original_question(self):
        a = base_argument()
        a["tradeoffs"] = [tradeoff(change="dropped two of three datasets", lost="whether it holds at a second site",
                                   still_answers_question=False, why="one site only")]
        self.assert_only(a, "C16", "ERROR")
        for bad in ("Does it hold across sites?", {"text": "Does it hold across sites?"},
                    {"text": "Does it hold across sites?", "changed_because": "felt like it"},
                    {"text": "", "changed_because": "budget: two datasets cut"}):  # a string, no reason, no prefix, no text
            a["original_question"] = bad
            res = self.assert_only(a, "C16", "ERROR")
            self.assertIn("changed_because", self.texts(res) if hasattr(self, "texts") else " ".join(f["text"] for f in res["errors"]))
        a["original_question"] = {"text": "Does it hold across sites?", "changed_because": "budget: the compute gate cut two datasets"}
        self.assertEqual(self.check(a), (0, {"errors": [], "warnings": [], "notes": []}))

    def test_c16_tradeoff_that_still_answers(self):
        a = base_argument()
        a["tradeoffs"] = [tradeoff()]
        self.assertEqual(self.check(a)[0], 0)

    def test_schema_unknown_enums(self):
        edits = {"kind": lambda a: a["claims"][1].update(kind="mechanism"),
                 "mode": lambda a: a["claims"][1].update(mode="describe"),
                 "role": lambda a: a["experiments"][5].update(role="cleanup"),
                 "rival": lambda a: a["claims"][0]["rivals"][4].update(type="overfitting"),
                 "negation": lambda a: a["claims"][0]["negation"].update(verdict="fine"),
                 "power": lambda a: a["claims"][0]["power"].update(verdict="ok")}
        for name, edit in edits.items():
            a = base_argument()
            edit(a)
            code, res = self.check(a)
            self.assertEqual(code, 1, name)
            self.assertIn("SCHEMA", {f["check"] for f in res["errors"]}, name)

    def test_schema_missing_keys(self):
        a = base_argument()
        del a["claims"][0]["warrant"]
        res = self.assert_only(a, "SCHEMA", "ERROR", claim="C1")
        self.assertIn("'warrant'", res["errors"][0]["text"])
        a = base_argument()
        del a["study_sentence"]
        self.assert_only(a, "SCHEMA", "ERROR")
        a = base_argument()
        a["schema"] = "ai-scientist-argument/0"
        self.assert_only(a, "SCHEMA", "ERROR")

    def test_no_idea_file_skips_with_notes(self):
        code, res = self.check(base_argument(), idea=None)
        self.assertEqual(code, 0)
        self.assertEqual((res["errors"], res["warnings"]), ([], []))
        self.assertEqual([n["check"] for n in res["notes"]], ["C3", "C10", "C20"])
        code, out, _ = run("argument-check", self.gen)
        self.assertEqual(code, 0)
        for check in ("C3", "C10", "C20"):  # each part that needs the seven fields says it did not run
            self.assertRegex(out, rf"(?m)^NOTE {check}: no idea file read")

    def test_idea_resolution_order(self):
        """idea.json wins over idea_draft.json; --idea wins over both; the {"idea": {...}} wrapper is accepted."""
        a = base_argument()
        dump(self.gen / "argument.json", a)
        bad = base_idea()
        bad["Experiments"] = bad["Experiments"][:3]
        dump(self.gen / "idea_draft.json", {"idea": bad})
        self.assertEqual(run("argument-check", self.gen)[0], 1)  # the draft is used and lacks E3..E5
        dump(self.gen / "idea.json", base_idea())
        self.assertEqual(run("argument-check", self.gen)[0], 0)
        self.assertEqual(run("argument-check", self.gen, "--idea", self.gen / "idea_draft.json")[0], 1)
        self.assertEqual(run("argument-check", self.gen, "--idea", self.gen / "nope.json")[0], 2)

    def test_no_idea_flag_ignores_a_leftover_draft(self):
        """Round 1 after an abandoned pair: the old pair's idea_draft.json must not be checked against."""
        dump(self.gen / "argument.json", base_argument())
        stale = base_idea()
        stale["Experiments"] = ["E0: something else entirely", "E1: another"]
        dump(self.gen / "idea_draft.json", stale)
        self.assertEqual(run("argument-check", self.gen)[0], 1)
        code, out, _ = run("argument-check", self.gen, "--no-idea")
        self.assertEqual(code, 0)
        self.assertRegex(out, r"(?m)^NOTE C3: ")
        self.assertIn("[no idea file]", out)
        self.assertEqual(run("argument-check", self.gen, "--no-idea", "--idea", self.gen / "idea_draft.json")[0], 2)

    def test_text_line_format(self):
        a = base_argument()
        a["claims"][0]["negation"]["verdict"] = "trivial"
        a["key_terms"][3] = "zebra crossing"
        dump(self.gen / "argument.json", a)
        dump(self.gen / "idea.json", base_idea())
        code, out, _ = run("argument-check", self.gen)
        self.assertEqual(code, 1)
        lines = out.strip().splitlines()
        self.assertRegex(lines[0], r"^ERROR C7 C1: \S")
        self.assertRegex(lines[1], r"^WARN C10: \S")
        self.assertRegex(lines[-1], r"^argument-check: 1 error\(s\), 1 warning\(s\).* - REVISE$")

    def test_missing_or_broken_argument_file(self):
        code, out, err = run("argument-check", self.gen)
        self.assertEqual(code, 2)
        self.assertIn("argument.json not found", err)
        (self.gen / "argument.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(run("argument-check", self.gen)[0], 2)
        self.assertEqual(run("argument-render", self.gen)[0], 2)

    def test_unusable_idea_file_is_exit_2_not_a_revision(self):
        dump(self.gen / "argument.json", base_argument())
        draft = self.gen / "idea_draft.json"
        no_exps = base_idea()
        del no_exps["Experiments"]
        for content in ("{bad", json.dumps([base_idea()]), json.dumps(no_exps), json.dumps(dict(base_idea(), Experiments=[]))):
            draft.write_text(content, encoding="utf-8")
            code, out, err = run("argument-check", self.gen)
            self.assertEqual(code, 2, content[:40])
            self.assertIn("not a usable idea file", err)
            self.assertEqual(run("argument-check", self.gen, "--no-idea")[0], 0)

    def test_experiment_id_shapes(self):
        sys.path.insert(0, str(SCRIPT.parent))
        try:
            import ideate_tools as it
        finally:
            sys.path.pop(0)
        for text, want in (("**E0 資料、統一前處理**\n- 本機", "E0"), ("E3: dose-response", "E3"), ("[E3 · tests C1] x", "E3"),
                           ("E3 [tests C1] Main test: x", "E3"), ("E4 [descriptive C2] y", "E4"), ("**E5 [release]** z", "E5"),
                           ("E10 Release: table", "E10"), ("- **[E12 · control C2]** y", "E12"), ("E03", "E3"),
                           ("EEG recordings from E3", None), ("Release the code", None), ("", None)):
            self.assertEqual(it.exp_id_of(text), want, text)

    def test_role_tag_convention_keeps_ids_in_the_experiment_stage(self):
        """The experiment stage (exp_plan.py, not part of this skill) must read the same ids from "E3 [tests C1] ..."."""
        shared = SCRIPT.parents[2] / "ai-scientist" / "scripts"
        if not (shared / "exp_plan.py").exists():
            self.skipTest("exp_plan.py not available")
        sys.path[:0] = [str(SCRIPT.parent), str(shared)]
        try:
            import exp_plan
            import ideate_tools as it
        finally:
            del sys.path[:2]
        entries = ["E0 [instrument] Build the pipeline. x", "E1 [tests C1] Main test: y", "E2 [control C1] Negative control: z",
                   "E3 [descriptive C2] Estimate w", "E4 [release] Package"]
        rows, warnings = exp_plan.split_experiments(entries)
        self.assertEqual(warnings, [])
        self.assertEqual([r["id"] for r in rows], [it.exp_id_of(e) for e in entries])


def with_e6(a: dict, idea: dict | None = None) -> dict:
    """Adds a second experiment with role tests for C1 to the argument; returns the idea that lists it."""
    a["experiments"].append({"id": "E6", "role": "tests", "claims": ["C1"]})
    idea = idea or base_idea()
    idea["Experiments"].append("E6 [tests C1] The same mismatch matrix on a second decoder family.")
    return idea


def estimate_primary() -> dict:
    """base_argument() turned into a descriptive study: C2 (mode estimate) is the primary claim."""
    a = base_argument()
    a["variant"] = "estimate"
    a["claims"][0]["primary"], a["claims"][1]["primary"] = False, True
    a["coverage"].update(question="part", tested_part="how far the covariance geometry moves",
                         untested=[{"part": "why the mismatch lowers decoding accuracy", "terms": [], "by": "C1"}])
    return a


class TestArgumentCheckDesign(ArgumentCase):
    """The checks added or changed after the validation run (C2, C7, C10, C13, C14, C16-C24). Each test trips exactly
    the check it names and shows the neighbouring fixture that passes."""

    def texts(self, res, level="errors"):
        return " || ".join(f["text"] for f in res[level])

    # ---- C2: every experiment that "tests" a claim has a decision rule
    def test_c2_tests_experiment_without_a_decision_rule(self):
        a = base_argument()
        idea = with_e6(a)
        res = self.assert_only(a, "C2", "ERROR", claim="C1", idea=idea)
        self.assertEqual(len(res["errors"]), 1)
        self.assertIn("E6", res["errors"][0]["text"])
        self.assertIn("decision rule", res["errors"][0]["text"])
        ok = copy.deepcopy(a)  # an evidence row with refuted_if
        ok["claims"][0]["evidence"].append({"experiment": "E6", "measure": "the same drop, second decoder family",
                                            "would_show": "the same sign", "can_fail": "yes: another decoder may not care",
                                            "refuted_if": "mean drop below 2 points in the second family"})
        self.assertEqual(self.check(ok, idea=idea), (0, {"errors": [], "warnings": [], "notes": []}))
        bad = copy.deepcopy(a)  # a mention in the falsifier after the deciding experiment is not a rule
        bad["claims"][0]["falsifier"] += " E6 is reported alongside."
        res = self.assert_only(bad, "C2", "ERROR", claim="C1", idea=idea)
        self.assertIn("only mentioned", res["errors"][0]["text"])
        self.assertIn("E2", res["errors"][0]["text"])  # which one decides
        ok = copy.deepcopy(a)  # the experiment the falsifier names FIRST is the deciding one and needs no row of its own
        ok["claims"][0]["falsifier"] = "E6: mean drop < 2 points in the second family; E2 confirms it."
        ok["claims"][0]["evidence"][0]["refuted_if"] = "mean drop < 2 points with a 95% CI that includes 0"
        self.assertEqual(self.check(ok, idea=idea)[0], 0)
        ok = copy.deepcopy(a)  # or it is not a test at all
        ok["experiments"][-1]["role"] = "descriptive"
        self.assertEqual(self.check(ok, idea=idea)[0], 0)

    def test_c2_applies_to_equivalence_claims(self):
        a = base_argument()
        a["claims"].append(equivalence_claim())
        a["experiments"][4].update(role="tests", claims=["C2", "C3"])
        a["claims"][2]["falsifier"] = "the 90% CI of the difference leaves the +/-2 point margin fixed in advance."
        res = self.assert_only(a, "C2", "ERROR", claim="C3")
        self.assertIn("E4", res["errors"][0]["text"])

    # ---- C7: direction-settled passes only as a claim about magnitude
    def test_c7_direction_settled(self):
        a = base_argument()
        a["claims"][0]["negation"]["verdict"] = "direction-settled"
        a["claims"][0]["falsifier"] = "E2: the lower limit of the 95% CI of the mean drop is under 2 points."
        res = self.assert_only(a, "C7", "ERROR", claim="C1")  # no effect size
        self.assertEqual(len(res["errors"]), 1)
        self.assertIn("smallest_effect_of_interest", res["errors"][0]["text"])
        a["claims"][0]["smallest_effect_of_interest"] = "2 accuracy points (design choice: the test-retest spread)"
        self.assertEqual(self.check(a), (0, {"errors": [], "warnings": [], "notes": []}))
        a["claims"][0]["falsifier"] = "E2: the lower limit of the 95% CI is below 0.5 points."  # 0.5 is not zero
        self.assertEqual(self.check(a)[0], 0)
        for zero in ("E2: the 95% CI of the mean drop includes 0.", "E2: mean drop <= 0", "E2: the drop does not differ from zero",
                     "E2: lower CI limit at or below 0 points", "E2: the 95% CI lower bound ≤ 0", "E2: CI overlaps zero",
                     "E2: CI crosses 0", "E2: drop = 0", "E2: drop is not positive", "E2: drop is at most zero",
                     "E2: the interval spans 0", "E2: a non-positive drop"):
            a["claims"][0]["falsifier"] = zero
            res = self.assert_only(a, "C7", "ERROR", claim="C1")
            self.assertEqual(len(res["errors"]), 1, zero)
            self.assertIn("compares with zero", res["errors"][0]["text"])
        for fine in ("E2: the lower limit is below 0.5 points", "E2: p > 0.05 for a drop of 2 points",
                     "E2: fewer than 10 of 109 subjects drop by 2 points", "E2: drop ≤ 0.9 points at alpha = 0.05"):
            a["claims"][0]["falsifier"] = fine
            self.assertEqual(self.check(a), (0, {"errors": [], "warnings": [], "notes": []}), fine)

    def test_c7_direction_settled_applies_to_equivalence_claims(self):
        a = base_argument()
        a["claims"].append(equivalence_claim())
        a["experiments"][4]["claims"] = ["C2", "C3"]
        a["claims"][2]["negation"]["verdict"] = "direction-settled"
        res = self.assert_only(a, "C7", "ERROR", claim="C3")
        self.assertIn("smallest_effect_of_interest", res["errors"][0]["text"])
        a["claims"][2]["smallest_effect_of_interest"] = "2 points (design choice: the margin)"
        self.assertEqual(self.check(a)[0], 0)

    def test_c7_expected_direction(self):
        a = base_argument()
        for edit in (lambda c: c.pop("expected_direction"), lambda c: c["expected_direction"].update(basis="keya2020"),
                     lambda c: c["expected_direction"].update(direction=" ")):  # absent, no prefix, no direction
            a = base_argument()
            edit(a["claims"][0])
            res = self.assert_only(a, "C7", "ERROR", claim="C1")
            self.assertIn("expected_direction", res["errors"][0]["text"])
        a = base_argument()  # a direction the author can name with a settled basis is not "contestable"
        a["claims"][0]["expected_direction"]["basis"] = "settled: eyes-closed alpha raises broadband RMS (textbook physiology)"
        res = self.assert_only(a, "C7", "ERROR", claim="C1")
        self.assertIn("direction-settled", res["errors"][0]["text"])
        a["claims"][0]["negation"]["verdict"] = "direction-settled"
        a["claims"][0]["smallest_effect_of_interest"] = "2 accuracy points (design choice)"
        a["claims"][0]["falsifier"] = "E2: the lower limit of the 95% CI of the mean drop is under 2 points."
        self.assertEqual(self.check(a), (0, {"errors": [], "warnings": [], "notes": []}))
        a = base_argument()  # unknown is an answer; an estimate or equivalence claim is not asked
        a["claims"][0]["expected_direction"]["basis"] = "unknown: nothing in the cards predicts the sign"
        a["claims"].append(equivalence_claim())
        a["experiments"][4]["claims"] = ["C2", "C3"]
        self.assertEqual(self.check(a), (0, {"errors": [], "warnings": [], "notes": []}))

    def test_c7_is_not_asked_of_an_estimate_claim(self):
        for negation in ({"text": "The geometry does not move.", "verdict": "trivial"}, None):
            a = base_argument()
            a["claims"][1]["negation"] = negation
            self.assertEqual(self.check(a), (0, {"errors": [], "warnings": [], "notes": []}))
        a = base_argument()
        a["claims"][0]["negation"] = None  # a test claim still needs it
        self.assert_only(a, "SCHEMA", "ERROR", claim="C1")

    def test_c7_zero_falsifier_is_fine_when_the_direction_is_open(self):
        a = base_argument()  # verdict contestable, falsifier "... a 95% CI that includes 0"
        self.assertEqual(self.check(a)[0], 0)
        a["claims"][1]["negation"]["verdict"] = "direction-settled"  # an estimate claim: nothing more is asked
        self.assertEqual(self.check(a), (0, {"errors": [], "warnings": [], "notes": []}))

    # ---- C10: the Experiments field is read as a whole
    def test_c10_term_split_across_two_entries_passes(self):
        idea = base_idea()
        idea["Experiments"] = [e.replace("covariance geometry", "geometry") if e.startswith("[E3") else
                               e.replace("covariance geometry", "covariance") for e in idea["Experiments"]]
        self.assertFalse(any("covariance" in e and "geometry" in e for e in idea["Experiments"]))
        self.assertEqual(self.check(base_argument(), idea=idea), (0, {"errors": [], "warnings": [], "notes": []}))
        idea["Experiments"] = [e.replace("geometry", "shape") for e in idea["Experiments"]]  # in no entry at all
        res = self.assert_only(base_argument(), "C10", "WARN", idea=idea)
        self.assertIn("any Experiments entry", res["warnings"][0]["text"])

    # ---- C13: one line per rival, told apart by its `how`
    def test_c13_two_rivals_of_one_type_print_two_lines(self):
        a = base_argument()
        a["claims"][0]["rivals"] += [{"type": "other", "how": "templates differ from real artifacts", "ruled_out_by": "(not addressed)"},
                                     {"type": "other", "how": "one amplifier only", "ruled_out_by": "(not addressed)"}]
        res = self.assert_only(a, "C13", "WARN", claim="C1")
        self.assertEqual(len(res["warnings"]), 2)
        self.assertIn("templates", res["warnings"][0]["text"])
        self.assertIn("one amplifier", res["warnings"][1]["text"])

    # ---- C14
    def test_c14_field_convention_on_the_primary_claim(self):
        a = base_argument()
        a["claims"][0]["warrant_basis"] = "(field convention)"
        res = self.assert_only(a, "C14", "WARN", claim="C1")
        self.assertIn("field convention", res["warnings"][0]["text"])
        a = base_argument()
        a["claims"][1]["warrant_basis"] = "(field convention)"  # allowed on a secondary claim
        self.assertEqual(self.check(a), (0, {"errors": [], "warnings": [], "notes": []}))

    # ---- C16: a reworded question is recorded, whatever the cause
    def test_c16_question_differs_from_round_1(self):
        r1 = base_argument()
        a = base_argument()
        a["question"] = a["question"].replace("and is the loss explained", "and how much of the loss is explained")
        idea = idea_asking(a["question"])
        res = self.assert_only(a, "C16", "ERROR", idea=idea, files={"argument_r1.json": r1})
        self.assertIn("argument_r1.json", res["errors"][0]["text"])
        a["original_question"] = {"text": r1["question"], "changed_because": "restatement: the reader read a whether"}
        self.assertEqual(self.check(a, idea=idea, files={"argument_r1.json": r1})[0], 0)

    def test_c16_dashes_and_spacing_are_not_a_rewording(self):
        r1 = base_argument()
        r1["question"] = "Why does a mismatch — of reference — lower accuracy?"
        a = base_argument()
        a["question"] = "Why does a mismatch -  of reference - lower accuracy?"
        a["key_terms"] = []
        code, res = self.check(a, idea=idea_asking("Why does a mismatch – of reference – lower accuracy?"),
                               files={"argument_r1.json": r1})
        self.assertEqual({f["check"] for f in res["errors"] + res["warnings"]}, {"C10"}, res)  # the term count only

    # ---- C17: is the result fixed before the experiment runs?
    def test_c17_construction_missing(self):
        for edit in (lambda c: c.pop("construction"), lambda c: c["construction"].update(outcome_formula=""),
                     lambda c: c["construction"].update(predictor_formula="(TBD)")):
            a = base_argument()
            edit(a["claims"][0])
            res = self.assert_only(a, "C17", "ERROR", claim="C1")
            self.assertEqual(len(res["errors"]), 1)
            self.assertIn("construction is missing", res["errors"][0]["text"])

    def test_c17_computable_without_the_experiment(self):
        a = base_argument()
        a["claims"][0]["construction"]["computable_without_experiment"] = "yes: it follows from the rank of R"
        res = self.assert_only(a, "C17", "ERROR", claim="C1")
        self.assertIn("is yes", res["errors"][0]["text"])
        a["claims"][0]["construction"]["computable_without_experiment"] = "probably not"
        res = self.assert_only(a, "C17", "ERROR", claim="C1")
        self.assertIn("no, partly or yes", res["errors"][0]["text"])
        a["claims"][0]["construction"]["computable_without_experiment"] = "partly: the sign follows from the clean recordings"
        res = self.assert_only(a, "C17", "WARN", claim="C1")
        self.assertIn("Short Hypothesis", res["warnings"][0]["text"])
        self.assertIn("the sign follows", res["warnings"][0]["text"])

    def test_c17_free_quantity(self):
        a = base_argument()
        a["claims"][0]["construction"]["free_quantity"] = " "
        res = self.assert_only(a, "C17", "ERROR", claim="C1")
        self.assertIn("free_quantity", res["errors"][0]["text"])

    def test_c17_positive_control_without_expected_value(self):
        a = base_argument()
        del a["claims"][0]["controls"]["positive_expected"]
        res = self.assert_only(a, "C17", "ERROR", claim="C1")
        self.assertIn("positive_expected", res["errors"][0]["text"])
        a = base_argument()  # any equivalence claim, primary or not
        a["claims"].append(equivalence_claim())
        a["experiments"][4]["claims"] = ["C2", "C3"]
        del a["claims"][2]["controls"]["positive_expected"]
        self.assert_only(a, "C17", "ERROR", claim="C3")
        a = base_argument()  # no positive control, nothing to derive
        a["claims"][0]["controls"]["positive"] = None
        del a["claims"][0]["controls"]["positive_expected"]
        self.assertEqual(self.check(a)[0], 0)

    def test_c17_negative_can_move_on_a_primary_that_is_not_a_cause(self):
        a = base_argument()
        a["variant"] = "none"
        a["claims"][0]["kind"] = "fact"
        self.assertEqual(self.check(a), (0, {"errors": [], "warnings": [], "notes": []}))
        del a["claims"][0]["controls"]["negative_can_move"]
        res = self.assert_only(a, "C17", "ERROR", claim="C1")
        self.assertIn("negative_can_move", res["errors"][0]["text"])
        a["claims"][0]["controls"]["negative_can_move"] = "no: the relabelled channels are outside the decoding set"
        self.assert_only(a, "C17", "ERROR", claim="C1")

    # ---- C18: what the two sides of the contrast share
    def shared(self) -> dict:
        a = base_argument()
        a["claims"][0]["construction"].update(
            predictor_formula="dose = a * RMS_r * c", outcome_formula="floor_r = min a : AUC[S(x + a*RMS_r*c), S(x)] >= 0.75",
            shared_terms=["RMS_r"],
            computable_without_experiment="no: RMS_r scales the dose only; where S leaves the clean distribution depends on "
                                          "the background inside the band S reads, which no table gives")
        a["claims"][0]["rivals"].append({"type": "incorporation", "how": "dose and floor are both scaled by RMS_r",
                                         "ruled_out_by": "E3"})
        return a

    def test_c18_shared_terms(self):
        self.assertEqual(self.check(self.shared()), (0, {"errors": [], "warnings": [], "notes": []}))
        a = self.shared()
        a["claims"][0]["construction"]["shared_terms"] = ["RMS_r", "sigma_bg"]
        res = self.assert_only(a, "C18", "ERROR", claim="C1")
        self.assertEqual(len(res["errors"]), 1)
        self.assertIn("sigma_bg", res["errors"][0]["text"])
        a = self.shared()
        a["claims"][0]["rivals"].pop()
        res = self.assert_only(a, "C18", "ERROR", claim="C1")
        self.assertIn("incorporation", res["errors"][0]["text"])
        self.assertIn("RMS_r", res["errors"][0]["text"])
        a = self.shared()  # a listed term that is in ONE formula only (here: the predictor's)
        a["claims"][0]["construction"]["shared_terms"] = ["RMS_r", "dose"]
        res = self.assert_only(a, "C18", "ERROR", claim="C1")
        self.assertEqual(len(res["errors"]), 1)
        self.assertIn("'dose' does not occur in both", res["errors"][0]["text"])

    def test_c18_a_shared_symbol_left_out_of_the_list(self):
        """The validation idea's own pair: dose and floor are both scaled by RMS_r, and shared_terms said []."""
        a = self.shared()
        a["claims"][0]["construction"]["shared_terms"] = []
        a["claims"][0]["rivals"].pop()
        res = self.assert_only(a, "C18", "ERROR", claim="C1")
        self.assertEqual(len(res["errors"]), 1)
        self.assertIn("'RMS_r' occurs in both formulas", res["errors"][0]["text"])
        a = self.shared()  # listed, yet "nothing is computable without the experiment": show the substitution
        self.assertEqual(self.check(a)[1]["warnings"], [])
        a["claims"][0]["construction"]["computable_without_experiment"] = "no: needs the injection"
        res = self.assert_only(a, "C17", "WARN", claim="C1")
        self.assertIn("substitution", res["warnings"][0]["text"])
        a = base_argument()  # an all-capitals token in both formulas is only asked about
        a["claims"][0]["construction"].update(predictor_formula="dose in multiples of the run's RMS",
                                              outcome_formula="the AUC of S against the clean epochs, strength in RMS units")
        res = self.assert_only(a, "C18", "WARN", claim="C1")
        self.assertIn("'RMS'", res["warnings"][0]["text"])
        self.assertEqual(len(res["warnings"]), 1)  # AUC is a function name, not a shared quantity

    def test_c18_incorporation_ruled_out_by_free_text(self):
        a = self.shared()
        a["claims"][0]["rivals"][-1]["ruled_out_by"] = "stated as an estimate of size, not a test of direction"
        res = self.assert_only(a, "C18", "ERROR", claim="C1")
        self.assertIn("ruled_out_by", res["errors"][0]["text"])
        a["claims"][0]["rivals"][-1]["ruled_out_by"] = "E9"  # an experiment that does not exist
        self.assert_only(a, "C18", "ERROR", claim="C1")
        a["claims"][0]["rivals"][-1]["ruled_out_by"] = "design: the time family is outside the primary endpoint"
        self.assertEqual(self.check(a)[0], 0)
        a = base_argument()  # free text is accepted on a secondary fact claim
        a["claims"][1]["rivals"].append({"type": "incorporation", "how": "x", "ruled_out_by": "reported as an estimate"})
        self.assertEqual(self.check(a)[0], 0)

    # ---- C19: every removal or demotion since round 1 has a row
    def ledger(self, r1_edit, check_text, ids):
        r1 = base_argument()
        r1_edit(r1)
        a = base_argument()
        res = self.assert_only(a, "C19", "ERROR", files={"argument_r1.json": r1})
        for needle in check_text:
            self.assertIn(needle, self.texts(res))
        a["tradeoffs"] = [tradeoff(gate="none", ids=ids, change="cut", lost="the second site")]
        self.assertEqual(self.check(a, files={"argument_r1.json": r1}), (0, {"errors": [], "warnings": [], "notes": []}))
        return res

    def test_c19_claim_gone(self):
        def edit(r1):
            r1["claims"].append(dict(copy.deepcopy(r1["claims"][1]), id="C4"))
        res = self.ledger(edit, ["C4", "gone"], ["C4"])
        self.assertEqual(len(res["errors"]), 1)

    def test_c19_mode_changed(self):
        res = self.ledger(lambda r1: r1["claims"][1].update(mode="test", falsifier="E4: CI includes 0"),
                          ["C2", "mode changed test -> estimate"], ["C2"])
        self.assertEqual([f["claim"] for f in res["errors"]], ["C2"])

    def test_c19_primary_moved(self):
        def edit(r1):
            r1["claims"][0]["primary"], r1["claims"][1]["primary"] = False, True
        res = self.ledger(edit, ["primary changed false -> true", "primary changed true -> false"], ["C1", "C2"])
        self.assertEqual(sorted(f["claim"] for f in res["errors"]), ["C1", "C2"])

    def test_c19_experiment_gone_or_role_changed(self):
        res = self.ledger(lambda r1: r1["experiments"].append({"id": "E8", "role": "descriptive", "claims": ["C2"]}),
                          ["E8", "gone"], ["E8"])
        self.assertEqual(len(res["errors"]), 1)
        self.ledger(lambda r1: r1["experiments"][4].update(role="control"), ["E4", "role changed control -> descriptive"], ["E4"])

    def test_c19_nothing_changed_since_round_1(self):
        self.assertEqual(self.check(base_argument(), files={"argument_r1.json": base_argument()}),
                         (0, {"errors": [], "warnings": [], "notes": []}))

    def test_c19_rows(self):
        a = base_argument()
        a["tradeoffs"] = [tradeoff(lost="")]
        res = self.assert_only(a, "C19", "ERROR")
        self.assertIn("lost is empty", res["errors"][0]["text"])
        a["tradeoffs"] = [tradeoff(covers_gap=False)]
        res = self.assert_only(a, "C19", "ERROR")
        self.assertIn("gap", res["errors"][0]["text"])
        a["tradeoffs"] = [tradeoff(covers_angle=False)]
        res = self.assert_only(a, "C19", "ERROR")
        self.assertIn("covers_angle", res["errors"][0]["text"])
        a["coverage"].update(angle="part", angle_dropped="the coupling half of the angle: no experiment crosses two metrics")
        self.assertEqual(self.check(a)[0], 0)

    # ---- C20: what the question, the title and the short hypothesis promise
    def part(self, **untested) -> dict:
        a = base_argument()
        a["coverage"] = {"question": "part", "tested_part": "whether a mismatch lowers accuracy",
                         "untested": [dict({"part": "how far the geometry moves", "terms": ["principal angle"], "by": "C2"},
                                           **untested)], "angle": "whole",
                         "angle_parts": [{"part": "reference mismatch", "by": "C1"}]}
        return a

    def test_c20_coverage_missing(self):
        a = base_argument()
        del a["coverage"]
        res = self.assert_only(a, "C20", "ERROR")
        self.assertIn("coverage is missing", res["errors"][0]["text"])

    def test_c20_part(self):
        self.assertEqual(self.check(self.part()), (0, {"errors": [], "warnings": [], "notes": []}))
        a = self.part()
        a["coverage"]["untested"] = []
        res = self.assert_only(a, "C20", "ERROR")
        self.assertIn("untested", res["errors"][0]["text"])
        a = self.part()
        a["coverage"]["tested_part"] = ""
        self.assert_only(a, "C20", "ERROR")
        for by in ("C9", "C1", None, ["C2", "C9"], []):  # unknown, the primary itself, absent, a list with an unknown id
            res = self.assert_only(self.part(by=by), "C20", "ERROR")
            self.assertIn("how far the geometry moves", res["errors"][0]["text"])
            self.assertIn("no claim covers", res["errors"][0]["text"])
        self.assertEqual(self.check(self.part(by=["C2"]))[0], 0)  # several secondary claims may carry one part
        for by in ({"claim": "C2"}, 2, [["C2"]]):  # a shape nobody expected is a SCHEMA finding, not a crash
            res = self.assert_only(self.part(by=by), "SCHEMA", "ERROR")
            self.assertIn("coverage.untested[0].by", res["errors"][0]["text"])

    def test_c20_angle_part_without_reason(self):
        a = base_argument()
        a["coverage"]["angle"] = "part"
        res = self.assert_only(a, "C20", "ERROR")
        self.assertIn("angle_dropped", res["errors"][0]["text"])

    def test_c20_title_names_an_untested_part(self):
        res = self.assert_only(self.part(terms=["covariance geometry", "principal angle"]), "C20", "ERROR")
        self.assertEqual(len(res["errors"]), 1)
        self.assertIn("Title", res["errors"][0]["text"])
        self.assertIn("covariance geometry", res["errors"][0]["text"])
        self.assertIn("C2", res["errors"][0]["text"])
        self.assertIn("no revision", res["errors"][0]["text"])  # a wording repair in the draft
        code, res = self.check(self.part(terms=["covariance geometry"]), idea=None)  # no idea file, no Title to read
        self.assertEqual((code, res["errors"], res["warnings"]), (0, [], []))

    def test_c20_short_hypothesis_without_the_question(self):
        idea = dict(base_idea(), **{"Short Hypothesis": "Why does a reference mismatch reduce accuracy? Although ..."})
        res = self.assert_only(base_argument(), "C20", "WARN", idea=idea)
        self.assertIn("Short Hypothesis", res["warnings"][0]["text"])

    def test_c20_dash_and_quote_variants_do_not_trip_it(self):
        a = base_argument()
        a["question"] = "Why does a ‘reference’ mismatch — between training and test — reduce motor imagery   decoding accuracy, " \
                        "and is the loss explained by covariance geometry?"
        idea = idea_asking("Why does a 'reference' mismatch - between training and test - reduce motor imagery decoding "
                           "accuracy, and is the loss explained by covariance geometry?")
        self.assertEqual(self.check(a, idea=idea), (0, {"errors": [], "warnings": [], "notes": []}))

    # ---- C21: an estimate is the primary claim only in a descriptive study
    def test_c21_estimate_primary(self):
        a = estimate_primary()
        for study in ("study: analytic        # analytic | descriptive\n", ""):  # declared, or a step7b without the line
            res = self.assert_only(a, "C21", "ERROR", claim="C2", files={"step7b_problem.md": STEP7B.format(study=study)})
            self.assertIn("study: descriptive", res["errors"][0]["text"])
        code, res = self.check(a)  # no step7b: not checked, and said so
        self.assertEqual((code, res["errors"], res["warnings"]), (0, [], []))
        self.assertEqual([(n["check"], n["claim"]) for n in res["notes"]], [("C21", "C2")])
        descriptive = {"step7b_problem.md": STEP7B.format(study="study: descriptive\n")}
        self.assertEqual(self.check(a, files=descriptive), (0, {"errors": [], "warnings": [], "notes": []}))

    def test_c21_downgraded_since_round_1(self):
        a = estimate_primary()
        a["tradeoffs"] = [tradeoff(gate="coherence", ids=["C1", "C2"], change="C1 demoted, C2 made primary",
                                   lost="the test of the mechanism")]
        files = {"step7b_problem.md": STEP7B.format(study="study: descriptive\n"), "argument_r1.json": base_argument()}
        res = self.assert_only(a, "C21", "ERROR", claim="C2", files=files)
        self.assertIn("original_question", res["errors"][0]["text"])
        a["original_question"] = {"text": "Why does it drop?", "changed_because": "coherence: the test was by construction"}
        self.assertEqual(self.check(a, files=files)[0], 0)
        files["argument_r1.json"] = estimate_primary()  # it was an estimate from the start
        a["original_question"], a["tradeoffs"] = None, []
        self.assertEqual(self.check(a, files=files), (0, {"errors": [], "warnings": [], "notes": []}))

    def test_c21_a_test_primary_is_not_asked(self):
        files = {"step7b_problem.md": STEP7B.format(study="study: analytic\n")}
        self.assertEqual(self.check(base_argument(), files=files), (0, {"errors": [], "warnings": [], "notes": []}))

    # ---- C22: the blind reader's doubts
    def doubt(self, **kw) -> dict:
        return dict({"source": "restatement-1", "doubt": "one site only", "level": "design", "response": "fixed",
                     "how": "E4 repeats the contrast on the second dataset"}, **kw)

    def test_c22_restatement_without_rows(self):
        a = base_argument()
        res = self.assert_only(a, "C22", "ERROR", files={"restatement_1.json": RESTATEMENT})
        self.assertIn("restatement-1", res["errors"][0]["text"])
        a["reader_doubts"] = [self.doubt()]
        self.assertEqual(self.check(a, files={"restatement_1.json": RESTATEMENT}),
                         (0, {"errors": [], "warnings": [], "notes": []}))
        both = {"restatement_1.json": RESTATEMENT, "restatement_2.json": RESTATEMENT}
        res = self.assert_only(a, "C22", "ERROR", files=both)
        self.assertIn("restatement-2", res["errors"][0]["text"])
        a["reader_doubts"].append(self.doubt(source="restatement-2", level="wording"))
        self.assertEqual(self.check(a, files=both)[0], 0)

    def test_c22_doubt_not_fixed(self):
        a = base_argument()
        a["reader_doubts"] = [self.doubt(), self.doubt(doubt="the control is weak", response="not-fixed",
                                                       how="data: no second dataset with rest runs on this machine")]
        res = self.assert_only(a, "C22", "WARN", files={"restatement_1.json": RESTATEMENT})
        self.assertEqual(len(res["warnings"]), 1)
        self.assertIn("the control is weak", res["warnings"][0]["text"])
        self.assertIn("Blind restatement unresolved", res["warnings"][0]["text"])

    def test_c22_second_restatement_due(self):
        r1 = base_argument()
        r1["claims"][0]["falsifier"] = "E2: mean drop < 1 point with a 95% CI that includes 0."
        a = base_argument()
        a["reader_doubts"] = [self.doubt()]
        files = {"restatement_1.json": RESTATEMENT, "argument_r1.json": r1}
        res = self.assert_only(a, "C22", "WARN", files=files)
        self.assertIn("second blind restatement", res["warnings"][0]["text"])
        self.assertIn("falsifier", res["warnings"][0]["text"])
        a["reader_doubts"].append(self.doubt(source="restatement-2"))  # done: not asked again
        self.assertEqual(self.check(a, files=dict(files, **{"restatement_2.json": RESTATEMENT}))[0:1], (0,))
        self.assertEqual(self.check(a, files=dict(files, **{"restatement_2.json": RESTATEMENT}))[1]["warnings"], [])
        a["reader_doubts"].pop()
        files["argument_r1.json"] = base_argument()  # the reader of round 1 saw this very claim
        self.assertEqual(self.check(a, files=files), (0, {"errors": [], "warnings": [], "notes": []}))
        r1["claims"][1]["statement"] += " (reworded)"  # a secondary claim changing is not a reason either
        r1["claims"][0]["falsifier"] = a["claims"][0]["falsifier"]
        self.assertEqual(self.check(a, files=dict(files, **{"argument_r1.json": r1}))[1]["warnings"], [])

    def test_c22_rows_without_a_restatement_file_are_only_reported(self):
        a = base_argument()
        a["reader_doubts"] = [self.doubt()]  # depth quick writes []; rows without a file are not an error
        self.assertEqual(self.check(a), (0, {"errors": [], "warnings": [], "notes": []}))

    # ---- C23: a route out of the model and out of the one dataset
    def synthetic(self, **kw) -> dict:
        a = base_argument()
        a["external_check"].update(dict({"synthetic": True, "real_data": "E4"}, **kw))
        return a

    def test_c23_missing(self):
        a = base_argument()
        del a["external_check"]
        res = self.assert_only(a, "C23", "ERROR")
        self.assertIn("external_check is missing", res["errors"][0]["text"])

    def test_c23_synthetic_evidence(self):
        self.assertEqual(self.check(self.synthetic()), (0, {"errors": [], "warnings": [], "notes": []}))
        for value in ("", "not applicable", "planned", "E0", "E5"):  # nothing; or an instrument / release step
            res = self.assert_only(self.synthetic(real_data=value), "C23", "ERROR")
            self.assertIn("real recordings", res["errors"][0]["text"], value)
        res = self.assert_only(self.synthetic(real_data="E9"), "C23", "ERROR")
        self.assertIn("E9", res["errors"][0]["text"])
        why = "none: no dataset on this machine has labelled real artifacts"
        res = self.assert_only(self.synthetic(real_data=why, inventory=[]), "C23", "ERROR")
        self.assertIn("inventory", res["errors"][0]["text"])
        self.assert_only(self.synthetic(real_data=why, inventory=[""]), "C23", "ERROR")  # an empty entry is no inventory
        self.assert_only(self.synthetic(real_data="none:"), "C23", "ERROR")  # a reason is required
        # round 1 (no argument_r1.json yet): "none" is not accepted before the scheduled revision has tried
        res = self.assert_only(self.synthetic(real_data=why + " (E8 was cut)"), "C23", "ERROR")
        self.assertEqual(len(res["errors"]), 1)
        self.assertIn("round 1", res["errors"][0]["text"])
        # afterwards it is recorded, not blocked
        a = self.synthetic(real_data=why + " (E8 was cut)")
        res = self.assert_only(a, "C23", "WARN", files={"argument_r1.json": a})
        self.assertIn("No real-data validation", res["warnings"][0]["text"])
        self.assertIn("labelled real artifacts", res["warnings"][0]["text"])

    def test_c23_single_dataset(self):
        one = lambda **kw: dict(base_argument(), external_check=dict(base_argument()["external_check"],
                                                                     datasets=["EEGMMIDB"], **kw))
        res = self.assert_only(one(), "C23", "ERROR")
        self.assertIn("second", res["errors"][0]["text"])
        self.assertEqual(self.check(one(second_dataset="E4"))[0], 0)
        res = self.assert_only(one(second_dataset="none: the second set has task runs only, no rest"), "C23", "WARN")
        self.assertIn("Single dataset", res["warnings"][0]["text"])
        res = self.assert_only(one(second_dataset="none: no rest runs", inventory=[]), "C23", "ERROR")
        both = one(synthetic=True, real_data="none: no labelled artifacts", second_dataset="none: no rest runs")
        res = self.assert_only(both, "C23", "WARN", files={"argument_r1.json": both})
        self.assertEqual(len(res["warnings"]), 2)

    def test_c23_config_without_probe(self):
        config = {"topic": "t", "local_environment": {"cached_data": ["~/mne_data"], "packages_present": ["mne 1.13"]}}
        res = self.assert_only(base_argument(), "C23", "WARN", files={"../step0_session_config.json": config})
        self.assertIn("env-probe", res["warnings"][0]["text"])
        config["local_environment"]["probe"] = {"date": "2026-10-04T10:00:00+08:00", "data_roots": {}, "packages": {}}
        self.assertEqual(self.check(base_argument(), files={"../step0_session_config.json": config}),
                         (0, {"errors": [], "warnings": [], "notes": []}))
        self.assertEqual(self.check(base_argument(), files={"../step0_session_config.json": "{not json"})[0], 0)  # ignored

    # ---- C24: the rival a skeptical reader reaches for first
    def test_c24_main_rival(self):
        a = base_argument()
        del a["claims"][0]["rivals"][1]["main"]
        res = self.assert_only(a, "C24", "ERROR", claim="C1")
        self.assertIn("found 0", res["errors"][0]["text"])
        a = base_argument()
        a["claims"][0]["rivals"][0]["main"] = True
        res = self.assert_only(a, "C24", "ERROR", claim="C1")
        self.assertIn("found 2", res["errors"][0]["text"])

    def test_c24_main_rival_not_addressed(self):
        a = base_argument()
        a["claims"][0]["rivals"][1]["ruled_out_by"] = "(not addressed)"
        code, res = self.check(a)
        self.assertEqual([(f["check"], f["claim"]) for f in res["errors"]], [("C24", "C1")])
        self.assertIn("main rival", res["errors"][0]["text"])
        self.assertEqual([f["check"] for f in res["warnings"]], ["C13"])

    def test_c24_not_asked_of_an_estimate_primary(self):
        a = estimate_primary()
        for r in a["claims"][0]["rivals"]:
            r.pop("main", None)
        files = {"step7b_problem.md": STEP7B.format(study="study: descriptive\n")}
        self.assertEqual(self.check(a, files=files), (0, {"errors": [], "warnings": [], "notes": []}))

    # ================================================================== repairs after the review of the fixes
    # ---- C17: the positive control, the statistic's shape, a primary claim rewritten in round 2
    def test_c17_no_positive_control_on_a_tested_primary(self):
        a = base_argument()
        a["claims"][0]["controls"] = None
        res = self.assert_only(a, "C17", "WARN", claim="C1")
        self.assertEqual(len(res["warnings"]), 1)
        self.assertIn("no positive control", res["warnings"][0]["text"])
        self.assertIn("Risk Factors", res["warnings"][0]["text"])

    def test_c17_planted_value_through_an_absolute_value(self):
        """The validation idea's E4: |floor(R02) - floor(R01)| cannot return a planted shift of 2 unchanged."""
        a = base_argument()
        a["claims"][0]["evidence"][0]["measure"] = "|acc(matched) - acc(mismatched)| relative to matched-reference calibration accuracy"
        a["claims"][0]["controls"]["positive_expected"] = "8 points: the rotation costs 8 points, so the drop is 8"
        res = self.assert_only(a, "C17", "WARN", claim="C1")
        self.assertEqual(len(res["warnings"]), 2, res)
        self.assertIn("positive_expected", res["warnings"][0]["text"])
        self.assertIn("absolute value", res["warnings"][0]["text"])
        self.assertIn("scope.limits", res["warnings"][1]["text"])
        a["claims"][0]["controls"]["positive_expected"] = "8 points only when the unplanted drop d >= 0: |d + 8| - |d| = 8 there"
        a["claims"][0]["scope"]["limits"].append("the claim is unsigned: a gain under mismatch would count as well")
        self.assertEqual(self.check(a), (0, {"errors": [], "warnings": [], "notes": []}))
        a = base_argument()  # a rank statistic; "rank-1" in the measure is not one
        a["claims"][0]["evidence"][0]["measure"] += " after a rank-1 rotation"
        self.assertEqual(self.check(a)[1]["warnings"], [])
        a["claims"][0]["falsifier"] = "E2: the rank of the mismatched pair among 9 pairs is above 2."
        res = self.assert_only(a, "C17", "WARN", claim="C1")
        self.assertIn("a rank", res["warnings"][0]["text"])

    def test_c17_primary_rewritten_but_construction_untouched(self):
        r1 = base_argument()
        r1["claims"][0].update(mode="equivalence", statement="Although one might expect a loss, a reference mismatch leaves "
                               "motor imagery decoding accuracy unchanged because the covariance geometry is preserved.")
        a = base_argument()
        a["tradeoffs"] = [tradeoff(gate="none", ids=["C1"], change="equivalence -> test", lost="nothing: the claim is sharper")]
        res = self.assert_only(a, "C17", "WARN", claim="C1", files={"argument_r1.json": r1})
        self.assertEqual(len(res["warnings"]), 1)
        for word in ("statement", "mode", "construction", "positive_expected", "steps 1-6"):
            self.assertIn(word, res["warnings"][0]["text"])
        a["claims"][0]["construction"]["free_quantity"] += " (re-derived for the test claim)"
        a["claims"][0]["controls"]["positive_expected"] += "; re-derived for the one-sided rule"
        self.assertEqual(self.check(a, files={"argument_r1.json": r1})[1]["warnings"], [])

    # ---- C19: an id that changed meaning, an experiment moved to another claim
    def test_c19_kind_changed_or_id_reused(self):
        res = self.ledger(lambda r1: r1["claims"][1].update(kind="evaluation"), ["C2", "kind changed evaluation -> fact"], ["C2"])
        self.assertEqual(len(res["errors"]), 1)
        res = self.ledger(lambda r1: r1["claims"][1].update(
            statement="Dry electrodes raise impedance in elderly volunteers during overnight sleep staging."),
            ["C2", "no longer reads as the claim", "never reused"], ["C2"])
        self.assertEqual(len(res["errors"]), 1)
        r1 = base_argument()  # a reworded claim is not a reused id
        r1["claims"][1]["statement"] = "Each reference operator shifts the covariance geometry by an angle we can measure."
        self.assertEqual(self.check(base_argument(), files={"argument_r1.json": r1}), (0, {"errors": [], "warnings": [], "notes": []}))

    def test_c19_experiment_moved_to_another_claim(self):
        res = self.ledger(lambda r1: r1["experiments"][3].update(claims=["C2"]), ["E3", "claims changed C2 -> C1"], ["E3"])
        self.assertEqual(len(res["errors"]), 1)
        r1 = base_argument()  # a claim that exists in only one of the two files does not make its experiments "moved"
        r1["claims"].append(dict(copy.deepcopy(r1["claims"][1]), id="C4"))
        r1["experiments"][4]["claims"] = ["C2", "C4"]
        a = base_argument()
        a["tradeoffs"] = [tradeoff(gate="none", ids=["C4"], change="C4 cut", lost="the second estimate")]
        self.assertEqual(self.check(a, files={"argument_r1.json": r1}), (0, {"errors": [], "warnings": [], "notes": []}))

    # ---- C20: the angle phrase by phrase; the self-assessed "whole" asked again of the claim's text
    def test_c20_angle_parts(self):
        a = base_argument()
        del a["coverage"]["angle_parts"]
        res = self.assert_only(a, "C20", "ERROR")
        self.assertIn("angle_parts", res["errors"][0]["text"])
        a = base_argument()
        a["coverage"]["angle_parts"][0]["by"] = "C9"
        res = self.assert_only(a, "C20", "ERROR")
        self.assertIn("neither a claim id", res["errors"][0]["text"])
        a = base_argument()  # the validation idea: "dose-response and coupling", and nothing about coupling
        a["angle"] = "reference mismatch and coupling of metrics"
        res = self.assert_only(a, "C20", "ERROR")
        self.assertEqual(len(res["errors"]), 1)
        self.assertIn("'coupling'", res["errors"][0]["text"])
        self.assertIn("'metrics'", res["errors"][0]["text"])
        self.assertIn("before round 1", res["errors"][0]["text"])
        a["coverage"]["angle_parts"].append({"part": "coupling of metrics", "by": "C2"})  # named, but nothing in C2 is about it
        res = self.assert_only(a, "C20", "WARN")
        self.assertEqual(len(res["warnings"]), 1)
        self.assertIn("'coupling'", res["warnings"][0]["text"])
        self.assertIn("C2", res["warnings"][0]["text"])
        a["coverage"]["angle_parts"][1]["by"] = "none"  # the honest answer needs angle: part and the reason
        res = self.assert_only(a, "C20", "ERROR")
        self.assertIn("by: none", res["errors"][0]["text"])
        a["coverage"].update(angle="part", angle_dropped="coupling: no experiment crosses two metrics; dropped at B4 for budget")
        self.assertEqual(self.check(a), (0, {"errors": [], "warnings": [], "notes": []}))

    def test_c20_angle_part_covered_by_an_experiment(self):
        a = base_argument()
        a["angle"] = "reference mismatch and the mismatch matrix"
        a["coverage"]["angle_parts"].append({"part": "mismatch matrix", "by": "E2"})
        self.assertEqual(self.check(a), (0, {"errors": [], "warnings": [], "notes": []}))  # E2's entry says "Mismatch matrix"
        a["coverage"]["angle_parts"][1]["by"] = "E0"
        res = self.assert_only(a, "C20", "WARN")
        self.assertIn("'matrix'", res["warnings"][0]["text"])
        code, res = self.check(a, idea=None)  # without the Experiments entries an experiment's text is not read
        self.assertEqual((code, res["errors"], res["warnings"]), (0, [], []))
        self.assertIn("C20", [n["check"] for n in res["notes"]])

    def test_c20_whole_question_but_a_key_term_is_outside_the_tested_claim(self):
        a = base_argument()
        a["claims"][0]["statement"] = a["claims"][0]["statement"].replace("covariance geometry", "channel layout")
        res = self.assert_only(a, "C20", "WARN")
        self.assertEqual(len(res["warnings"]), 1)
        self.assertIn("'covariance geometry'", res["warnings"][0]["text"])
        self.assertIn("Title names it too", res["warnings"][0]["text"])
        code, res = self.check(a, idea=None)
        self.assertNotIn("Title", res["warnings"][0]["text"])
        a["coverage"].update(question="part", tested_part="why a mismatch lowers accuracy",
                             untested=[{"part": "whether covariance geometry explains it", "terms": [], "by": "C2"}])
        self.assertEqual(self.check(a)[1]["warnings"], [])

    # ---- C21: every estimate says why it is one
    def test_c21_estimate_because(self):
        for value in (None, "", "because the direction is known", "size open: no colon after the prefix word"):
            a = base_argument()
            a["claims"][1]["estimate_because"] = value
            res = self.assert_only(a, "C21", "ERROR", claim="C2")
            self.assertIn("estimate_because", res["errors"][0]["text"])
        a = base_argument()
        a["claims"][1]["estimate_because"] = "size-open: the operators differ in rank, so the angle is above zero; its size is not known"
        self.assertEqual(self.check(a), (0, {"errors": [], "warnings": [], "notes": []}))
        a["claims"][1]["estimate_because"] = ("by-construction: the twins share a numerator, so a test of direction was given up; "
                                              "a reader no longer learns whether the difference exceeds the noise")
        res = self.assert_only(a, "C21", "WARN", claim="C2")
        self.assertIn("scope given up", res["warnings"][0]["text"])
        self.assertIn("the twins share a numerator", res["warnings"][0]["text"])

    def test_c21_estimates_outnumber_tests_in_an_analytic_study(self):
        a = base_argument()
        a["claims"].append(dict(copy.deepcopy(a["claims"][1]), id="C3"))
        a["experiments"][4]["claims"] = ["C2", "C3"]
        analytic = {"step7b_problem.md": STEP7B.format(study="study: analytic\n")}
        res = self.assert_only(a, "C21", "WARN", files=analytic)
        self.assertIn("2 of 3", res["warnings"][0]["text"])
        self.assertEqual(self.check(a)[1]["warnings"], [])  # no step7b: the study's kind is unknown
        self.assertEqual(self.check(a, files={"step7b_problem.md": STEP7B.format(study="study: descriptive\n")})[1]["warnings"], [])

    def test_c21_study_relabelled_descriptive_after_round_1(self):
        a = estimate_primary()
        files = {"step7b_problem.md": STEP7B.format(study="study: descriptive\n"),
                 "step7b_problem_r1.md": STEP7B.format(study="study: analytic\n"), "argument_r1.json": estimate_primary()}
        res = self.assert_only(a, "C21", "WARN", claim="C2", files=files)
        self.assertIn("Primary claim downgraded to an estimate", res["warnings"][0]["text"])
        files["step7b_problem_r1.md"] = files["step7b_problem.md"]  # descriptive from the start
        self.assertEqual(self.check(a, files=files), (0, {"errors": [], "warnings": [], "notes": []}))

    # ---- C22: the reader's file is read, and a doubt is not waved through
    def test_c22_not_fixed_needs_an_obstacle(self):
        a = base_argument()
        files = {"restatement_1.json": RESTATEMENT}
        a["reader_doubts"] = [self.doubt(response="not-fixed", how="it would need a second site")]
        code, res = self.check(a, files=files)
        self.assertEqual((code, [f["check"] for f in res["errors"]]), (1, ["SCHEMA"]))
        self.assertIn("data:", res["errors"][0]["text"])
        for excuse in ("no gate forced a revision", "it was not forced", "out of scope here", "left for future work"):
            a["reader_doubts"] = [self.doubt(response="not-fixed", how=f"budget: {excuse}")]
            code, res = self.check(a, files=files)
            self.assertEqual([f["check"] for f in res["errors"]], ["C22"], excuse)
            self.assertIn("not an obstacle", res["errors"][0]["text"])
        a["reader_doubts"] = [self.doubt(response="not-fixed", how="conflict: C2 needs the same epochs unsplit")]
        self.assert_only(a, "C22", "WARN", files=files)

    def test_c22_design_doubt_marked_fixed_names_what_changed(self):
        a = base_argument()
        a["reader_doubts"] = [self.doubt(how="noted in the Experiments entry")]
        res = self.assert_only(a, "C22", "ERROR", files={"restatement_1.json": RESTATEMENT})
        self.assertIn("experiment or claim", res["errors"][0]["text"])
        a["reader_doubts"] = [self.doubt(level="wording", how="noted in the Experiments entry")]
        self.assertEqual(self.check(a, files={"restatement_1.json": RESTATEMENT})[0], 0)
        a["reader_doubts"] = [self.doubt(level="wording", how=".")]
        self.assert_only(a, "SCHEMA", "ERROR", files={"restatement_1.json": RESTATEMENT})

    def test_c22_reader_says_only_part_is_tested(self):
        narrower = dict(RESTATEMENT, tested_part="Only whether the accuracy drops is tested; the geometry account is described.")
        a = base_argument()
        a["reader_doubts"] = [self.doubt()]
        res = self.assert_only(a, "C22", "ERROR", files={"restatement_1.json": narrower})
        self.assertIn("only part of the question", res["errors"][0]["text"])
        self.assertIn("the geometry account", res["errors"][0]["text"])
        for said in ("all of it", "All of it: E2 decides the whole question.", "The whole question is put to the test in E2."):
            self.assertEqual(self.check(a, files={"restatement_1.json": dict(RESTATEMENT, tested_part=said)})[0], 0, said)
        b = self.part()  # declared: the claim tests a part
        b["reader_doubts"] = [self.doubt()]
        self.assertEqual(self.check(b, files={"restatement_1.json": narrower})[0], 0)
        a["original_question"] = {"text": "Why and how far?", "changed_because": "restatement: the reader found it wider than the test"}
        self.assertEqual(self.check(a, files={"restatement_1.json": narrower})[0], 0)
        a["original_question"]["changed_because"] = "wording only: a comma"  # that is not an answer to the reader
        self.assert_only(a, "C22", "ERROR", files={"restatement_1.json": narrower})
        a["original_question"] = None  # the latest reader counts
        a["reader_doubts"].append(self.doubt(source="restatement-2"))
        self.assertEqual(self.check(a, files={"restatement_1.json": narrower, "restatement_2.json": RESTATEMENT})[0], 0)

    def test_c22_one_row_per_numbered_doubt(self):
        three = dict(RESTATEMENT, biggest_doubt="1. One site only. 2. The control is weak (AUC 0.75 is arbitrary). 3. No power figure.")
        a = base_argument()
        a["reader_doubts"] = [self.doubt()]
        res = self.assert_only(a, "C22", "ERROR", files={"restatement_1.json": three})
        self.assertIn("numbers 3 doubts", res["errors"][0]["text"])
        a["reader_doubts"] += [self.doubt(doubt="the control is weak"), self.doubt(doubt="no power figure", level="wording")]
        self.assertEqual(self.check(a, files={"restatement_1.json": three})[0], 0)
        a["reader_doubts"] = [{"source": "restatement-1", "doubt": "none stated", "level": "wording", "response": "fixed",
                               "how": "nothing to answer"}]  # a reader with no doubt still gets its row
        self.assertEqual(self.check(a, files={"restatement_1.json": dict(RESTATEMENT, biggest_doubt="none")}),
                         (0, {"errors": [], "warnings": [], "notes": []}))

    def test_restatement_file_that_is_not_a_restatement_is_exit_2(self):
        dump(self.gen / "argument.json", base_argument())
        dump(self.gen / "idea.json", base_idea())
        for content in ("just a string", [RESTATEMENT], {"research_question": "q?"}, dict(RESTATEMENT, biggest_doubt=" ")):
            dump(self.gen / "restatement_1.json", content)
            code, out, err = run("argument-check", self.gen)
            self.assertEqual(code, 2, content)
            self.assertIn("biggest_doubt", err)

    # ---- C23: "no data" only after looking at what is on the disk
    def test_c23_inventory_names_what_is_on_the_disk(self):
        (self.gen.parent / "datasets").mkdir()
        (self.gen.parent / "datasets" / "nemar_screening.md").write_text("# screened datasets\n", encoding="utf-8")
        (self.gen.parent / "datasets" / "download_selected.py").write_text("pass\n", encoding="utf-8")  # a script: not asked
        config = {"local_environment": {"probe": {"date": "2026-10-05T10:00:00+08:00", "packages": {}, "data_roots": {
            "~/mne_data": ["MNE-eegbci-data"], "~/mne_data/MNE-eegbci-data": ["files"], "~/.cache/torch": ["hub"],
            "~/scikit_learn_data": [], str(self.gen.parent / "datasets"): ["nemar_screening.md"]}}}}
        a = self.synthetic(real_data="none: no dataset supplies a strength scale for real artifacts", inventory=["looked"])
        files = {"argument_r1.json": a, "../step0_session_config.json": config}
        code, res = self.check(a, files=files)
        self.assertEqual({f["check"] for f in res["errors"]}, {"C23"})
        text = self.texts(res)
        for needle in ("'looked' does not say why", "$RD/datasets/nemar_screening.md", "data root ~/mne_data ", "~/.cache/torch"):
            self.assertIn(needle, text)
        self.assertEqual(len(res["errors"]), 4, res["errors"])  # not the script, the empty root, the sub-root or datasets/ itself
        a["external_check"]["inventory"] = [
            "~/mne_data/MNE-eegbci-data: rest and imagery runs, no labelled artifacts",
            "~/.cache/torch: model weights only",
            "$RD/datasets/nemar_screening.md: ds004505 has treadmill artifacts but no strength scale; a rank check would do"]
        res = self.assert_only(a, "C23", "WARN", files=files)
        self.assertEqual(len(res["warnings"]), 1)
        b = self.synthetic(real_data="E4", inventory=["looked"])  # a route is named: the inventory is not audited
        self.assertEqual(self.check(b, files=files)[0], 0)

    def test_c23_synthetic_false_but_the_study_says_injection(self):
        a = base_argument()
        a["study_sentence"] = "A repeated-measures injection experiment on 109 adults."
        res = self.assert_only(a, "C23", "WARN")
        self.assertIn("'injection'", res["warnings"][0]["text"])
        a = base_argument()
        a["claims"][0]["evidence"][0]["measure"] += " on simulated rotations"
        self.assert_only(a, "C23", "WARN")
        self.assertEqual(self.check(self.synthetic())[1]["warnings"], [])  # declared synthetic, with a route

    # ---- bad input never looks like "revise"
    def test_an_unexpected_exception_is_exit_2(self):
        dump(self.gen / "argument.json", base_argument())
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import ideate_tools as it\n"
                "def boom(*a, **k): raise TypeError('unhashable type: list')\n"
                "it.check_argument = boom; sys.argv = ['ideate_tools.py', 'argument-check', sys.argv[2], '--json']; it.main()")
        p = subprocess.run([sys.executable, "-c", code, str(SCRIPT.parent), str(self.gen)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertIn("cannot read", p.stderr)
        self.assertEqual(p.stdout, "")

    # ---- SCHEMA
    def test_schema_new_fields(self):
        edits = {
            "variant missing": lambda a: a.pop("variant"),
            "variant unknown": lambda a: a.update(variant="replication"),
            "gate": lambda a: a.update(tradeoffs=[tradeoff(gate="budget")]),
            "ids": lambda a: a.update(tradeoffs=[tradeoff(ids="C4")]),
            "ids items": lambda a: a.update(tradeoffs=[tradeoff(ids=[4])]),
            "covers_gap": lambda a: a.update(tradeoffs=[tradeoff(covers_gap="yes")]),
            "covers_angle": lambda a: a.update(tradeoffs=[{k: v for k, v in tradeoff().items() if k != "covers_angle"}]),
            "doubts type": lambda a: a.update(reader_doubts={"doubt": "x"}),
            "doubt source": lambda a: a.update(reader_doubts=[self.doubt(source="reviewer")]),
            "doubt level": lambda a: a.update(reader_doubts=[self.doubt(level="minor")]),
            "doubt response": lambda a: a.update(reader_doubts=[self.doubt(response="noted")]),
            "doubt how": lambda a: a.update(reader_doubts=[self.doubt(how="")]),
            "doubt text": lambda a: a.update(reader_doubts=[self.doubt(doubt=" ")]),
            "coverage.question": lambda a: a["coverage"].update(question="most"),
            "coverage.angle": lambda a: a["coverage"].pop("angle"),
            "shared_terms": lambda a: a["claims"][0]["construction"].update(shared_terms="none"),
            "synthetic": lambda a: a["external_check"].update(synthetic="no"),
            "datasets": lambda a: a["external_check"].update(datasets=[]),
        }
        for name, edit in edits.items():
            a = base_argument()
            edit(a)
            res = self.assert_only(a, "SCHEMA", "ERROR")
            self.assertEqual(len(res["errors"]), 1, name)

    def test_ctx_none_is_no_files(self):
        sys.path.insert(0, str(SCRIPT.parent))
        try:
            import ideate_tools as it
        finally:
            sys.path.pop(0)
        self.assertEqual(it.check_argument(base_argument(), base_idea()["Experiments"]), [])
        self.assertEqual(it.ARG_ORDER[-1], "C28")      # C25-C28: the planning block (it_plan.py), only with its files
        self.assertEqual(it._norm_text("A — b  ‘c’ “d” − e"), "a - b 'c' \"d\" - e")
        r1 = base_argument()
        r1["claims"][0].update(mode="equivalence", statement="Although x,  it is the same.")
        self.assertEqual(it._primary_changed(base_argument(), r1), ["statement", "mode"])
        self.assertEqual(it._primary_changed(base_argument(), base_argument()), [])

    # ---- bad input
    def test_unreadable_context_files_are_exit_2(self):
        dump(self.gen / "argument.json", base_argument())
        dump(self.gen / "idea.json", base_idea())
        for name in ("argument_r1.json", "restatement_1.json", "restatement_2.json"):
            (self.gen / name).write_text("{not json", encoding="utf-8")
            code, out, err = run("argument-check", self.gen)
            self.assertEqual(code, 2, name)
            self.assertIn(name, err)
            (self.gen / name).unlink()
        dump(self.gen / "argument_r1.json", [1, 2])
        self.assertEqual(run("argument-check", self.gen)[0], 2)
        (self.gen / "argument_r1.json").unlink()
        self.assertEqual(run("argument-check", self.gen)[0], 0)


class TestArgumentRender(ArgumentCase):
    def test_render(self):
        a = base_argument()
        a["claims"][0]["statement"] += " | with a pipe"
        dump(self.gen / "argument.json", a)
        code, out, err = run("argument-render", self.gen)
        self.assertEqual(code, 0, err)
        md = (self.gen / "argument.md").read_text(encoding="utf-8")
        for needle in ("# Argument — reference_mismatch_geometry", "### C1 (primary)", "### C2", "**Rival explanations**",
                       "| leakage |", "## Representation", "## Experiments", "| E3 | control | C1 |", "## Trade-offs",
                       "None recorded.", "calibration accuracy", "edit the JSON, not this file", "| can fail? |",
                       "**Comparator of the falsifier**: matched-reference calibration accuracy",
                       "**Can the negative control move the measure?**: yes:"):
            self.assertIn(needle, md)
        self.assertNotIn(" | with a pipe", md)  # a pipe inside a cell would break the table
        self.assertEqual(json.loads((self.gen / "argument.json").read_text(encoding="utf-8")), a)  # source untouched

    def test_render_new_blocks(self):
        a = base_argument()
        a["coverage"] = {"question": "part", "tested_part": "whether a mismatch lowers accuracy",
                         "untested": [{"part": "how far the geometry moves", "terms": ["principal angle"], "by": "C2"}],
                         "angle": "part", "angle_dropped": "the coupling half: no experiment crosses two metrics",
                         "angle_parts": [{"part": "reference mismatch", "by": "C1"}, {"part": "coupling", "by": "none"}]}
        a["claims"][0]["smallest_effect_of_interest"] = "2 accuracy points (design choice)"
        a["claims"][0]["evidence"][0]["refuted_if"] = "mean drop under 2 points"
        a["tradeoffs"] = [tradeoff(gate="restatement", ids=["C4", "E7"], lost="the second amplifier", covers_angle=False)]
        a["reader_doubts"] = [{"source": "restatement-1", "doubt": "one site only", "level": "design",
                               "response": "not-fixed", "how": "no second dataset with rest runs on this machine"}]
        dump(self.gen / "argument.json", a)
        self.assertEqual(run("argument-render", self.gen)[0], 0)
        md = (self.gen / "argument.md").read_text(encoding="utf-8")
        for needle in ("- **Variant**: cause", "## Coverage", "**Question covered by the primary claim**: part",
                       "**Tested part**: whether a mismatch lowers accuracy",
                       "**Untested part**: how far the geometry moves — carried by C2", "**Angle covered**: part",
                       "**Angle dropped**: the coupling half", "**Angle part**: reference mismatch — covered by C1",
                       "**Angle part**: coupling — covered by none", "**Expected direction**: a mismatch lowers accuracy — "
                       "basis: contested:", "**Estimate because**: descriptive: the angle has no direction", "## External check", "**Primary evidence is synthetic**: no",
                       "**Datasets carrying the primary claim**: EEGMMIDB; Lee2019_MI", "MNE-lee2019-mi-data",
                       "**Construction**", "- Predictor formula: pair (train reference, test reference)",
                       "- Outcome formula: drop = acc(matched pair)", "- Shared terms: none",
                       "- Computable without the experiment: no:", "- Free quantity: the sensitivity",
                       "**Smallest effect of interest**: 2 accuracy points (design choice)",
                       "**Positive control, expected value**: a 30 degree rotation",
                       "| experiment | measure | would show | can fail? | refuted if |", "| mean drop under 2 points |",
                       "| type | main | how it would arise here | ruled out by |", "| bias | main |",
                       "| gate | ids | change | because | lost | answers question | covers gap | covers angle | why |",
                       "| restatement | C4; E7 |", "| the second amplifier | yes | yes | NO |", "## Reader doubts",
                       "| source | level | doubt | response | how |", "| restatement-1 | design | one site only | not-fixed |"):
            self.assertIn(needle, md)
        c2 = md.split("### C2")[1].split("## Representation")[0]  # the estimate claim
        for label in ("Falsifier", "Negative control", "Positive control", "Power", "Expected direction"):
            self.assertIn(f"**{label}**: not applicable (estimate)", c2)
        self.assertNotIn("Estimate because", md.split("### C2")[0])
        self.assertNotIn("not applicable (estimate)", md.split("### C2")[0])
        self.assertNotIn("**Construction**", c2)

    def test_render_without_the_new_fields(self):
        """A file written before the fields existed still renders (it fails the check, which is the gate's job)."""
        a = base_argument()
        for k in ("variant", "coverage", "external_check", "reader_doubts"):
            del a[k]
        del a["claims"][0]["construction"]
        dump(self.gen / "argument.json", a)
        self.assertEqual(run("argument-render", self.gen)[0], 0)
        md = (self.gen / "argument.md").read_text(encoding="utf-8")
        self.assertEqual(md.count("Not recorded."), 2)
        self.assertIn("## Reader doubts\n\nNone recorded.", md)

    def test_render_tolerates_sparse_file(self):
        dump(self.gen / "argument.json", {"schema": "ai-scientist-argument/1", "claims": [{"id": "C1"}]})
        self.assertEqual(run("argument-render", self.gen)[0], 0)
        self.assertIn("(TBD)", (self.gen / "argument.md").read_text(encoding="utf-8"))


class TestPower(unittest.TestCase):
    def power(self, *args):
        code, out, err = run("power", *args, "--json")
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_corr_matches_table_6c(self):
        # total N for r at two-sided alpha .05, beta .20: 0.30 -> 85, 0.20 -> 194, 0.50 -> 29
        for n, r in ((85, 0.30), (194, 0.20), (29, 0.50)):
            self.assertAlmostEqual(self.power("--mode", "corr", "--n", n)["min_detectable"], r, delta=0.006)
        # two-sided alpha .01, beta .10: r = 0.30 -> 158
        self.assertAlmostEqual(self.power("--mode", "corr", "--n", 158, "--alpha", 0.01, "--power", 0.9)["min_detectable"],
                               0.30, delta=0.006)

    def test_two_group_matches_table_6a(self):
        # per group at two-sided alpha .05, beta .20: E/S 0.5 -> 64, 0.25 -> 253, 1.0 -> 17 (t-based table, so looser)
        for n, d, tol in ((64, 0.50, 0.01), (253, 0.25, 0.005), (17, 1.00, 0.05)):
            self.assertAlmostEqual(self.power("--mode", "two-group", "--n1", n, "--n2", n)["min_detectable"], d, delta=tol)
        # beta .10: E/S 0.5 -> 86
        self.assertAlmostEqual(self.power("--mode", "two-group", "--n1", 86, "--n2", 86, "--power", 0.9)["min_detectable"],
                               0.50, delta=0.01)

    def test_two_group_unequal_is_worse_than_equal(self):
        eq = self.power("--mode", "two-group", "--n1", 50, "--n2", 50)["min_detectable"]
        un = self.power("--mode", "two-group", "--n1", 20, "--n2", 80)["min_detectable"]
        self.assertGreater(un, eq)

    def test_paired_is_half_the_per_group_table_value(self):
        self.assertAlmostEqual(self.power("--mode", "paired", "--n", 32)["min_detectable"], 0.50, delta=0.01)

    def test_estimate_matches_table_6d(self):
        # W/S at 95%: 0.60 -> 43, 0.20 -> 385; at 99%: 0.50 -> 107
        self.assertAlmostEqual(self.power("--mode", "estimate", "--n", 43)["ci_width"], 0.60, delta=0.005)
        self.assertAlmostEqual(self.power("--mode", "estimate", "--n", 385)["ci_width"], 0.20, delta=0.002)
        self.assertAlmostEqual(self.power("--mode", "estimate", "--n", 107, "--conf", 0.99)["ci_width"], 0.50, delta=0.005)
        res = self.power("--mode", "estimate", "--n", 43, "--sd", 10)
        self.assertEqual(res["unit"], "raw")
        self.assertAlmostEqual(res["ci_width"], 6.0, delta=0.05)

    def test_output_says_it_is_rough(self):
        code, out, _ = run("power", "--mode", "corr", "--n", 20)
        self.assertEqual(code, 0)
        self.assertIn("rough estimate", out)
        self.assertIn("n < 30", out)
        self.assertIn("independent units", out)
        self.assertTrue(self.power("--mode", "corr", "--n", 20)["small_n"])
        self.assertFalse(self.power("--mode", "corr", "--n", 109)["small_n"])

    def test_bad_arguments(self):
        for args in (("--mode", "corr"), ("--mode", "corr", "--n", 3), ("--mode", "two-group", "--n", 100),
                     ("--mode", "paired", "--n", 40, "--alpha", 1.5), ("--mode", "corr", "--n", 50, "--effect", 2),
                     ("--mode", "equivalence"), ("--mode", "equivalence", "--n", 1), ("--mode", "paired", "--n", 40, "--effect", 0),
                     ("--mode", "estimate", "--n", 40, "--sided", 1), ("--mode", "paired", "--n", 40, "--sided", 3)):
            self.assertEqual(run("power", *args)[0], 2, args)

    def test_one_sided_detects_a_smaller_effect(self):
        for args in (("--mode", "paired", "--n", 109), ("--mode", "corr", "--n", 85), ("--mode", "two-group", "--n1", 64, "--n2", 64)):
            two, one = self.power(*args), self.power(*args, "--sided", 1)
            self.assertLess(one["min_detectable"], two["min_detectable"], args)
            self.assertEqual((two["sided"], one["sided"]), (2, 1))
            self.assertIn("two-sided", two["text"])
            self.assertIn("one-sided", one["text"])
        # one-sided alpha .05 is two-sided alpha .10
        self.assertEqual(self.power("--mode", "paired", "--n", 109, "--sided", 1)["min_detectable"],
                         self.power("--mode", "paired", "--n", 109, "--alpha", 0.10)["min_detectable"])
        code, out, _ = run("power", "--mode", "paired", "--n", 109)
        self.assertEqual(out.splitlines()[0], "power paired: n=109 -> d >= 0.27 @ 80% power, two-sided alpha = 0.05")

    def test_equivalence(self):
        code, out, _ = run("power", "--mode", "equivalence", "--n", 109)
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], "power equivalence: n=109 -> equivalence margin >= 0.28 SD @ 80% power "
                                              "(two one-sided tests, alpha = 0.05 each)")
        res = self.power("--mode", "equivalence", "--n", 109)
        self.assertAlmostEqual(res["margin"], (1.6449 + 1.2816) / 109 ** 0.5, delta=0.001)
        two = self.power("--mode", "equivalence", "--n1", 50, "--n2", 60, "--sd", 2)
        self.assertAlmostEqual(two["margin"], (1.6449 + 1.2816) * (1 / 50 + 1 / 60) ** 0.5, delta=0.001)
        self.assertAlmostEqual(two["min_detectable_raw"], 2 * two["margin"], delta=0.001)
        self.assertEqual((two["n1"], two["n2"]), (50, 60))
        # showing sameness needs a wider margin than detecting a difference of that size needs an effect
        self.assertGreater(res["margin"], self.power("--mode", "paired", "--n", 109)["min_detectable"])
        self.assertLess(self.power("--mode", "equivalence", "--n", 400)["margin"], res["margin"])

    def test_effect_gives_the_largest_sd(self):
        res = self.power("--mode", "paired", "--n", 109, "--effect", 1.0)
        self.assertAlmostEqual(res["max_sd_for_effect"], 1.0 / res["min_detectable"], delta=0.02)
        est = self.power("--mode", "estimate", "--n", 109, "--effect", 1.0)
        self.assertAlmostEqual(est["max_sd_for_effect"], 1.0 / est["ci_width_in_sd"], delta=0.02)
        eq = self.power("--mode", "equivalence", "--n", 109, "--effect", 0.5)
        self.assertAlmostEqual(eq["max_sd_for_effect"], 0.5 / eq["margin"], delta=0.02)
        code, out, _ = run("power", "--mode", "paired", "--n", 109, "--effect", 1)
        self.assertRegex(out, r"an effect of 1 is detectable only if the SD is at most 3\.7")
        code, out, _ = run("power", "--mode", "estimate", "--n", 109, "--effect", 1)
        self.assertRegex(out, r"the interval reaches a total width of 1 only if the SD is at most 2\.6")
        self.assertNotIn("max_sd_for_effect", self.power("--mode", "paired", "--n", 109))

    @unittest.skipUnless(PREV_SCRIPT.exists(), "pre-fix copy of ideate_tools.py not available")
    def test_existing_invocations_print_what_they_printed(self):
        for args in (("--mode", "corr", "--n", 85), ("--mode", "corr", "--n", 20, "--alpha", 0.01, "--power", 0.9),
                     ("--mode", "two-group", "--n1", 20, "--n2", 80), ("--mode", "two-group", "--n1", 64, "--sd", 3.5),
                     ("--mode", "paired", "--n", 109), ("--mode", "paired", "--n", 12, "--sd", 0.4),
                     ("--mode", "estimate", "--n", 43), ("--mode", "estimate", "--n", 107, "--conf", 0.99, "--sd", 10),
                     ("--mode", "corr"), ("--mode", "two-group", "--n", 100)):
            for flags in ((), ("--json",)):
                self.assertEqual(run("power", *args, *flags), run("power", *args, *flags, script=PREV_SCRIPT), args)


# ------------------------------------------------------------------- env-probe
class TestEnvProbe(unittest.TestCase):
    CONFIG = {"topic": "t", "depth": "standard", "consumed": [{"gap": "GAP_001", "angle": "a", "idea": "i", "generation": 1}],
              "local_environment": {
                  "cached_data": ["CACHED_ROOT (only fsaverage; no EEGBCI dataset cached yet)", "a note that is no path"],
                  "packages_present": ["json 2.0", "surely_not_a_module_qq 1.0"],
                  "packages_missing": ["unittest", "another_missing_module_qq/alias"],
                  "hardware": "CPU"}}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.rd = tmp / "topic_research"
        (self.rd / "datasets").mkdir(parents=True)
        (self.rd / "datasets" / "nemar_screening.md").write_text("# screen\n", encoding="utf-8")
        self.cached = tmp / "cache_root"
        for name in ("MNE-eegbci-data", "MNE-fsaverage-data"):
            (self.cached / name).mkdir(parents=True)
        self.config = json.loads(json.dumps(self.CONFIG).replace("CACHED_ROOT", str(self.cached)))
        dump(self.rd / "step0_session_config.json", self.config)

    def tearDown(self):
        self._tmp.cleanup()

    def test_listing_and_stale_lines(self):
        code, out, err = run("env-probe", self.rd)
        self.assertEqual(code, 0, err)
        self.assertRegex(out, rf"(?m)^data root {re.escape(str(self.cached))}: 2 entries\n  MNE-eegbci-data\n  MNE-fsaverage-data$")
        self.assertRegex(out, r"(?m)^data root .*topic_research/datasets: 1 entry\n  nemar_screening\.md$")
        self.assertRegex(out, r"(?m)^package json: \S")
        self.assertRegex(out, r"(?m)^package surely_not_a_module_qq: NOT installed$")
        stale = sorted(ln for ln in out.splitlines() if ln.startswith("stale: "))
        self.assertEqual(len(stale), 2, out)
        self.assertRegex(stale[0], r"surely_not_a_module_qq .*packages_present.*not importable")
        self.assertRegex(stale[1], r"unittest .*packages_missing.*importable")
        self.assertRegex(out, r"(?m)^package another_missing_module_qq: NOT installed$")  # "name/alias": the first token
        self.assertEqual(json.loads((self.rd / "step0_session_config.json").read_text(encoding="utf-8")), self.config)  # no --write

    def test_roots_and_packages_flags(self):
        other = Path(self._tmp.name) / "other_root"
        (other / "ds000001").mkdir(parents=True)
        code, out, err = run("env-probe", self.rd, "--roots", f"{other},{other}/nope", "--packages", "os,nope_qq", "--json")
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        self.assertEqual(res["data_roots"], {str(other): ["ds000001"]})  # --roots replaces the defaults
        self.assertEqual(res["roots_not_found"], [f"{other}/nope"])
        self.assertIsNotNone(res["packages"]["os"])
        self.assertIsNone(res["packages"]["nope_qq"])
        self.assertEqual(list(res["packages"])[:2], ["os", "nope_qq"])
        self.assertEqual(res["interpreter"], sys.executable)

    def test_write_adds_the_probe_and_keeps_every_other_key(self):
        code, out, err = run("env-probe", self.rd, "--write")
        self.assertEqual(code, 0, err)
        new = json.loads((self.rd / "step0_session_config.json").read_text(encoding="utf-8"))
        probe = new["local_environment"].pop("probe")
        self.assertEqual(new, self.config)
        self.assertEqual(list(new), list(self.config))
        self.assertEqual(sorted(probe), ["data_roots", "date", "interpreter", "packages"])
        self.assertRegex(probe["date"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
        self.assertEqual(probe["data_roots"][str(self.cached)], ["MNE-eegbci-data", "MNE-fsaverage-data"])
        self.assertIsNone(probe["packages"]["surely_not_a_module_qq"])
        self.assertFalse(list(self.rd.glob("*.tmp")))
        # the gate then sees a probe
        gen = self.rd / "gen_1"
        dump(gen / "argument.json", base_argument())
        dump(gen / "idea.json", base_idea())
        self.assertEqual(run("argument-check", gen)[1].strip(), "argument-check: 0 error(s), 0 warning(s) [idea: idea.json] - OK")

    def test_punctuation_after_a_path_or_a_package_name(self):
        """The A1 prose is free text: "path: note", "path, note", "name>=1.3", "name==2.2", "name,", "name: note"."""
        self.config["local_environment"].update(
            cached_data=[f"{self.cached}: two folders", f"{self.cached}/MNE-eegbci-data, 109 subjects", f"({self.cached}) no path first"],
            packages_present=["json>=2.0", "os==1.0", "surely_not_a_module_qq~=1.0"],
            packages_missing=["unittest,", "another_missing_module_qq: not installed", "tempfile (stdlib)"])
        dump(self.rd / "step0_session_config.json", self.config)
        code, out, err = run("env-probe", self.rd, "--json")
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        self.assertEqual(res["data_roots"][str(self.cached)], ["MNE-eegbci-data", "MNE-fsaverage-data"])
        self.assertIn(f"{self.cached}/MNE-eegbci-data", res["data_roots"])
        self.assertFalse([r for r in res["roots_not_found"] if str(self.cached) in r], res["roots_not_found"])
        self.assertEqual(sorted(res["packages"]), ["another_missing_module_qq", "json", "os", "surely_not_a_module_qq",
                                                   "tempfile", "unittest"])
        self.assertIsNotNone(res["packages"]["json"])
        self.assertIsNotNone(res["packages"]["os"])
        self.assertEqual(len(res["stale"]), 3, res["stale"])  # surely_not... listed present; unittest, tempfile listed missing

    def test_at_most_200_children_are_listed(self):
        big = Path(self._tmp.name) / "big_root"
        big.mkdir()
        for i in range(201):
            (big / f"ds{i:04d}").mkdir()
        code, out, err = run("env-probe", self.rd, "--roots", str(big), "--json")
        self.assertEqual(code, 0, err)
        children = json.loads(out)["data_roots"][str(big)]
        self.assertEqual((len(children), children[0], children[-1]), (200, "ds0000", "ds0199"))

    def test_config_without_local_environment(self):
        dump(self.rd / "step0_session_config.json", {"topic": "t"})
        self.assertEqual(run("env-probe", self.rd, "--roots", str(self.cached), "--write")[0], 0)
        new = json.loads((self.rd / "step0_session_config.json").read_text(encoding="utf-8"))
        self.assertEqual(list(new["local_environment"]), ["probe"])

    def test_missing_or_broken_config_is_exit_2(self):
        (self.rd / "step0_session_config.json").unlink()
        self.assertEqual(run("env-probe", self.rd)[0], 2)
        (self.rd / "step0_session_config.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(run("env-probe", self.rd)[0], 2)


# ------------------------------------------------------- replay of the validation run
@unittest.skipUnless((VALIDATION_GEN / "argument.json").exists() and (VALIDATION_GEN / "argument_r1.json").exists(),
                     "validation generation not available")
class TestValidationReplay(unittest.TestCase):
    """The generation the revised flow was validated on passed argument-check with 0 errors in both rounds while
    three judges found its primary test partly fixed by construction, its question wider than its test, its cuts
    unrecorded and its positive control unable to return the planted value. The checks must now say so. Works on a
    temporary copy; the folder itself is evidence and is never written."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.gen = Path(self._tmp.name) / "research" / "gen_1"
        shutil.copytree(VALIDATION_GEN, self.gen)
        self.before = {p.name: p.stat().st_mtime_ns for p in VALIDATION_GEN.iterdir()}

    def tearDown(self):
        self.assertEqual({p.name: p.stat().st_mtime_ns for p in VALIDATION_GEN.iterdir()}, self.before)
        self._tmp.cleanup()

    def findings(self, *extra):
        code, out, err = run("argument-check", self.gen, "--json", *extra)
        self.assertIn(code, (0, 1), err)
        res = json.loads(out)
        count = lambda rows: sorted((f["check"], f["claim"] or "-") for f in rows)
        summary = run("argument-check", self.gen, *extra)[1].strip().splitlines()[-1]
        return code, count(res["errors"]), count(res["warnings"]), count(res["notes"]), res, summary

    def test_g1_the_finalized_generation_no_longer_passes(self):
        code, errors, warnings, notes, res, summary = self.findings()
        self.assertEqual(code, 1)
        self.assertEqual(summary, "argument-check: 16 error(s), 7 warning(s) [idea: idea.json] - REVISE")
        self.assertEqual(errors, sorted([("SCHEMA", "-"), ("C2", "C1"), ("C7", "C1"), ("C16", "-"), ("C17", "C1"), ("C17", "C1"),
                                         ("C19", "C1"), ("C19", "-"), ("C19", "-"), ("C19", "-"), ("C19", "-"),
                                         ("C20", "-"), ("C21", "C2"), ("C21", "C3"), ("C23", "-"), ("C24", "C1")]), res["errors"])
        self.assertEqual(warnings, [("C13", "C1"), ("C13", "C1"), ("C13", "C1"), ("C13", "C2"), ("C14", "C1"), ("C17", "C1"),
                                    ("C21", "-")])
        self.assertEqual(notes, [])
        said = lambda check, level="errors": " || ".join(f["text"] for f in res[level] if f["check"] == check)
        self.assertIn("expected_direction", said("C7"))        # nobody was asked which direction was expected, or why
        self.assertIn("estimate_because", said("C21"))         # two of three claims were estimates with no reason given
        self.assertIn("2 of 3 claims are estimates", said("C21", "warnings"))
        self.assertIn("absolute value", said("C17", "warnings"))  # |floor(R02) - floor(R01)| loses the predicted sign
        text = {c: " || ".join(f["text"] for f in res["errors"] if f["check"] == c) for c in ("SCHEMA", "C2", "C17", "C19")}
        self.assertIn("variant", text["SCHEMA"])
        self.assertIn("E6", text["C2"])
        self.assertIn("construction", text["C17"])
        self.assertIn("positive_expected", text["C17"])
        for needle in ("C1: mode changed equivalence -> test", "claim C4", "E6: role changed control -> tests",
                       "E7: role changed descriptive -> release", "experiment E8"):
            self.assertIn(needle, text["C19"])
        other = [f["text"] for f in res["warnings"] if f["check"] == "C13" and f["claim"] == "C1" and "'other'" in f["text"]]
        self.assertEqual(len(other), 2)  # the two `other` rivals of C1 print separately

    def test_g2_with_the_reader_file(self):
        dump(self.gen / "restatement_1.json", RESTATEMENT)
        code, errors, warnings, notes, res, summary = self.findings()
        self.assertEqual(summary, "argument-check: 17 error(s), 8 warning(s) [idea: idea.json] - REVISE")
        self.assertEqual(errors.count(("C22", "-")), 1)
        due = [f["text"] for f in res["warnings"] if f["check"] == "C22"]
        self.assertEqual(len(due), 1)
        for word in ("statement", "mode", "falsifier", "second blind restatement"):
            self.assertIn(word, due[0])

    def test_g3_the_round_1_draft_no_longer_passes(self):
        (self.gen / "argument_r1.json").replace(self.gen / "argument.json")
        code, errors, warnings, notes, res, summary = self.findings("--no-idea")
        self.assertEqual(code, 1)
        self.assertEqual(summary, "argument-check: 9 error(s), 7 warning(s) [no idea file] - REVISE")
        self.assertEqual(errors, [("C17", "C1"), ("C17", "C1"), ("C20", "-"), ("C21", "C2"), ("C21", "C3"), ("C21", "C4"),
                                  ("C23", "-"), ("C24", "C1"), ("SCHEMA", "-")])  # C2-C4 were estimates from the first draft
        self.assertEqual(warnings, [("C13", "C1"), ("C13", "C1"), ("C13", "C2"), ("C13", "C4"), ("C14", "C1"), ("C14", "C4"),
                                    ("C21", "-")])
        self.assertEqual(notes, [("C10", "-"), ("C20", "-"), ("C3", "-")])

    def test_g6_filling_the_new_fields_by_gesture_is_seen(self):
        """The generation with every new field filled the easy way - coverage 'whole', shared_terms [], 'none:' with a
        one-line inventory, the positive control 'returns 2', one doubt 'noted' - as a reviewer of the fixes did. Each
        defect the judges found by hand must still produce a line."""
        a = json.loads((self.gen / "argument.json").read_text(encoding="utf-8"))
        c1, c2, c3 = a["claims"]
        a.update(variant="invariance",
                 original_question={"text": json.loads((self.gen / "argument_r1.json").read_text(encoding="utf-8"))["question"],
                                    "changed_because": "wording only: 'the end' became 'the two ends'"},
                 coverage={"question": "whole", "angle": "whole", "angle_parts": [{"part": a["angle"], "by": "C1"}]},
                 external_check={"synthetic": True, "datasets": ["EEGMMIDB"], "inventory": ["~/mne_data: EEGBCI only"],
                                 "real_data": "none: no dataset in the evidence base supplies a strength scale for real artifacts",
                                 "second_dataset": "none: the second dataset had 18 subjects and four confounds"},
                 reader_doubts=[{"source": "restatement-1", "doubt": "the measurement is too coarse", "level": "design",
                                 "response": "not-fixed", "how": "no gate forced a revision; future work"}],
                 tradeoffs=[tradeoff(gate="none", ids=["C1", "C4", "E6", "E7", "E8"], change="primary moved to the floor; second "
                                     "dataset removed", lost="nothing: the second dataset had four confounds")])
        c1.update(construction={"predictor_formula": "dose = a * RMS_r * c",
                                "outcome_formula": "floor_r = min a : AUC[S(x_i + a*RMS_r*c), S(x_j)] >= 0.75",
                                "shared_terms": [], "computable_without_experiment": "no: needs injection",
                                "free_quantity": "the floor"},
                  expected_direction={"direction": "the floor moves", "basis": "unknown: nothing predicts it"})
        c1["controls"]["positive_expected"] = "2 steps: the ladder is displaced by two steps, so the excess shift is 2"
        c1["rivals"][1]["main"] = True
        c1["evidence"][1]["refuted_if"] = "paired difference at or below 0"
        for c in (c2, c3):
            c.update(estimate_because="descriptive: a table", falsifier=None, controls=None, power=None)
        dump(self.gen / "argument.json", a)
        dump(self.gen / "restatement_1.json", dict(RESTATEMENT, tested_part="Only the floor along amplitude is tested; the "
                                                   "ceiling, coverage and extent are described.",
                                                   biggest_doubt="1. Too coarse. 2. The odd/even baseline is unfair."))
        (self.gen.parent / "datasets").mkdir()
        (self.gen.parent / "datasets" / "nemar_screening.md").write_text("# phantom and treadmill datasets\n", encoding="utf-8")
        code, errors, warnings, notes, res, summary = self.findings()
        said = lambda check, level="errors": " || ".join(f["text"] for f in res[level] if f["check"] == check)
        self.assertEqual(code, 1)
        self.assertEqual(sorted(set(c for c, _ in errors)), ["C18", "C22", "C23", "SCHEMA"], res["errors"])
        self.assertIn("'RMS_r' occurs in both formulas", said("C18"))             # result partly fixed by construction
        self.assertIn("only part of the question", said("C22"))                    # question wider than the test
        self.assertIn("numbers 2 doubts", said("C22"))
        self.assertIn("data:", said("SCHEMA"))                                     # "no gate forced a revision"
        self.assertIn("nemar_screening.md", said("C23"))                           # the screened real-artifact datasets
        self.assertIn("planted value", said("C17", "warnings"))                    # E4 cannot return 2 through |.|
        self.assertIn("'temporal coverage'", said("C20", "warnings"))              # the oversold title term
        self.assertIn("Title names it too", said("C20", "warnings"))
        self.assertIn("'coupling'", said("C20", "warnings"))                       # half the angle, covered by nothing
        self.assertIn("second blind restatement", said("C22", "warnings"))

    def test_render_of_the_old_file_still_works(self):
        self.assertEqual(run("argument-render", self.gen)[0], 0)
        md = (self.gen / "argument.md").read_text(encoding="utf-8")
        self.assertIn("**Falsifier**: not applicable (estimate)", md)

    def test_g4_env_probe_contradicts_the_a1_prose(self):
        config = VALIDATION_GEN.parents[1] / "step0_session_config.json"
        if not config.exists() or not (Path.home() / "mne_data" / "MNE-eegbci-data").is_dir():
            self.skipTest("the session config or ~/mne_data/MNE-eegbci-data is not on this machine")
        shutil.copy(config, self.gen.parent / "step0_session_config.json")
        code, out, err = run("env-probe", self.gen.parent)
        self.assertEqual(code, 0, err)
        block = out.split("data root ~/mne_data:")[1].split("data root ")[0]
        self.assertIn("\n  MNE-eegbci-data\n", block)  # the A1 prose says "no ... EEGBCI dataset cached yet"

    def test_g5_power(self):
        two = run("power", "--mode", "paired", "--n", 109)[1].splitlines()[0]
        one = run("power", "--mode", "paired", "--n", 109, "--sided", 1)[1].splitlines()[0]
        self.assertEqual(two, "power paired: n=109 -> d >= 0.27 @ 80% power, two-sided alpha = 0.05")
        self.assertRegex(one, r"d >= 0\.2[0-6] @ 80% power, one-sided alpha = 0\.05")


# -------------------------------------------------------------- concept-index
OLD_NOTE = """# alpha2020

- Method: xDAWN + LDA on 20 subjects.
- **Future work:** dry electrodes.
Not done: no cross-site test; reference never varied.
"""
NEW_NOTE = """# beta2022

- Method: Riemannian MDM, 3 datasets.
Claim scope: "outperforms" on three public datasets; no claim beyond wet electrodes.
Assumes: the reference electrode does not matter.
Disagrees with: alpha2020 - reports the opposite ranking of LDA and MDM, on a different split.
Not done: no high-pass sweep.
"""
NEW_NOTE_NONE = """# gamma2023

- **Claim scope:** correlates in one cohort.
- **Assumes:** (TBD)
- **Disagrees with:** none found in text
- Disagrees with: No conflict with the other read papers.
Not done: (TBD)
"""
SIGNAL_KEYS = ["isolated_points", "plane_pairs_without_any_line", "open_debates", "evolution_chain_ends",
               "not_done_and_future_work", "claim_type_counts", "dangling_references", "methods"]
TOP_KEYS = ["nodes", "edges", "planes", "bodies", "structure_reliable", "structure_note", "signals"]


class TestConceptIndex(unittest.TestCase):
    def build(self, tmp, notes: dict) -> Path:
        rd = Path(tmp) / "topic_research"
        (rd / "knowledge" / "_notes").mkdir(parents=True)
        (rd / "knowledge" / "points").mkdir()
        (rd / "knowledge" / "points" / "P_draft_x.md").write_text(
            "---\nid: P_draft_x\ntype: point\nname: \"x\"\nclaim_type: empirical\nsource: \"alpha2020\"\nyear: 2020\n---\n\n# x\n",
            encoding="utf-8")
        for name, text in notes.items():
            (rd / "knowledge" / "_notes" / f"{name}.md").write_text(text, encoding="utf-8")
        return rd

    def index(self, rd, script=SCRIPT):
        code, out, err = run("concept-index", rd, script=script)
        self.assertEqual(code, 0, err)
        return json.loads((rd / "knowledge" / "concept_index.json").read_text(encoding="utf-8")), out

    def test_with_claim_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            rd = self.build(tmp, {"alpha2020": OLD_NOTE, "beta2022": NEW_NOTE, "gamma2023": NEW_NOTE_NONE})
            idx, out = self.index(rd)
            s = idx["signals"]
            self.assertEqual(s["assumptions"], [{"paper": "beta2022", "text": "the reference electrode does not matter."}])
            self.assertEqual([d["paper"] for d in s["disagreements"]], ["beta2022"])
            self.assertTrue(s["disagreements"][0]["text"].startswith("alpha2020 - reports the opposite"))
            self.assertEqual(idx["notes_with_claim_fields"], "2/3")
            self.assertIn("notes_with_claim_fields=2/3", out)
            # existing keys: same names, same order, new ones only appended
            self.assertEqual(list(s)[:len(SIGNAL_KEYS)], SIGNAL_KEYS)
            self.assertEqual(list(s)[len(SIGNAL_KEYS):], ["assumptions", "disagreements"])
            self.assertEqual(list(idx)[:len(TOP_KEYS)], TOP_KEYS)
            self.assertEqual(list(idx)[len(TOP_KEYS):], ["notes_with_claim_fields"])
            # the existing harvest is untouched by the new lines
            self.assertEqual([(d["paper"], d["kind"]) for d in s["not_done_and_future_work"]],
                             [("alpha2020", "future work"), ("alpha2020", "not done"), ("beta2022", "not done")])

    def test_without_claim_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            rd = self.build(tmp, {"alpha2020": OLD_NOTE})
            idx, _ = self.index(rd)
            self.assertEqual(idx["signals"]["assumptions"], [])
            self.assertEqual(idx["signals"]["disagreements"], [])
            self.assertEqual(idx["notes_with_claim_fields"], "0/1")
            self.assertEqual(len(idx["signals"]["not_done_and_future_work"]), 2)

    def test_no_notes_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            rd = self.build(tmp, {})
            (rd / "knowledge" / "_notes").rmdir()
            idx, _ = self.index(rd)
            self.assertEqual(idx["notes_with_claim_fields"], "0/0")

    @unittest.skipUnless(OLD_SCRIPT.exists(), "pre-change copy of ideate_tools.py not available")
    def test_only_gains_keys_relative_to_the_previous_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            rd = self.build(tmp, {"alpha2020": OLD_NOTE, "beta2022": NEW_NOTE})
            old, _ = self.index(rd, script=OLD_SCRIPT)
            new, _ = self.index(rd)
            self.assertEqual(new.pop("notes_with_claim_fields"), "1/2")
            for k in ("assumptions", "disagreements"):
                new["signals"].pop(k)
            self.assertEqual(new, old)
            self.assertEqual(list(new["signals"]), list(old["signals"]))


# -------------------------------------------------------------------- link-run
OLD_POINTER_KEYS = ["idea", "topic_json", "research_dir", "generation_dir", "generation", "gap", "angle",
                    "references_bib", "citation_keys", "sota_review", "journal_recommendations"]


class TestLinkRun(unittest.TestCase):
    def build(self, tmp, with_new: bool):
        root = Path(tmp)
        run_dir = root / "experiments" / "2026-10-04_reference_mismatch_geometry_attempt_0"
        dump(run_dir / "idea.json", base_idea())
        topic = dump(root / "ideas" / "topic.json", [base_idea()])
        rd = root / "ideas" / "topic_research"
        dump(rd / "step0_session_config.json", {"consumed": [
            {"gap": "GAP_001", "angle": "reference mismatch", "idea": "reference_mismatch_geometry", "generation": 1,
             "also_uses": []}]})
        (rd / "step4_references.bib").write_text("% bib\n", encoding="utf-8")
        gen = rd / "gen_1"
        dump(gen / "idea.json", {"idea": base_idea()})
        (gen / "step6_sota_review.md").write_text("# sota\n", encoding="utf-8")
        if with_new:
            (gen / "step7b_problem.md").write_text("# Problem and question\n", encoding="utf-8")
            dump(gen / "argument.json", base_argument())
        return run_dir, topic, gen

    def test_with_problem_and_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, topic, gen = self.build(tmp, True)
            code, out, err = run("link-run", run_dir, topic)
            self.assertEqual(code, 0, err)
            ptr = json.loads((run_dir / "ideation_source.json").read_text(encoding="utf-8"))
            self.assertEqual(list(ptr), OLD_POINTER_KEYS + ["problem", "argument"])
            self.assertEqual(Path(ptr["problem"]), (gen / "step7b_problem.md").resolve())
            self.assertEqual(Path(ptr["argument"]), (gen / "argument.json").resolve())
            self.assertTrue(Path(ptr["problem"]).is_absolute() and Path(ptr["argument"]).is_absolute())
            self.assertEqual((ptr["generation"], ptr["gap"]), (1, "GAP_001"))
            self.assertIn("problem: ok", out)

    def test_without_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, topic, gen = self.build(tmp, False)
            code, out, err = run("link-run", run_dir, topic)
            self.assertEqual(code, 0, err)
            ptr = json.loads((run_dir / "ideation_source.json").read_text(encoding="utf-8"))
            self.assertIsNone(ptr["problem"])
            self.assertIsNone(ptr["argument"])
            self.assertEqual(Path(ptr["sota_review"]), (gen / "step6_sota_review.md").resolve())
            self.assertIsNone(ptr["journal_recommendations"])

    def test_generation_folder_not_identified(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, topic, gen = self.build(tmp, True)
            (gen / "idea.json").unlink()
            self.assertEqual(run("link-run", run_dir, topic)[0], 0)
            ptr = json.loads((run_dir / "ideation_source.json").read_text(encoding="utf-8"))
            self.assertEqual((ptr["generation_dir"], ptr["problem"], ptr["argument"]), (None, None, None))

    @unittest.skipUnless(OLD_SCRIPT.exists(), "pre-change copy of ideate_tools.py not available")
    def test_existing_pointer_fields_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, topic, _ = self.build(tmp, False)
            self.assertEqual(run("link-run", run_dir, topic, script=OLD_SCRIPT)[0], 0)
            old = json.loads((run_dir / "ideation_source.json").read_text(encoding="utf-8"))
            self.assertEqual(run("link-run", run_dir, topic)[0], 0)
            new = json.loads((run_dir / "ideation_source.json").read_text(encoding="utf-8"))
            self.assertEqual({k: new[k] for k in old}, old)


# ------------------------------------------------- validate / append-idea
class TestIdeaContractUnchanged(unittest.TestCase):
    def old_style_idea(self):
        idea = base_idea()
        idea["Name"] = "old_style"
        idea["Experiments"] = ["**E0 Data**\n- 109 subjects", "E1 Baseline: CSP+LDA", "E2: Mismatch matrix"]
        return idea

    def test_append_then_validate(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "topic.json"
            for idea, wrap in ((self.old_style_idea(), False), (base_idea(), True)):
                src = dump(Path(tmp) / f"{idea['Name']}.json", {"idea": idea} if wrap else idea)
                code, out, err = run("append-idea", archive, src)
                self.assertEqual(code, 0, out + err)
            data = json.loads(archive.read_text(encoding="utf-8"))
            self.assertEqual(data, [self.old_style_idea(), base_idea()])
            self.assertEqual([list(i) for i in data], [list(base_idea())] * 2)  # the 7 keys, in order
            code, out, _ = run("validate", archive)
            self.assertEqual((code, out.strip().splitlines()), (0, ["topic.json: 2 idea(s)", "OK"]))

    def test_rejections_are_the_same(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "topic.json"
            good = dump(Path(tmp) / "good.json", base_idea())
            self.assertEqual(run("append-idea", archive, good)[0], 0)
            self.assertEqual(run("append-idea", archive, good)[0], 2)  # duplicate Name
            extra = dict(base_idea(), Name="with_argument", Argument={"claims": []})  # an 8th key stays illegal
            self.assertEqual(run("append-idea", archive, dump(Path(tmp) / "extra.json", extra))[0], 2)
            reordered = {k: base_idea()[k] for k in reversed(list(base_idea()))}
            reordered["Name"] = "reordered"
            self.assertEqual(run("append-idea", archive, dump(Path(tmp) / "re.json", reordered))[0], 2)
            short = dict(base_idea(), Name="short_abstract", Abstract="too short")
            self.assertEqual(run("append-idea", archive, dump(Path(tmp) / "short.json", short))[0], 2)
            self.assertEqual(len(json.loads(archive.read_text(encoding="utf-8"))), 1)
            dump(archive, [base_idea(), dict(base_idea(), Name="Bad Name")])
            code, out, _ = run("validate", archive)
            self.assertEqual(code, 2)
            self.assertIn("1 problem(s)", out)

    @unittest.skipUnless(OLD_SCRIPT.exists(), "pre-change copy of ideate_tools.py not available")
    def test_same_output_as_the_previous_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            ideas = [self.old_style_idea(), base_idea(), dict(base_idea(), Name="Bad Name"),
                     dict(base_idea(), Name="short_abstract", Abstract="too short")]
            results = []
            for tag, script in (("old", OLD_SCRIPT), ("new", SCRIPT)):
                archive = Path(tmp) / tag / "topic.json"
                trace = []
                for i, idea in enumerate(ideas):
                    src = dump(Path(tmp) / tag / f"idea_{i}.json", idea)
                    code, out, err = run("append-idea", archive, src, script=script)
                    trace.append((code, out.replace(str(archive), "ARCHIVE"), err))
                trace.append(run("validate", archive, script=script))
                dump(archive, ideas)
                trace.append(run("validate", archive, script=script))
                results.append((trace, archive.read_text(encoding="utf-8")))
            self.assertEqual(results[0], results[1])


if __name__ == "__main__":
    unittest.main()
