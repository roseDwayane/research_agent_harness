"""Run production fusion and planning on frozen IdeaBench references."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from evaluation.litsearch.adapter import _hashes, write_json
from harness.config import HarnessConfig
from harness.context import RunContext
from harness.executors import ExecResult, RecipeExecutor
from harness.pipeline import PipelineAgent
from harness.steps import GenerationAgent
from harness.recipes import load as load_recipes
from harness.skill import Skill
from ideate_v2.registry import Registry


def offline_recipes():
    """Keep production Units and checks, but deconstruct one frozen abstract per call."""
    recipes = load_recipes()
    for step in recipes['A7.D'].phases['main']:
        if step.kind == 'run' and 'decon-plan' in step.spec['run']:
            step.spec['run'] += ' --abs-size 1'
    return recipes


def prepare(rd: Path, refs: list[dict], max_questions: int) -> None:
    if len(refs) != 5 or len({r['paperId'] for r in refs}) != 5:
        raise ValueError('exactly five distinct references required')
    rd.mkdir(parents=True, exist_ok=True)
    frozen = rd / '_state' / 'ideabench' / 'references.json'
    payload = {'references': refs, 'max_questions': max_questions}
    if frozen.exists():
        if json.loads(frozen.read_text(encoding='utf-8')) != payload:
            raise ValueError('frozen references changed; use a new output directory')
        return
    write_json(frozen, payload)
    now = datetime.now(timezone.utc).isoformat()
    topic = rd / 'topic.md'
    topic.write_text('# Biomedical research ideas from five fixed references\n', encoding='utf-8')
    write_json(rd / 'step0_session_config.json', {
        'topic': 'Biomedical research ideas from five fixed references', 'topic_file': topic.name,
        'depth': 'quick', 'timestamp': now, 'max_num_generations': max_questions,
        'protocol': {'review_type': 'scoping', 'framework': {'name': 'PCC'},
                     'axes': [{'id': 'C1', 'terms': ['biomedical research']}], 'timeframe': '1900-2026',
                     'languages': ['en']}, 'queries': [], 'anchor_terms': [], 'known_items': [],
        'sources': ['IdeaBench'], 'target_venues': [], 'expert_domain': 'biomedical research',
        'local_environment': {'artefacts': [], 'cached_data': [], 'packages_present': [], 'packages_missing': []}})
    papers = [{**r, 'id': r['paperId'], 'citation_key': f'anon{r.get("year") or "nd"}{chr(96+i)}',
               'access_level': 'abstract-only', 'source': 'IdeaBench'} for i, r in enumerate(refs, 1)]
    write_json(rd / 'step2_raw_papers.json', {'papers': papers, 'search_summary': {'offline': True}})
    write_json(rd / 'step3_shortlist.json', {'papers': papers, 'summary': {'included': 5}})
    write_json(rd / 'step3_bibliometrics.json', {'papers': {}})
    write_json(rd / 'step3_gate.json', {'excluded': {}})
    write_json(rd / 'screening_scores.json', {'scores': [
        {'id': p['id'], 'rel': 5, 'qual': 3, 'rationale': 'Frozen IdeaBench reference; offline screening.'}
        for p in papers]})
    write_json(rd / 'step2b_snowball_papers.json', {'rounds': [], 'caveats': [], 'offline': True})
    write_json(rd / 'step3_tier1_candidates.json', {'candidates': [], 'top_ups': 0})
    write_json(rd / 'step5_fetch_log.json', {'attempts': [], 'offline': True})
    (rd / 'step5_full_text').mkdir(exist_ok=True)
    (rd / 'step5_full_text' / '_access_log.md').write_text('Abstract-only offline inputs.\n', encoding='utf-8')
    (rd / 'step3_missing_pdfs.md').write_text('All references are abstract-only.\n', encoding='utf-8')
    (rd / 'step4_citation_keys.jsonl').write_text(''.join(json.dumps({'id': p['id'], 'key': p['citation_key']}) + '\n' for p in papers), encoding='utf-8')
    (rd / 'step4_citation_keys.md').write_text('\n'.join(p['citation_key'] for p in papers) + '\n', encoding='utf-8')
    (rd / 'step4_references.bib').write_text(''.join(f"@article{{{p['citation_key']}, title={{{p['title']}}}}}\n" for p in papers), encoding='utf-8')
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    from it_export import log_path, shortlist_basis
    log = log_path(rd)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(''.join(json.dumps({'id': p['id'], 'key': p['citation_key']}) + '\n' for p in papers), encoding='utf-8')
    from ideate_v2.jsonio import sha256_file
    write_json(rd / 'step4_bib_metadata.json', {'schema': 'ideate-bib/1', 'offline': True,
        'entries': {p['citation_key']: {'id': p['id'], 'source': 'IdeaBench'} for p in papers},
        'basis': {'log': sha256_file(log), 'shortlist': shortlist_basis(rd)}})
    write_json(rd / 'search_caveats.json', {'schema': 'ideate-search-caveats/1', 'at': now, 'caveats': [], 'must_disclose': []})
    write_json(rd / 'fulltext_caveats.json', {'schema': 'ideate-fulltext-caveats/1', 'at': now, 'caveats': [], 'must_disclose': []})
    reg = Registry.load()
    events = []
    for unit in ('A1.p', 'A1.q', 'A1.v', 'A1.e', 'A2.s', 'A2.m', 'A2.c', 'A3.b', 'A3.g',
                 'A3', 'A5', 'A4.k', 'A4.b', 'A6.d', 'A6.c'):
        inputs = _hashes(reg, rd, unit, 'reads')
        events.extend(({'ev': 'begin', 'unit': unit, 'inst': '-', 'at': now, 'inputs': inputs},
                       {'ev': 'done', 'unit': unit, 'inst': '-', 'at': now, 'inputs': inputs,
                        'outputs': _hashes(reg, rd, unit, 'owns'), 'counts': {}, 'degraded': [],
                        'tool': 'ideabench-frozen-adapter'}))
    ledger = rd / '_state' / 'ledger.jsonl'
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')


def run_p2(task_dir: Path, refs: list[dict], model, *, max_questions: int, say=print) -> list[dict]:
    rd = task_dir / 'P2' / 'research'
    prepare(rd, refs, max_questions)
    cfg = HarnessConfig(worker='ollama', model=model.model, ollama_url=model.url,
                        num_ctx=model.num_ctx, num_predict=model.num_predict,
                        think=model.think,
                        temperature=model.temperature, worker_timeout_s=model.timeout_s,
                        depth='quick', max_num_generations=max_questions)
    reg = Registry.load()
    ctx = RunContext(reg, cfg, Skill(cfg), rd, rd / 'topic.md', say=say)
    executor = RecipeExecutor()
    class OfflineFinalize:
        def execute(self, ctx, unit, recipe, phase, gen, attempt):
            question = json.loads((ctx.rd / f'gen_{gen}' / 'question.json').read_text(encoding='utf-8'))
            config_path = ctx.rd / 'step0_session_config.json'
            config = json.loads(config_path.read_text(encoding='utf-8'))
            config.setdefault('consumed', []).append({'question': question['id'], 'gen': gen})
            write_json(config_path, config)
            gd = ctx.rd / f'gen_{gen}'
            (gd / 'step8_journal_recommendations.md').write_text('Offline benchmark: journal lookup omitted.\n', encoding='utf-8')
            return ExecResult(True)
    pipe = PipelineAgent(reg, offline_recipes(), lambda unit: OfflineFinalize() if unit == 'B6' else executor)
    fusion = pipe.run(ctx, 'F1', 'F4')
    if fusion['failed']:
        raise RuntimeError(f"production pipeline failed; inspect {ctx.state_dir / 'summary.json'}")
    generations, failed = pipe._stage_b(ctx)
    if failed:
        raise RuntimeError(f'production Stage B failed; inspect {ctx.state_dir}')
    ideas = []
    for generation in generations:
        k = generation.gen
        path = rd / f'gen_{k}' / 'idea.json'
        if generation.status in ('finalized', 'finalized-with-doubt') and path.is_file():
            ideas.append({'question_id': generation.question, 'path': str(path.relative_to(task_dir)),
                          'idea': json.loads(path.read_text(encoding='utf-8'))})
        elif generation.status != 'abandoned':
            raise RuntimeError(f'production generation {k} failed; inspect {ctx.state_dir}')
    write_json(task_dir / 'P2_ideas.json', {'protocol': 'P2', 'n': len(ideas), 'ideas': ideas})
    return ideas
