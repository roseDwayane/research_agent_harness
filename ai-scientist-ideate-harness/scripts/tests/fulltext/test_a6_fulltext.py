#!/usr/bin/env python3
"""Tests for A6 full text (it_fulltext: A6.d fetch, A6.c convert; the commands tier1, download, arxiv-pdfs, figures and
fulltext-status as Unit boundaries on the ledger), offline.

The good state is built by the commands themselves on six shortlisted papers: tier1, download (a fake paper_pdf server),
arxiv-pdfs (a fake transfer), the markdown pdf2md.sh would write, the figure pages, fulltext-status. Counter-examples:
tests/fixtures/fulltext/a6/neg/*.json - each edits the good state and names the check code it must raise.

Interrupt (armour condition 8): IDEATE_FAIL_AFTER_WRITES=k stops the k+1-th write of a command. Afterwards the ledger
holds no `done` for the Unit after that call, every file it owns still parses, and a second run gives what an
uninterrupted run gives.

  python3 .claude/skills/ai-scientist-ideate/scripts/tests/fulltext/test_a6_fulltext.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1]
FIX = SCRIPTS / "tests" / "fixtures" / "fulltext" / "a6"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "tests" / "search"))
import ideate_tools  # noqa: E402
import it_common  # noqa: E402
import it_fulltext  # noqa: E402
import it_ledger  # noqa: E402
import it_trace  # noqa: E402
from test_a1_frame import apply_ops  # noqa: E402

if importlib.util.find_spec("mcp") is None:     # no `mcp` package here: the names mcp_bridge imports, as stubs - the
    _mcp, _client, _stdio = (types.ModuleType(n) for n in ("mcp", "mcp.client", "mcp.client.stdio"))   # server is faked
    _mcp.ClientSession = _mcp.StdioServerParameters = _stdio.stdio_client = None
    sys.modules.update({"mcp": _mcp, "mcp.client": _client, "mcp.client.stdio": _stdio})
import mcp_bridge  # noqa: E402

# (id, key, composite, tier, doi, arxiv id) - garcia2019 has no DOI: paper_pdf cannot fetch it, arXiv can
PAPERS = [("paper_001", "smith2020", 4.6, 1, "10.1000/a1", None), ("paper_002", "chen2021", 4.4, 1, "10.1000/a2", None),
          ("paper_003", "garcia2019", 4.1, 1, None, "2101.00001"), ("paper_004", "kim2022", 3.8, 2, "10.1000/a4", None),
          ("paper_005", "patel2018", 3.5, 2, "10.1000/a5", None), ("paper_006", "lee2023", 3.2, 2, "10.1000/a6", None)]
TARGETS = {"candidates": it_fulltext.CANDIDATES, "fetch_log": it_fulltext.FETCH_LOG, "shortlist": "step3_shortlist.json",
           "processed": it_fulltext.PROCESSED, "index": it_fulltext.FIGURES + "/index.json",
           "step0": "step0_session_config.json"}


def make_pdf(text: str) -> bytes:
    """A one-page PDF poppler reads, padded past the 1 KiB pdf_is_complete asks for."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = bytearray(b"%PDF-1.4\n%" + b"0" * 1100 + b"\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def ns(rd, **kw):
    return SimpleNamespace(research_dir=str(rd), **kw)


def tier1(rd, **kw):
    ideate_tools.cmd_tier1(ns(rd, **{"depth": None, "top_up": False, "targets": False, **kw}))


def fake_transfer(url: str, tmp: Path) -> None:
    tmp.write_bytes(make_pdf(f"Figure 1: arXiv copy of {url.rsplit('/', 1)[-1]}"))


def arxiv_pdfs(rd):
    old, ideate_tools._download_to, ideate_tools.ARXIV_PAUSE = ideate_tools._download_to, fake_transfer, 0
    try:
        ideate_tools.cmd_arxiv_pdfs(ns(rd))
    finally:
        ideate_tools._download_to, ideate_tools.ARXIV_PAUSE = old, 3


