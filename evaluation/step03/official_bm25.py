"""Official-protocol corpus BM25 -> frozen top-100 -> existing Step 3.

Stages are explicit so a data/network failure cannot be mistaken for an evaluated
baseline. No gold is injected into candidates or exposed to Step 3. Existing API
experiments are never overwritten. Optional dependencies: pip install -e .[litsearch].
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from scholar_research import __file__ as engine_file
from scholar_research.config import Config
from scholar_research.schemas.paper import Paper, RawPapers, SearchSummary
from scholar_research.session import Session
from scholar_research.steps.base import Context
from scholar_research.steps.s3_screen import run as screen
from scholar_research.utils import dump_json, load_json
from .metrics import mrr, ndcg_at_k, recall_at_k
from .rank import sort_ids

DATASET = 'princeton-nlp/LitSearch'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows), encoding='utf-8')


def signature(q):
    return q['query'], tuple(sorted(int(c) for c in q['corpusids']))


def corpus_text(p):
    # Official utils.get_clean_title_abstract, including the labels/newline.
    return f"Title: {p['title']}\nAbstract: {p['abstract']}"


def kv_pairs(corpus):
    # Official build_index.create_kv_pairs uses a dictionary keyed by exact text.
    # Preserve both overwrite semantics and input insertion order.
    return {corpus_text(p): int(p['corpusid']) for p in corpus}


def tokenize(text):
    import nltk
    stop = set(nltk.corpus.stopwords.words('english'))
    stem = nltk.stem.PorterStemmer().stem
    return [stem(t) for t in nltk.word_tokenize(text.lower()) if t not in stop]


def download(root):
    import httpx
    from datasets import load_dataset
    import nltk
    if (root/'data_manifest.json').exists():
        manifest = load_json(root/'data_manifest.json')
        for filename, expected in manifest['sha256'].items():
            if sha(root/filename) != expected:
                raise ValueError('Frozen data hash mismatch: '+filename)
        print('Reusing verified frozen official data', flush=True)
        return
    root.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        resp = client.get('https://huggingface.co/api/datasets/'+DATASET)
        resp.raise_for_status(); revision = resp.json()['sha']
        resp = client.get('https://api.github.com/repos/princeton-nlp/LitSearch/commits/main')
        resp.raise_for_status(); commit = resp.json()['sha']
        originals = {}
        for name in ['eval/retrieval/bm25.py','eval/retrieval/kv_store.py','eval/retrieval/build_index.py',
                     'eval/retrieval/evaluate_index.py','utils/utils.py']:
            resp = client.get(f'https://raw.githubusercontent.com/princeton-nlp/LitSearch/{commit}/{name}')
            resp.raise_for_status()
            target = root/'official_sources'/name
            target.parent.mkdir(parents=True, exist_ok=True); target.write_text(resp.text,encoding='utf-8')
            originals[name] = sha(target)
    nltk_dir = root/'nltk_data'
    for resource in ('punkt','stopwords'):
        if not nltk.download(resource, download_dir=str(nltk_dir), quiet=True, raise_on_error=True):
            raise RuntimeError('NLTK download failed: '+resource)
    cache = root/'hf_cache'
    queries = [dict(q) for q in load_dataset(DATASET,'query',split='full',revision=revision,cache_dir=str(cache))]
    corpus_ds = load_dataset(DATASET,'corpus_clean',split='full',revision=revision,cache_dir=str(cache))
    corpus = [{k:p[k] for k in ('corpusid','title','abstract')} for p in corpus_ds]
    if len(queries) != 597 or len(corpus) != 64183:
        raise ValueError(f'Unexpected official dataset size: {len(queries)} queries / {len(corpus)} papers')
    write_jsonl(root/'queries.jsonl',queries); write_jsonl(root/'corpus_title_abstract.jsonl',corpus)
    dump_json(root/'data_manifest.json', {'dataset':DATASET,'dataset_revision':revision,'upstream_commit':commit,
              'official_source_sha256':originals,'downloaded_at':now(),'query_count':len(queries),'corpus_count':len(corpus),
              'sha256':{name:sha(root/name) for name in ('queries.jsonl','corpus_title_abstract.jsonl')}})


def pack_metrics(gold, ids):
    gold = [str(g) for g in gold]; ids = [str(i) for i in ids]
    return {'R@5':recall_at_k(gold,ids,5),'R@20':recall_at_k(gold,ids,20),
            'MRR':mrr(gold,ids),'nDCG@10':ndcg_at_k(gold,ids,10), 'R@100':recall_at_k(gold,ids,100)}


def aggregate(rows):
    keys = ('R@5','R@20','MRR','nDCG@10','R@100')
    return {'n':len(rows),**{k:sum(r['metrics'][k] for r in rows)/len(rows) if rows else None for k in keys}}


def baseline(root):
    import nltk
    import numpy as np
    from rank_bm25 import BM25Okapi
    started = time.perf_counter()
    nltk.data.path.insert(0,str(root/'nltk_data'))
    manifest = load_json(root/'data_manifest.json')
    for name, expected in manifest['sha256'].items():
        if sha(root/name) != expected: raise ValueError('Frozen input changed: '+name)
    corpus = read_jsonl(root/'corpus_title_abstract.jsonl')
    queries = read_jsonl(root/'queries.jsonl')
    pairs = kv_pairs(corpus)
    ids = list(pairs.values()); texts = list(pairs)
    encoded_file = root/'encoded_corpus.jsonl'
    contract = {'corpus_sha256':sha(root/'corpus_title_abstract.jsonl'),'numpy':np.__version__,'nltk':nltk.__version__,
                'format':'Title: {title}\\nAbstract: {abstract}', 'k1':1.5,'b':.75,'epsilon':.25,
                'tokenization':'nltk.word_tokenize(lowercase) -> english stopwords removal -> PorterStemmer',
                'tie_break':'np.argsort(scores)[::-1], matching official source', 'n_raw':len(corpus),'n_indexed':len(ids)}
    if encoded_file.exists() and (root/'index_contract.json').exists():
        if load_json(root/'index_contract.json') != contract: raise ValueError('Index contract changed; use new output directory')
        encoded = read_jsonl(encoded_file)
    else:
        stop = set(nltk.corpus.stopwords.words('english')); stem = nltk.stem.PorterStemmer().stem
        encoded = []
        for i,text in enumerate(texts,1):
            encoded.append([stem(t) for t in nltk.word_tokenize(text.lower()) if t not in stop])
            if i%2000==0: print(f'Tokenized {i}/{len(texts)}',flush=True)
        write_jsonl(encoded_file,encoded); dump_json(root/'index_contract.json',contract)
    if len(encoded)!=len(ids): raise ValueError('Index rows do not match corpus')
    index = BM25Okapi(encoded,k1=1.5,b=.75,epsilon=.25)
    result_path=root/'bm25_full597.jsonl'
    previous=read_jsonl(result_path) if result_path.exists() else []
    for i,r in enumerate(previous):
        if signature(r)!=signature(queries[i]): raise ValueError('Cached query ordering mismatch')
    results=list(previous)
    for i,q in enumerate(queries[len(results):],len(results)):
        scores=index.get_scores(tokenize(q['query']))
        order=np.argsort(scores)[::-1][:200].tolist()
        retrieved=[ids[j] for j in order]
        row={**q,'official_query_index':i,'retrieved':retrieved,'bm25_scores':[float(scores[j]) for j in order],
             'metrics':pack_metrics(q['corpusids'],retrieved)}
        with result_path.open('a',encoding='utf-8') as f: f.write(json.dumps(row,ensure_ascii=False)+'\n')
        results.append(row)
        if len(results)%20==0: print(f'BM25 queries {len(results)}/{len(queries)}',flush=True)
    grouped={}
    for split in ('inline','author'):
        for specificity in (0,1):
            xs=[r for r in results if (r['query_set'].startswith('inline'))==(split=='inline') and r['specificity']==specificity]
            grouped[f'{split}_{"specific" if specificity else "broad"}']=aggregate(xs)
    summary={'all_questions':aggregate(results),'groups':grouped,'wall_seconds':time.perf_counter()-started,
             'contract':contract,'llm_calls':0,'llm_tokens':0,
             'note':'Official BM25 preprocessing/Okapi/tie protocol adapted without the unrelated dense/OpenAI dependencies. Full corpus, direct corpus-ID gold. MRR/nDCG are harness additions; no claim of exact paper reproduction until group results checked.'}
    dump_json(root/'bm25_summary.json',summary)
    print(json.dumps(summary,indent=2),flush=True)


def prepare(root, subset, old_source, out):
    queries=read_jsonl(root/'queries.jsonl'); results=read_jsonl(root/'bm25_full597.jsonl')
    if len(results)!=len(queries): raise ValueError('Official BM25 baseline must finish before preparing sessions')
    by_signature={signature(r):r for r in results}
    corpus={int(p['corpusid']):p for p in read_jsonl(root/'corpus_title_abstract.jsonl')}
    questions=load_json(subset)['questions']
    prior={r['qid']:r for r in read_jsonl(old_source/'results.jsonl')}
    cfg=Config.load(None); sessions=[]
    out.mkdir(parents=True,exist_ok=True)
    for q in questions:
        if signature(q) not in by_signature: raise ValueError('Subset query not in official dataset: '+q['qid'])
        result=by_signature[signature(q)]; old=old_source/'sessions'/prior[q['qid']]['session']
        if len(result['retrieved'][:100]) != 100 or len(set(result['retrieved'][:100])) != 100:
            raise ValueError('BM25 must supply exactly 100 unique candidates')
        d=out/'sessions'/q['qid']; d.mkdir(parents=True,exist_ok=True)
        sc=load_json(old/'step0_session_config.json')
        # Reuse frozen topic/PICO only. No target-paper fields are put in Step 0.
        sc['session_id']='official_'+q['qid']; sc['current_step']=2
        session=Session(d,cfg)
        raw_papers=[]
        for rank,cid in enumerate(result['retrieved'][:100],1):
            p=corpus[int(cid)]
            raw_papers.append(Paper(id=str(cid),title=p['title'],abstract=p['abstract'],
                                   sources_found_in=['LitSearch corpus_clean'],found_via='official_bm25'))
        raw=RawPapers(session_id=sc['session_id'],topic=sc['topic'],search_timestamp=now(),
                      search_summary=SearchSummary(total_raw_results=100,after_dedup=100,snowball_additions=0,final_count=100,
                        sources={'litsearch_official_bm25':100},queries={'litsearch_official_bm25':1},doi_coverage='0%',hub_papers=[],clusters=[]),papers=raw_papers)
        manifest={'qid':q['qid'],'official_query_index':result['official_query_index'],
                  'top100_corpusids':result['retrieved'][:100],'data_manifest_sha256':sha(root/'data_manifest.json'),
                  'subset_sha256':sha(subset),'config_sha256':hashlib.sha256(json.dumps(sc,sort_keys=True).encode()).hexdigest()}
        if (d/'input_contract.json').exists():
            existing=load_json(d/'input_contract.json')
            if existing!=manifest: raise ValueError('Frozen session contract changed: '+q['qid'])
        else:
            dump_json(d/'step0_session_config.json',sc);dump_json(d/'step2_raw_papers.json',raw.model_dump())
            manifest['step2_sha256']=sha(d/'step2_raw_papers.json')
            # Persist hashes separately, so reruns compare stable config/top100 rather than timestamp.
            dump_json(d/'input_contract.json',{k:v for k,v in manifest.items() if k!='step2_sha256'})
            dump_json(d/'input_hashes.json',{'step2_sha256':manifest['step2_sha256'],'step0_sha256':sha(d/'step0_session_config.json')})
        sessions.append({'qid':q['qid'],'session':q['qid'],'query':q['query'],'corpusids':q['corpusids'],
                         'query_set':q['query_set'],'specificity':q['specificity'],'quality':q['quality'],
                         'bm25_top100':result['retrieved'][:100]})
    write_jsonl(out/'tasks.jsonl',sessions)
    dump_json(out/'prepare_summary.json',{'prepared':len(sessions),'candidates_each':100,'api_search_calls':0,
              'metadata_note':'Official clean corpus gives title/abstract; authors, year, citation count, venue unknown, no API enrichment. Step 3 scores recency/quality under this limitation.'})


def verify_inputs(folder):
    expected=load_json(folder/'input_hashes.json')
    for name in ('step0','step2'):
        filename='step0_session_config.json' if name=='step0' else 'step2_raw_papers.json'
        if sha(folder/filename)!=expected[name+'_sha256']: raise ValueError('Frozen '+name+' input changed')


def score(root, out, *, limit=None):
    import httpx
    from scholar_research.llm.client import OllamaBackend
    tasks=read_jsonl(out/'tasks.jsonl'); cfg=Config.load(None)
    if limit is not None:
        if limit < 1: raise ValueError('limit must be positive')
        tasks=tasks[:limit]
    # Preserve the previous Step 3 scoring budget/model, without copying credentials.
    cfg.llm.model='qwen3.8';cfg.llm.provider='ollama';cfg.llm.temperature=0
    cfg.llm.max_tokens=3072;cfg.llm.num_ctx=8192;cfg.llm.request_timeout=300;cfg.llm.think=False
    cfg.screening.batch_size=12
    cfg.screening.threshold_include=3.5;cfg.screening.threshold_borderline=3
    contract={'llm':cfg.llm.model_dump(),'screening':cfg.screening.model_dump(),'transport':'IPv4-only',
              'prompts_sha256':{name:sha(Path(engine_file).parent/'llm'/'prompts'/name) for name in ('s3_criteria.md','s3_score.md')}}
    if (out/'run_contract.json').exists() and load_json(out/'run_contract.json')!=contract:
        raise ValueError('Scoring model/prompt/config changed; use a new experiment output')
    dump_json(out/'run_contract.json',contract)
    completed=[];failures=[];consecutive=0;started=time.perf_counter()
    for task in tasks:
        folder=out/'sessions'/task['session'];verify_inputs(folder)
        if (folder/'completed.json').exists():
            marker=load_json(folder/'completed.json')
            for filename,expected in marker['outputs_sha256'].items():
                if sha(folder/filename)!=expected: raise ValueError('Completed output changed: '+task['qid'])
            completed.append(task['qid']);continue
        backend=OllamaBackend(cfg.llm)
        backend._client.close()
        backend._client=httpx.Client(base_url=cfg.llm.base_url.rstrip('/'),timeout=httpx.Timeout(cfg.llm.request_timeout,connect=10),
                                     transport=httpx.HTTPTransport(local_address='0.0.0.0'))
        session=Session(folder,cfg);ctx=Context(session,cfg,llm_backend=backend)
        def say(message):
            print(task['qid']+': '+message,flush=True)
            dump_json(out/'progress.json',{'status':'running','active':task['qid'],'completed':completed,'failed':failures,'total':len(tasks),'message':message,'updated_at':now()})
        ctx.ui_print=say;say('Scoring all 100 candidates (no gold-hit gating)')
        try:
            begin=time.perf_counter();screen(ctx)
            papers=load_json(folder/'step3_screening_all.json')['papers']
            if {p['id'] for p in papers}!={str(c) for c in task['bm25_top100']}:
                raise ValueError('Step 3 candidate IDs do not match frozen top100')
            if any(p['screening']['rationale'].startswith('LLM returned no score') for p in papers):
                raise ValueError('Fallback score detected; not counting question as completed')
            dump_json(folder/'completed.json',{'qid':task['qid'],'scored_papers':100,'wall_seconds':time.perf_counter()-begin,'finished_at':now(),
                      'outputs_sha256':{name:sha(folder/name) for name in ('step3_screening_all.json','step3_shortlist.json')}})
            completed.append(task['qid']);consecutive=0
        except Exception as exc:
            failures.append({'qid':task['qid'],'error':str(exc)});consecutive+=1
        finally:
            ctx.close()
            backend._client.close()
        evaluate(root,out,tasks=tasks)
        if consecutive>=3:break
    state='completed' if len(completed)==len(tasks) else 'stopped_after_repeated_failures' if consecutive>=3 else 'incomplete'
    dump_json(out/'progress.json',{'status':state,'completed':completed,'failed':failures,'total':len(tasks),'wall_seconds_this_invocation':time.perf_counter()-started,'updated_at':now()})
    evaluate(root,out,tasks=tasks)


def evaluate(root,out, *, tasks=None):
    if tasks is None: tasks=read_jsonl(out/'tasks.jsonl')
    rows=[];usage={'input_tokens':0,'output_tokens':0,'wall_seconds':0.0,'failed_usage_unknown':0}
    for t in tasks:
        d=out/'sessions'/t['session'];complete=(d/'completed.json').exists()
        rankings={'bm25':[str(c) for c in t['bm25_top100']]}
        if complete:
            ps=load_json(d/'step3_screening_all.json')['papers']
            rankings.update({kind:sort_ids(ps,by=kind)[0] for kind in ('relevance','composite')})
        empty={'R@5':0,'R@20':0,'MRR':0,'nDCG@10':0,'R@100':0}
        rows.append({**t,'completed':complete,'hit':bool(set(t['corpusids'])&set(t['bm25_top100'])),
                     'metrics':{kind:pack_metrics(t['corpusids'],rankings[kind]) if kind in rankings else dict(empty) for kind in ('bm25','relevance','composite')}})
        attempts=d/'.cache'/'llm'/'ledger_attempts.jsonl'
        # Attempt telemetry includes retries; do not double-count the success ledger.
        ledger=d/'.cache'/'llm'/'ledger.jsonl'
        events=read_jsonl(attempts) if attempts.exists() else read_jsonl(ledger) if ledger.exists() else []
        for event in events:
            if event.get('cache_hit'):continue
            for key in ('input_tokens','output_tokens'):usage[key]+=(event.get('usage') or {}).get(key,0) or 0
            usage['wall_seconds']+=event.get('wall_seconds',0) or 0
            usage['failed_usage_unknown']+=int(event.get('usage') is None and event.get('status')=='failed')
    def pack(xs):
        return {kind:aggregate([{'metrics':r['metrics'][kind]} for r in xs]) for kind in ('bm25','relevance','composite')}
    summary={'n':len(rows),'completed':sum(r['completed'] for r in rows),'overall':pack(rows),'hit_only':pack([r for r in rows if r['hit']]),
             'usage':usage,'note':'Until completed==n, relevance/composite have incomplete questions counted as zero. BM25 fixed top100 is the same candidate pool. No gold given to Step 3.'}
    dump_json(out/'comparison_summary.json',summary);write_jsonl(out/'comparison_per_question.jsonl',rows)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['download','baseline','prepare','score','evaluate'])
    parser.add_argument('--root',type=Path,default=Path('eval_runs/litsearch/official_bm25'))
    parser.add_argument('--out',type=Path,default=Path('eval_runs/litsearch/official_bm25_step3_80'))
    parser.add_argument('--subset',type=Path,default=Path('eval_runs/litsearch/modeA/subset_v1.json'))
    parser.add_argument('--old-source',type=Path,default=Path('eval_runs/litsearch/modeB_step3_retry6_v2'))
    args=parser.parse_args()
    if args.stage=='download':download(args.root)
    elif args.stage=='baseline':baseline(args.root)
    elif args.stage=='prepare':prepare(args.root,args.subset,args.old_source,args.out)
    elif args.stage=='score':score(args.root,args.out)
    else:print(json.dumps(evaluate(args.root,args.out),indent=2))
