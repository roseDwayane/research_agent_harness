"""Reference-only P1/P2 generation, independent ranking, Python Insight Scores.

Adapted from IdeaBench Figures 1/2 (not a verbatim reproduction). P2 reuses
Steps 3,4,6,7,8; Step 5 is deliberately abstract-only to match P1 information.
"""
from __future__ import annotations

import json
import random
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, create_model, field_validator

from scholar_research.cache import Cache
from scholar_research.config import Config
from scholar_research.llm.client import LLMClient
from scholar_research.llm.ledger import Ledger
from scholar_research.llm.prompts import load_prompt
from scholar_research.schemas.paper import Paper, RawPapers, SearchSummary, Shortlist
from scholar_research.schemas.session_config import PICO, SessionConfig
from scholar_research.session import Session, now_iso
from scholar_research.steps import s3_screen, s4_export, s6_sota, s7_gaps, s8_hypothesis
from scholar_research.steps.base import Context
from scholar_research.utils import dump_json, load_json, sha256_obj, write_text
from .build import _safe_dir_name
from .extract import IdeaBenchTargetIdea, extract_target_idea
from .targets import filter_openalex_references
from .usage import stage_span

METRICS = {
    "novelty": "A substantive new scientific question, mechanism, method, or application beyond these references; mere relabeling and incoherent speculation do not count.",
    "feasibility": "A testable study achievable with plausible available methods, data, resources and ethical constraints; identify unsupported assumptions.",
    "significance": "Potential to resolve an important scientific or clinical uncertainty if the proposed study succeeds.",
    "clarity": "An unambiguous research claim, intelligible rationale, and understandable proposed test.",
}


class ResearchContext(BaseModel):
    topic: str = Field(min_length=1)
    pico: PICO


class Ideas(BaseModel):
    ideas: list[str]

    @field_validator("ideas")
    @classmethod
    def valid_ideas(cls, values):
        normalized = []
        for value in values:
            normalized.append(IdeaBenchTargetIdea(summary=value).summary)
        if len({v.casefold() for v in normalized}) != len(values):
            raise ValueError("ideas must be distinct")
        return normalized


class Ranking(BaseModel):
    order: list[int]
    rationale: str

    @field_validator("order")
    @classmethod
    def permutation(cls, values):
        if sorted(values) != list(range(1, len(values) + 1)):
            raise ValueError("order must be a complete permutation of anonymous IDs")
        return values


class Coherence(BaseModel):
    failed_ids: list[int]
    rationale: str

    @field_validator("failed_ids")
    @classmethod
    def unique_positive(cls, values):
        if len(set(values)) != len(values) or any(v < 1 for v in values):
            raise ValueError("failed IDs must be unique positive integers")
        return values


def gap_slots(gaps: list[dict]) -> list[str]:
    if not gaps or len({g['id'] for g in gaps}) != len(gaps):
        raise ValueError("need distinct gaps; repeated gaps cannot fill slots")
    return [g["id"] for g in gaps]


def _export(ctx: Context):
    """Step 4 adapter: frozen refs may lack authors, so cite marked placeholders.

    Reuse normal keys/BibTeX formatting without inventing author identities.
    Standard Step 4 remains unchanged for ordinary research sessions.
    """
    sl = Shortlist.model_validate(load_json(ctx.session.path("step3_shortlist.json")))
    if all(p.authors for p in sl.papers):
        return s4_export.run(ctx)
    keys = s4_export.citation_keys(sl.papers)
    mapping = {p.id: {"key": keys[p.id]} for p in sl.papers}
    dump_json(ctx.session.path("step4_citation_keys.json"), mapping)
    write_text(ctx.session.path("step4_citation_keys.md"), "\n".join(f"{keys[p.id]}: {p.title}" for p in sl.papers))
    write_text(ctx.session.path("step4_references_apa.md"), "Author metadata unavailable in frozen benchmark references; title/year registry follows.\n\n" +
               "\n\n".join(f"{p.title}. ({p.year}). {p.journal or ''}" for p in sl.papers))
    write_text(ctx.session.path("step4_references.bib"), "\n\n".join(s4_export.format_bibtex(p, keys[p.id], s4_export.entry_type(p), ["author metadata unavailable"]) for p in sl.papers))


