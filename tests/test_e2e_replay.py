"""End-to-end offline run of all 9 steps, then replay (cache read-only) → byte-identical outputs."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scholar_research.config import Config
from scholar_research.llm.client import FakeBackend
from scholar_research.pipeline import run_range, snapshot
from scholar_research.session import Session
from scholar_research.steps.base import Context
from tests.fakes import FakeHttpx, fake_llm


@pytest.fixture
def offline(monkeypatch):
    import scholar_research.providers.base as base

    monkeypatch.setattr(base.httpx, "Client", FakeHttpx)
    monkeypatch.setattr(base.time, "sleep", lambda *_: None)
    FakeHttpx.calls.clear()
    yield


def _ctx(session: Session, cfg: Config, backend: FakeBackend, mode: str = "auto") -> Context:
    ctx = Context(session, cfg, llm_backend=backend)
    ctx.checkpoint_mode = mode
    ctx.ui_print = lambda *_: None
    return ctx


def test_full_pipeline_then_replay_is_byte_identical(tmp_path: Path, offline):
    cfg = Config.load(None)
    cfg.paths.research_root = str(tmp_path / "10_Research")
    cfg.llm.model = "claude-test-pinned"
    backend = FakeBackend(fake_llm)
    s = Session.create(Path(cfg.paths.research_root), "EEG neurofeedback for MCI", cfg, session_id="20260919")
    assert s.name == "20260919_eeg-neurofeedback-for-mci"

    m = run_range(_ctx(s, cfg, backend), 1, 9)
    assert [r["status"] for r in m.data["steps"]] == ["ok"] * 9, [r.get("error") for r in m.data["steps"]]
    assert s.last_completed() == 9 and s.load_config().current_step == 9

    # ---- contract checks against the skills' file formats ----
    raw = json.loads(s.path("step2_raw_papers.json").read_text(encoding="utf-8"))
    assert raw["papers"][0]["id"] == "paper_001"
    ids = [p["id"] for p in raw["papers"]]
    assert ids == sorted(ids) and len(ids) == len(set(ids))
    assert raw["search_summary"]["snowball_additions"] >= 1 and any(p["found_via"] == "snowball" for p in raw["papers"])
    d = next(p for p in raw["papers"] if p["arxiv_id"] == "2401.00001")
    assert d["doi"] == "10.1000/d"  # DOI recovery via S2 ARXIV lookup
    a = next(p for p in raw["papers"] if p["doi"] == "10.1000/a")
    assert set(a["sources_found_in"]) >= {"semantic_scholar", "openalex"}
    assert a["citation_network"]["in_degree"] >= 1  # E → A via OpenAlex referenced_works

    sl = json.loads(s.path("step3_shortlist.json").read_text(encoding="utf-8"))
    assert sl["screening_config"]["weights"] == {"relevance": 0.5, "quality": 0.3, "recency_impact": 0.2}
    for p in sl["papers"]:
        sc = p["screening"]
        assert sc["composite"] == round(sc["relevance"] * 0.5 + sc["quality"] * 0.3 + sc["recency_impact"] * 0.2, 2)
        assert sc["composite"] >= sl["screening_config"]["threshold"]
    allrec = json.loads(s.path("step3_screening_all.json").read_text(encoding="utf-8"))
    assert len(allrec["papers"]) == len(raw["papers"])
    rats = next(p for p in allrec["papers"] if "Rodent" in p["title"])
    assert rats["screening"]["category"] == "excluded" and "rats" in rats["screening"]["exclusion_reason"]
    md3 = s.path("step3_screening_results.md").read_text(encoding="utf-8")
    assert "Checkpoint 2" in md3 and "Population mismatch" in md3

    bib = s.path("step4_references.bib").read_text(encoding="utf-8")
    keys = json.loads(s.path("step4_citation_keys.json").read_text(encoding="utf-8"))
    assert len(re.findall(r"^@", bib, re.M)) == len(sl["papers"]) == len(keys)
    apa = s.path("step4_references_apa.md").read_text(encoding="utf-8")
    assert "Lee, A., Chan, B., & Dee, C. (2023)." in apa

    log = s.path("step5_full_text/_access_log.md").read_text(encoding="utf-8")
    assert "full-text-html" in log
    d_key = keys[d["id"]]["key"]
    dmd = s.path(f"step5_full_text/{d_key}.md").read_text(encoding="utf-8")
    assert 'access_level: "full-text-html"' in dmd and "extraction_method" in dmd and "## 2 Methods" in dmd
    assert "summarized" not in log

    canvas = json.loads(s.path("step6_knowledge_graph.canvas").read_text(encoding="utf-8"))
    node_ids = {n["id"] for n in canvas["nodes"]}
    assert all(e["fromNode"] in node_ids and e["toNode"] in node_ids for e in canvas["edges"])  # phantom edge dropped
    assert all(keys[p["id"]]["key"] in node_ids for p in sl["papers"])
    assert "step6_sota_review.md" in canvas["nodes"][0]["file"]

    gaps = json.loads(s.path("step7_gaps.json").read_text(encoding="utf-8"))
    comps = [g["composite"] for g in gaps["gaps"]]
    assert comps == sorted(comps, reverse=True) and gaps["gaps"][0]["id"] == "GAP_001"
    assert comps[0] == round(5 * 0.4 + 4 * 0.3 + 3 * 0.3, 2) == 4.1  # Home-based delivery ranked first by code
    md7 = s.path("step7_gap_analysis.md").read_text(encoding="utf-8")
    assert "5 × 0.40 + 4 × 0.30 + 3 × 0.30 = 2.00 + 1.20 + 0.90 = **4.10**" in md7

    cps = json.loads(s.path("checkpoints.json").read_text(encoding="utf-8"))["decisions"]
    assert cps["3"]["decision"]["lock"] == "GAP_001" and cps["4"]["decision"]["approved"] is True
    hyp = s.path("step8_hypothesis_specification.md").read_text(encoding="utf-8")
    assert 'selected_gap: "GAP_001"' in hyp and "dropped_gaps:" in hyp

    intro = s.path("step9_manuscript/01_intro.tex").read_text(encoding="utf-8")
    assert "Phantom2099" not in intro.split("% TODO: phantom")[1].split("\n")[1:] and r"\cite{Fake2000}" not in intro
    assert "TODO: citation needed" in intro
    pruned = s.path("step9_manuscript/references.bib").read_text(encoding="utf-8")
    cited = set(re.findall(r"\\cite\{([^}]*)\}", intro + s.path("step9_manuscript/02_relatedwork.tex").read_text(encoding="utf-8")))
    cited_keys = {k.strip() for grp in cited for k in grp.split(",")}
    assert cited_keys <= set(keys[p]["key"] for p in keys)
    assert set(re.findall(r"^@\w+\{([^,]+),", pruned, re.M)) == cited_keys
    val = json.loads(s.path("step9_manuscript/_validation.json").read_text(encoding="utf-8"))
    assert set(val["phantom_removed"]) == {"Phantom2099", "Fake2000"}

    manifest = json.loads(s.path("run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["config"]["api"]["anthropic_api_key"] in (None, "<set>")
    assert manifest["steps"][2]["prompt_versions"]["s3_score"] == "1.0.0"
    assert manifest["totals"]["llm"]["calls"] > 0

    # ---------------- replay: read-only cache, no network, no LLM ---------------- #
    before = snapshot(s, list(range(1, 10)))
    http_calls = len(FakeHttpx.calls)
    llm_calls = backend.calls
    s2 = Session(s.dir, cfg, cache_mode="read-only")
    m2 = run_range(_ctx(s2, cfg, backend), 1, 9, stop_at_checkpoint=False)
    assert [r["status"] for r in m2.data["steps"]] == ["ok"] * 9
    after = snapshot(s2, list(range(1, 10)))
    assert before == after, [f for f in before if before[f] != after.get(f)]
    assert len(FakeHttpx.calls) == http_calls and backend.calls == llm_calls  # zero external calls on replay
    assert m2.data["totals"]["cache"]["misses"] == 0 and m2.data["totals"]["llm"]["cache_hits"] == m2.data["totals"]["llm"]["calls"]


def test_checkpoint2_rescue_and_file_decisions(tmp_path: Path, offline):
    cfg = Config.load(None)
    cfg.paths.research_root = str(tmp_path / "10_Research")
    backend = FakeBackend(fake_llm)
    s = Session.create(Path(cfg.paths.research_root), "EEG neurofeedback for MCI", cfg, session_id="20260919")
    ctx = _ctx(s, cfg, backend, mode="file")
    ctx.decisions = {"checkpoint1": {"approved": True}}
    run_range(ctx, 1, 3)
    allrec = json.loads(s.path("step3_screening_all.json").read_text(encoding="utf-8"))
    border = [p["id"] for p in allrec["papers"] if p["screening"]["category"] == "borderline"]
    assert border, "fixture should produce at least one borderline paper"
    # decision file rescues one borderline paper → shortlist gains it with manually_included
    ctx.decisions["checkpoint2"] = {"include": [border[0]]}
    run_range(ctx, 4, 4)
    sl = json.loads(s.path("step3_shortlist.json").read_text(encoding="utf-8"))
    rescued = next(p for p in sl["papers"] if p["id"] == border[0])
    assert rescued["manually_included"] is True and sl["summary"]["manually_included"] == 1
    assert border[0] in json.loads(s.path("step4_citation_keys.json").read_text(encoding="utf-8"))
    assert json.loads(s.path("checkpoints.json").read_text(encoding="utf-8"))["decisions"]["2"]["decision"]["include"] == [border[0]]


def test_interactive_without_tty_pauses_cleanly(tmp_path: Path, offline):
    cfg = Config.load(None)
    cfg.paths.research_root = str(tmp_path / "10_Research")
    s = Session.create(Path(cfg.paths.research_root), "EEG neurofeedback for MCI", cfg, session_id="20260919")
    msgs = []
    ctx = _ctx(s, cfg, FakeBackend(fake_llm), mode="interactive")
    ctx.ui_print = msgs.append
    m = run_range(ctx, 1, 3)
    assert [r["status"] for r in m.data["steps"]] == ["ok", "blocked"]
    assert s.last_completed() == 1 and s.pending_checkpoint() == 1
    assert any("Checkpoint 1" in x for x in msgs)
