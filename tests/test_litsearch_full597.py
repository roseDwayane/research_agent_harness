import pytest

from evaluation.step03.full597 import MonitoredBackend, ServiceStopped, summarize, task_rows
from evaluation.step03.official_bm25 import pack_metrics
from scholar_research.llm.client import OllamaBackend


def test_full_task_preparation_preserves_all_queries_and_rejects_mismatch():
    queries=[{'query':f'query {i}','corpusids':[1000+i],'query_set':'inline_acl','specificity':1,'quality':2} for i in range(597)]
    baseline=[{**q,'retrieved':list(range(100))} for q in queries]
    tasks=task_rows(queries,baseline)
    assert len(tasks)==597
    assert tasks[0]['qid']=='official_0001' and tasks[-1]['qid']=='official_0597'
    assert tasks[0]['bm25_top100']==list(range(100))
    assert 1000 not in tasks[0]['bm25_top100']  # missing gold is not injected
    baseline[0]['query']='changed'
    with pytest.raises(ValueError,match='ordering mismatch'):task_rows(queries,baseline)


def test_pending_questions_remain_in_overall_denominator():
    zero={k:0 for k in ('R@5','R@20','MRR','nDCG@10','R@100')}
    known=pack_metrics([1],[1])
    u={str(s):dict(input_tokens=0,output_tokens=0,request_wall_seconds=0,unknown_failed_attempts=0,attempts=0) for s in (1,3)}
    first={'initialized':True,'completed':True,'hit':True,'query_set':'inline_acl','specificity':1,
           'metrics':{k:known for k in ('bm25','relevance','composite')},'usage':u,'stage_times':{'1':1,'3':2}}
    second={**first,'initialized':False,'completed':False,'hit':False,
            'metrics':{k:zero for k in ('bm25','relevance','composite')},'stage_times':{'1':None,'3':None}}
    result=summarize([first,second])
    assert result['overall']['relevance']['R@5']==.5
    assert result['completed']==1 and result['initialized']==1
    assert result['stage_wall_seconds']['3']=={'defined_n':1,'total':2,'mean':2}


def test_three_transport_failures_stop_and_keep_observer_events(monkeypatch):
    def fake_call(self,**kwargs):
        for _ in range(3):self.attempt_observer({'status':'failed'})
    monkeypatch.setattr(OllamaBackend,'__call__',fake_call)
    backend=MonitoredBackend.__new__(MonitoredBackend)
    events=[];backend.attempt_observer=events.append;MonitoredBackend.consecutive=0
    with pytest.raises(ServiceStopped):backend()
    assert len(events)==3
    assert backend.attempt_observer==events.append
    MonitoredBackend.consecutive=0
