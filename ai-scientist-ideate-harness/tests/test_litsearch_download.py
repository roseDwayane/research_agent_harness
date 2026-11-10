import json

import pytest

from evaluation.litsearch import download as dl


def test_normalize_official_queries_keeps_gold_only_in_tasks():
    rows = [{'query': 'Which paper studies X?', 'corpusids': [17, 23],
             'query_set': 'inline_acl', 'specificity': 1, 'quality': 2}]
    tasks = dl.normalize_queries(rows)
    assert tasks[0]['qid'] == 'ls_001'
    assert tasks[0]['corpusids'] == ['17', '23']
    assert tasks[0]['query_set'] == 'inline_acl'
    with pytest.raises(ValueError):
        dl.normalize_queries([{'query': 'No gold', 'corpusids': []}])


def test_download_reuses_verified_files_and_rejects_changed_inputs(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(dl, '_revision', lambda revision: 'fixed-sha')
    monkeypatch.setattr(dl, '_load', lambda config, revision, cache: calls.append(config) or
                        [{'query': 'Find paper A', 'corpusids': [4]}])
    first = dl.download(tmp_path, kind='step0203', revision='fixed-sha')
    assert first['task_count'] == 1 and calls == ['query']
    assert dl.download(tmp_path, kind='step0203', revision='fixed-sha') == first
    assert calls == ['query']
    (tmp_path / 'tasks.jsonl').write_text('{}\n', encoding='utf-8')
    with pytest.raises(ValueError, match='frozen LitSearch file changed'):
        dl.download(tmp_path, kind='step0203', revision='fixed-sha')


def test_step03_download_outputs_corpus_and_bm25_tasks(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, '_revision', lambda revision: 'fixed-sha')
    def fake_load(config, revision, cache):
        if config == 'query':
            return [{'query': 'Find paper A', 'corpusids': [4]}]
        return [{'corpusid': i, 'title': f'Paper {i}', 'abstract': 'Abstract'} for i in range(101)]
    monkeypatch.setattr(dl, '_load', fake_load)
    monkeypatch.setattr(dl, 'bm25_top_k', lambda tasks, corpus, out, top_k: [
        {**task, 'bm25_top100': [str(p['corpusid']) for p in corpus[:top_k]]} for task in tasks])
    result = dl.download(tmp_path, kind='step03', revision='fixed-sha')
    task = json.loads((tmp_path / 'tasks.jsonl').read_text(encoding='utf-8'))
    assert result['corpus_count'] == 101
    assert len(task['bm25_top100']) == 100
    assert (tmp_path / 'corpus_title_abstract.jsonl').is_file()
