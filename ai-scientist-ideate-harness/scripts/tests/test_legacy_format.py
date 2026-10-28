#!/usr/bin/env python3
"""Regression tests for the archived engine's output format (it_legacy.py): the files both engines write keep every
field, type and nesting the archived engine wrote (fixtures/legacy/archived: trimmed copies of its output), beside the
pipeline's own fields, which stay as they were.

  python3 scripts/tests/test_legacy_format.py
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ARCH = SCRIPTS / "tests" / "fixtures" / "legacy" / "archived"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "tests" / "search"))
import it_collide  # noqa: E402
import it_common  # noqa: E402
import it_frame  # noqa: E402
import it_legacy  # noqa: E402
import it_ledger  # noqa: E402
import it_screen  # noqa: E402

JSON_FILES = list(it_legacy.JSON_SPEC)
# maps keyed by data (source names, query ids, weight names): compared as one wildcard
MAPS = {"$.search_summary.sources", "$.search_summary.queries", "$.screening_config.weights"}


def arch(name: str):
    return json.loads((ARCH / name).read_text(encoding="utf-8"))


def shape(v, path="$", out=None) -> dict:
    """path -> JSON types; `[]` = each array item, `{*}` = each value of a data-keyed map."""
    out = {} if out is None else out
    out.setdefault(path, set()).add(it_legacy._jtype(v))
    if isinstance(v, dict):
        for k, x in v.items():
            shape(x, f"{path}.{{*}}" if path in MAPS else f"{path}.{k}", out)
    elif isinstance(v, list):
        for x in v:
            shape(x, f"{path}[]", out)
    return out


def lost_paths(old_doc, new_doc) -> list[str]:
    """Paths of the archived document the new one lacks - except below an array or map that is present but empty in
    the new one (no items to carry them: content, not structure)."""
    so, sn = shape(old_doc), shape(new_doc)
    out = []
    for p in so:
        if p in sn:
            continue
        cut = [p[:i] for i in range(len(p), 0, -1) if p[:i].endswith(("[]", ".{*}"))]
        if any(a not in sn and a[: -(2 if a.endswith("[]") else 4)] in sn for a in cut):
            continue
        out.append(p)
    return sorted(out)


def subset(a, b) -> bool:
    """Every key and value of `a` is in `b` (lists item by item): nothing the pipeline wrote was dropped or changed."""
    if isinstance(a, dict):
        return isinstance(b, dict) and all(k in b and subset(v, b[k]) for k, v in a.items())
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(subset(x, y) for x, y in zip(a, b))
    return a == b


class TestArchivedFixturesAreTheSpec(unittest.TestCase):
    """The spec accepts the archived engine's own output: it describes the original format, not this pipeline's."""

    def test_json_spec_accepts_archived(self):
        for name in JSON_FILES:
            self.assertEqual(it_legacy.check_json(name, arch(name)), [], name)

    def test_md_spec_accepts_archived(self):
        for name in it_legacy.MD_SPEC:
            if it_legacy.MD_SPEC[name].get("skill"):          # a file the archived engine did not write
                continue
            text = (ARCH / name.replace("gen_*/", "")).read_text(encoding="utf-8")
            self.assertEqual(it_legacy.check_md(name, text), [], name)


REFS = SCRIPTS.parent / "references"


def template_headings(path: Path, marker: str) -> set[str]:
    """The heading templates of the ```markdown block of a rules file that contains `marker` (a template line's
    annotation after two spaces or an arrow is dropped)."""
    text = path.read_text(encoding="utf-8")
    block = next(b for b in text.split("```markdown")[1:] if marker in b.split("```")[0]).split("```")[0]
    out = set()
    for ln in block.splitlines():
        if re.match(r"^#{1,6} ", ln):
            out.add(it_legacy.heading_template(re.split(r"\s{2,}|←", ln)[0].replace("{n}", "1").replace("{Venue}", "x")))
    return out


