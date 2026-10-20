"""Build an IdeaBench-style target/ref subset under ``eval_runs/ideabench/``."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from scholar_research.cache import Cache
from scholar_research.config import Config
from scholar_research.llm.client import Backend, LLMClient
from scholar_research.llm.ledger import Ledger
from scholar_research.providers.base import HttpClient
from scholar_research.providers.semantic_scholar import SemanticScholar
from scholar_research.session import now_iso
from scholar_research.utils import dump_json, write_text
from .cutoffs import MODEL_REGISTRY, validate_target_window
from .extract import extract_target_idea
from .s2 import fetch_references, filter_references, pick_low_resource, ref_card
from .targets import (
    fetch_openalex_references,
    filter_openalex_references,
    search_targets,
    to_target_card,
)

Say = Callable[[str], None]


def _safe_dir_name(paper_id: str) -> str:
    """Windows-safe folder name (paperId may be pmid:123 / openalex:W…)."""
    return re.sub(r"[^\w.\-]+", "_", paper_id)[:180]


def build_subset(
    out_dir: Path,
    config: Config,
    *,
    models: list[str],
    target_start: str = "2026-01-01",
    target_end: str = "2026-06-30",
    m: int = 20,
    low_k: int = 5,
    seed: int = 0,
    source: str = "openalex",
    skip_extract: bool = False,
    skip_background_filter: bool = True,
    extract_backend: Backend | None = None,
    say: Say | None = None,
) -> dict[str, Any]:
    """Validate cutoff window → fetch targets → refs → filter → optional idea extract.

    ``source``: ``openalex`` (default) | ``pubmed`` | ``pubmed+openalex`` | ``s2``.
    """
    log = say or (lambda _m: None)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ideas").mkdir(exist_ok=True)
    (out_dir / "refs").mkdir(exist_ok=True)

    safety = validate_target_window(models, target_start, target_end)
    log(f"[cutoff] latest={safety['latest_cutoff']} safe_start={safety['safe_start']}")
    log(f"[cutoff] window {target_start}..{target_end} OK for models={models}")
    log(f"[source] {source}")

    cache = Cache(out_dir / ".cache", config.cache_mode)
    http = HttpClient(cache, timeout=config.search.request_timeout, max_attempts=config.search.max_attempts)
    http.log = lambda m: log(f"    {m}")
    s2 = SemanticScholar(http, api_key=config.api.semantic_scholar_key)

    try:
        log(f"[targets] fetching m={m} biomedical papers …")
        raw_targets = search_targets(
            http,
            source=source,
            target_start=target_start,
            target_end=target_end,
            need=m,
            config_api=config.api,
            say=log,
        )
        if len(raw_targets) < m:
            log(f"[targets] WARNING: only {len(raw_targets)}/{m} papers satisfied filters")

        extract_llm: LLMClient | None = None
        if not skip_extract:
            try:
                judge_cfg = config.resolve_judge_llm(allow_same_model=True)
            except RuntimeError:
                judge_cfg = config.llm
            extract_llm = LLMClient(
                judge_cfg,
                cache,
                Ledger(out_dir / ".cache" / "llm" / "ledger.jsonl"),
                backend=extract_backend,
                api_key=config.api.anthropic_api_key,
            )
            log(f"[extract] model={judge_cfg.model} provider={judge_cfg.provider}")

        rows: list[dict[str, Any]] = []
        for i, p in enumerate(raw_targets, 1):
            card = to_target_card(p)
            pid = card["paperId"]
            log(f"[{i}/{len(raw_targets)}] {pid} — {(card.get('title') or '')[:80]}")
            ref_dir = out_dir / "refs" / _safe_dir_name(pid)
            ref_dir.mkdir(parents=True, exist_ok=True)

            refs_all: list[dict[str, Any]] = []
            refs_filt_cards: list[dict[str, Any]] = []
            try:
                if source == "s2" or str(pid).startswith("s2:") or (len(pid) == 40 and ":" not in pid):
                    # Legacy S2 paperId hex
                    refs_raw = fetch_references(s2, pid, limit=500)
                    refs_all = [ref_card(r) for r in refs_raw if r.get("paperId")]
                    refs_filt_cards = [ref_card(r) for r in filter_references(refs_raw)]
                else:
                    refs_raw = fetch_openalex_references(
                        http,
                        openalex_id=card.get("openalex_id") or (pid.split(":", 1)[1] if str(pid).startswith("openalex:") else None),
                        referenced_works=card.get("referenced_works") or p.get("referenced_works"),
                        doi=card.get("doi"),
                        mailto=config.api.openalex_mailto,
                        api_key=config.api.openalex_api_key,
                        limit=500,
                    )
                    refs_all = refs_raw
                    refs_filt_cards = filter_openalex_references(refs_raw)
            except Exception as e:  # noqa: BLE001
                log(f"  refs FAILED: {e}")

            refs_low = pick_low_resource(refs_filt_cards, low_k, seed=seed + i)

            dump_json(ref_dir / "all.json", {"paperId": pid, "n": len(refs_all), "references": refs_all})
            dump_json(ref_dir / "filtered.json", {"paperId": pid, "n": len(refs_filt_cards), "references": refs_filt_cards})
            dump_json(ref_dir / f"low{low_k}.json", {"paperId": pid, "n": len(refs_low), "k": low_k, "seed": seed + i, "references": refs_low})

            idea_text = None
            idea_path = out_dir / "ideas" / f"{_safe_dir_name(pid)}.txt"
            if extract_llm is not None and card.get("abstract"):
                try:
                    idea_text = extract_target_idea(extract_llm, card["abstract"])
                    write_text(idea_path, idea_text)
                except Exception as e:  # noqa: BLE001
                    log(f"  extract FAILED: {e}")

            row = {
                **card,
                "n_refs_all": len(refs_all),
                "n_refs_filtered": len(refs_filt_cards),
                "n_refs_low": len(refs_low),
                "idea_path": str(idea_path.relative_to(out_dir)) if idea_text else None,
                "has_idea": bool(idea_text),
            }
            # referenced_works is bulky; drop from jsonl row
            row.pop("referenced_works", None)
            rows.append(row)

        targets_path = out_dir / "targets.jsonl"
        with targets_path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

        manifest = {
            "benchmark": "IdeaBench-style target subset",
            "built_at": now_iso(),
            "domain": "biomedical",
            "target_source": source,
            "target_source_note": (
                "OpenAlex/PubMed targets use existing provider auth/cache/http paths; "
                "OpenAlex tries top venues first and backfills with biomedical journal articles if needed."
            ),
            "models": models,
            "model_cutoffs": {m: MODEL_REGISTRY[m] for m in models},
            "cutoff_check": safety,
            "target_start": target_start,
            "target_end": target_end,
            "m_requested": m,
            "m_kept": len(rows),
            "low_k": low_k,
            "n_reserved": 5,
            "seed": seed,
            "filters": {
                "min_citations": 5,
                "drop_non_primary": True,
                "require_ref_abstract": True,
                "background_section_filter": (not skip_background_filter),
                "note": "Background-section filter skipped by default (needs full text); documented IdeaBench delta.",
            },
            "extract_prompt": "ideabench_extract_idea (IdeaBench Figure 5 / Appendix wording)",
            "skip_extract": skip_extract,
            "paths": {
                "targets": "targets.jsonl",
                "ideas": "ideas/",
                "refs": "refs/{paperId}/all.json|filtered.json|low{k}.json",
            },
        }
        dump_json(out_dir / "manifest.json", manifest)
        log(f"[done] {len(rows)} targets → {out_dir}")
        return manifest
    finally:
        http.close()
