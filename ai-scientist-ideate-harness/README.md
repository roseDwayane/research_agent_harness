# ai-scientist-ideate-harness

The ideate stage of AI-Scientist (slides 3–5 of `aiscientist_architecture`): from a topic markdown to a list of 7-key
research ideas, run as a **harness of agents**. Each small step (Unit) is one agent. Each big step runs its Units
between two gates. A code conductor, not an LLM, decides what runs next.

```
topic.md ─▶ Stage A, once per topic                      Stage B, once per idea
            S1 define → S2 search → S3 screen →           P0 take a question → P1–P5 inside B5's three rounds
            S4 snowball → S5 export → F1 deconstruct →    → coherence gate → B6 finalize
            F2 align → F3 collide → F4 reconstruct
                                                            ─▶ <topic>.json + <topic>_research/ + ERRORS.md
```

## What is where

| Folder | What it is |
|---|---|
| `scripts/`, `references/`, `mcp/scholar_mcp`, `mcp/paper_pdf_mcp`, `SKILL.md` | The ideate skill. It implements every Unit: `ideate_tools.py`, `it_*.py`, the ledger, each Unit's checks, and the rules each Unit follows |
| `contracts/` | The architecture as data: 17 steps, 38 Units, 15 gates, 12 loops, 66 artifacts and retry policies (`architecture.json`, `units/`). `legacy_snapshot.json` is pinned by hash to `scripts/ideate_units.json` |
| `contracts/recipes/` | How each Unit is executed: `run` (a skill command), `write` (a Claude worker), `fanout` (one worker per batch). All 38 are still `draft` |
| `ideate_v2/` | The referee: gate checks, loop bounds, retry ownership, error records, events and the three-level report (Unit → step → overall). Standard library only |
| `harness/` | The conductor: `PipelineAgent` → `StepAgent` / `GenerationAgent` → `UnitAgent` |
| `mcp/ideate_v2_mcp/` | Optional MCP server over `ideate_v2`, for a Claude session that inspects or conducts a run interactively (`references/orchestration.md`) |
| `evals/`, `tests/`, `scripts/tests/` | Behaviour cases and fixtures, the v2 and harness tests, and the skill's own suite |

**An agent** is one Unit contract plus one executor, run inside the same shell (`harness/shell.py`):

1. Upstream Units must be done.
2. The executor runs.
3. Every artifact the contract names must exist.
4. The Unit's own checks must pass.
5. A failure goes to the retry policy that owns it.

A custom executor goes through the same shell, so swapping a Unit cannot bypass its contract.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # Python >= 3.10
cp mcp/.env.example mcp/scholar_mcp/.env                    # then fill in the keys you have (gitignored)
claude --version                                            # Claude Code CLI, logged in: the workers are `claude -p`
```

Sources without a key are skipped and the run records a caveat; OpenAlex, arXiv, Crossref and PubMed need no key.
`pdftotext`/`pdftoppm` (poppler) are used for full text when no `PDF2MD_API_KEY` is set.

## Try it

```bash
.venv/bin/ideate-harness check                     # contracts, docs, recipes, tests, evals, lint: everything should PASS
mkdir -p /tmp/try && cp evals/datasets/fusion_ready/eeg_topic.md /tmp/try/
.venv/bin/ideate-harness run /tmp/try/eeg_topic.md --dry-run --generations 2   # the whole pipeline on fixtures:
                                                                              # no network, no tokens
```

The dry run replaces the skill's commands and the Claude workers with fixtures. ideate_v2 still evaluates the contract
half of every gate for real. Inject faults to see how they are handled:

```bash
--inject A2.s=external_service                     # retried by the orchestrator (RP-UNIT), then done
--inject A2.s=external_service,external_service    # exhausted: downstream stops, one root cause
--inject A3=check:C05                              # a check failure: not retried, the run stops
--inject B5=revise:P2                              # round-2 revision: P2..P5 produced again
--inject GATE-coherence=fail,fail                  # decision gate: the question is abandoned, the next one taken
```

A real run (this costs tokens; start small):

```bash
.venv/bin/ideate-harness run path/to/topic.md --smoke-cap 4 --generations 1 --budget 3
```

`--smoke-cap N` limits every database and snowball route to N papers. `--budget` caps each worker call in USD.
Resume a run with the same command; Units that are already done are skipped.

Other options:

- `--from F1 --to F4` runs part of Stage A.
- `--depth quick` runs without full text and with weak evidence.
- `--replay` returns recorded network answers instead of calling the services.

## What a run leaves

| Where | What |
|---|---|
| `<topic>.json` | The ideas (the downstream contract: exactly 7 keys each) |
| `<topic>_research/` | The evidence base and every Unit's files (the layout is in `SKILL.md`) |
| `<topic>_research/ERRORS.md` | The report: status per step, root causes, and the caveats each idea must disclose |
| `<topic>_research/_state/errors/<run_id>/` | Events and error records per Unit; step and overall reports |
| `<topic>_research/_state/harness/<run_id>/` | `summary.json` (status, tokens and cost per Unit), worker prompts and answers, command logs |

To inspect a research folder:

- `ideate-harness status <RD>` shows every Unit's state.
- `ideate-harness report <RD>` rebuilds the report.
- `ideate-harness trace <RD> <error_id|unit>` follows an error to its root cause and lists what it affects.

## Swapping a Unit

```bash
.venv/bin/ideate-harness run topic.md --agent A3=my_package.screen:MyScreen
```

`MyScreen` needs one method:

```python
execute(ctx, unit, recipe, phase, gen, attempt) -> harness.executors.ExecResult
```

It must leave the same artifacts as the Unit it replaces; the shell checks them.

## Status

- The conductor, the contracts and the dry run are complete and tested: `ideate-harness check` passes 14/14.
- The recipes are drafts: none has run on a real topic yet.
- Known open questions are listed in `ARCHITECTURE.md` §10. For example, Stage B is not on the ledger yet (OQ-06), and
  loops without a declared bound get the bounds in `harness/config.py` (OQ-07).
