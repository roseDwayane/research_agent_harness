"""harness - the code conductor of the ideate stage (slides 3-5).

Every small step (Unit) is an agent: one contract (contracts/ + scripts/ideate_units.json) and one executor, run inside
the same shell (shell.UnitAgent) that checks what the agent wrote. Big steps (steps.StepAgent) run their Units in
dependency order between two gates; the pipeline (pipeline.PipelineAgent) runs Stage A once and Stage B once per idea.
The rules (gates, loop bounds, retry ownership) and the records (events, errors, reports) are ideate_v2's.

  config.py         HarnessConfig (harness.toml [harness])
  skill.py          the boundary to the Unit implementation (scripts/ideate_tools.py, mcp_bridge.py)
  recipes.py        how each Unit is executed: run / write / fanout steps (contracts/recipes/*.json)
  claude_worker.py  one `claude -p` worker: task, rules, allowed tools, cost
  executors.py      RecipeExecutor (script, Claude, fan-out steps) and the Executor protocol
  fake.py           FakeSkill + FakeExecutor: the dry run (fixtures, no network, no tokens)
  context.py        RunContext: the run's ids, events and error records
  shell.py          UnitAgent: preconditions -> executor -> output contract -> the Unit's checks -> retry
  loops.py          the declared loops the conductor runs (LOOP-01/02/04/08) and their bounds
  steps.py          StepAgent and ReflectionStep (B5 rounds around P1-P5)
  pipeline.py       PipelineAgent: Stage A, Stage B per generation, the report
  cli.py            ideate-harness run | status | report | trace | recipes | check

Standard library only (Python >= 3.10); the Unit implementation it drives needs the packages in requirements.txt.
"""
from __future__ import annotations

__version__ = "2.1.0"
