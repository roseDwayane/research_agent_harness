"""Adapter from frozen IdeaBench references to the current Stage A/B conductor.

The adapter replaces only the online acquisition boundary.  Fusion (A7.D onward)
and planning (P0--P5/B5) are executed by the production harness recipes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from harness.config import HarnessConfig
from harness.context import RunContext, instance_of
from harness.executors import ExecResult, RecipeExecutor
from harness.pipeline import PipelineAgent
from harness.recipes import load as load_recipes
from harness.skill import Skill
from ideate_v2.jsonio import sha256_file, sha256_json
from ideate_v2.ledger import spec_hash, spec_id
from ideate_v2.registry import Registry

from .client import ModelConfig
from .jsonio import read_json, write_json

PREPARED_UNITS = ("A1.p", "A1.q", "A1.v", "A1.e", "A2.s", "A2.m", "A2.c", "A3.b", "A3.g",
                  "A3", "A5", "A4.k", "A4.b", "A6.d", "A6.c")


def _citation_key(index: int) -> str:
    return f"ideabench_ref_{index:02d}"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _hashes(reg: Registry, rd: Path, unit: str, side: str) -> dict:
    cfg = read_json(rd / "step0_session_config.json")
    io = (reg.legacy_card(unit) or {}).get("io") or {}
    specs = io.get(side) or []
    if side == "reads":
        specs = [s for s in specs if s.get("hash_at") != "done"]
    result = {}
    for spec in specs:
        sid = spec_id(spec)
        status, value = spec_hash(rd, sid, cfg)
        result[sid] = value if status == "verified" else "ideabench-frozen:" + sha256_json(sid)[:16]
    return result


def prepare_research_dir(rd: Path, refs: list[dict], *, max_questions: int) -> dict:
    """Materialize and hash the fixed-five offline acquisition boundary."""
    if len(refs) != 5 or len({r["paperId"] for r in refs}) != 5:
        raise ValueError("offline preparation requires five distinct references")
    rd = Path(rd)
    rd.mkdir(parents=True, exist_ok=True)
    frozen = rd / "_state" / "ideabench" / "frozen_references.json"
    payload = {"schema": "ideabench-frozen-references/1", "count": 5, "references": refs}
    if frozen.is_file() and read_json(frozen) != payload:
        raise ValueError("frozen references changed; use a new task directory")
    write_json(frozen, payload)
    prepared_path = rd / "_state" / "ideabench" / "prepared.json"
    if prepared_path.is_file():
        existing = read_json(prepared_path)
        if existing.get("references_sha256") != sha256_file(frozen) or \
                existing.get("max_questions") != max_questions:
            raise ValueError("prepared pipeline contract changed; use a new task directory")
        return existing
    now = datetime.now(timezone.utc).isoformat()
    topic = rd / "ideabench_topic.md"
    _write_text(topic, "# Offline IdeaBench ideation\n\nIdentify evidence-grounded biomedical research gaps.\n")
    write_json(rd / "step0_session_config.json", {
        "topic": "Offline IdeaBench ideation", "topic_file": topic.name, "depth": "standard",
        "timestamp": now, "max_num_generations": max_questions,
        "protocol": {"review_type": "fixed-reference offline evaluation", "framework": {"name": "IdeaBench"}},
        "queries": [], "sources": ["IdeaBench fixed references"], "anchor_terms": [], "known_items": [],
        "local_environment": {"artefacts": [], "cached_data": [], "packages_present": [], "packages_missing": []},
    })
    papers = []
    bib = []
    keys = []
    for i, ref in enumerate(refs, 1):
        key = _citation_key(i)
        paper = {**ref, "id": ref["paperId"], "citation_key": key, "access_level": "abstract-only",
                 "source": "IdeaBench", "included": True}
        papers.append(paper)
        keys.append({"id": ref["paperId"], "key": key})
        title = str(ref["title"]).replace("{", "").replace("}", "")
        bib.append(f"@article{{{key},\n  title = {{{title}}},\n  year = {{{ref.get('year') or ''}}}\n}}\n")
    write_json(rd / "step2_raw_papers.json", {"papers": papers, "search_summary": {"offline": True}})
    write_json(rd / "step3_shortlist.json", {"papers": papers, "summary": {"included": 5, "offline": True}})
    write_json(rd / "step3_tier1_candidates.json", {"candidates": [], "top_ups": 0, "offline": True})
    _write_text(rd / "step4_citation_keys.jsonl", "".join(json.dumps(x) + "\n" for x in keys))
    _write_text(rd / "step4_citation_keys.md", "\n".join(f"- `{x['key']}`: {x['id']}" for x in keys) + "\n")
    _write_text(rd / "step4_references.bib", "\n".join(bib))
    write_json(rd / "step4_bib_metadata.json", {"count": 5, "source": "IdeaBench", "offline": True})
    write_json(rd / "step5_fetch_log.json", {"attempts": [], "offline": True,
                                              "reason": "abstracts supplied by official dataset"})
    _write_text(rd / "step3_missing_pdfs.md", "# Missing PDFs\n\nAll five inputs are intentionally abstract-only.\n")
    _write_text(rd / "step5_full_text" / "_access_log.md", "# Access log\n\nOffline evaluation; no retrieval attempted.\n")
    caveats = {"schema": "ideate-search-caveats/1", "at": now, "caveats": [], "must_disclose": []}
    write_json(rd / "search_caveats.json", caveats)
    write_json(rd / "fulltext_caveats.json", {**caveats, "schema": "ideate-fulltext-caveats/1"})

    reg = Registry.load()
    events = []
    for unit in PREPARED_UNITS:
        inputs = _hashes(reg, rd, unit, "reads")
        events += [{"ev": "begin", "unit": unit, "inst": "-", "at": now, "inputs": inputs},
                   {"ev": "done", "unit": unit, "inst": "-", "at": now, "inputs": inputs,
                    "outputs": _hashes(reg, rd, unit, "owns"), "counts": {}, "degraded": [],
                    "tool": "ideabench-offline-adapter"}]
    ledger = rd / "_state" / "ledger.jsonl"
    _write_text(ledger, "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events))
    contract = {"schema": "ideabench-prepared-run/1", "references_sha256": sha256_file(frozen),
                "ledger_sha256": sha256_file(ledger), "resume_boundary": "STEP-F1/A7.D",
                "online_search": False, "online_fulltext": False, "max_questions": max_questions}
    write_json(prepared_path, contract)
    return contract


class OfflineB6Executor:
    """Finish bookkeeping without B6's journal web lookup."""
    def execute(self, ctx, unit, recipe, phase, gen, attempt):
        gd = ctx.rd / f"gen_{gen}"
        idea = read_json(gd / "idea.json")
        question = read_json(gd / "question.json")
        for command in (f"ideate_tools.py append-idea $IDEAS $GEN/idea.json",
                        f"ideate_tools.py consume $RD --question {question['id']} --idea {idea['Name']}"):
            result = ctx.skill.run(command, ctx.subs(gen))
            if result.returncode:
                err = ctx.error("IDEATE.TOOL.FAILED", result.stderr or command, unit=unit,
                                instance=instance_of(gen), attempt=attempt)
                return ExecResult(False, [err])
        _write_text(gd / "step8_journal_recommendations.md",
                    "# Journal recommendations\n\nSkipped by the offline IdeaBench protocol.\n")
        _write_text(gd / "body" / f"B_draft_{idea['Name']}.md",
                    "# Prescriptive body\n\nThe offline evaluation ends at the finalized idea specification.\n")
        return ExecResult(True, metrics={"calls": 0}, notes=["offline B6: web lookup skipped"])


