#!/usr/bin/env python3
"""Build the fixture research folders under evals/datasets/ deterministically.

Ledger 'done' events carry the hashes of the files they produced (same formats as the legacy ledger), so the states
the evals assert are verified by hashing, not asserted by fiat. Re-running the builder yields byte-identical files.

    python evals/build_datasets.py            # (re)build evals/datasets/
    python evals/build_datasets.py --check    # exit 1 when the committed datasets differ from a fresh build

Datasets
  search_complete     every search Unit done (A3 re-screened after A5), caveats file valid
  search_stale        search_complete, then step3_gate.json edited after A3.g's done
  search_interrupted  A2.s begun and never done
  search_failed_a3    A3 recorded a fail
  ledger_malformed    a ledger line that does not parse
  fusion_ready        search + full text + fusion done; 3 ready questions of a target of 5
  fusion_no_ready     fusion done but no ready and no screen_unresolved question
  planning            gen_1: a sound generation; gen_2: weak decision tree and a 300-word abstract
"""
from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from ideate_v2.jsonio import sha256_json  # noqa: E402
from ideate_v2.ledger import spec_hash, spec_id  # noqa: E402
from ideate_v2.registry import Registry  # noqa: E402

DATASETS = HERE / "datasets"
T0 = "2026-10-17T09:00:00+00:00"
REG = Registry.load()


def _w(rd: Path, rel: str, data) -> None:
    p = rd / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _hashes(rd: Path, specs: list[dict]) -> dict:
    """Ledger hashes of a card's io specs, as the legacy ledger records them; the specs v2 cannot reproduce (basis,
    parts, views) get a fixed placeholder - v2 reports them as unverifiable either way."""
    cfg = json.loads((rd / "step0_session_config.json").read_text(encoding="utf-8"))
    out = {}
    for s in specs:
        sid = spec_id(s)
        status, h = spec_hash(rd, sid, cfg)
        out[sid] = h if status == "verified" else "fixture:" + sha256_json(sid)[:16]
    return out


class Ledger:
    def __init__(self, rd: Path):
        self.rd, self.lines, self.n = rd, [], 0

    def _at(self) -> str:
        self.n += 1
        return f"2026-10-17T09:{self.n // 60:02d}:{self.n % 60:02d}+00:00"

    def run(self, unit: str, inst: str = "-") -> None:
        """begin + done with the inputs and outputs the Unit's legacy card declares (io.reads / io.owns)."""
        io = (REG.legacy_card(unit) or {}).get("io") or {}
        ins = _hashes(self.rd, [s for s in io.get("reads") or [] if s.get("hash_at") != "done"])
        self.lines.append({"ev": "begin", "unit": unit, "inst": inst, "at": self._at(), "inputs": ins})
        self.lines.append({"ev": "done", "unit": unit, "inst": inst, "at": self._at(), "inputs": ins,
                           "outputs": _hashes(self.rd, io.get("owns") or []), "counts": {}, "degraded": [],
                           "tool": "fixture"})

    def begin(self, unit: str, inst: str = "-") -> None:
        self.lines.append({"ev": "begin", "unit": unit, "inst": inst, "at": self._at(), "inputs": {}})

    def fail(self, unit: str, why: str, inst: str = "-") -> None:
        self.lines.append({"ev": "fail", "unit": unit, "inst": inst, "at": self._at(), "why": why})

    def save(self, extra_raw: str = "") -> None:
        body = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self.lines) + extra_raw
        _w(self.rd, "_state/ledger.jsonl", body)


