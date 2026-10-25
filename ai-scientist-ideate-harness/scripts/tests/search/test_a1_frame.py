#!/usr/bin/env python3
"""Tests for A1 frame (it_frame.py; rules references/search/A1-frame.md): the good path through the CLI, one failing
counter-example per handoff check (tests/fixtures/search/a1/neg/*.json), ownership, the rendered Boolean form, and the
refusal of every search-block check on a step0 without a protocol.

  python3 .claude/skills/ai-scientist-ideate/scripts/tests/search/test_a1_frame.py

Only unittest + tempfile + subprocess. Every run works in a temporary directory; nothing in the repo is written.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2]
TOOLS = SCRIPTS / "ideate_tools.py"
FIX = SCRIPTS / "tests" / "fixtures" / "search" / "a1"
REPO = SCRIPTS.parents[3]
sys.path.insert(0, str(SCRIPTS))
import it_frame  # noqa: E402


def run(*args):
    p = subprocess.run([sys.executable, str(TOOLS), *map(str, args)], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def apply_ops(doc, ops):
    """set / delete / append on dotted paths; list indices are integers."""
    for op in ops:
        keys = op["path"].split(".")
        cur = doc
        for k in keys[:-1]:
            cur = cur[int(k)] if isinstance(cur, list) else cur[k]
        last = keys[-1]
        if op["op"] == "set":
            if isinstance(cur, list):
                cur[int(last)] = op["value"]
            else:
                cur[last] = op["value"]
        elif op["op"] == "delete":
            del cur[int(last) if isinstance(cur, list) else last]
        elif op["op"] == "append":
            (cur[int(last)] if isinstance(cur, list) else cur[last]).append(op["value"])
    return doc


class FakeProbeServer:
    """Answers the probe as the scholar server would for the fixture topic: ten hits per source for each trial query,
    and the known items themselves for their lookups (tests/fixtures/search/a1/good/scope_probe.json)."""

    def __init__(self):
        self.known = json.loads((FIX / "good" / "scope_probe.json").read_text())["known_items"]

    async def call(self, tool, params):
        assert tool == "scholar_search", tool
        if params.get("found_via") == "probe:known-item":
            return {"papers": [{"title": k["title"], "doi": k["doi"], "year": k["year"], "authors": ["A B"]}
                               for k in self.known if params["query"].split()[0].lower() in k["title"].lower()]}
        return {"papers": [{"title": f"hit {i}", "sources_found_in": [src]} for src in ("openalex", "pubmed") for i in range(10)],
                "source_errors": {}}


def run_probe(rd: Path) -> dict:
    import asyncio

    async def nosleep(_):
        return None
    cfg = json.loads((rd / "step0_session_config.json").read_text())
    return asyncio.run(it_frame.run_probe(FakeProbeServer(), cfg, rd, "x@example.com",
                                          fetch=lambda url, rd=None: {"meta": {"count": 2140}}, sleep=nosleep))


def build_good(tmp: Path) -> Path:
    """A research dir taken through A1.p -> A1.q -> probe (a fake scholar server) -> A1.v -> A1.e."""
    shutil.copy(FIX / "good" / "topic.md", tmp / "topic.md")
    rd = tmp / "topic_research"
    rd.mkdir()
    for cmd, f in (("set-protocol", "protocol.json"), ("set-strategy", "strategy.json")):
        code, out = run("frame", cmd, rd, FIX / "good" / f)
        assert code == 0, out
    run_probe(rd)
    code, out = run("frame", "set-context", rd, FIX / "good" / "context.json")
    assert code == 0, out
    code, out = run("frame", "eval-brief", rd)
    assert code == 0, out
    code, out = run("frame", "set-evaluation", rd, FIX / "good" / "evaluation.json")
    assert code == 0, out
    return rd


class TestGoodPath(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.rd = build_good(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_check_passes(self):
        code, out = run("frame", "check", self.rd)
        self.assertEqual(code, 0, out)
        self.assertIn("OK", out)

    def test_e6_readings_and_older_rounds(self):
        """§14 F4: a new round must report E6, and an E6 note makes its criterion soft; a round stored before E6
        (no `checks`) is judged on E1-E5 and makes nothing soft."""
        ev = json.loads((self.rd / "step1_protocol_evaluation.json").read_text())
        self.assertEqual(ev["rounds"][-1]["checks"], list(it_frame.CHECK_IDS))
        self.assertEqual(it_frame.soft_criteria(self.rd), {})
        old = {k: v for k, v in ev["rounds"][-1].items() if k != "checks"}
        old["findings"] = [f for f in old["findings"] if f["check"] != "E6"]
        self.assertEqual(it_frame.check_round(old), [])
        self.assertEqual([f["code"] for f in it_frame.check_round({**old, "checks": list(it_frame.CHECK_IDS)})], ["E02"])
        note = {"check": "E6", "result": "note", "criterion": "EX1", "word": "real speakers",
                "alt_reading": "the speakers' real faces", "evidence": "EX1"}
        new = {**old, "checks": list(it_frame.CHECK_IDS), "findings": old["findings"] + [note]}
        self.assertEqual(it_frame.check_round(new, {"IN1", "EX1"}), [])
        self.assertEqual([f["code"] for f in it_frame.check_round(new, {"IN1"})], ["E06"])
        ev["rounds"][-1] = new
        (self.rd / "step1_protocol_evaluation.json").write_text(json.dumps(ev))
        self.assertEqual(it_frame.soft_criteria(self.rd)["EX1"]["word"], "real speakers")
        ev["rounds"][-1]["findings"].append({**note, "criterion": "IN1", "word": "dense"})   # an IN stays a note
        (self.rd / "step1_protocol_evaluation.json").write_text(json.dumps(ev))
        self.assertEqual(set(it_frame.soft_criteria(self.rd)), {"EX1"})

    def test_boolean_rendered_from_axes(self):
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())
        q1 = cfg["queries"][0]
        self.assertEqual(q1["boolean_query"], '(EEG OR electroencephalograph* OR "scalp recording") AND ("artifact rejection" OR '
                                              '"artefact removal" OR "automated cleaning" OR "artifact detection")')
        self.assertEqual(q1["query"], q1["flat_query"])

    def test_protocol_hash_and_no_copy(self):
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())
        self.assertEqual(cfg["protocol"]["timeframe"], "2013-2026")
        self.assertNotIn("pico", cfg)
        self.assertTrue(cfg["protocol"]["topic_sha256"])

    def test_view_rendered(self):
        view = (self.rd / "step1_protocol.md").read_text()
        for part in ("Question framework — PICO", "Search axes", "Eligibility criteria", "Deviation log", "approved-with-notes"):
            self.assertIn(part, view)

    def test_topic_change_is_stale_warning(self):
        (self.tmp / "topic.md").write_text("# changed\n")
        code, out = run("frame", "check", self.rd, "--unit", "A1.p")
        self.assertEqual(code, 0, out)
        self.assertIn("P10", out)
        self.assertIn("STALE", out)

    def test_probe_field_of_b0_survives_context(self):
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())
        cfg["local_environment"]["probe"] = {"at": "x"}
        (self.rd / "step0_session_config.json").write_text(json.dumps(cfg))
        code, out = run("frame", "set-context", self.rd, FIX / "good" / "context.json")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads((self.rd / "step0_session_config.json").read_text())["local_environment"]["probe"], {"at": "x"})


class TestNegativeFixtures(unittest.TestCase):
    """Every handoff check has a counter-example that must fail it (armor §7.4)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.rd = build_good(cls.tmp)
        cls.cfg = json.loads((cls.rd / "step0_session_config.json").read_text())
        cls.ev = json.loads((cls.rd / "step1_protocol_evaluation.json").read_text())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_every_counter_example_fails_its_check(self):
        cases = sorted((FIX / "neg").glob("*.json"))
        self.assertGreaterEqual(len(cases), 30)
        for path in cases:
            case = json.loads(path.read_text())
            with self.subTest(case=path.stem):
                cfg = copy.deepcopy(self.cfg)
                if case["target"] == "evaluation":
                    ev = apply_ops(copy.deepcopy(self.ev), case["ops"])
                    rd = self.tmp / f"ev_{path.stem}"
                    rd.mkdir(exist_ok=True)
                    (rd / "step1_protocol_evaluation.json").write_text(json.dumps(ev))
                else:
                    cfg = apply_ops(cfg, case["ops"])
                    rd = self.rd
                fs = it_frame.run_checks(cfg, rd, case["unit"])
                level = case.get("level", "ERROR")
                codes = {f["code"] for f in fs if f["level"] == level}
                self.assertIn(case["expect"], codes, f"{path.stem}: {case['why']} - got {sorted(codes)} at {level}")


