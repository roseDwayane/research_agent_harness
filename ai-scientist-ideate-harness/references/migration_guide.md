# Migration guide

Plan, milestones and the full component mapping: [ARCHITECTURE.md §8](../ARCHITECTURE.md#8-migration-and-transition-plan).
This page is the checklist for doing it.

## Ground rules

* **Additive first.** v2 reads the legacy state and writes only `<RD>/_state/errors/**` and `<RD>/ERRORS.md`; it can
  run beside the legacy flow on any topic without changing it (D-07).
* **The legacy skill stays the implementation of every Unit.** v2 changes it only through reviewed, per-Unit
  changes (milestone M4), each keeping the Unit's id, outputs and parts.
* **Every step is reversible**: contracts and v2 code are separate commits; legacy changes are per Unit; ledgers and
  logs are append-only.

## Setup

```
pip install -r requirements-dev.txt
export IDEATE_LEGACY_SKILL_DIR=<path to the legacy ai-scientist-ideate>     # drift and shadow checks
python scripts/import_legacy_registry.py --check          # snapshot in sync?
python scripts/run_checks.py
```

Register the server next to the legacy ones (project `.mcp.json`; see [mcp/README.md](../mcp/README.md)) with
`IDEATE_ALLOWED_ROOTS` set to the folder that holds the topics.

## Checklist by milestone

| Milestone | Done when | Verify with |
|---|---|---|
| M1 baseline | legacy suite results recorded per platform; snapshot pinned | `import_legacy_registry.py --check`; ARCHITECTURE.md §9.5 |
| M2 contracts | every Unit, gate, loop and artifact contracted | `validate_contracts.py` (0 ERROR, 0 WARN) |
| M3 infrastructure | taxonomy, events, reports, validators in CI | `run_checks.py`; CI green |
| M4 Units | Stage B on the ledger at L4; B6 split; A6 replay; Windows fixes; ledger append lock | legacy `units check`; legacy suite without new failures |
| M5 MCP | `ideate_v2` registered; SKILL.md calls it | `tests/test_mcp_server.py`; a run writes `ERRORS.md` |
| M6 evals | deterministic evals in CI; rubric baselines | `run_evals.py`; rubric baseline file |
| M7 shadow | v2 and legacy agree on real topics | `evals/shadow_compare.py` → 0 unexpected |
| M8 rollout | v2 gates advisory, then blocking | two weeks advisory without a false refusal |
| M9 monitoring | report per run, tokens per Unit | `ERRORS.md` + events metrics |
| M10 retirement | no new run uses the archived engine or the no-protocol flow | repository search; archive note |

## Replacing a Unit implementation

1. Keep the Unit id, its owned artifacts and parts, and its declared revision interfaces.
2. Change schemas by adding fields; otherwise bump the schema version and update readers in the same change.
3. Keep one counter-example per check code (`units check`), and the interrupt (and replay, when networked) test.
4. Update `contracts/units/*.json` if inputs, outputs, requires or the retry policy change; run
   `validate_contracts.py` and `render_docs.py`.
5. Re-import the snapshot (`import_legacy_registry.py`) and run the shadow comparison on the fixtures.

## Rollback

| What | How |
|---|---|
| v2 server | remove its `.mcp.json` entry; the skill runs without it |
| v2 gates (blocking) | switch back to advisory (M8) |
| contracts | revert the commit; regenerate the docs |
| a legacy Unit change | revert the Unit's commit; its downstream goes stale and re-runs from the ledger |
| v2 files in a research folder | delete `<RD>/_state/errors/` and `<RD>/ERRORS.md` (nothing reads them but v2) |

## Known blockers

OQ-02 (the v0.4 `scholar_research/v2` code is missing), OQ-06 (Stage B off the ledger), OQ-08 (Windows), OQ-13
(`.env` in the shipped archive) — details in ARCHITECTURE.md §10.1.