class FakePaperPdf:
    """paper_pdf as it answers for the fixture: a PDF for every candidate with a DOI, `no DOI` for the others."""

    def __init__(self, name, rd):
        self.rd = Path(rd)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def call(self, tool, params):
        assert tool == "paper_pdf_download", tool
        cands = {c["citation_key"]: c for c in json.loads(Path(params["md_path"]).read_text())["candidates"]}
        out, results = Path(params["output_dir"]), []
        out.mkdir(exist_ok=True)
        for k in params["only_keys"]:
            if cands[k].get("doi"):
                (out / f"{k}.pdf").write_bytes(make_pdf(f"Figure 1: A test figure of {k}"))
                results.append({"citation_key": k, "status": "downloaded", "source": "unpaywall"})
            else:
                results.append({"citation_key": k, "status": "failed", "reason": "no DOI in candidate list"})
        return {"results": results, "downloaded": sum(r["status"] == "downloaded" for r in results), "skipped": 0,
                "failed": sum(r["status"] == "failed" for r in results), "total": len(results), "output_dir": str(out)}


def download(rd, **kw):
    old, mcp_bridge.Server = mcp_bridge.Server, FakePaperPdf
    try:
        asyncio.run(mcp_bridge.cmd_download(ns(rd, **{"retry_failed": False, "concurrency": 1, **kw})))
    finally:
        mcp_bridge.Server = old


def convert(rd):
    """What pdf2md.sh leaves (markdown + marker's _meta.json) and what `figures` records, without poppler."""
    rd = Path(rd)
    ft = rd / "step5_full_text"
    (ft / "figure").mkdir(parents=True, exist_ok=True)
    index, done = [], {}
    for pdf in sorted((rd / "pdfs").glob("*.pdf")):
        k = pdf.stem
        (ft / f"{k}.md").write_text(f"# {k}\n\nFigure 1: A test figure of {k}\n", encoding="utf-8")
        (ft / f"{k}_meta.json").write_text("{}\n")
        (ft / "figure" / f"{k}_p01.png").write_bytes(b"\x89PNG fixture")
        index.append({"key": k, "file": f"{k}_p01.png", "page": 1, "source": "page", "dpi": 130,
                      "captions": [f"Figure 1: A test figure of {k}"]})
        done[k] = {"pdf_sha": it_common.sha256_file(pdf), "pages": 1, "caption_pages": 1}
    (ft / "figure" / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    (rd / it_fulltext.PROCESSED).write_text(json.dumps(done, indent=2) + "\n")


def build(tmp: Path) -> Path:
    rd = tmp / "topic_research"
    rd.mkdir(parents=True)
    (rd / "step0_session_config.json").write_text(json.dumps({
        "topic": "full-text fixture", "depth": "standard",
        "protocol": {"framework": {"name": "PICO", "slots": [{"slot": "population", "value": "adults"}]}}}, indent=2))
    papers = [{"id": pid, "citation_key": k, "title": f"Paper {k}", "doi": doi, "arxiv_id": ax, "year": 2020,
               "screening": {"composite": comp, "tier": tier}} for pid, k, comp, tier, doi, ax in PAPERS]
    (rd / "step3_shortlist.json").write_text(json.dumps({"papers": papers, "summary": {"included": len(papers)}}, indent=2))
    (rd / "step4_citation_keys.jsonl").write_text("".join(json.dumps({"key": k, "id": pid, "authors_basis": "openalex",
                                                                      "n_authors": 1}) + "\n" for pid, k, *_ in PAPERS))
    (rd / "step2_raw_papers.json").write_text(json.dumps({"papers": [{"id": pid, "title": f"Paper {k}", "year": 2020,
                                                                      "found_by": ["Q1"], "sources_found_in": ["openalex"]}
                                                                     for pid, k, *_ in PAPERS]}))
    tier1(rd)
    download(rd)
    arxiv_pdfs(rd)
    convert(rd)
    ideate_tools.cmd_fulltext_status(ns(rd))
    return rd


def apply_edits(rd: Path, case: dict) -> None:
    for e in case["edits"]:
        if e["target"] == "fs":
            for op in e["ops"]:
                p = rd / op["path"]
                if op["op"] == "delete":
                    p.unlink()
                elif op["op"] == "write":
                    p.write_bytes(op["text"].encode("utf-8"))
                elif op["op"] == "copy":
                    shutil.copyfile(rd / op["from"], p)
            continue
        p = rd / TARGETS[e["target"]]
        p.write_text(json.dumps(apply_ops(json.loads(p.read_text()), e["ops"]), indent=2))


def owned(rd: Path, unit: str) -> dict:
    """What the Unit owns, comparable across runs (time stamps removed); every JSON file must parse."""
    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k != "at"}
        return [strip(v) for v in x] if isinstance(x, list) else x
    out = {}
    for spec in it_ledger.io(unit)["owns"]:
        files = sorted(rd.glob(spec["glob"])) if "glob" in spec else [rd / spec["file"]]
        for f in files:
            if not f.exists():
                out[f.relative_to(rd).as_posix()] = None
            elif f.suffix == ".json":
                out[f.relative_to(rd).as_posix()] = strip(json.loads(f.read_text()))
            else:
                out[f.relative_to(rd).as_posix()] = it_common.sha256_file(f)
    return out


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = Path(tempfile.mkdtemp())
        cls.good = build(cls._tmp / "good")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def copy(self) -> Path:
        dst = Path(tempfile.mkdtemp()) / "topic_research"
        shutil.copytree(self.good, dst)
        self.addCleanup(shutil.rmtree, dst.parent, True)
        return dst