# ------------------------------------------------------------------------------------------------ content
def search_files(rd: Path) -> None:
    _w(rd, "eeg_topic.md", "# EEG artefact handling\n\n## Keywords\nEEG, artefact, ICA\n")
    _w(rd, "step0_session_config.json", {
        "topic": "EEG artefact handling", "topic_file": "eeg_topic.md", "depth": "standard", "timestamp": T0,
        "protocol": {"review_type": "scoping", "framework": {"name": "PCC"}, "axes": [{"id": "C1", "terms": ["eeg"]}],
                     "timeframe": "2013-2026", "languages": ["en"]},
        "queries": [{"id": "Q1", "strategy": "primary", "flat_query": "eeg artefact rejection", "status": "active"}],
        "anchor_terms": ["eeg"], "sources": ["openalex", "pubmed"], "known_items": [],
        "target_venues": ["NeuroImage", "J Neural Eng"], "expert_domain": "EEG signal processing",
        "local_environment": {"artefacts": [], "cached_data": [], "packages_present": ["mne"], "packages_missing": []},
        "max_num_generations": 3})
    _w(rd, "step1_protocol.md", "# Protocol (view)\n")
    _w(rd, "step1_protocol_evaluation.json", {"rounds": [{"round": 1, "verdict": "approved-with-notes"}],
                                              "final": {"status": "approved-with-notes", "round": 1, "unresolved": []}})
    _w(rd, "step2_queries/Q1@1a2b3c.json", {"kind": "query", "id": "Q1", "complete": True, "papers": ["paper_001"]})
    _w(rd, "step2_raw_papers.json", {"papers": [{"id": f"paper_{i:03d}", "title": f"Paper {i}"} for i in range(1, 6)],
                                     "search_summary": {"caveats": []}})
    _w(rd, "step2_relevance_check.json", {"rounds": [{"round": 0, "verdicts": {"Q1": "ok"}}], "caveats": []})
    _w(rd, "step3_bibliometrics.json", {"papers": {"paper_001": {"impact": 3.4}}})
    _w(rd, "step3_gate.json", {"excluded": {}})
    _w(rd, "screening_scores.json", {"scores": {"paper_001": {"relevance": 5, "quality": 4}}})
    _w(rd, "step3_shortlist.json", {"papers": [{"id": "paper_001", "citation_key": "smith2020"}],
                                    "summary": {"included": 12}})
    _w(rd, "step2b_snowball_papers.json", {"rounds": [{"round": 1, "added": 1}], "caveats": []})
    _w(rd, "step4_citation_keys.jsonl", json.dumps({"id": "paper_001", "key": "smith2020"}) + "\n")
    _w(rd, "step4_references.bib", "@article{smith2020,\n  title = {Paper 1},\n  year = {2020}\n}\n")
    cav = [{"code": "source-failed", "unit": "A2.s", "text": "scopus failed twice", "must_disclose": False},
           {"code": "accept-weak", "unit": "A2.c", "text": "Q1 accepted weak", "must_disclose": True}]
    _w(rd, "search_caveats.json", {"schema": "ideate-search-caveats/1", "at": T0, "caveats": cav,
                                   "must_disclose": [c for c in cav if c["must_disclose"]]})


SEARCH_ORDER = ["A1.p", "A1.q", "A1.v", "A1.e", "A2.s", "A2.m", "A2.c", "A3.b", "A3.g", "A3", "A5",
                "A3.b", "A3.g", "A3", "A4.k", "A4.b"]          # A5's additions screened again before export
FUSION_ORDER = ["A6.d", "A6.c", "A7.D", "A7.A1", "A7.A2", "A7.A3", "B1", "A7.X1", "A7.X2", "B3.c", "B3", "A7.R1",
                "A7.R2", "A7.R3", "B2", "B3.5", "F.9"]


def search_ledger(rd: Path, led: Ledger, stop_before: str | None = None) -> None:
    for unit in SEARCH_ORDER:
        if unit == stop_before:
            return
        led.run(unit)


