import json
from pydantic import BaseModel, Field
from scholar_research.cache import Cache
from scholar_research.config import LLMConfig
from scholar_research.llm.client import LLMClient, FakeBackend
from scholar_research.llm.ledger import Ledger
from evaluation.step08.ideabench.usage import usage_report


class Output(BaseModel):
    value: int = Field(ge=1)


def test_validation_retry_tokens_and_cache_are_not_double_counted(tmp_path):
    values = iter([{'value': 0}, {'value': 1}])
    client = LLMClient(LLMConfig(model='test'), Cache(tmp_path / '.cache', 'read-write'),
                       Ledger(tmp_path / '.cache/llm/generator_ledger.jsonl'), FakeBackend(lambda *args: next(values)))
    variables = {'context': 'test', 'references': 'test', 'n': 1}
    assert client.structured('ideabench_generate', Output, variables, step=81).value == 1
    assert client.structured('ideabench_generate', Output, variables, step=81).value == 1
    row = usage_report(tmp_path)['by_target_stage_role'][0]
    assert row['requests'] == 2
    assert row['input_tokens'] == 20
    assert row['output_tokens'] == 10
    assert row['cache_hits'] == 1


def test_failed_only_attempt_file_has_unknown_usage(tmp_path):
    path = tmp_path / '.cache/llm/generator_ledger_attempts.jsonl'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'call_id': 'failed', 'step': 8, 'prompt': 's8_hypothesis',
        'status': 'failed', 'usage_known': False, 'usage': None, 'wall_seconds': 7}) + '\n')
    row = usage_report(tmp_path)['by_target_stage_role'][0]
    assert row['unknown_usage_requests'] == row['failed_requests'] == 1
    assert row['wall_seconds'] == 7