class TestChecks(Fixture):
    def test_good_state_has_no_finding(self):
        self.assertEqual(it_fulltext.run_checks(self.good), [])

    def test_counter_examples(self):
        cases = sorted((FIX / "neg").glob("*.json"))
        self.assertEqual(len(cases), 12)
        for f in cases:
            case = json.loads(f.read_text())
            with self.subTest(f.stem):
                rd = self.copy()
                apply_edits(rd, case)
                got = {(x["code"], x["level"]) for x in it_fulltext.run_checks(rd, case["unit"])}
                self.assertIn((case["expect"], case["level"]), got, f"{f.stem}: {got}")


class TestCommands(Fixture):
    def test_units_done_after_build(self):
        self.assertEqual(it_ledger.unit_state(self.good, "A6.d")["state"], "done")
        self.assertEqual(it_ledger.unit_state(self.good, "A6.c")["state"], "done")
        self.assertEqual(it_ledger.next_unit(self.good, "fulltext")[0], None)
        self.assertEqual(it_ledger.current_block(self.good), "fulltext")
        status = (self.good / "STATUS.md").read_text()
        self.assertIn("## Full text (A6)", status)
        self.assertIn("| A6.d | ✔ done", status)
        self.assertIn("| A6.c | ✔ done", status)

    def test_candidates_follow_the_depth_and_record_their_origin(self):
        cf = json.loads((self.good / it_fulltext.CANDIDATES).read_text())
        self.assertEqual((cf["depth"], cf["count"], cf["top_ups"]), ("standard", 6, 0))
        self.assertEqual({c["added_by"] for c in cf["candidates"]}, {"depth"})
        log = json.loads((self.good / it_fulltext.FETCH_LOG).read_text())["attempts"]
        self.assertEqual([a["route"] + ":" + a["status"] for a in log["garcia2019"]], ["paper_pdf:failed", "arxiv:ok"])

    def test_download_records_every_attempt(self):
        log = json.loads((self.good / it_fulltext.FETCH_LOG).read_text())["attempts"]
        self.assertEqual({k: [a["status"] for a in v if a["route"] == "paper_pdf"] for k, v in log.items()},
                         {k: ["failed" if k == "garcia2019" else "ok"] for _, k, *_ in PAPERS})
        self.assertEqual(json.loads((self.good / "_download_attempted.json").read_text()), sorted(k for _, k, *_ in PAPERS))

    def test_a_server_error_remembers_nothing_as_tried(self):
        rd = self.copy()
        (rd / "pdfs" / "lee2023.pdf").unlink()
        for f in (rd / it_fulltext.FETCH_LOG, rd / "_download_attempted.json"):
            f.unlink()

        class Broken(FakePaperPdf):
            async def call(self, tool, params):
                return {"_text": "server error"}
        old, mcp_bridge.Server = mcp_bridge.Server, Broken
        try:
            with self.assertRaises(SystemExit):
                asyncio.run(mcp_bridge.cmd_download(ns(rd, retry_failed=False, concurrency=1)))
        finally:
            mcp_bridge.Server = old
        self.assertFalse((rd / "_download_attempted.json").exists())
        self.assertEqual(it_ledger.unit_state(rd, "A6.d")["state"], "failed")

    def test_tier1_alone_waits_for_the_download(self):
        rd = self.copy()
        shutil.rmtree(rd / "pdfs")
        (rd / it_fulltext.FETCH_LOG).unlink()
        tier1(rd)
        st = it_ledger.unit_state(rd, "A6.d")
        self.assertEqual(st["state"], "waiting")
        self.assertTrue(st["why"].startswith("F01"), st["why"])

    def test_quick_depth_is_done_with_no_candidate(self):
        rd = self.copy()
        p = rd / "step0_session_config.json"
        p.write_text(json.dumps({**json.loads(p.read_text()), "depth": "quick"}))
        tier1(rd)
        self.assertEqual(json.loads((rd / it_fulltext.CANDIDATES).read_text())["count"], 0)
        self.assertEqual(it_ledger.unit_state(rd, "A6.d")["state"], "done")

    def test_one_top_up_only(self):
        rd = self.copy()
        tier1(rd, top_up=True)
        self.assertEqual(json.loads((rd / it_fulltext.CANDIDATES).read_text())["top_ups"], 1)
        with self.assertRaises(SystemExit):
            tier1(rd, top_up=True)
        self.assertEqual(it_ledger.unit_state(rd, "A6.d")["state"], "failed")

    def test_access_levels_and_caveats(self):
        rd = self.copy()
        (rd / "step5_full_text" / "patel2018_meta.json").unlink()
        ideate_tools.cmd_fulltext_status(ns(rd))
        sl = {p["citation_key"]: p["access_level"] for p in json.loads((rd / "step3_shortlist.json").read_text())["papers"]}
        self.assertEqual(sl["patel2018"], "full-text-plain")
        self.assertEqual(it_ledger.unit_state(rd, "A6.c")["state"], "done")
        self.assertEqual(it_ledger.degraded_codes(rd, "A6.c"), ["fulltext-plain"])
        cav = {c["code"]: c["unit"] for c in it_ledger.fusion_caveats(rd)}
        self.assertEqual(cav.get("fulltext-plain"), "A6.c")

    def test_a_new_pdf_makes_a6c_stale(self):
        rd = self.copy()
        (rd / "pdfs" / "lee2023.pdf").write_bytes(make_pdf("Figure 1: a replaced copy"))
        self.assertEqual(it_ledger.unit_state(rd, "A6.c")["state"], "stale")

    def test_a7d_waits_on_a6c_only_once_the_fulltext_block_ran(self):
        """A7.D requires A6.c: a topic with full-text events sees an A6.c change as upstream staleness; a topic fetched
        before these Units existed (no full-text events) does not."""
        self.assertIn("A6.c", it_ledger.requires("A7.D"))
        for with_events in (True, False):
            rd = self.copy()
            if not with_events:
                (rd / it_ledger.LEDGER).unlink()
            it_ledger._append(rd, {"ev": "done", "unit": "A7.D", "inst": "-", "at": "t",
                                   "inputs": it_ledger.hashes(rd, it_ledger.io("A7.D")["reads"]),
                                   "outputs": it_ledger.hashes(rd, it_ledger.io("A7.D")["owns"])})
            self.assertEqual(it_ledger.unit_state(rd, "A7.D")["state"], "done", with_events)
            if with_events:
                p = rd / "step3_tier1_candidates.json"          # an A6.d output changes: A6.d, then A6.c, then A7.D
                p.write_text(p.read_text().replace('"top_ups": 0', '"top_ups": 1'))
                st = it_ledger.unit_state(rd, "A7.D")
                self.assertEqual(st["state"], "stale")
                self.assertIn("upstream A6.c", st["why"])

    def test_trace_reports_the_fetch_and_the_level(self):
        out = it_trace.trace(self.good, "garcia2019")
        steps = {s["unit"]: s["text"] for s in out["steps"]}
        self.assertIn("arxiv ok", steps["A6.d"])
        self.assertIn("paper_pdf failed (no DOI in candidate list)", steps["A6.d"])
        self.assertIn("access level full-text", steps["A6.c"])
        self.assertTrue(any("A6.d" in line for line in out["comments"]))

    @unittest.skipUnless(shutil.which("pdftoppm") and shutil.which("pdftotext") and shutil.which("pdfinfo"), "no poppler")
    def test_figures_records_every_pdf(self):
        rd = self.copy()
        (rd / it_fulltext.PROCESSED).unlink()
        (rd / it_fulltext.FIGURES / "index.json").unlink()
        for f in (rd / it_fulltext.FIGURES).glob("*.png"):
            f.unlink()
        ideate_tools.cmd_figures(ns(rd, dpi=40, all_pages=False))
        done = json.loads((rd / it_fulltext.PROCESSED).read_text())
        self.assertEqual(set(done), {k for _, k, *_ in PAPERS})
        self.assertTrue(all(d["caption_pages"] == 1 for d in done.values()), done)
        self.assertEqual(it_ledger.unit_state(rd, "A6.c")["state"], "done")