def fusion_files(rd: Path, ready: int, unresolved: int) -> None:
    _w(rd, "step3_tier1_candidates.json", {"candidates": ["smith2020"], "top_ups": 0})
    _w(rd, "pdfs/smith2020.pdf", "%PDF-1.4\n% fixture\n%%EOF\n")
    _w(rd, "step5_fetch_log.json", {"attempts": [{"key": "smith2020", "route": "unpaywall", "result": "ok"}]})
    _w(rd, "step5_full_text/smith2020.md", "# Paper 1\n\nFull text.\n")
    _w(rd, "knowledge/decon/smith2020.json", {"schema": "ai-scientist-decon/1", "key": "smith2020", "units": []})
    _w(rd, "knowledge/alignment.json", {"vocab": {"eeg": {}}, "vocab_basis": "x", "coords": {}, "coords_basis": "x"})
    _w(rd, "knowledge/methods_matrix_input.json", {"rows": []})
    _w(rd, "knowledge/methods_matrix.json", {"rows": []})
    _w(rd, "knowledge_cards.json", {"points": [], "planes": []})
    _w(rd, "lens.json", {"persona": "EEG lab", "local": {"date": "2026-10-17"}})
    _w(rd, "knowledge/collision_candidates.json", {"candidates": [], "truncated": []})
    _w(rd, "knowledge/collisions.jsonl", json.dumps({"collision_id": "X0001", "result": "conflict", "type": "paper"}) + "\n")
    _w(rd, "step7_gaps.json", {"gaps": [{"id": "GAP_001", "rank": 1}]})
    _w(rd, "knowledge/lines/D_draft_debate.md", "# Debate line\n")
    _w(rd, "knowledge/body/B_draft_eeg_descriptive.md", "# Descriptive body\n")
    _w(rd, "step6_sota_review.md", "# SOTA\n")
    qs = [{"id": f"Q_{i:03d}", "status": "ready", "gap_rank": i} for i in range(1, ready + 1)]
    qs += [{"id": f"Q_{ready + i:03d}", "status": "screen_unresolved", "gap_rank": ready + i} for i in range(1, unresolved + 1)]
    qs += [{"id": "Q_099", "status": "abandoned", "gap_rank": 9}]
    for q in qs:
        _w(rd, f"questions/{q['id']}.md", f"---\nstatus: {q['status']}\n---\n# {q['id']}\n")
    _w(rd, "questions/index.json", {"at": T0, "target_ready": 5, "ready": ready, "questions": qs})
    cav = [{"code": "questions-short", "unit": "B3.5", "text": f"{ready} ready of 5", "must_disclose": True}] if ready < 5 else []
    _w(rd, "fusion_caveats.json", {"schema": "ideate-fusion-caveats/1", "at": T0, "caveats": cav,
                                   "must_disclose": [c for c in cav if c["must_disclose"]]})


def fusion_ledger(led: Ledger) -> None:
    for unit in FUSION_ORDER:
        led.run(unit)


def planning_files(rd: Path) -> None:
    _w(rd, "step0_session_config.json", {"topic": "EEG artefact handling", "depth": "standard", "max_num_generations": 3})
    words = lambda n: " ".join(["word"] * n)  # noqa: E731
    good_tree = {"root": "N0", "nodes": [
        {"id": "N0", "role": "instrument", "claims": [], "branches": [
            {"kind": "pass", "next": "N1", "prior": "likely"}, {"kind": "fail", "leaf": "L0", "prior": "unlikely"}]},
        {"id": "N1", "role": "tests", "claims": ["C1"], "branches": [
            {"kind": "supported", "leaf": "L1", "prior": "possible"}, {"kind": "refuted", "leaf": "L2", "prior": "possible"},
            {"kind": "uninformative", "leaf": "L3", "prior": "unlikely"}]}],
        "leaves": [{"id": "L0", "paper": "not-publishable"}, {"id": "L1", "paper": "finding"},
                   {"id": "L2", "paper": "informative-null"}, {"id": "L3", "paper": "methods-caveat"}]}
    weak_tree = {"root": "N1", "nodes": [
        {"id": "N1", "role": "tests", "claims": ["C1"], "branches": [
            {"kind": "supported", "leaf": "L1", "prior": "possible"},
            {"kind": "uninformative", "leaf": "L2", "prior": "likely"}]}],
        "leaves": [{"id": "L1", "paper": "finding"}, {"id": "L2", "paper": "methods-caveat"}]}
    for k, tree, n_words in ((1, good_tree, 200), (2, weak_tree, 300)):
        g = f"gen_{k}"
        _w(rd, f"{g}/question.json", {"id": f"Q_00{k}", "gap": "GAP_001"})
        _w(rd, f"{g}/step7b_problem.md", "# Problem\n")
        _w(rd, f"{g}/step8_hypothesis.md", "# Hypothesis\n")
        _w(rd, f"{g}/p1_prefill.json", {"default_form": "moderation"})
        _w(rd, f"{g}/argument.json", {"claims": [{"id": "C1", "primary": True}], "experiments": [{"id": "E1"}]})
        _w(rd, f"{g}/decision_tree.json", tree)
        _w(rd, f"{g}/attack_plan.json", {"targets": []})
        _w(rd, f"{g}/related_work.md", "Related work.\n")
        _w(rd, f"{g}/packaging.json", {"tree_gate": "ok"})
        _w(rd, f"{g}/idea_draft.json", {"Name": f"idea_{k}", "Abstract": words(n_words)})
    _w(rd, "gen_1/reflection_log.md", "## Round 1/3\nACTION:\nFinalizeIdea\n")
    _w(rd, "gen_1/idea.json", {"Name": "idea_1"})