def ideas_schema(n):
    return create_model(f"Ideas{n}", __base__=Ideas, ideas=(list[str], Field(min_length=n, max_length=n)))


def balanced_orders(count: int, seed: int) -> list[list[int]]:
    base = list(range(count))
    random.Random(seed).shuffle(base)
    return [base[i:] + base[:i] for i in range(count)]


def insight_score(rank: int, n: int) -> float:
    if n < 1 or not 1 <= rank <= n + 1:
        raise ValueError("invalid target rank or n")
    return (rank - 1) / n


def reference_blob(refs: list[dict]) -> str:
    return "\n\n".join(f"Reference {i}: {r['title']} ({r['year']})\nAbstract: {r['abstract']}" for i, r in enumerate(refs, 1))


def _load_tasks(dataset: Path, limit: int | None):
    manifest = load_json(dataset / "manifest.json")
    tasks = [json.loads(s) for s in (dataset / "targets.jsonl").read_text(encoding="utf-8").splitlines() if s]
    if len({t['paperId'] for t in tasks}) != len(tasks):
        raise ValueError("duplicate targets")
    loaded = []
    for task in tasks[:limit]:
        path = dataset / "refs" / _safe_dir_name(task["paperId"]) / f"low{manifest['low_k']}.json"
        refs = load_json(path)["references"]
        if len(refs) != manifest["low_k"] or len({r['paperId'] for r in refs}) != len(refs):
            raise ValueError(f"{task['paperId']}: incomplete or duplicate low-resource references")
        if any(not all(r.get(k) for k in ("paperId", "title", "abstract", "year", "publicationTypes")) for r in refs):
            raise ValueError("reference fields incomplete")
        if len(filter_openalex_references(refs)) != len(refs):
            raise ValueError("reference filtering requirements violated")
        if any(r['paperId'] == task['paperId'] or (r.get('doi') and r.get('doi') == task.get('doi')) for r in refs):
            raise ValueError("target appears among generator references")
        idea = IdeaBenchTargetIdea(summary=(dataset / task["idea_path"]).read_text(encoding="utf-8")).summary
        loaded.append((task["paperId"], refs, idea))
    if not loaded:
        raise ValueError("empty dataset")
    return manifest, loaded


