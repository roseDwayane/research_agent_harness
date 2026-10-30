#!/usr/bin/env python3
"""Tests for A4 export (it_export.py; rules references/search/A4-export.md), offline: the fixture topic taken through
A3 -> A5 -> A3 (test_a5_snowball.build_good), then A4.k keys and A4.b bibliography against a fake Crossref. One
counter-example per handoff check lives in tests/fixtures/search/a4/neg/*.json.

  python3 .claude/skills/ai-scientist-ideate/scripts/tests/search/test_a4_export.py
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

SCRIPTS = Path(__file__).resolve().parents[2]
TOOLS = SCRIPTS / "ideate_tools.py"
BRIDGE = SCRIPTS / "mcp_bridge.py"
FIX = SCRIPTS / "tests" / "fixtures" / "search" / "a4"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import it_export  # noqa: E402
from test_a1_frame import apply_ops  # noqa: E402
from test_a5_snowball import build_good as build_a5  # noqa: E402


def _mcp_python() -> str | None:
    """mcp_bridge.py exits 4 without the `mcp` package, even for a command that makes no MCP call."""
    import os
    for py in [os.environ.get("IDEATE_MCP_PYTHON"), sys.executable, "/opt/anaconda3/envs/drug/bin/python"]:
        if py and Path(py).exists() and subprocess.run([py, "-c", "import mcp"], capture_output=True).returncode == 0:
            return py
    return None


MCP_PY = _mcp_python()


def run(*args, tool=TOOLS):
    py = MCP_PY if tool == BRIDGE else sys.executable
    p = subprocess.run([py, str(tool), *map(str, args)], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


CROSSREF = {"10.1016/j.neuroimage.2017.06.030": {
    "DOI": "10.1016/j.neuroimage.2017.06.030", "type": "journal-article",
    "title": ["Autoreject: Automated artifact rejection for MEG and EEG data"],
    "author": [{"family": "Jas", "given": "Mainak"}, {"family": "Engemann", "given": "Denis A."},
               {"family": "Bekhti", "given": "Yousra"}],
    "container-title": ["NeuroImage"], "volume": "159", "page": "417-429", "issued": {"date-parts": [[2017, 10]]}}}


def crossref_fetch(url, rd=None):
    assert url.startswith("https://api.crossref.org/works?"), url
    filt = unquote(re.search(r"filter=([^&]+)", url).group(1))
    dois = [x.split(":", 1)[1] for x in filt.split(",")]
    return {"message": {"items": [CROSSREF[d] for d in dois if d in CROSSREF]}}


def export(rd):
    code, out = run("export", rd)
    assert code == 0, out
    cfg = json.loads((rd / "step0_session_config.json").read_text())
    it_export.build_bibliography(cfg, rd, "x@example.com", fetch=crossref_fetch)


def build_good(tmp: Path) -> Path:
    rd = build_a5(tmp)
    export(rd)
    return rd


def apply4(path: Path, case: dict) -> None:
    if path.suffix == ".jsonl":
        lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        for op in case["ops"]:
            if op["op"] == "log_append":
                v = dict(op["value"])
                if v.get("key") == "@first":
                    v["key"] = lines[0]["key"]
                if v.get("id") == "@first":
                    v["id"] = lines[0]["id"]
                lines.append(v)
            elif op["op"] == "log_drop_first":
                lines = lines[1:]
            elif op["op"] == "log_set_first":
                lines[0][op["field"]] = op["value"]
        path.write_text("".join(json.dumps(l) + "\n" for l in lines))
    elif path.suffix == ".bib":
        text = path.read_text()
        for op in case["ops"]:
            if op["op"] == "bib_drop_first":
                i = text.index("\n@")
                j = text.find("\n@", i + 1)
                text = text[:i] + (text[j:] if j > 0 else "\n")
        path.write_text(text)
    else:
        path.write_text(json.dumps(apply_ops(json.loads(path.read_text()), case["ops"])))


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.rd = build_good(cls.tmp / "a")
        cls.sl = json.loads((cls.rd / "step3_shortlist.json").read_text())
        cls.keys = {p["id"]: p["citation_key"] for p in cls.sl["papers"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def copy(self, name):
        d = self.tmp / name
        shutil.copytree(self.rd.parent, d)
        return d / "topic_research"

    def test_a4_check_passes(self):
        code, out = run("a4-check", self.rd)
        self.assertEqual(code, 0, out)

    def test_keys_from_fuller_authors(self):
        self.assertEqual(self.keys["paper_002"], "jasetal2017")   # 1 author in the search record: "jas2017"
        log = it_export.read_log(self.rd)
        e = next(x for x in log if x["id"] == "paper_002")
        self.assertEqual((e["authors_basis"], e["n_authors"]), ("openalex", 3))
        self.assertEqual(len(set(self.keys.values())), len(self.keys))

    def test_crossref_entry(self):
        bib = (self.rd / "step4_references.bib").read_text()
        entry = bib[bib.index("{jasetal2017,"):].split("\n}\n")[0]
        self.assertIn("Jas, Mainak and Engemann, Denis A. and Bekhti, Yousra", entry)
        self.assertIn("159", entry)
        self.assertIn("417-429", entry)
        meta = json.loads((self.rd / "step4_bib_metadata.json").read_text())
        self.assertEqual(meta["entries"]["jasetal2017"]["source"], "crossref")
        others = [v for k, v in meta["entries"].items() if k != "jasetal2017"]
        self.assertTrue(others and all(v["source"].startswith("search record") and v["why"] for v in others))

    def test_rerun_keeps_keys(self):
        rd = self.copy("rerun")
        before = it_export.read_log(rd)
        export(rd)
        self.assertEqual(it_export.read_log(rd), before)
        self.assertEqual({p["id"]: p["citation_key"] for p in json.loads((rd / "step3_shortlist.json").read_text())["papers"]},
                         self.keys)

    def test_retired_key_never_reused(self):
        rd = self.copy("retire")
        f = rd / "step3_shortlist.json"
        sl = json.loads(f.read_text())
        jas = next(p for p in sl["papers"] if p["id"] == "paper_002")
        sl["papers"] = [p for p in sl["papers"] if p["id"] != "paper_002"]
        f.write_text(json.dumps(sl))
        cfg = json.loads((rd / "step0_session_config.json").read_text())
        out = it_export.mint_keys(cfg, rd)
        self.assertEqual(out["retired"], 1)
        self.assertIn("retired, never reused", (rd / "step4_citation_keys.md").read_text())
        twin = dict(jas, id="paper_900", title="Another 2017 paper by Jas", citation_key=None,
                    authors=["Mainak Jas", "B Two", "C Three"])
        sl = json.loads(f.read_text())
        sl["papers"].append(twin)
        f.write_text(json.dumps(sl))
        it_export.mint_keys(cfg, rd)
        sl = json.loads(f.read_text())
        self.assertEqual(next(p for p in sl["papers"] if p["id"] == "paper_900")["citation_key"], "jasetal2017a")

    def test_collision_takes_next_suffix(self):
        rd = self.copy("collide")
        f = rd / "step3_shortlist.json"
        sl = json.loads(f.read_text())
        jas = next(p for p in sl["papers"] if p["id"] == "paper_002")
        sl["papers"] += [dict(jas, id=f"paper_9{i}", title=f"Twin {i}", citation_key=None,
                               authors=["Mainak Jas", "B Two", "C Three"]) for i in (1, 2)]
        f.write_text(json.dumps(sl))
        it_export.mint_keys(json.loads((rd / "step0_session_config.json").read_text()), rd)
        sl = json.loads(f.read_text())
        self.assertEqual(sorted(p["citation_key"] for p in sl["papers"] if p["id"] in ("paper_91", "paper_92")),
                         ["jasetal2017a", "jasetal2017b"])

    @unittest.skipIf(MCP_PY is None, "no interpreter with the `mcp` package (IDEATE_MCP_PYTHON)")
    def test_bibliography_offline_cli(self):
        rd = self.copy("offline")
        code, out = run("bibliography", rd, "--offline", tool=BRIDGE)
        self.assertEqual(code, 0, out)
        code, out = run("a4-check", rd)
        self.assertEqual(code, 0, out)
        self.assertIn("L04", out)

    @unittest.skipIf(MCP_PY is None, "no interpreter with the `mcp` package (IDEATE_MCP_PYTHON)")
    def test_bibliography_needs_keys(self):
        rd = self.copy("nokeys")
        (rd / it_export.LOG).unlink()
        code, out = run("bibliography", rd, "--offline", tool=BRIDGE)
        self.assertEqual(code, 2, out)
        self.assertIn("A4.k is not done", out)


class TestNegativeFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.rd = build_good(cls.tmp / "a")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_every_counter_example_fails_its_check(self):
        cases = sorted((FIX / "neg").glob("*.json"))
        self.assertGreaterEqual(len(cases), 9)
        files = {"log": it_export.LOG, "shortlist": "step3_shortlist.json", "bib": "step4_references.bib",
                 "meta": "step4_bib_metadata.json"}
        for path in cases:
            case = json.loads(path.read_text())
            with self.subTest(case=path.stem):
                d = self.tmp / f"c_{path.stem}"
                shutil.copytree(self.rd.parent, d)
                rd = d / "topic_research"
                apply4(rd / files[case["target"]], case)
                cfg = json.loads((rd / "step0_session_config.json").read_text())
                fs = it_export.run_checks(cfg, rd, case["unit"])
                codes = {x["code"] for x in fs if x["level"] == case.get("level", "ERROR")}
                self.assertIn(case["expect"], codes, f"{path.stem}: {case['why']} - got {sorted(codes)}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
