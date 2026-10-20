"""Observed request costs and elapsed stage spans, including failed attempts."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import time
import csv


@contextmanager
def stage_span(folder: Path, stage: str):
    started = time.perf_counter()
    row = {'stage': stage, 'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'ok'}
    try:
        yield
    except BaseException as exc:
        row.update(status='failed', error_type=type(exc).__name__)
        raise
    finally:
        row.update(ended_at=datetime.now(timezone.utc).isoformat(), wall_seconds=time.perf_counter()-started)
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / 'stage_times.jsonl').open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(row) + '\n')


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def usage_report(out: Path):
    """Attempt events supersede successful-call totals; never count both."""
    by = {}
    paths = set(out.rglob('*ledger.jsonl'))
    paths.update(p.with_name(p.name.replace('_attempts.jsonl', '.jsonl')) for p in out.rglob('*ledger_attempts.jsonl'))
    for path in sorted(paths):
        events_path = path.with_name(path.stem + '_attempts.jsonl')
        events = _rows(events_path) if events_path.exists() else []
        tracked = {e['call_id'] for e in events}
        historical = [r for r in (_rows(path) if path.exists() else []) if r.get('call_id') not in tracked]
        rows = [(r, 'attempt') for r in events] + [(r, 'historical_success') for r in historical]
        for r, origin in rows:
            relative = path.relative_to(out).parts
            target = relative[1] if relative[0] == 'tasks' else (r.get('tag', '').split(':')[0] or 'shared')
            prompt = r.get('prompt', 'unknown')
            role = 'judge' if prompt in ('s8_rubric', 'ideabench_rank', 'ideabench_coherence') else 'generator'
            key = (target, str(r.get('step')), prompt, role)
            item = by.setdefault(key, {'target': target, 'step': r.get('step'), 'prompt': prompt, 'role': role,
                'model': r.get('model'), 'input_tokens': 0, 'output_tokens': 0, 'wall_seconds': 0,
                'requests': 0, 'cache_hits': 0, 'unknown_usage_requests': 0, 'failed_requests': 0,
                'historical_success_records': 0})
            if r.get('cache_hit'):
                item['cache_hits'] += 1
                continue
            item['requests'] += 1
            item['historical_success_records'] += int(origin == 'historical_success')
            item['wall_seconds'] += r.get('wall_seconds', 0)
            item['failed_requests'] += int(r.get('status') == 'failed')
            usage = r.get('usage')
            if usage is None or (origin == 'attempt' and not r.get('usage_known')) or not usage:
                item['unknown_usage_requests'] += 1
            else:
                for k in ('input_tokens', 'output_tokens'):
                    item[k] += usage.get(k, 0)
    spans = [{'path': str(p.relative_to(out)), **r} for p in out.rglob('stage_times.jsonl') for r in _rows(p)]
    report = {'generated_at': datetime.now(timezone.utc).isoformat(), 'by_target_stage_role': list(by.values()),
              'stage_elapsed_spans': spans,
              'note': 'Known observed tokens only. Historical records omit failed requests and earlier validation attempts. '
                      'Unknown usage is counted separately; request seconds differ from end-to-end stage seconds. '
                      'Step 1 is replaced by shared benchmark context; Step 2 injects frozen references; Step 5 is abstract-only. '
                      'Inherited targets retain historical prompt versions and are not a uniform-version experiment.'}
    inherited_path = out / 'inherited_results.json'
    inherited = set(json.loads(inherited_path.read_text(encoding='utf-8'))['target_ids']) if inherited_path.exists() else set()
    target_dirs = sorted(p for p in (out / 'tasks').glob('*') if p.is_dir())
    report['targets'] = [{'target': p.name, 'cohort': 'historical5' if p.name in inherited else 'continuation15',
        'p1_generated': (p / 'P1_ideas.json').exists(), 'p2_generated': (p / 'P2_ideas.json').exists(),
        'n_specs': len(list(p.glob('P2/spec_*/step8_hypothesis.json'))),
        'paired_rank_complete': all((p / f'{protocol}_scores.json').exists() and
            json.loads((p / f'{protocol}_scores.json').read_text(encoding='utf-8'))['status'] == 'ok' for protocol in ('P1', 'P2'))}
        for p in target_dirs]
    totals = {}
    for row in by.values():
        key = (row['role'], row['prompt'])
        total = totals.setdefault(key, {'role': key[0], 'prompt': key[1], 'input_tokens': 0, 'output_tokens': 0,
            'wall_seconds': 0, 'requests': 0, 'unknown_usage_requests': 0, 'failed_requests': 0})
        for column in ('input_tokens', 'output_tokens', 'wall_seconds', 'requests', 'unknown_usage_requests', 'failed_requests'):
            total[column] += row[column]
    report['totals_by_role_prompt'] = list(totals.values())
    report['n_targets_present'] = len(target_dirs)
    report['n_paired_complete'] = sum(t['paired_rank_complete'] for t in report['targets'])
    (out / 'usage_summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if by:
        with (out / 'usage_by_target_step.csv').open('w', newline='', encoding='utf-8-sig') as fh:
            writer = csv.DictWriter(fh, fieldnames=list(next(iter(by.values()))))
            writer.writeheader()
            writer.writerows(by.values())
    return report