def generate_p2(root: Path, refs: list[dict], research: ResearchContext, cfg: Config, say, backend=None):
    root.mkdir(parents=True, exist_ok=True)
    session = Session(root / "pipeline", cfg)
    session.dir.mkdir(parents=True, exist_ok=True)
    if not session.has("step0_session_config.json"):
        with stage_span(session.dir, 'Step 0 benchmark configuration'):
            session.save_config(SessionConfig(session_id="20260101", topic=research.topic, topic_original=research.topic,
                                topic_slug="ideabench", timestamp=session.clock.for_step(1), pico=research.pico, field_type="biomedical"))
        papers = [Paper(id=f"paper_{i:03d}", title=r["title"], abstract=r["abstract"], year=r["year"],
                        journal=r.get("venue"), doi=r.get("doi"), citation_count=r["citationCount"],
                        sources_found_in=["benchmark"], found_via="frozen low-resource references") for i, r in enumerate(refs, 1)]
        raw = RawPapers(session_id="20260101", topic=research.topic, search_timestamp=session.clock.for_step(2), papers=papers,
                        search_summary=SearchSummary(total_raw_results=len(papers), after_dedup=len(papers), snowball_additions=0,
                        final_count=len(papers), sources={"benchmark": len(papers)}, queries={}, doi_coverage="unknown", hub_papers=[], clusters=[]))
        with stage_span(session.dir, 'Step 2 frozen reference injection'):
            dump_json(session.path("step2_raw_papers.json"), raw.model_dump())
        session.record_checkpoint(1, "auto", {"approved": True}, "Benchmark shared reference-only context")
    ctx = Context(session, cfg, llm_backend=backend)
    ctx.ui_print = say
    try:
        for step, func in ((3, s3_screen.run), (4, _export), (6, s6_sota.run), (7, s7_gaps.run)):
            if session.step_done(step):
                continue
            say(f"    P2 Step {step}")
            with stage_span(session.dir, f'Step {step}'):
                func(ctx)
            session.set_current_step(step)
            if step == 3:
                session.record_checkpoint(2, "auto", {"include": []}, "Keep screening decisions; no judge-based rescue")
                if not load_json(session.path("step3_shortlist.json"))["papers"]:
                    raise RuntimeError("P2 screening retained no papers")
            if step == 4:
                with stage_span(session.dir, 'Step 5 abstract-only adapter'):
                    write_text(session.path("step5_full_text/_access_log.md"), "Benchmark abstract-only: no retrieval beyond the frozen references.\n")
        gaps = load_json(session.path("step7_gaps.json"))["gaps"]
        slots = gap_slots(gaps)
        n = len(slots)
        valid_keys = set(load_json(session.path("step4_citation_keys.json"))[p['id']]['key']
                         for p in load_json(session.path("step3_shortlist.json"))["papers"])
        if len({g['gap']['title_en'].strip().casefold() for g in gaps}) != n:
            raise ValueError("P2 returned duplicate gap titles")
        for gap in gaps:
            evidence = gap['gap']['supporting_evidence']
            if any(e['citation_key'] not in valid_keys for e in evidence) or len({e['citation_key'] for e in evidence}) < 2:
                raise ValueError("each P2 gap must cite at least two distinct supplied papers")
        outputs = []
        for i, gap in enumerate(slots, 1):
            branch = Session(root / f"spec_{i:02d}", cfg)
            branch.dir.mkdir(exist_ok=True)
            if not branch.has("step8_hypothesis.json"):
                for path in session.dir.iterdir():
                    if path.is_file() and path.name.startswith(("step0_", "step3_", "step4_", "step6_", "step7_")):
                        shutil.copy2(path, branch.dir / path.name)
                constraint = "Propose a single main research study, grounded in the locked gap. Do not present proposed findings as established results."
                branch.record_checkpoint(3, "auto", {"lock": gap, "drop": [], "constraint": constraint}, f"One gap per slot {i}/{n}")
                branch_ctx = Context(branch, cfg, llm_backend=backend)
                try:
                    say(f"    P2 Step 8 slot {i}/{n} ({gap})")
                    with stage_span(branch.dir, 'Step 8 generator'):
                        s8_hypothesis.run(branch_ctx)
                finally:
                    branch_ctx.close()
            # Compression is by generator; the evaluation judge never feeds P2.
            spec = load_json(branch.path("step8_hypothesis.json"))["spec"]
            english = {k: v for k, v in spec.items() if not k.endswith("_zh") and k not in ("journals", "submission_strategy_en", "journal_selection_criteria_en")}
            with stage_span(branch.dir, 'P2 idea compression'):
                idea = extract_target_idea(ctx.llm, json.dumps(english, ensure_ascii=False), step=81)
            outputs.append({"idea": idea, "gap_id": gap, "spec_path": f"spec_{i:02d}/step8_hypothesis.json"})
        Ideas(ideas=[o["idea"] for o in outputs])
        dump_json(root / "allocation.json", {"rule": "one spec per distinct ranked gap; no judge selection", "slots": slots})
        return outputs
    finally:
        ctx.close()


