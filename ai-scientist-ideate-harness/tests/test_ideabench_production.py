from pathlib import Path

from ideabench_eval.production import prepare
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
