from pathlib import Path

import json

from ideabench_eval.client import ModelConfig
from ideabench_eval.production import offline_recipes, prepare
from ideate_v2.gates import evaluate_gate
from ideate_v2.registry import Registry


def test_frozen_five_references_pass_f1_entry(tmp_path):
    refs = [{'paperId': str(i), 'title': f'Paper {i}', 'abstract': f'Abstract {i}', 'year': 2020}
            for i in range(1, 6)]
    prepare(tmp_path, refs, 3)
    assert evaluate_gate(Registry.load(), tmp_path, 'GATE-a4-check')['passed']
    from harness.config import HarnessConfig
    from harness.skill import Skill
    result = Skill(HarnessConfig()).gate_check(Registry.load().get('GATE-a4-check'),
                                               __import__('harness.skill', fromlist=['Subs']).Subs(tmp_path, tmp_path / 'topic.md'))
    assert result[0], [r.stderr or r.stdout for r in result[1]]
    scores = json.loads((tmp_path / 'screening_scores.json').read_text(encoding='utf-8'))['scores']
    assert len(scores) == 5
    assert [row['id'] for row in scores] == [str(i) for i in range(1, 6)]
    assert all(row['rel'] == 5 and row['qual'] == 3 for row in scores)


def test_offline_deconstruction_has_one_abstract_per_batch():
    commands = [s.spec['run'] for s in offline_recipes()['A7.D'].phases['main'] if s.kind == 'run']
    assert all('--abs-size 1' in command for command in commands if 'decon-plan' in command)
    assert ModelConfig('http://localhost:11434', 'qwen3.8').think is False


def test_standard_depth_keeps_frozen_references_and_passes_entry(tmp_path):
    refs = [{'paperId': str(i), 'title': f'Paper {i}', 'abstract': f'Abstract {i}', 'year': 2020}
            for i in range(1, 6)]
    prepare(tmp_path, refs, 3, depth='standard')
    config = json.loads((tmp_path / 'step0_session_config.json').read_text(encoding='utf-8'))
    frozen = json.loads((tmp_path / '_state' / 'ideabench' / 'references.json').read_text(encoding='utf-8'))
    assert config['depth'] == frozen['depth'] == 'standard'
    assert (tmp_path / 'step3_tier1_candidates.json').is_file()
    assert evaluate_gate(Registry.load(), tmp_path, 'GATE-a4-check')['passed']
