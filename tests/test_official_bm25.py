import json

import pytest

from evaluation.step03.official_bm25 import (
    corpus_text, evaluate, kv_pairs, pack_metrics, prepare, signature, verify_inputs, write_jsonl,
)


def test_official_text_and_duplicate_dictionary_semantics():
    a={'corpusid':1,'title':'Title','abstract':'Abstract'}
    b={**a,'corpusid':2}
    assert corpus_text(a)=='Title: Title\nAbstract: Abstract'
    assert list(kv_pairs([a,b]).values())==[2]
    assert signature({'query':'q','corpusids':[2,1]})==('q',(1,2))


def test_gold_denominator_does_not_drop_unretrieved_ids():
    values=pack_metrics([1,2],[1,3])
    assert values['R@5']==.5
    assert values['R@100']==.5
    assert values['MRR']==1


def fixture(tmp_path):
    root=tmp_path/'official';root.mkdir()
    out=tmp_path/'experiment';old=tmp_path/'old';(old/'sessions'/'s').mkdir(parents=True)
    corpus=[{'corpusid':i,'title':f'Paper {i}','abstract':f'Abstract {i}'} for i in range(1,102)]
    q={'qid':'ls_001','query':'Question','corpusids':[101],'query_set':'inline_acl','specificity':1,'quality':2}
    write_jsonl(root/'queries.jsonl',[q]);write_jsonl(root/'corpus_title_abstract.jsonl',corpus)
    write_jsonl(root/'bm25_full597.jsonl',[{**q,'retrieved':list(range(1,102)),'official_query_index':0}])
    (root/'data_manifest.json').write_text('{}')
    write_jsonl(old/'results.jsonl',[{'qid':'ls_001','session':'s'}])
    sc={'session_id':'20261012','topic':'Question','topic_original':'Question','topic_slug':'question','timestamp':'2026-10-12',
        'pico':{'population':'P','intervention':'I','comparison':'C','outcome':'O'},'field_type':'cs_engineering'}
    (old/'sessions'/'s'/'step0_session_config.json').write_text(json.dumps(sc))
    subset=tmp_path/'subset.json';subset.write_text(json.dumps({'questions':[q]}))
    return root,out,old,subset


def test_prepare_no_gold_injection_replay_and_missing_scores(tmp_path):
    root,out,old,subset=fixture(tmp_path)
    prepare(root,subset,old,out)
    folder=out/'sessions'/'ls_001'
    raw=json.loads((folder/'step2_raw_papers.json').read_text())
    assert len(raw['papers'])==100
    assert '101' not in {p['id'] for p in raw['papers']}
    assert 'corpusids' not in json.loads((folder/'step0_session_config.json').read_text())
    frozen=(folder/'step2_raw_papers.json').read_bytes()
    prepare(root,subset,old,out)
    assert (folder/'step2_raw_papers.json').read_bytes()==frozen
    summary=evaluate(root,out)
    assert summary['completed']==0
    assert summary['overall']['relevance']['R@5']==0
    assert summary['hit_only']['bm25']['n']==0
    verify_inputs(folder)
    (folder/'step2_raw_papers.json').write_text('{}')
    with pytest.raises(ValueError,match='Frozen step2'):
        verify_inputs(folder)


def test_prepare_rejects_incomplete_top100(tmp_path):
    root,out,old,subset=fixture(tmp_path)
    results=json.loads((root/'bm25_full597.jsonl').read_text())
    results['retrieved']=[1,2]
    write_jsonl(root/'bm25_full597.jsonl',[results])
    with pytest.raises(ValueError,match='100 unique'):
        prepare(root,subset,old,out)