def run_pipeline_p2(task_dir: Path, refs: list[dict], model: ModelConfig, *, max_questions: int, say=print) -> list[dict]:
    """Run the current production Stage A fusion and Stage B pipeline on frozen references."""
    rd = Path(task_dir) / "P2" / "research"
    prepare_research_dir(rd, refs, max_questions=max_questions)
    cfg = HarnessConfig(worker="ollama", model=model.model, ollama_url=model.url, num_ctx=model.num_ctx,
                        num_predict=model.num_predict, temperature=model.temperature,
                        worker_timeout_s=model.timeout_s, max_num_generations=max_questions, resume=True)
    reg, recipes = Registry.load(), load_recipes()
    default = RecipeExecutor()
    ctx = RunContext(reg, cfg, Skill(cfg), rd, rd / "ideabench_topic.md", say=say)
    pipeline = PipelineAgent(reg, recipes, lambda unit: OfflineB6Executor() if unit == "B6" else default)
    summary = pipeline.run(ctx, "F1", "B6")
    ideas = []
    for row in summary["generations"]:
        path = rd / f"gen_{row['gen']}" / "idea.json"
        if row["status"] in ("finalized", "finalized-with-doubt") and path.is_file():
            ideas.append({"question_id": row.get("question"), "path": str(path.relative_to(task_dir)),
                          "idea": read_json(path), "status": row["status"]})
    write_json(Path(task_dir) / "P2_ideas.json", {"protocol": "P2", "n": len(ideas), "ideas": ideas,
                                                  "pipeline_summary": str((ctx.state_dir / 'summary.json').relative_to(task_dir))})
    return ideas