# ------------------------------------------------------------------------------------------------ datasets
def build(root: Path) -> None:
    def fresh(name: str) -> Path:
        d = root / name
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        return d

    rd = fresh("search_complete")
    search_files(rd)
    led = Ledger(rd)
    search_ledger(rd, led)
    led.save()

    rd = fresh("search_stale")
    search_files(rd)
    led = Ledger(rd)
    search_ledger(rd, led)
    led.save()
    _w(rd, "step3_gate.json", {"excluded": {"paper_004": "X-RET"}})          # edited after A3.g's done

    rd = fresh("search_interrupted")
    search_files(rd)
    led = Ledger(rd)
    search_ledger(rd, led, stop_before="A2.s")
    led.begin("A2.s")
    led.save()

    rd = fresh("search_failed_a3")
    search_files(rd)
    led = Ledger(rd)
    search_ledger(rd, led, stop_before="A3")
    led.begin("A3")
    led.fail("A3", "C03: invented evidence in batch 4")
    led.save()

    rd = fresh("ledger_malformed")
    search_files(rd)
    led = Ledger(rd)
    search_ledger(rd, led, stop_before="A2.m")
    led.save(extra_raw='{"ev": "begin", "unit": "A2.m", "inst": "-", "at": \n')

    for name, ready, unresolved in (("fusion_ready", 3, 0), ("fusion_no_ready", 0, 0)):
        rd = fresh(name)
        search_files(rd)
        fusion_files(rd, ready, unresolved)
        led = Ledger(rd)
        search_ledger(rd, led)
        fusion_ledger(led)
        led.save()

    rd = fresh("planning")
    planning_files(rd)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):        # a console code page (cp1252) must not crash on a path
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    ap = argparse.ArgumentParser(description="Build the eval fixture research folders.")
    ap.add_argument("--check", action="store_true", help="compare a fresh build with evals/datasets/")
    a = ap.parse_args(argv)
    if not a.check:
        build(DATASETS)
        print(f"built {', '.join(sorted(p.name for p in DATASETS.iterdir() if p.is_dir()))}")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        build(Path(tmp))
        diffs = []

        def walk(cmp: filecmp.dircmp, rel: str) -> None:
            diffs.extend(f"{rel}{n}" for n in cmp.left_only + cmp.right_only + cmp.diff_files + cmp.funny_files)
            for n, sub in cmp.subdirs.items():
                walk(sub, f"{rel}{n}/")
        walk(filecmp.dircmp(tmp, DATASETS), "")
        if diffs:
            print("DRIFT: datasets differ from a fresh build: " + ", ".join(sorted(diffs)[:20]))
            return 1
        print("datasets match a fresh build")
        return 0


if __name__ == "__main__":
    sys.exit(main())