class TestWritesAreGuarded(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.rd = build_good(self.tmp)
        self.before = (self.rd / "step0_session_config.json").read_text()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def bad(self, name, data):
        p = self.tmp / name
        p.write_text(json.dumps(data))
        return p

    def test_error_writes_nothing(self):
        prot = json.loads((FIX / "good" / "protocol.json").read_text())
        prot["protocol"]["criteria"]["exclusion"] = []
        code, out = run("frame", "set-protocol", self.rd, self.bad("p.json", prot))
        self.assertEqual(code, 2, out)
        self.assertEqual((self.rd / "step0_session_config.json").read_text(), self.before)

    def test_foreign_keys_refused(self):
        for cmd, data in (("set-protocol", {"protocol": {}, "queries": []}),
                          ("set-strategy", {"queries": [], "target_venues": []}),
                          ("set-context", {"target_venues": [], "protocol": {}})):
            code, out = run("frame", cmd, self.rd, self.bad(f"{cmd}.json", data))
            self.assertEqual(code, 2, f"{cmd}: {out}")
            self.assertIn("does not own", out)

    def test_set_context_refuses_a_malformed_file(self):
        code, out = run("frame", "set-context", self.rd, self.bad("ctx.json", {"target_venues": ["ACL", "EMNLP"],
                                                                            "expert_domain": "NLP", "local_environment": "none"}))
        self.assertEqual(code, 2, out)
        self.assertIn("local_environment is an object", out)
        self.assertNotIn("Traceback", out)

    def test_set_strategy_refused_after_search(self):
        (self.rd / "step2_raw_papers.json").write_text("{}")
        before = (self.rd / "step0_session_config.json").read_bytes()
        code, out = run("frame", "set-strategy", self.rd, FIX / "good" / "strategy.json")
        self.assertEqual(code, 0, out)                                   # the same strategy: re-recorded, not rewritten
        self.assertEqual((self.rd / "step0_session_config.json").read_bytes(), before)
        st = json.loads((FIX / "good" / "strategy.json").read_text())
        st["queries"][1]["flat_query"] = "EEG artefact removal"
        code, out = run("frame", "set-strategy", self.rd, self.bad("changed.json", st))
        self.assertEqual(code, 2, out)
        self.assertIn("query-revise", out)

    def test_query_revise_retires_and_logs(self):
        rev = {"retire": "Q2", "reason": "on-anchor share 31%", "round": 1,
               "add": {"id": "Q2b", "strategy": "synonym-swap", "axes": {"C1": ["EEG"], "C2": ["artifact detection"]},
                       "flat_query": "EEG artifact detection", "rationale": "detection wording"}}
        code, out = run("frame", "query-revise", self.rd, self.bad("rev.json", rev))
        self.assertEqual(code, 0, out)
        cfg = json.loads((self.rd / "step0_session_config.json").read_text())
        q2 = next(q for q in cfg["queries"] if q["id"] == "Q2")
        self.assertEqual((q2["status"], q2["retired_by"]), ("retired", "Q2b"))
        self.assertEqual(cfg["queries_history"][-1]["by"], "A2.c")
        self.assertIn("on-anchor share 31%", (self.rd / "step1_protocol.md").read_text())

    def test_evaluation_rounds_capped(self):
        ev = json.loads((FIX / "good" / "evaluation.json").read_text())
        ev["verdict"] = "revision-required"
        ev["findings"][0] = {"check": "E1", "result": "fail", "severity": "improvable", "fix_target": "A1.q",
                             "evidence": "x", "fix": "y"}
        tmp = Path(tempfile.mkdtemp())
        try:
            rd = build_good(tmp)
            (rd / "step1_protocol_evaluation.json").unlink()
            code, out = run("frame", "set-evaluation", rd, self.bad("r1.json", ev))
            self.assertEqual(code, 0, out)
            self.assertIn("pending-revision", out)
            code, out = run("frame", "set-evaluation", rd, self.bad("r1b.json", ev))
            self.assertEqual(code, 0, out)                      # the same reply again: the same round, not a second one
            self.assertEqual(len(json.loads((rd / "step1_protocol_evaluation.json").read_text())["rounds"]), 1)
            ev_b = dict(ev, summary="a different reply on an unrevised protocol")
            code, out = run("frame", "set-evaluation", rd, self.bad("r1c.json", ev_b))
            self.assertEqual(code, 2, out)                      # nothing was revised
            st = json.loads((FIX / "good" / "strategy.json").read_text())   # the fix goes through A1.q's own tool
            st["queries"][0]["rationale"] = "revised after round 1"
            code, out = run("frame", "set-strategy", rd, self.bad("strategy_r2.json", st))
            self.assertEqual(code, 0, out)
            code, out = run("frame", "set-evaluation", rd, self.bad("r2.json", ev))
            self.assertEqual(code, 0, out)
            self.assertIn("accepted-with-doubts", out)
            code, out = run("frame", "set-evaluation", rd, self.bad("r2again.json", ev))
            self.assertEqual(code, 0, out)                      # round 2's reply stored again (a resumed run)
            code, out = run("frame", "set-evaluation", rd, self.bad("r3.json", dict(ev, summary="a third reading")))
            self.assertEqual(code, 2, out)                      # no third round
            code, out = run("frame", "check", rd, "--unit", "A1.e")
            self.assertEqual(code, 0, out)
        finally:
            shutil.rmtree(tmp)


class TestStalenessAndGate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.rd = build_good(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def cfg(self):
        return json.loads((self.rd / "step0_session_config.json").read_text())

    def test_gate_open_when_a1_done(self):
        self.assertEqual(it_frame.search_gate(self.cfg(), self.rd), [])

    def test_gate_closed_without_evaluation(self):
        (self.rd / "step1_protocol_evaluation.json").unlink()
        self.assertIn("E01", {f["code"] for f in it_frame.search_gate(self.cfg(), self.rd)})

    def test_gate_ignores_a1v(self):
        cfg = self.cfg()
        cfg.pop("target_venues")
        self.assertEqual(it_frame.search_gate(cfg, self.rd), [])

    def test_gate_needs_a_protocol(self):
        cfg = self.cfg()
        cfg.pop("protocol")
        with self.assertRaises(SystemExit):
            it_frame.search_gate(cfg, self.rd)

    @unittest.skipUnless(Path("/opt/anaconda3/envs/drug/bin/python").exists(), "needs the interpreter with `mcp`")
    def test_search_refuses_before_a1(self):
        (self.rd / "step1_protocol_evaluation.json").unlink()
        p = subprocess.run(["/opt/anaconda3/envs/drug/bin/python", str(SCRIPTS / "mcp_bridge.py"), "search", str(self.rd)],
                           capture_output=True, text=True, timeout=60)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("A1 is not done", p.stderr)
        self.assertFalse((self.rd / "step2_raw_papers.json").exists())

    def test_protocol_rewrite_makes_strategy_stale(self):
        prot = json.loads((FIX / "good" / "protocol.json").read_text())
        prot["protocol"]["timeframe"] = "2015-2026"
        f = self.tmp / "p2.json"
        f.write_text(json.dumps(prot))
        code, out = run("frame", "set-protocol", self.rd, f, "--note", "narrower timeframe")
        self.assertEqual(code, 0, out)
        code, out = run("frame", "check", self.rd, "--unit", "A1.q")
        self.assertEqual(code, 1, out)
        self.assertIn("Q21", out)

    def test_unchanged_strategy_keeps_probe(self):
        code, out = run("frame", "set-strategy", self.rd, FIX / "good" / "strategy.json")
        self.assertEqual(code, 0, out)
        self.assertIn("scope_probe", self.cfg())
        st = json.loads((FIX / "good" / "strategy.json").read_text())
        st["queries"][0]["rationale"] += " (reworded)"           # rationale is not what the probe answered
        st["queries"][0]["flat_query"] = "EEG artifact rejection"
        f = self.tmp / "s2.json"
        f.write_text(json.dumps(st))
        code, out = run("frame", "set-strategy", self.rd, f)
        self.assertEqual(code, 0, out)
        self.assertNotIn("scope_probe", self.cfg())

    def test_declared_revision_keeps_evaluation_current(self):
        (self.rd / "step2_raw_papers.json").write_text("{}")
        rev = {"retire": "Q2", "reason": "low on-anchor share", "round": 1,
               "add": {"id": "Q2b", "strategy": "synonym-swap", "axes": {"C1": ["EEG"], "C2": ["artifact detection"]},
                       "flat_query": "EEG artifact detection", "rationale": "detection wording"}}
        f = self.tmp / "rev.json"
        f.write_text(json.dumps(rev))
        code, out = run("frame", "query-revise", self.rd, f)
        self.assertEqual(code, 0, out)
        self.assertEqual(it_frame.search_gate(self.cfg(), self.rd), [])


class TestRulesLiveInOnePlace(unittest.TestCase):
    """PLAN_ideate_layout.md R1/R2: A1's checked numbers are stated in its rule home and agree with the code; the other
    references and SKILL.md link to it instead of restating them."""
    SKILL = SCRIPTS.parent

    def test_rule_home_agrees_with_constants(self):
        text = (self.SKILL / "references" / "search" / "A1-frame.md").read_text()
        lo, hi = it_frame.FLAT_WORDS
        for phrase in (f"{lo}–{hi} plain content words", "2–4 search axes",
                       f"Aim for {it_frame.MIN_TERMS['standard']}–{it_frame.MAX_TERMS_WARN} terms (quick: ≥ {it_frame.MIN_TERMS['quick']})"):
            self.assertIn(phrase, text)
        rows = {}
        for line in text.splitlines():
            m = __import__("re").match(r"\| `([a-z-]+)` \|.*\|(.*)\|(.*)\|(.*)\|$", line)
            if m and m.group(1) in it_frame.STRATEGIES:
                rows[m.group(1)] = [c.strip() == "✔" for c in m.groups()[1:]]
        for i, depth in enumerate(("quick", "standard", "deep")):
            want = set(it_frame.DEPTH_STRATEGIES[depth])
            got = {st for st, marks in rows.items() if marks[i]}
            self.assertEqual(got, want, f"A1-frame.md variant table, {depth}")

    def test_no_restatement_elsewhere(self):
        import re
        forbidden = re.compile(r"3[–-]5[ -](key)?words?|3[–-]5 keywords|synonym-swap|anchor-methods")   # A1 jargon / numbers
        for f in [self.SKILL / "SKILL.md", *sorted((self.SKILL / "references").glob("*.md"))]:
            if f.name == "units.md":            # generated from the code constants
                continue
            hits = [l for l in f.read_text().splitlines() if forbidden.search(l)]
            self.assertEqual(hits, [], f"{f.name} restates an A1 rule; link to search/A1-frame.md instead")


class TestRegistry(unittest.TestCase):
    def test_units_check(self):
        """Cards complete, pointers resolve, every done-check has its counter-example, units.md up to date (R3)."""
        code, out = run("units", "check")
        self.assertEqual(code, 0, out)


class TestRegistryLint(unittest.TestCase):
    """The lint itself has counter-examples: a false `yes`, an undeclared reviser, an unlisted owned key."""

    def lint(self, mutate):
        import it_units
        reg = json.loads(it_units.REGISTRY.read_text())
        mutate(reg)
        tmp = Path(tempfile.mkdtemp())
        try:
            f = tmp / "ideate_units.json"
            f.write_text(json.dumps(reg))
            old = it_units.REGISTRY
            it_units.REGISTRY = f
            try:
                return it_units.check()
            finally:
                it_units.REGISTRY = old
        finally:
            shutil.rmtree(tmp)

    def card(self, reg, uid):
        return next(c for c in reg["units"] if c["id"] == uid)

    def test_emitted_codes_are_found(self):
        import it_units
        codes = it_units.emitted_codes("it_frame.py")
        self.assertIn("Q21", codes)
        self.assertEqual(codes["P10"], {"WARN"})

    def test_yes_without_ledger_refused(self):
        def m(r):
            r["infrastructure"]["ledger"] = False                 # a registry whose ledger is not built
            self.card(r, "A1.p")["achieved"]["8"]["status"] = "yes"
        probs = self.lint(m)
        self.assertTrue(any("condition 8 claims `yes`" in p for p in probs), probs)

    def test_replay_needed_for_network_unit(self):
        def m(r):
            r["infrastructure"]["interrupt_harness"] = True
            r["infrastructure"]["replay"] = False                 # a registry without the replay harness
            self.card(r, "A1.q")["achieved"]["9"]["status"] = "yes"
        probs = self.lint(m)
        self.assertTrue(any("condition 9" in p and "replay" in p for p in probs), probs)

    def test_undeclared_reviser_refused(self):
        probs = self.lint(lambda r: self.card(r, "A1.q").update(revised_by=[]))
        self.assertTrue(any("cmd_query_revise" in p for p in probs), probs)

    def test_owned_key_must_be_listed(self):
        probs = self.lint(lambda r: self.card(r, "A1.q")["owns"].remove("step0.strategy_basis"))
        self.assertTrue(any("strategy_basis" in p for p in probs), probs)


class TestKnownItems(unittest.TestCase):
    def test_match(self):
        hits = [{"title": "Autoreject: automated artifact rejection for MEG and EEG data", "doi": "10.1/a"},
                {"title": "Something else entirely about EEG", "doi": "10.1/b"}]
        items = [{"title": "Autoreject: Automated artifact rejection for MEG and EEG data"}, {"doi": "10.1/B"},
                 {"title": "A paper that does not exist anywhere at all"}]
        got = it_frame.match_known_items(items, hits)
        self.assertEqual([g["resolved"] for g in got], [True, True, False])


class TestNoProtocol(unittest.TestCase):
    """The search block runs on a topic framed by A1: every handoff check refuses a step0 without a protocol."""

    def test_every_check_refuses(self):
        with tempfile.TemporaryDirectory() as t:
            rd = Path(t) / "topic_research"
            rd.mkdir()
            (rd / "step0_session_config.json").write_text(json.dumps({"topic": "x", "queries": []}))
            for cmd in (("frame", "check"), ("a2-check",), ("a3-check",), ("a4-check",), ("a5-check",)):
                code, out = run(*cmd, rd)
                self.assertEqual(code, 2, f"{cmd}: {out}")
                self.assertIn("starts at A1", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