class TestSpecsFollowTheRules(unittest.TestCase):
    """The sections the checker asks of a model-written file are the ones its template in the rules lists."""

    def test_prescriptive_body(self):
        tpl = template_headings(REFS / "knowledge-templates.md", "body_role: prescriptive") - {"# idea title research plan"}
        want = it_legacy.MD_SPEC["gen_*/body/B_draft_*.md"]["headings"]
        covered = lambda t, h: t == h or t.startswith(h + " ")  # noqa: E731
        self.assertEqual({h for h in want if not any(covered(t, h) for t in tpl)}, set())
        self.assertEqual({t for t in tpl if not any(covered(t, h) for h in want)}, set())

    def test_sota_review(self):
        tpl = template_headings(REFS / "research-cycle.md", "# State-of-the-art review")
        want = set(it_legacy.MD_SPEC["step6_sota_review.md"]["headings"])
        self.assertEqual({h for h in want if not any(t == h or t.startswith(h + " ") for t in tpl)}, set())

    def test_journal_recommendations(self):
        tpl = template_headings(REFS / "research-cycle.md", "journals_recommended")
        want = set(it_legacy.MD_SPEC["gen_*/step8_journal_recommendations.md"]["headings"])
        self.assertEqual({h for h in want if not any(t == h or t.startswith(h + " ") for t in tpl)}, set())

    def test_hypothesis_sections(self):
        doc = "\n\n".join(["# Hypothesis — gen 1", "## Selected gap summary", "## Research questions", "## Hypotheses",
                           "## Rival explanations", "## Operational definitions", "## Scope", "## Conceptual framework",
                           "## Risk assessment\n\n| Risk | Likelihood | Impact | Mitigation |\n|---|---|---|---|",
                           "## By-construction check (C1, primary)", "## External check", "## Power",
                           "## Traceability\n\n| Element | Source | Evidence |\n|---|---|---|"])
        self.assertEqual(it_legacy.check_md("gen_*/step8_hypothesis.md", doc), [])
        self.assertEqual(it_legacy.check_md("gen_*/step8_hypothesis.md", doc.replace("## Power", "## Notes")),
                         ["gen_*/step8_hypothesis.md: no '## power' section"])
        self.assertEqual(it_legacy.spec_key("gen_3/body/B_draft_x.md"), "gen_*/body/B_draft_*.md")