class TestInterrupt(Fixture):
    def interrupt(self, unit: str, prepare, cmd):
        """prepare(rd) sets up a state in which cmd(rd) writes; each write is interrupted in turn."""
        ref = self.copy()
        prepare(ref)
        cmd(ref)
        want = owned(ref, unit)
        self.assertEqual(it_ledger.unit_state(ref, unit)["state"], "done")
        k = 0
        while True:
            rd = self.copy()
            prepare(rd)
            n0 = len(it_ledger._events(rd))
            os.environ["IDEATE_FAIL_AFTER_WRITES"] = str(k)
            it_common._WRITES[0] = 0
            try:
                cmd(rd)
                stopped = False
            except it_common.InjectedFailure:
                stopped = True
            finally:
                os.environ.pop("IDEATE_FAIL_AFTER_WRITES", None)
            if not stopped:
                break
            evs = it_ledger._events(rd)[n0:]
            self.assertFalse([e for e in evs if e["unit"] == unit and e["ev"] == "done"], f"{unit} k={k}")
            self.assertEqual(it_ledger.unit_state(rd, unit)["state"], "failed", f"{unit} k={k}")
            owned(rd, unit)                       # every owned file still parses
            cmd(rd)
            self.assertEqual(owned(rd, unit), want, f"{unit} k={k}")
            self.assertEqual(it_ledger.unit_state(rd, unit)["state"], "done", f"{unit} k={k}")
            k += 1
        self.assertGreaterEqual(k, 1, f"{unit}: the command wrote nothing")

    def test_interrupt_a6d(self):
        def prepare(rd):                          # garcia2019's arXiv copy not yet fetched
            (rd / "pdfs" / "garcia2019.pdf").unlink()
            p = rd / it_fulltext.FETCH_LOG
            log = json.loads(p.read_text())
            log["attempts"]["garcia2019"] = [a for a in log["attempts"]["garcia2019"] if a["route"] != "arxiv"]
            p.write_text(json.dumps(log, indent=2))

        def cmd(rd):
            tier1(rd)
            arxiv_pdfs(rd)
        self.interrupt("A6.d", prepare, cmd)

    def test_interrupt_a6c(self):
        def prepare(rd):                          # access levels not yet written, one full text in CRLF
            p = rd / "step3_shortlist.json"
            sl = json.loads(p.read_text())
            for x in sl["papers"]:
                x.pop("access_level", None)
            p.write_text(json.dumps(sl, indent=2))
            (rd / "step5_full_text" / "kim2022.md").write_bytes(b"# kim2022\r\nFigure 1: A test figure of kim2022\r\n")

        self.interrupt("A6.c", prepare, lambda rd: ideate_tools.cmd_fulltext_status(ns(rd)))


if __name__ == "__main__":
    unittest.main()
