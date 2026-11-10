"""Frozen LitSearch inputs and artifact adapters for the current S2/S3 pipeline."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ideate_v2.jsonio import sha256_json
from ideate_v2.ledger import spec_hash, spec_id
from ideate_v2.registry import Registry

PREPARED = ("A1.p", "A1.q", "A1.e", "A1.v", "A2.s", "A2.m", "A2.c")


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _hashes(reg, rd, unit, side):
    cfg = read_json(rd / "step0_session_config.json")
    specs = ((reg.legacy_card(unit) or {}).get("io") or {}).get(side) or []
    if side == "reads":
        specs = [s for s in specs if s.get("hash_at") != "done"]
    out = {}
    for spec in specs:
        sid = spec_id(spec)
        status, value = spec_hash(rd, sid, cfg)
        out[sid] = value if status == "verified" else "litsearch-frozen:" + sha256_json(sid)[:16]
    return out


def prepare_step3(rd: Path, task: dict, candidates: list[dict]) -> dict:
    """Inject an exact candidate set at the S2/S3 boundary, with a resumable hash contract."""
    rd = Path(rd)
    rd.mkdir(parents=True, exist_ok=True)
    if not candidates or len({str(p["id"]) for p in candidates}) != len(candidates):
        raise ValueError("candidates must have distinct ids")
    frozen = {"schema": "litsearch-s3-input/1", "qid": task["qid"], "query": task["query"],
              "gold_is_hidden": True, "candidate_ids": [str(p["id"]) for p in candidates]}
    contract_path = rd / "_state" / "evaluation" / "input_contract.json"
    if contract_path.is_file() and read_json(contract_path) != frozen:
        raise ValueError("frozen Step 3 input changed; use a new session directory")
    write_json(contract_path, frozen)
    now = datetime.now(timezone.utc).isoformat()
    topic = rd / "litsearch_topic.md"
    topic.write_text("# LitSearch query\n\n" + task["query"] + "\n", encoding="utf-8")
    cfg = {"topic": task["query"], "topic_file": topic.name, "depth": "standard", "timestamp": now,
           "protocol": {"review_type": "benchmark", "framework": {"name": "custom"},
                        "axes": [{"id": "C1", "terms": task["query"].split()[:4]}],
                        "timeframe": "1900-2026", "languages": ["en"]},
           "queries": [{"id": "Q1", "strategy": "benchmark", "flat_query": task["query"], "status": "active"}],
           "anchor_terms": [], "known_items": [], "sources": ["LitSearch frozen candidates"],
           "target_venues": [], "expert_domain": "literature search evaluation",
           "local_environment": {"artefacts": [], "cached_data": [], "packages_present": [], "packages_missing": []}}
    write_json(rd / "step0_session_config.json", cfg)
    write_json(rd / "step1_protocol_evaluation.json", {"rounds": [{"round": 1, "verdict": "accepted"}],
                                                        "final": {"status": "accepted", "round": 1, "unresolved": []}})
    (rd / "step1_protocol.md").write_text("# Frozen benchmark protocol\n", encoding="utf-8")
    papers = [{**p, "id": str(p["id"]), "found_via": "Q1",
               "sources_found_in": p.get("sources_found_in") or ["LitSearch frozen candidates"]}
              for p in candidates]
    qfile = rd / "step2_queries" / "Q1@frozen.json"
    write_json(qfile, {"kind": "query", "id": "Q1", "complete": True, "papers": papers,
                       "source_results": [{"source": "LitSearch frozen candidates", "status": "ok",
                                           "count": len(papers)}]})
    for paper in papers:
        paper.update(found_by=["Q1"], merged_from=1, anchor_match=None,
                     has_abstract=bool(str(paper.get("abstract") or "").strip()), code_hint=None,
                     superseded_only=False, retired_only=False)
    instance = {"file": qfile.name, "sha": sha256(qfile)}
    write_json(rd / "step2_raw_papers.json", {"schema": "ideate-raw/2", "topic": task["query"],
        "search_timestamp": now, "papers": papers, "search_summary": {
        "total_raw_results": len(papers), "after_dedup": len(papers), "final_count": len(papers),
        "instances": [instance], "merges": 0, "identification": {}, "minted_ids": 0,
        "enrichment": {}, "sem_sim": {}, "sources": {"litsearch-frozen": len(papers)},
        "queries": {"Q1": 1}, "caveats": []}})
    registry = rd / "_state" / "paper_ids.jsonl"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text("".join(json.dumps({"id": p["id"], "minted_by": "evaluation-adapter", "at": now,
                                              "dois": [], "arxiv": None, "title": p["title"].casefold()}) + "\n"
                                for p in papers), encoding="utf-8")
    raw_sha = sha256(rd / "step2_raw_papers.json")
    write_json(rd / "step2_relevance_check.json", {"rounds": [{"round": 0, "verdicts": [
        {"query": "Q1", "verdict": "ok", "reason": "Frozen benchmark candidate pool"}],
        "raw_sha": raw_sha, "known_items": [], "vocabulary": [], "term_pull": [],
        "summary": "Fixed candidate pool; no relevance replanning."}],
                                                    "caveats": [], "frozen": True})
    reg, events = Registry.load(), []
    for unit in PREPARED:
        inputs = _hashes(reg, rd, unit, "reads")
        events.extend(({"ev": "begin", "unit": unit, "inst": "-", "at": now, "inputs": inputs},
                       {"ev": "done", "unit": unit, "inst": "-", "at": now, "inputs": inputs,
                        "outputs": _hashes(reg, rd, unit, "owns"), "counts": {}, "degraded": [],
                        "tool": "litsearch-evaluation-adapter"}))
    ledger = rd / "_state" / "ledger.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    hashes = {"step0_session_config.json": sha256(rd / "step0_session_config.json"),
              "step2_raw_papers.json": sha256(rd / "step2_raw_papers.json"),
              "prepared_ledger_sha256": sha256(ledger)}
    write_json(rd / "_state" / "evaluation" / "input_hashes.json", hashes)
    return {**frozen, "hashes": hashes}


def verify_frozen(rd: Path) -> None:
    hashes = read_json(Path(rd) / "_state" / "evaluation" / "input_hashes.json")
    paths = {"step0_session_config.json": Path(rd) / "step0_session_config.json",
             "step2_raw_papers.json": Path(rd) / "step2_raw_papers.json"}
    for name, path in paths.items():
        if sha256(path) != hashes[name]:
            raise ValueError(f"frozen input changed: {name}")


def scored_papers(rd: Path) -> list[dict]:
    """Join current A3 score/shortlist artifacts back onto the frozen candidate records."""
    rd = Path(rd)
    raw = read_json(rd / "step2_raw_papers.json").get("papers") or []
    scores_doc = read_json(rd / "screening_scores.json")
    scores = scores_doc.get("scores") or scores_doc.get("papers") or {}
    shortlist = read_json(rd / "step3_shortlist.json").get("papers") or []
    categories = {str(p.get("id")): (p.get("screening") or {}).get("category") or p.get("category")
                  for p in shortlist}
    rows = []
    from evaluation.step03.scoring import normalize_screening
    for paper in raw:
        pid = str(paper["id"])
        score = scores.get(pid, {}) if isinstance(scores, dict) else next(
            (x.get("screening", x) for x in scores if str(x.get("id")) == pid), {})
        rows.append(normalize_screening(paper, score, categories.get(pid)))
    if len(rows) != len(scores):
        raise ValueError("STEP-S3 did not score every frozen candidate exactly once")
    write_json(rd / "step3_screening_all.json", {"schema": "litsearch-step3-screening/1", "papers": rows})
    return rows