def summarize(records: list[dict], task_ids: list[str], metrics: list[str]):
    by = {(r["paperId"], r["protocol"]): r for r in records}
    complete = [pid for pid in task_ids if all((pid, p) in by and by[pid, p].get("status") == "ok" for p in ("P1", "P2"))
                and by[pid, 'P1']['n'] == by[pid, 'P2']['n']]
    scores = {p: {q: (sum(by[pid, p]["scores"][q] for pid in complete) / len(complete) if complete else None) for q in metrics} for p in ("P1", "P2")}
    counts = {pid: by[pid, 'P2']['n'] for pid in complete}
    strata = {}
    for n in sorted(set(counts.values())):
        group = [pid for pid in complete if counts[pid] == n]
        group_scores = {p: {q: sum(by[pid,p]['scores'][q] for pid in group)/len(group)
                                                for q in metrics} for p in ('P1', 'P2')}
        strata[str(n)] = {"m": len(group), "insight_scores": group_scores,
                          "P2_minus_P1": {q: group_scores['P2'][q]-group_scores['P1'][q] for q in metrics}}
    return {"m_requested": len(task_ids), "m_paired": len(complete), "n_by_target": counts, "stratified_by_n": strata, "paired_target_ids": complete,
            "excluded_target_ids": [pid for pid in task_ids if pid not in complete], "insight_scores": scores,
            "P2_minus_P1": {q: (scores["P2"][q] - scores["P1"][q] if complete else None) for q in metrics},
            "status": "complete" if len(complete) == len(task_ids) else "incomplete"}


def score_p2_rubrics(folder: Path, config: Config, *, judge_backend=None, say=print):
    """Absolute evaluation is independent of relative ranking and coherence gates."""
    from evaluation.step08 import run_step8_rubric
    branches = sorted((folder / 'P2').glob('spec_*'))
    results = []
    for branch in branches:
        if not (branch / 'step8_hypothesis.json').exists():
            continue
        try:
            for required in ('step0_session_config.json', 'step3_shortlist.json', 'step7_gaps.json'):
                if not (branch / required).exists():
                    raise FileNotFoundError(f'missing evaluation context: {required}')
            if not any((branch / f).exists() for f in ('step6_sota.json', 'step6_sota_review.md')):
                raise FileNotFoundError('missing SOTA context')
            say(f'    Absolute rubric {branch.name}')
            # Only an explicit imported-results manifest authorizes preserving old-version scores.
            inherited = folder.parents[1] / 'inherited_results.json'
            preserve = inherited.exists() and folder.name in load_json(inherited)['target_ids']
            if preserve and (branch / 'step8_rubric_scores.json').exists():
                payload = load_json(branch / 'step8_rubric_scores.json')
            else:
                with stage_span(branch, 'Step 8 rubric judge'):
                    payload = run_step8_rubric(Session(branch, config), config, judge_backend=judge_backend, say=say)
            results.append({'spec_path': str(branch.relative_to(folder)).replace('\\', '/'), 'status': 'ok',
                            'means': payload['means'], 'ratings': payload['ratings']})
        except Exception as exc:
            results.append({'spec_path': str(branch.relative_to(folder)), 'status': 'failed', 'error': f'{type(exc).__name__}: {exc}'})
            say(f'    Absolute rubric FAILED: {exc}')
    dump_json(folder / 'P2_rubric_summary.json', {'specs': results})
    return results


def costs(out: Path):
    """Aggregate observed successful call ledgers; keep retries/cache explicit."""
    from evaluation.step08.metrics import METRICS as RUBRIC_METRICS
    rubric_tags = {f'rubric:{m.id}' for m in RUBRIC_METRICS}
    totals = {}
    for path in out.rglob('*ledger.jsonl'):
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line:
                continue
            entry = json.loads(line)
            prompt = entry['prompt']
            if prompt == 's8_rubric' and entry.get('tag') not in rubric_tags:
                continue  # Historical removed metrics are not this experiment's rubric cost.
            group = ('rubric' if prompt == 's8_rubric' else 'ranking' if prompt in ('ideabench_rank', 'ideabench_coherence')
                     else 'P1_generation' if prompt == 'ideabench_generate' else 'shared_context' if prompt == 'ideabench_context'
                     else 'P2_generation')
            total = totals.setdefault(group, {'recorded_calls': 0, 'cache_hits': 0, 'validation_attempts': 0,
                                              'input_tokens': 0, 'output_tokens': 0, 'wall_seconds': 0.0})
            total['recorded_calls'] += 1
            total['cache_hits'] += int(entry.get('cache_hit', False))
            if not entry.get('cache_hit'):
                total['validation_attempts'] += entry.get('validation_attempts', 1)
            for key in ('input_tokens', 'output_tokens'):
                total[key] += (entry.get('usage') or {}).get(key, 0)
            total['wall_seconds'] += entry.get('wall_seconds', 0)
    return {'by_stage': totals, 'note': 'Observed successful-call ledgers, including resumed cache reads. Failed calls and earlier validation-attempt tokens may be absent; not a complete billing estimate.'}


