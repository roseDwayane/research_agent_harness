import json

from evaluation.litsearch.mapping import build_mapping, gold_ids


def test_mapping_is_built_before_retrieval_and_resumes(tmp_path):
    tasks = tmp_path / 'tasks.jsonl'
    tasks.write_text(json.dumps({'qid': 'q1', 'query': 'Find X', 'corpusids': ['7', '8']}) + '\n', encoding='utf-8')
    out = tmp_path / 'gold_id_map.json'
    calls = []
    def lookup(cid, *, api_key):
        calls.append(cid)
        if cid == '8' and calls.count('8') == 1:
            raise TimeoutError('try again')
        return {'paperId': f'paper-{cid}', 'title': f'Title {cid}',
                'externalIds': {'DOI': f'10.123/{cid}'}}
    first = build_mapping(tasks, out, delay=0, lookup=lookup, say=lambda _: None)
    assert first['status'] == 'incomplete' and first['mapped'] == 1
    second = build_mapping(tasks, out, delay=0, lookup=lookup, say=lambda _: None)
    assert second['status'] == 'complete' and calls == ['7', '8', '8']
    records = json.loads(out.read_text(encoding='utf-8'))
    assert records['7']['paperId'] == 'paper-7'
    assert records['8']['doi'] == '10.123/8'


def test_gold_ids_are_unique_and_keep_first_order():
    assert gold_ids([{'corpusids': [1, 2]}, {'corpusids': [2, 3]}]) == ['1', '2', '3']


def test_mapping_limit_selects_first_n_questions(tmp_path):
    tasks = tmp_path / 'tasks.jsonl'
    tasks.write_text('{"corpusids":[1]}\n{"corpusids":[2]}\n', encoding='utf-8')
    result = build_mapping(tasks, tmp_path / 'map.json', limit=1, delay=0,
                           lookup=lambda cid, api_key: {'paperId': f'paper-{cid}'}, say=lambda _: None)
    assert result['questions'] == result['gold_ids'] == result['mapped'] == 1


def test_batch_mapping_reuses_success_and_retries_only_missing(tmp_path):
    tasks = tmp_path / 'tasks.jsonl'
    tasks.write_text('{"corpusids":[1,2,3]}\n', encoding='utf-8')
    out = tmp_path / 'map.json'
    groups = []
    def batch(ids, *, api_key):
        groups.append(ids)
        return [{'corpusId': int(cid), 'paperId': f'paper-{cid}'} if cid != '2' or len(groups) > 1 else None
                for cid in ids]
    first = build_mapping(tasks, out, batch_lookup=batch, say=lambda _: None)
    assert first['mapped'] == 2 and first['unmapped'] == 1
    second = build_mapping(tasks, out, batch_lookup=batch, say=lambda _: None)
    assert second['status'] == 'complete'
    assert groups == [['1', '2', '3'], ['2']]
