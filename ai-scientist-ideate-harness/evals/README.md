# Evaluations

Behaviour checks of the v2 architecture through the same entry point the MCP server uses (`tools/envelope.execute`:
schema validation, envelope, structured errors), plus whitelisted pure rule functions and contract mutations.

```
evals/
├── run_evals.py          runner -> results/latest.json (gitignored) + a summary line; exit 1 on any failure
├── case.schema.json      the case format (validated before anything runs)
├── cases/                registry_contracts · status_gates · loops_rules · observability_errors · rubric_quality
├── datasets/             fixture research folders (built by build_datasets.py; hashes in their ledgers are real)
├── expected/             reviewed regression snapshots (EV-REG-006 Unit inventory, EV-STATUS-006 stale-state map)
├── rubrics/              rubrics for the model-judged Units (probabilistic; not executed without a judge)
├── build_datasets.py     deterministic dataset builder; --check detects drift
└── shadow_compare.py     v2 vs legacy `ideate_tools.py status` on the same folders (needs the legacy skill)
```

## Run

```
python evals/run_evals.py                  # all cases
python evals/run_evals.py --tag architecture-risk
python evals/run_evals.py --case EV-GATE-006 --json
python evals/run_evals.py --update-expected   # rewrite snapshots - review the diff before committing
python evals/build_datasets.py --check
IDEATE_LEGACY_SKILL_DIR=<legacy skill> python evals/shadow_compare.py
```

Results: `results/latest.json` holds every case's status (`pass`, `fail`, `error`, `not_executed`), failures and
duration, plus counts, the pass rate of executed cases and a breakdown by tag.

## Case format

| Field | Meaning |
|---|---|
| `case_id` | `EV-<AREA>-<NNN>` |
| `unit_id` | the Unit (or infrastructure id) under test |
| `description` | what the case proves |
| `tags` | normal, boundary, invalid-input, failure, recovery, regression, architecture-risk, security, idempotency, … |
| `evaluation_method` | `deterministic` or `llm_rubric` |
| `dataset` | fixture folder copied fresh into a temporary root for this case |
| `steps` | `{id, tool, args}` or `{id, function, args}`; args may use `$RUN`, `$WORK`, `$OUTSIDE`, `${<step>:<json pointer>}` |
| `assertions` | `{step?, path (JSON pointer), op, value}`; ops: eq, ne, gte, lte, in, contains, len_eq, len_gte, matches, any_eq, none_eq, all_eq, exists, not_exists |
| `expected_error` | `{error_code}` of the last step |
| `expected_output` | `{file, path}`: the normalised subtree must equal a reviewed snapshot (volatile ids and times removed) |
| `rubric` | rubric id for `llm_rubric` cases |

Each case runs in its own temporary root, which is the only allowed root, so cases cannot affect one another or the
committed datasets.

## Deterministic vs model-judged

Deterministic cases assert what code guarantees and must all pass. `llm_rubric` cases (EV-QUAL-*) judge model
output quality against [rubrics/model_units.md](rubrics/model_units.md); they need a judge and baselines (OQ-11) and
are reported as `not_executed` until then — never as passed.

## Datasets

| Folder | State |
|---|---|
| `search_complete` | all 13 search Units done (A3 re-screened after A5); caveat file with one must-disclose caveat |
| `search_stale` | as above, then `step3_gate.json` edited after A3.g's done |
| `search_interrupted` | A2.s begun, never done |
| `search_failed_a3` | A3 recorded a fail |
| `ledger_malformed` | a torn ledger line (line 11) |
| `fusion_ready` / `fusion_no_ready` | search + full text + fusion done; 3 ready questions of 5 / none ready |
| `planning` | gen_1 sound; gen_2 with a weak decision tree and a 300-word abstract |

Ledger events record, for every Unit, the inputs and outputs its legacy card declares (`io`), hashed the way the
legacy ledger hashes them; spec forms v2 cannot reproduce get a fixed placeholder.