def run_experiment(dataset: Path, out: Path, config: Config, *, limit: int | None = None,
                   phase: str = "all", metrics: list[str] | None = None, seed: int = 0, rubric: bool = False,
                   generator_backend=None, judge_backend=None, say=print):
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    if phase not in ("all", "generate", "rank", "rubric"):
        raise ValueError("unknown phase")
    metrics = metrics or ["novelty", "feasibility"]
    if not metrics or any(q not in METRICS for q in metrics):
        raise ValueError("unknown metric")
    judge_cfg = config.resolve_judge_llm()
    if config.llm.model.removesuffix(":latest").casefold() == judge_cfg.model.removesuffix(":latest").casefold():
        raise ValueError("generator and judge must differ, including Ollama aliases")
    _, tasks = _load_tasks(Path(dataset), limit)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    prompts = ["ideabench_context", "ideabench_generate", "ideabench_coherence", "ideabench_rank", "ideabench_extract_idea",
               "s3_criteria", "s3_score", "s6_note", "s6_sota", "s7_gaps", "s8_hypothesis"]
    if rubric or phase == 'rubric':
        prompts.append('s8_rubric')
    from evaluation.step08.metrics import METRICS as RUBRIC_METRICS, anchors_for
    contract = {"protocol_version": "1.2.0", "dataset_sha256": sha256_obj(tasks), "n_rule": "actual P2 gap count, matched by P1 per task", "seed": seed,
                "metrics": metrics, "generator": config.llm.model_dump(), "judge": judge_cfg.model_dump(),
                "screening": config.screening.model_dump(), "gaps": config.gaps.model_dump(),
                "prompts": {p: sha256_obj(load_prompt(p).__dict__) for p in prompts},
                "rank_permutations": "n_i + 1 balanced rotations", "P2_allocation": "one spec per distinct actual gap",
                "P2_fulltext": "abstract-only, no external retrieval", "rubric": rubric or phase == 'rubric',
                "rubric_metrics": [m.id for m in RUBRIC_METRICS],
                "rubric_anchors_sha256": sha256_obj({m.id: {field: anchors_for(m.id, field) for field in ('biomedical', 'cs_engineering')}
                                                    for m in RUBRIC_METRICS}),
                "provenance": "https://arxiv.org/abs/2411.02429; adapted Figures 1/2; same extraction prompt",
                "limitations": ["Variable n_i differs from original fixed-n IdeaBench; report n-stratified scores",
                                "Step 4 uses title/year and Anonymous BibTeX when frozen refs lack authors",
                                "Single judge not calibrated to human ratings", "Target extraction and ranking share judge model",
                                "Model cutoff registry is supplied metadata, not independently verified contamination proof",
                                "OpenAlex source/type mapping differs from S2; no background-section filter"]}
    contract_path = out / "experiment_manifest.json"
    if contract_path.exists() and load_json(contract_path) != contract:
        raise ValueError("run contract changed: use a new output directory")
    dump_json(contract_path, contract)
    cache = Cache(out / ".cache", config.cache_mode)
    gen = LLMClient(config.llm, cache, Ledger(out / ".cache/llm/generator_ledger.jsonl"), backend=generator_backend, api_key=config.api.anthropic_api_key)
    judge = LLMClient(judge_cfg, cache, Ledger(out / ".cache/llm/judge_ledger.jsonl"), backend=judge_backend, api_key=config.api.anthropic_api_key)
    errors = []
    if phase in ("all", "generate"):
        for index, (pid, refs, _) in enumerate(tasks, 1):
            say(f"[{index}/{len(tasks)}] generate {pid}")
            folder = out / "tasks" / _safe_dir_name(pid)
            folder.mkdir(parents=True, exist_ok=True)
            blob = reference_blob(refs)
            context_path = folder / "context.json"
            if context_path.exists():
                research = ResearchContext.model_validate(load_json(context_path))
            else:
                with stage_span(folder, 'Shared benchmark context'):
                    research = gen.structured("ideabench_context", ResearchContext, {"references": blob}, step=80, tag=pid)
                dump_json(context_path, research.model_dump())
            for protocol in ("P2", "P1"):
                path = folder / f"{protocol}_ideas.json"
                if path.exists():
                    say(f"    {protocol} resumed from saved ideas")
                    continue
                try:
                    if protocol == "P1":
                        n = load_json(folder / 'P2_ideas.json')['n']
                        with stage_span(folder, 'P1 generator'):
                            generated = gen.structured("ideabench_generate", ideas_schema(n), {"context": research.model_dump_json(), "references": blob, "n": n}, step=81, tag=pid)
                        values = [{"idea": v} for v in generated.ideas]
                    else:
                        values = generate_p2(folder / "P2", refs, research, config, say, generator_backend)
                        n = len(values)
                    dump_json(path, {"paperId": pid, "protocol": protocol, "model": config.llm.model, "n": n, "ideas": values})
                    say(f"    {protocol} saved {n} ideas")
                except Exception as exc:
                    error = {"paperId": pid, "protocol": protocol, "phase": "generate", "error": f"{type(exc).__name__}: {exc}"}
                    errors.append(error)
                    dump_json(folder / f"{protocol}_error.json", error)
                    say(f"    {protocol} FAILED: {exc}")
            dump_json(out / "errors.json", errors)
        if phase == "generate":
            result = {"phase": phase, "m_requested": len(tasks), "generation_errors": errors}
            dump_json(out / "generation_summary.json", result)
            return result
    records, absolute = [], {}
    if rubric or phase == 'rubric':
        for pid, _, _ in tasks:
            folder = out / 'tasks' / _safe_dir_name(pid)
            absolute[pid] = score_p2_rubrics(folder, config, judge_backend=judge_backend, say=say)
            dump_json(out / 'rubric_summary.json', {'by_target': absolute})
        successful = [r for values in absolute.values() for r in values if r['status'] == 'ok']
        failed = [r for values in absolute.values() for r in values if r['status'] != 'ok']
        target_means = {pid: sum(r['means']['overall'] for r in values if r['status'] == 'ok') /
                        sum(r['status'] == 'ok' for r in values) for pid, values in absolute.items() if any(r['status'] == 'ok' for r in values)}
        rubric_summary = {'by_target': absolute, 'n_specs_scored': len(successful), 'n_specs_failed': len(failed),
                          'n_targets_scored': len(target_means), 'target_overall_means': target_means,
                          'overall_target_weighted': sum(target_means.values())/len(target_means) if target_means else None,
                          'overall_spec_weighted': sum(r['means']['overall'] for r in successful)/len(successful) if successful else None,
                          'note': 'Rubric scores are descriptive P2 diagnostics, independent of relative ranking eligibility.'}
        dump_json(out / 'rubric_summary.json', rubric_summary)
        if phase == 'rubric':
            dump_json(out / 'costs.json', costs(out))
            return {'phase': 'rubric', 'n_specs_scored': len(successful), 'n_specs_failed': len(failed)}
    for index, (pid, refs, target) in enumerate(tasks, 1):
        say(f"[{index}/{len(tasks)}] rank {pid}")
        folder = out / "tasks" / _safe_dir_name(pid)
        for protocol in ("P1", "P2"):
            result_path = folder / f"{protocol}_scores.json"
            if result_path.exists() and load_json(result_path).get('status') == 'ok':
                records.append(load_json(result_path))
                continue
            record = {"paperId": pid, "protocol": protocol, "status": "failed"}
            try:
                payload = load_json(folder / f"{protocol}_ideas.json")
                n = payload['n']
                generated = ideas_schema(n)(ideas=[o["idea"] for o in payload["ideas"]]).ideas
                record['n'] = n
                rank_schema = create_model(f"Rank{n+1}", __base__=Ranking, order=(list[int], Field(min_length=n+1, max_length=n+1)))
                texts = [target] + generated
                permutations = balanced_orders(n+1, seed + int(sha256_obj(pid)[:8], 16))
                gate_order = permutations[0]
                anonymous = "\n\n".join(f"Hypothesis {i}: {texts[j]}" for i, j in enumerate(gate_order, 1))
                with stage_span(folder, f'{protocol} coherence judge'):
                    gate = judge.structured("ideabench_coherence", Coherence, {"ideas": anonymous, "count": n+1}, step=82, tag=f"{pid}:{protocol}:coherence")
                if any(i > n+1 for i in gate.failed_ids):
                    raise ValueError("coherence judge returned an unknown ID")
                dump_json(folder / f"{protocol}_coherence.json", {**gate.model_dump(), "display_to_internal": gate_order})
                if gate.failed_ids:
                    raise ValueError("coherence gate failed; retained for audit, excluded from paired scoring")
                scores, rankings = {}, {}
                for q in metrics:
                    runs = []
                    for turn, order in enumerate(permutations):
                        anonymous = "\n\n".join(f"Hypothesis {i}: {texts[j]}" for i, j in enumerate(order, 1))
                        with stage_span(folder, f'{protocol} {q} ranking judge'):
                            rank = judge.structured("ideabench_rank", rank_schema, {"metric": q, "definition": METRICS[q],
                                                    "references": reference_blob(refs), "ideas": anonymous, "count": n+1}, step=83, tag=f"{pid}:{protocol}:{q}:{turn}")
                        target_display = order.index(0)+1
                        target_rank = rank.order.index(target_display)+1
                        runs.append({"display_to_internal": order, "order": rank.order, "rationale": rank.rationale,
                                     "target_rank": target_rank, "score": insight_score(target_rank, n)})
                        dump_json(folder / f"{protocol}_{q}_rankings.json", runs)
                    scores[q] = sum(r["score"] for r in runs) / len(runs)
                    rankings[q] = runs
                    say(f"    {protocol} {q}: {scores[q]:.3f}")
                record.update(status="ok", scores=scores, rankings=rankings)
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
                say(f"    {protocol} rank FAILED: {exc}")
            dump_json(result_path, record)
            records.append(record)
        summary = summarize(records, [t[0] for t in tasks], metrics)
        dump_json(out / "summary.json", summary)
    report = [f"IdeaBench-style evaluation: {summary['status']}", f"Paired tasks: {summary['m_paired']}/{summary['m_requested']}; n varies with actual gap count",
              "Scores use only the same complete target pairs for both protocols. Higher means more generated ideas ranked above the target."]
    for q in metrics:
        report.append(f"{q}: P1={summary['insight_scores']['P1'][q]}, P2={summary['insight_scores']['P2'][q]}, P2-P1={summary['P2_minus_P1'][q]}")
    report += ["", "Limitations:"] + contract["limitations"]
    if rubric:
        summary['rubric'] = {'n_specs_scored': rubric_summary['n_specs_scored'], 'n_specs_failed': rubric_summary['n_specs_failed'],
                             'n_targets_scored': rubric_summary['n_targets_scored'], 'summary_path': 'rubric_summary.json'}
        dump_json(out / 'summary.json', summary)
    dump_json(out / 'costs.json', costs(out))
    write_text(out / "report.md", "\n\n".join(report))
    return summary
