"""Uniform query-only Step 1 initialization and fixed BM25 top100 Step 3, all 597.

Resume markers and request caches survive interruptions. No API search, gold
conditioning, or reuse of the earlier 80 PICO/specs. Single worker for Ollama.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path

import httpx

from scholar_research import __file__ as engine_file
from scholar_research.config import Config
from scholar_research.llm.client import OllamaBackend
from scholar_research.schemas.paper import Paper, RawPapers, SearchSummary
from scholar_research.session import Session
from scholar_research.steps.base import Context
from scholar_research.steps.s1_init import run as initialize
from scholar_research.steps.s3_screen import run as screen
from scholar_research.utils import slugify
from .official_bm25 import aggregate, now, pack_metrics, read_jsonl, sha, signature, sort_ids


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temporary.replace(path)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


class ServiceStopped(BaseException):
    pass


class MonitoredBackend(OllamaBackend):
    consecutive = 0

    def __init__(self, cfg):
        super().__init__(cfg)
        self._client.close()
        self._client = httpx.Client(base_url=cfg.base_url.rstrip('/'), timeout=httpx.Timeout(cfg.request_timeout, connect=10),
                                    transport=httpx.HTTPTransport(local_address='0.0.0.0'))

    def __call__(self, **kwargs):
        observer = self.attempt_observer
        def monitored(event):
            if observer:
                observer(event)
            MonitoredBackend.consecutive = MonitoredBackend.consecutive + 1 if event['status'] == 'failed' else 0
            if MonitoredBackend.consecutive >= 3:
                raise ServiceStopped('Three consecutive transport failures; stopping rather than repeating failed calls.')
        self.attempt_observer = monitored
        try:
            return super().__call__(**kwargs)
        finally:
            self.attempt_observer = observer


def task_rows(queries, baseline):
    if len(queries) != 597 or len(baseline) != 597:
        raise ValueError('Expected completed official 597-query baseline')
    tasks = []
    for i, (q, b) in enumerate(zip(queries, baseline), 1):
        if signature(q) != signature(b):
            raise ValueError('Baseline query ordering mismatch')
        candidates = b['retrieved'][:100]
        if len(candidates) != 100 or len(set(candidates)) != 100:
            raise ValueError('Exactly 100 unique candidates required')
        tasks.append({**q, 'qid': f'official_{i:04d}', 'official_query_index': i-1, 'bm25_top100': candidates})
    return tasks


def frozen_hashes(folder, names):
    return {name: sha(folder/name) for name in names}


def verify(folder, hashes):
    for name, expected in hashes.items():
        if sha(folder/name) != expected:
            raise ValueError('Frozen file changed: '+str(folder/name))


def usage(folder):
    path = folder/'.cache/llm/ledger_attempts.jsonl'
    events = read_jsonl(path) if path.exists() else []
    result = {}
    for step in (1, 3):
        xs = [e for e in events if e.get('step') == step]
        result[str(step)] = {
            'input_tokens': sum((e.get('usage') or {}).get('input_tokens', 0) for e in xs),
            'output_tokens': sum((e.get('usage') or {}).get('output_tokens', 0) for e in xs),
            'request_wall_seconds': sum(e.get('wall_seconds', 0) for e in xs),
            'unknown_failed_attempts': sum(e.get('status') == 'failed' and e.get('usage') is None for e in xs),
            'attempts': len(xs),
        }
    return result


def summarize(rows):
    def pack(xs):
        return {kind: aggregate([{'metrics':r['metrics'][kind]} for r in xs]) for kind in ('bm25','relevance','composite')}
    completed = [r for r in rows if r['completed']]
    result = {'n':len(rows), 'initialized':sum(r['initialized'] for r in rows), 'completed':len(completed),
              'overall':pack(rows), 'hit_only':pack([r for r in rows if r['hit']]),
              'groups':{}, 'usage':{}, 'stage_wall_seconds':{},
              'note':'Model metrics are provisional until all 597 finish; pending/failed ranks stay zero. Gold denominator is complete. No gold inputs to initialization/scoring.'}
    for split in ('inline','author'):
        for specific in (0,1):
            xs = [r for r in rows if r['query_set'].startswith('inline') == (split=='inline') and r['specificity']==specific]
            result['groups'][f'{split}_{"specific" if specific else "broad"}'] = pack(xs)
    for step in ('1','3'):
        result['usage'][step] = {key:sum(r['usage'][step][key] for r in rows) for key in ('input_tokens','output_tokens','request_wall_seconds','unknown_failed_attempts','attempts')}
        times = [r['stage_times'][step] for r in rows if r['stage_times'].get(step) is not None]
        result['stage_wall_seconds'][step] = {'defined_n':len(times),'total':sum(times),'mean':statistics.mean(times) if times else None}
    return result


def evaluate(out, tasks):
    rows=[]
    for t in tasks:
        folder=out/'sessions'/t['qid']
        init=read(folder/'prepared.json') if (folder/'prepared.json').exists() else None
        done=read(folder/'completed.json') if (folder/'completed.json').exists() else None
        rankings={'bm25':[str(c) for c in t['bm25_top100']]}
        if done:
            ps=read(folder/'step3_screening_all.json')['papers']
            rankings.update({k:sort_ids(ps,by=k)[0] for k in ('relevance','composite')})
        zero={'R@5':0,'R@20':0,'MRR':0,'nDCG@10':0,'R@100':0}
        rows.append({**t,'initialized':bool(init),'completed':bool(done),
                     'hit':bool(set(t['corpusids'])&set(t['bm25_top100'])),
                     'metrics':{k:pack_metrics(t['corpusids'],rankings[k]) if k in rankings else dict(zero) for k in ('bm25','relevance','composite')},
                     'usage':usage(folder), 'stage_times':{'1':init['initialization_wall_seconds'] if init else None,'3':done['wall_seconds'] if done else None}})
    result=summarize(rows)
    save(out/'comparison_summary.json',result)
    temporary=out/'comparison_per_question.jsonl.tmp'
    temporary.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    temporary.replace(out/'comparison_per_question.jsonl')
    lines=['# LitSearch 完整 597 題：统一初始化與 Step 3', '',
           f"初始化：{result['initialized']}/597；Step 3：{result['completed']}/597。", '',
           '所有題目重新從官方 query 執行相同 Step 1；固定官方 BM25 top-100，跳過 API 搜尋。原 80 題結果保留。']
    if result['completed']==597:
        lines += ['', '| 題型 | 排序 | 題數 | R@5 | R@20 | MRR | nDCG@10 |','| --- | --- | --- | --- | --- | --- | --- |']
        for name,values in result['groups'].items():
            for kind,v in values.items():
                lines.append(f"| {name} | {kind} | {v['n']} | {v['R@5']:.3f} | {v['R@20']:.3f} | {v['MRR']:.3f} | {v['nDCG@10']:.3f} |")
    else:
        lines += ['', '尚未全數完成，模型指標只保存於 JSON 作診斷，不把它們標成正式完整結果。']
    lines += ['', '| 階段 | 已知 input tokens | 已知 output tokens | 已知 request 時間（分鐘） | 用量未知的失敗 |','| --- | --- | --- | --- | --- |']
    for step,label in [('1','Step 1 初始化'),('3','Step 3 篩選')]:
        u=result['usage'][step]
        lines.append(f"| {label} | {u['input_tokens']:,} | {u['output_tokens']:,} | {u['request_wall_seconds']/60:.2f} | {u['unknown_failed_attempts']} |")
    lines += ['', '## 協定', '',
              '- 初始化輸入只有 query 與固定評估日期，不使用 gold IDs、gold paper 或 top-100 內容。',
              '- Step 1 產生的五條 queries 保存供追查，但本實驗 Step 2 固定使用原始官方 query 的 BM25 top-100，不執行它們。',
              '- Step 3 使用原 s3_criteria／s3_score prompt 與 0.50／0.30／0.20 權重；入選門檻 3.5，borderline 3.0。',
              '- 官方 corpus 的年份、作者、引用數與 venue 未補入；Step 3 摘要每篇最多 2500 字元，BM25 使用完整摘要。',
              '- 按 inline／author、broad／specific 分組；specific 主報 R@5／R@20，broad 主報 R@20。',
              '- 尚未完成的題目留在 overall 並計零；不依 gold 是否命中決定執行範圍。',
              '- 無標準答案的相關論文不自動視為負例；不宣稱 shortlist precision。',
              '- 已知 tokens 含重試；未知失敗用量另列，不視為零。cache 可重用，完成題目不再呼叫模型。']
    temporary=out/'report.md.tmp';temporary.write_text('\n'.join(lines)+'\n',encoding='utf-8');temporary.replace(out/'report.md')
    return result


def run(root,out,date):
    root=root.resolve();out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    manifest=read(root/'data_manifest.json')
    for filename,expected in manifest['sha256'].items():
        if sha(root/filename)!=expected:raise ValueError('Frozen official data changed')
    tasks=task_rows(read_jsonl(root/'queries.jsonl'),read_jsonl(root/'bm25_full597.jsonl'))
    corpus={int(p['corpusid']):p for p in read_jsonl(root/'corpus_title_abstract.jsonl')}
    cfg=Config.load(None)
    cfg.llm.model='qwen3.8';cfg.llm.provider='ollama';cfg.llm.temperature=0;cfg.llm.think=False
    cfg.llm.num_ctx=8192;cfg.llm.max_tokens=3072;cfg.llm.request_timeout=300
    cfg.screening.batch_size=12;cfg.screening.threshold_include=3.5;cfg.screening.threshold_borderline=3
    prompts=Path(engine_file).parent/'llm/prompts'
    contract={'dataset_manifest_sha256':sha(root/'data_manifest.json'),'baseline_sha256':sha(root/'bm25_full597.jsonl'),
              'llm':cfg.llm.model_dump(),'screening':cfg.screening.model_dump(),'transport':'IPv4-only',
              'evaluation_date':date,'n':597,'top_k':100,'uniform_initialization':'existing s1_init, all queries; no old80 reuse',
              'prompt_hashes':{n:sha(prompts/n) for n in ('s1_init.md','s3_criteria.md','s3_score.md')}}
    if (out/'run_contract.json').exists() and read(out/'run_contract.json')!=contract:
        raise ValueError('Frozen run configuration changed; use another output directory')
    save(out/'run_contract.json',contract)
    task_file=out/'tasks.jsonl'
    if task_file.exists() and read_jsonl(task_file)!=tasks:raise ValueError('Frozen tasks changed')
    if not task_file.exists():task_file.write_text(''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in tasks),encoding='utf-8')
    started=time.perf_counter();errors=[];active=None;phase='starting';message='';consecutive=0
    def progress(status='running'):
        initialized=sum((out/'sessions'/t['qid']/'prepared.json').exists() for t in tasks)
        completed=sum((out/'sessions'/t['qid']/'completed.json').exists() for t in tasks)
        save(out/'progress.json',{'status':status,'total':597,'initialized':initialized,'completed':completed,
             'active':active,'phase':phase,'message':message,'errors':errors,'updated_at':now(),
             'wall_seconds_this_invocation':time.perf_counter()-started})
    progress();evaluate(out,tasks)
    terminal='completed'
    try:
        for t in tasks:
            active=t['qid'];folder=out/'sessions'/active
            if (folder/'completed.json').exists():
                verify(folder,read(folder/'prepared.json')['inputs_sha256'])
                verify(folder,read(folder/'completed.json')['outputs_sha256']);continue
            session=Session(folder,cfg)
            if not (folder/'.state.json').exists():
                session.state.update(topic_original=t['query'],session_id=date.replace('-','')+'_'+active,topic_slug=slugify(t['query']))
                session.state['step_timestamps']={'1':date+'T00:00:00-07:00','3':date+'T00:00:00-07:00'}
                session.save_state()
            backend=MonitoredBackend(cfg.llm);ctx=Context(session,cfg,llm_backend=backend)
            def say(text):
                nonlocal message
                message=text;print(active+': '+text,flush=True);progress()
            ctx.ui_print=say
            try:
                if (folder/'prepared.json').exists():
                    verify(folder,read(folder/'prepared.json')['inputs_sha256'])
                else:
                    phase='step1_init';say('Initialize from query only');begin=time.perf_counter();initialize(ctx)
                    elapsed=time.perf_counter()-begin
                    sc=session.load_config();sc.current_step=2;session.save_config(sc)
                    papers=[Paper(id=str(cid),title=corpus[int(cid)]['title'],abstract=corpus[int(cid)]['abstract'],
                              sources_found_in=['LitSearch corpus_clean'],found_via='official_bm25') for cid in t['bm25_top100']]
                    raw=RawPapers(session_id=sc.session_id,topic=sc.topic,search_timestamp=now(),
                          search_summary=SearchSummary(total_raw_results=100,after_dedup=100,snowball_additions=0,final_count=100,
                            sources={'litsearch_official_bm25':100},queries={'litsearch_official_bm25':1},doi_coverage='0%',hub_papers=[],clusters=[]),papers=papers)
                    save(folder/'step2_raw_papers.json',raw.model_dump())
                    save(folder/'prepared.json',{'qid':active,'initialization_wall_seconds':elapsed,
                         'inputs_sha256':frozen_hashes(folder,['step0_session_config.json','step1_search_queries.md','step2_raw_papers.json']),
                         'query_sha256':hashlib.sha256(t['query'].encode()).hexdigest()})
                phase='step3_screen';say('Score the same 100 BM25 candidates');begin=time.perf_counter();screen(ctx)
                papers=read(folder/'step3_screening_all.json')['papers']
                if len(papers)!=100 or {p['id'] for p in papers}!={str(cid) for cid in t['bm25_top100']}:
                    raise ValueError('Step 3 does not cover all frozen candidate IDs')
                if any(p['screening']['rationale'].startswith('LLM returned no score') for p in papers):
                    raise ValueError('Fallback scores detected; not counting as completed')
                save(folder/'completed.json',{'qid':active,'finished_at':now(),'wall_seconds':time.perf_counter()-begin,
                    'scored_papers':100,'outputs_sha256':frozen_hashes(folder,['step3_screening_all.json','step3_shortlist.json','step3_screening_results.md'])})
                consecutive=0
            except Exception as exc:
                errors.append({'qid':active,'phase':phase,'error':str(exc)});consecutive+=1
            finally:
                ctx.close();backend._client.close()
            progress();evaluate(out,tasks)
            if consecutive>=3:
                terminal='stopped_after_repeated_failures';break
    except ServiceStopped as exc:
        errors.append({'qid':active,'phase':phase,'error':str(exc)});terminal='stopped_after_repeated_transport_failures'
    except KeyboardInterrupt:
        terminal='interrupted'
    except BaseException:
        progress('failed');raise
    finally:
        result=evaluate(out,tasks)
        if terminal=='completed' and result['completed']!=597:terminal='incomplete'
        phase='finished' if terminal=='completed' else phase
        progress(terminal)
    return terminal


if __name__=='__main__':
    import msvcrt
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('eval_runs/litsearch/official_bm25'))
    parser.add_argument('--out',type=Path,default=Path('eval_runs/litsearch/official_bm25_step3_597'))
    parser.add_argument('--date',default='2026-10-13')
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    # An OS-held byte lock prevents two resumes from writing the same caches.
    with (args.out/'runner.lock').open('a+b') as lock:
        if lock.tell()==0:lock.write(b'1');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise SystemExit('Another full597 worker already owns this output directory.')
        try:state=run(args.root,args.out,args.date)
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
    print('Full 597 run status: '+state,flush=True)
    raise SystemExit(0 if state=='completed' else 2)