class TestSearchBlockEndToEnd(unittest.TestCase):
    """The fixture topic through the real tools - A1 -> A2 -> A3 -> A5 -> A3 -> A4 (test_a4_export.build_good) - writes
    step0, the raw collection, the shortlist and their views in the archived format."""

    @classmethod
    def setUpClass(cls):
        import test_a4_export
        if test_a4_export.MCP_PY is None:
            raise unittest.SkipTest("mcp_bridge.py needs the `mcp` package")
        cls.tmp = Path(tempfile.mkdtemp())
        cls.rd = test_a4_export.build_good(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def doc(self, name):
        return json.loads((self.rd / name).read_text(encoding="utf-8"))

    def test_json_files_meet_the_archived_spec(self):
        for name in ("step0_session_config.json", "step2_raw_papers.json", "step3_shortlist.json", "step3_screening_all.json"):
            self.assertEqual(it_legacy.check_json(name, self.doc(name)), [], name)

    def test_screening_all_is_the_full_decision_table(self):
        d, sl = self.doc("step3_screening_all.json"), self.doc("step3_shortlist.json")
        cands = {p["id"] for p in self.doc("step2_raw_papers.json")["papers"]} | \
                {p["id"] for p in self.doc("step2b_snowball_papers.json")["papers"]}
        ids = [p["id"] for p in d["papers"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), cands)                                  # every candidate, once
        kept = {p["id"]: p for p in d["papers"] if p["screening"]["category"] != "excluded"}
        self.assertEqual(set(kept), {p["id"] for p in sl["papers"]})        # included + borderline = the shortlist
        for p in sl["papers"]:
            self.assertEqual(kept[p["id"]]["screening"]["category"], "borderline" if p["screening"]["tier"] == 4 else "included")
            self.assertEqual(kept[p["id"]]["screening"]["composite"], p["screening"]["composite"])
        comp = [p["screening"]["composite"] for p in d["papers"]]
        self.assertEqual(comp, sorted((c for c in comp if c is not None), reverse=True) + [None] * comp.count(None))
        for p in d["papers"]:
            s = p["screening"]
            self.assertNotIn("citation_key", p)                              # A4.k's part, written after A3
            self.assertNotIn("access_level", p)                              # A6.c's part
            if s["category"] == "excluded":
                self.assertTrue(s["exclusion_reason"].startswith(s["exclusion_code"] + ": "))
                self.assertIsNone(s["tier"])
                # unscored exactly when excluded before scoring
                self.assertEqual(s["composite"] is None, s["stage"] in ("gate", "criteria", "criteria-title", "duplicate"))
        self.assertEqual(d["summary"]["candidates"], len(ids))
        self.assertEqual([t["tier"] for t in d["tier_names"]], [1, 2, 3, 4])
        cfg = self.doc("step0_session_config.json")
        self.assertEqual([c["id"] for c in d["criteria_inclusion"]], [c["id"] for c in cfg["protocol"]["criteria"]["inclusion"]])

    def test_screening_all_is_a3s(self):
        self.assertIn({"file": "step3_screening_all.json"}, it_ledger.io("A3")["owns"])

    def test_no_archived_path_is_lost(self):
        for name in ("step0_session_config.json", "step2_raw_papers.json", "step3_shortlist.json", "step3_screening_all.json"):
            self.assertEqual(lost_paths(arch(name), self.doc(name)), [], name)
        sources = self.doc("step2_raw_papers.json")["search_summary"]["sources"]
        self.assertTrue(set(it_legacy.ARCHIVED_SOURCES) <= set(sources))     # arxiv: 0 when not searched

    def test_citation_network_rows_are_consistent(self):
        """A row's degrees are counted from its own lists, in every file that carries the network."""
        for name in ("step2_raw_papers.json", "step3_shortlist.json", "step3_screening_all.json"):
            for p in self.doc(name)["papers"]:
                n = p["citation_network"]
                self.assertEqual((n["in_degree"], n["out_degree"], n["is_hub"]),
                                 (len(p["cited_by"]), len(p["references"]), len(p["cited_by"]) >= it_legacy.HUB_IN_DEGREE),
                                 f"{name} {p['id']}")

    def test_views_meet_the_archived_spec(self):
        for name in ("step2_search_summary.md", "step3_screening_results.md", "step4_citation_keys.md"):
            text = (self.rd / name).read_text(encoding="utf-8")
            self.assertEqual(it_legacy.check_md(name, text), [], name)

    def test_views_keep_their_own_text(self):
        text = (self.rd / "step3_screening_results.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("<!-- generated by `ideate_tools.py screen-build` (A3) - do not edit -->\n# Screening results", text)
        self.assertLess(text.index("## Exclusions by reason"), text.index(it_legacy.LEGACY_RULE.strip()[:20]))

    def test_pipeline_fields_are_kept(self):
        sl, raw, cfg = self.doc("step3_shortlist.json"), self.doc("step2_raw_papers.json"), self.doc("step0_session_config.json")
        self.assertEqual(sl["schema"], "ideate-shortlist/2")
        self.assertIn("screened", sl["summary"])
        self.assertTrue(all("roles" in p and "arithmetic" in p["screening"] for p in sl["papers"]))
        self.assertEqual(raw["schema"], it_legacy.read_json(self.rd / "step2_raw_papers.json")["schema"])
        self.assertTrue(all("found_by" in p for p in raw["papers"]))
        self.assertIn("protocol", cfg)
        self.assertEqual(cfg["topic_slug"], it_legacy.slugify(cfg["topic_original"]))
        self.assertGreaterEqual(cfg["current_step"], 1)           # the folder as it was at step0's last write

    def test_legacy_category_follows_the_tier(self):
        for p in self.doc("step3_shortlist.json")["papers"]:
            self.assertEqual(p["screening"]["category"], "borderline" if p["screening"]["tier"] == 4 else "included")

    def test_legacy_step0_keys_raise_no_ownership_warning(self):
        self.assertEqual(it_frame.check_ownership(self.doc("step0_session_config.json")), [])

    def test_the_archived_models_read_the_files(self):
        arch_root = SCRIPTS.parents[1] / "archived"
        if not (arch_root / "scholar_research" / "schemas").is_dir():
            self.skipTest("archived/scholar_research not present")
        sys.path.insert(0, str(arch_root))
        try:
            from scholar_research.schemas.paper import RawPapers
            from scholar_research.schemas.session_config import SessionConfig
        except ImportError as e:
            self.skipTest(f"archived engine not importable: {e}")
        SessionConfig.model_validate(self.doc("step0_session_config.json"))
        RawPapers.model_validate(self.doc("step2_raw_papers.json"))
        # ScreeningRecord: the scored rows, with the two known differences set aside - recency_impact is A3.b's
        # one-decimal score (archived: an integer), and a row excluded before scoring has no scores
        from scholar_research.schemas.paper import ScreeningRecord
        d = self.doc("step3_screening_all.json")
        rows = [p for p in d["papers"] if p["screening"]["composite"] is not None]
        for p in rows:
            p["screening"]["recency_impact"] = round(p["screening"]["recency_impact"])
        ScreeningRecord.model_validate({**d, "papers": rows})


def gaps_doc() -> dict:
    g = {"id": "GAP_001", "title": "No dose-response test in MCI", "description": "d", "move": "apply-wider",
         "type": {"primary": "methodological", "secondary": "population"}, "collisions": ["X0001"],
         "axes": ["method-config"], "supporting": [{"key": "smithetal2020", "how": "4 sessions, null"},
                                                   {"key": "parketal2019", "how": "20 sessions, gains"}],
         "counter": [{"key": "parketal2019", "why_open": "pooled populations"}], "why_it_matters": "w",
         "consequence_evidence": ["X0014"], "severity": 4, "novelty": 3, "novelty_basis": "shortlist only",
         "feasibility": 5, "feasibility_basis": ["lens:method-family:meta-analysis"]}
    g2 = {**copy.deepcopy(g), "id": "GAP_002", "title": "Second", "severity": 2, "counter": [], "consequence_evidence": []}
    return {"topic": "t", "gaps": [g, g2], "not_gaps": [], "single_paper": ["x"], "adjacent": [], "revisions_needed": [],
            "ranked": ["GAP_001", "GAP_002"], "composites": {"GAP_001": 4.0, "GAP_002": 3.2}, "retired": [],
            "at": "2026-10-26T15:22:31-07:00"}


STEP0 = {"topic": "EEG neurofeedback for MCI", "timestamp": "2026-10-26T14:39:13-07:00", "sources": ["openalex", "pubmed"],
         "queries": [], "protocol": {"framework": {"name": "PICO", "slots": [{"slot": "population", "value": "MCI"},
                                                                          {"slot": "intervention", "value": "NF"}]},
                                     "timeframe": "2005-2026", "setting": "CPU"}}
SHORTLIST = {"papers": [{"id": "paper_001", "citation_key": "smithetal2020", "year": 2020,
                         "screening": {"tier": 2, "composite": 4.2}}]}
RAW = {"search_summary": {"instances": [{"file": "Q1@abc.json"}], "identification": {"openalex": {}}},
       "papers": [{"id": "paper_001", "openalex_id": "W1", "found_by": ["Q1"], "sources_found_in": ["openalex"]}]}


class TestWriters(unittest.TestCase):
    def setUp(self):
        self.rd = Path(tempfile.mkdtemp())
        it_common.write_json(self.rd / "step0_session_config.json", copy.deepcopy(STEP0))
        it_common.write_json(self.rd / "step3_shortlist.json", copy.deepcopy(SHORTLIST))

    def tearDown(self):
        shutil.rmtree(self.rd, ignore_errors=True)

    def test_gaps_written_stable_carry_the_archived_fields(self):
        it_common.write_json_stable(self.rd / "step7_gaps.json", gaps_doc())
        doc = json.loads((self.rd / "step7_gaps.json").read_text(encoding="utf-8"))
        self.assertEqual(it_legacy.check_json("step7_gaps.json", doc), [])
        self.assertEqual(lost_paths(arch("step7_gaps.json"), doc), [])
        self.assertTrue(subset(gaps_doc(), doc))
        g = doc["gaps"][0]
        self.assertEqual((g["rank"], g["composite"], g["gap"]["title_en"]), (1, 4.0, "No dose-response test in MCI"))
        self.assertEqual(g["gap"]["supporting_evidence"][0], {"citation_key": "smithetal2020", "year": 2020,
                                                              "explanation_en": "4 sessions, null"})
        self.assertEqual(doc["session_id"], "20261026")

    def test_an_unchanged_stable_rewrite_keeps_the_file(self):
        it_common.write_json_stable(self.rd / "step7_gaps.json", gaps_doc())
        self.assertFalse(it_common.write_json_stable(self.rd / "step7_gaps.json", {**gaps_doc(), "at": "later"}))

    def test_gap_view_meets_the_archived_spec(self):
        doc = it_common.with_legacy(self.rd / "step7_gaps.json", gaps_doc())
        text = it_legacy.gap_analysis_md("<!-- view -->\n# Gap analysis - t\n", {"topic": "t"}, doc)
        self.assertEqual(it_legacy.check_md("step7_gap_analysis.md", text), [])

    def test_step0_carries_the_archived_keys(self):
        cfg = json.loads((self.rd / "step0_session_config.json").read_text(encoding="utf-8"))
        self.assertEqual(it_legacy.check_json("step0_session_config.json", cfg), [])
        self.assertEqual(cfg["pico"]["population"], "MCI")
        self.assertEqual(cfg["field_type"], "biomedical")
        self.assertEqual(cfg["session_id"], "20261026")

    def test_session_id_and_engine_are_pinned(self):
        p = self.rd / "step0_session_config.json"
        cfg = json.loads(p.read_text(encoding="utf-8"))
        cfg["engine"]["llm_model"] = "model-a"
        it_common.write_json(p, {**cfg, "timestamp": "2027-01-01T00:00:00+00:00"})
        again = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual((again["session_id"], again["engine"]["llm_model"]), ("20261026", "model-a"))

    def test_augment_is_additive_and_idempotent(self):
        docs = {"step0_session_config.json": STEP0, "step2_raw_papers.json": RAW, "step3_shortlist.json": SHORTLIST,
                "step7_gaps.json": gaps_doc()}
        for name, doc in docs.items():
            once = it_legacy.augment(self.rd / name, copy.deepcopy(doc))
            self.assertTrue(subset(doc, once), name)
            self.assertEqual(it_legacy.augment(self.rd / name, copy.deepcopy(once)), once, name)

    def test_current_step_is_the_highest_step_on_disk(self):
        self.assertEqual(it_legacy.current_step(self.rd), 3)           # step0 with a protocol, the shortlist
        (self.rd / "step7_gaps.json").write_text("{}", encoding="utf-8")
        self.assertEqual(it_legacy.current_step(self.rd), 7)
        (self.rd / "gen_1").mkdir()
        (self.rd / "gen_1" / "step8_hypothesis.md").write_text("x", encoding="utf-8")
        self.assertEqual(it_legacy.current_step(self.rd), 8)

    def test_screening_all_rows_for_each_exclusion_path(self):
        (self.rd / "step3_bibliometrics.json").write_text(json.dumps({"papers": {
            f"paper_00{i}": {"impact": 3.4} for i in range(1, 6)}}), encoding="utf-8")
        inc = {"id": "paper_001", "title": "kept", "screening": {"relevance": 4, "quality": 3, "recency_impact": 3.4,
                                                                  "composite": 3.58, "tier": 3, "rationale": "r"}}
        scored = {"relevance": 2, "quality": 2, "recency_impact": 3.4, "composite": 2.28, "tier": 4, "rationale": "low"}
        excluded = [({"id": "paper_002", "title": "editorial"}, None, "X-TYPE", "OpenAlex type: editorial"),
                    ({"id": "paper_003", "title": "off topic"}, None, "EX1", "population mismatch"),
                    ({"id": "paper_004", "title": "weak", "has_abstract": False}, scored, "SCORE", "low"),
                    ({"id": "paper_005", "title": "again"}, None, "DUP", "duplicate of paper_001")]
        scores = {"scores": [{"id": "paper_003", "violates": ["EX1"], "rationale": "population mismatch"}]}
        d = it_legacy.screening_all(self.rd, STEP0, {"screening_config": {}, "papers": [inc]}, excluded, scores,
                                    it_screen.TIER_NAMES, it_screen.GATE_CODES)
        self.assertEqual(it_legacy.check_json("step3_screening_all.json", d), [])
        by = {p["id"]: p["screening"] for p in d["papers"]}
        self.assertEqual([p["id"] for p in d["papers"]], ["paper_001", "paper_004", "paper_002", "paper_003", "paper_005"])
        self.assertEqual({k: by[k]["stage"] for k in by if k != "paper_001"},
                         {"paper_002": "gate", "paper_003": "criteria", "paper_004": "score", "paper_005": "duplicate"})
        self.assertEqual((by["paper_003"]["composite"], by["paper_003"]["recency_impact"], by["paper_003"]["violates"]),
                         (None, 3.4, ["EX1"]))
        self.assertEqual((by["paper_004"]["composite"], by["paper_004"]["tier"], by["paper_004"]["no_abstract"]),
                         (2.28, None, True))
        self.assertEqual(scored["tier"], 4)                                   # the caller's dict is not changed
        self.assertEqual(d["summary"]["excluded_by_stage"], {"gate": 1, "criteria": 1, "score": 1, "duplicate": 1})

    def test_other_files_are_untouched(self):
        d = {"papers": [{"id": "p"}]}
        self.assertIs(it_legacy.augment(self.rd / "step2b_snowball_papers.json", d), d)


class TestLedger(unittest.TestCase):
    def test_legacy_step0_keys_are_not_a_units_write(self):
        before = {"files": {}, "step0": {"topic": "a", "current_step": "x", "pico": "y"}}
        after = {"files": {}, "step0": {"topic": "a", "current_step": "z", "pico": "w"}}
        self.assertEqual(it_ledger._changed(before, after), (set(), set()))
        after["step0"]["topic"] = "b"
        self.assertEqual(it_ledger._changed(before, after)[1], {"topic"})

    def test_no_owner_lists_a_legacy_key(self):
        owned = {k for ks in it_frame.OWNERS.values() for k in ks}
        self.assertEqual(owned & set(it_legacy.LEGACY_STEP0_KEYS), set())


class TestRules(unittest.TestCase):
    def test_constants_agree_with_the_pipeline(self):
        g = {"severity": 4, "novelty": 3, "feasibility": 5}
        self.assertEqual(it_collide.composite(g), round(sum(g[k] * w for k, w in it_legacy.GAP_WEIGHTS.items()), 2))
        self.assertEqual(it_screen.tier_of(it_legacy.INCLUDED_FLOOR), 3)
        self.assertEqual(it_screen.tier_of(it_legacy.INCLUDED_FLOOR - 0.01), 4)
        self.assertEqual(it_screen.INCLUDE_AT, 3.0)

    def test_network_follows_the_archived_rules(self):
        papers = [{"id": f"p{i}", "openalex_id": f"W{i}", "title": "alpha neurofeedback memory"} for i in range(5)]
        net, clusters = it_legacy.network(papers, {"p1": ["W0"], "p2": ["W0", "W9"], "p3": ["W0", "W3"]})
        self.assertEqual(net["p0"]["cited_by"], ["p1", "p2", "p3"])
        self.assertEqual(net["p3"]["references"], ["p0"])          # self-citation and outside works dropped
        self.assertTrue(net["p0"]["citation_network"]["is_hub"])     # in-degree >= 3
        self.assertEqual([c["paper_ids"] for c in clusters], [["p0", "p1", "p2", "p3"]])
        self.assertEqual(net["p4"]["citation_network"]["cluster"], None)

    def test_raw_summary_keeps_the_archived_keys(self):
        """sources lists the archived four (arxiv 0 when not searched); queries counts each paper once per query id, a
        superseded instance ("Q1@<hash>", kept after a re-run) counting for its query."""
        doc = {"search_summary": {"instances": [{"file": "Q1@abc.json"}, {"file": "Q2@def.json"}],
                                  "identification": {"openalex": {}, "scopus": {}}},
               "papers": [{"id": "paper_001", "found_by": ["Q1", "Q1@abc"], "sources_found_in": ["openalex"]},
                          {"id": "paper_002", "found_by": ["Q1@abc", "D1"], "sources_found_in": ["semantic_scholar"]}]}
        s = it_legacy.raw_papers(doc, Path(tempfile.mkdtemp()))["search_summary"]
        self.assertEqual(s["sources"], {"semantic_scholar": 1, "openalex": 1, "pubmed": 0, "arxiv": 0, "scopus": 0})
        self.assertEqual(s["queries"], {"Q1": 2, "Q2": 0, "D1": 1, "snowball": 0})

    def test_a_row_joins_its_own_lists_and_the_network(self):
        """A shortlist record carries the raw file's network and a snowball record its own cited_by: both are kept
        (in their order) and the candidate network's edges added; the degrees follow the joined lists."""
        net = {"p1": {"references": ["p2", "p3"], "cited_by": [],
                      "citation_network": {"in_degree": 0, "out_degree": 2, "is_hub": False, "cluster": "cluster_A"}},
               "p2": {"references": [], "cited_by": ["p1", "p4"],
                      "citation_network": {"in_degree": 2, "out_degree": 0, "is_hub": False, "cluster": "cluster_A"}}}
        q1 = it_legacy._paper({"id": "p1", "references": [], "cited_by": []}, net)
        self.assertEqual((q1["references"], q1["citation_network"]["out_degree"]), (["p2", "p3"], 2))
        q2 = it_legacy._paper({"id": "p2", "cited_by": ["p9", "p1"]}, net)       # snowball: the seeds that cite it
        self.assertEqual(q2["cited_by"], ["p9", "p1", "p4"])
        self.assertEqual(q2["citation_network"], {"in_degree": 3, "out_degree": 0, "is_hub": True, "cluster": "cluster_A"})
        self.assertEqual(it_legacy._paper({"id": "p5"}, net)["citation_network"],
                         {"in_degree": 0, "out_degree": 0, "is_hub": False, "cluster": None})

    def test_in_text_citation(self):
        self.assertEqual(it_legacy.in_text({"authors": ["Ann Lee"], "year": 2020}), "(Lee, 2020)")
        self.assertEqual(it_legacy.in_text({"authors": ["Lee, Ann", "Bo Kim"], "year": 2020}), "(Lee & Kim, 2020)")
        self.assertEqual(it_legacy.in_text({"authors": ["A Lee", "B Kim", "C Wu"], "year": 2020}), "(Lee et al., 2020)")

    def test_slug_is_the_archived_one(self):
        self.assertEqual(it_legacy.slugify("EEG neurofeedback for MCI"), "eeg-neurofeedback-for-mci")
        self.assertEqual(len(it_legacy.slugify("x" * 80)), 40)


class TestTypedFrontMatter(unittest.TestCase):
    """The concept index carries the same types with or without PyYAML (it fell back to strings: year "2011")."""

    def test_fallback_types_scalars_as_yaml_does(self):
        import ideate_tools
        saved = sys.modules.get("yaml")
        sys.modules["yaml"] = None                                  # import yaml -> ImportError: the fallback parser
        try:
            fm = ideate_tools.frontmatter('---\nid: P_x\nyear: 2011\nscore: 0.5\nok: true\nparent: \n'
                                          'name: "2011"\ntags: [a, 3]\n---\nbody\n')
        finally:
            if saved is None:
                sys.modules.pop("yaml", None)
            else:
                sys.modules["yaml"] = saved
        self.assertEqual(fm, {"id": "P_x", "year": 2011, "score": 0.5, "ok": True, "parent": None, "name": "2011",
                              "tags": ["a", 3]})


class TestIdeaName(unittest.TestCase):
    def test_argument_without_idea_warns(self):
        import ideate_tools
        texts = [f["text"] for f in ideate_tools.check_argument({"schema": ideate_tools.ARG_SCHEMA}, None)
                 if f["level"] == "WARN" and f["check"] == "SCHEMA"]
        self.assertTrue(any("'idea' should be the idea's Name" in t for t in texts))
        texts = [f["text"] for f in ideate_tools.check_argument({"schema": ideate_tools.ARG_SCHEMA, "idea": "x_y"}, None)]
        self.assertFalse(any("'idea' should be" in t for t in texts))


if __name__ == "__main__":
    unittest.main()
