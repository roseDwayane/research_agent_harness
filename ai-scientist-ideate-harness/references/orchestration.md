# Orchestration by a Claude session (interactive mode)

> This was Gino's `SKILL.md` for the v2 control layer, kept as the reference for **interactive** runs, where a Claude
> session conducts and asks the `ideate_v2` MCP server before each step. The default way to run the pipeline is the
> code conductor in `harness/` (`ideate-harness run`, see [../README.md](../README.md)); there the same gates, loop
> bounds and retry decisions are applied by code, and this page describes what each of them means.

You run the ideate stage as a sequence of **Units** (38) grouped in **steps** separated by **gates**, exactly as
[ARCHITECTURE.md](../ARCHITECTURE.md) specifies. Each Unit's work is done by the legacy skill's commands and
rules; this skill adds the control layer around them: which Unit runs next, whether a gate lets you through, whether
a loop may iterate again, who may retry a failure, and an auditable record of the run.

## Scope

| Use it for | Do not use it for |
|---|---|
| generating ideas from a topic file (Stage A once per topic, Stage B once per idea) | running experiments, plots, writeup, review (other skills) |
| resuming an interrupted ideation run, or explaining why it stopped | editing artifacts by hand to make a check pass |
| status, gate checks, error reports and traces of a research folder | topics without a protocol (the frozen legacy flow; use the legacy skill directly) |
| validating the architecture contracts after a change | anything that needs network access from the v2 server (it has none) |

## Inputs and outputs

* **Input**: a topic markdown (`<topic>.md`) and its research folder `<topic>_research/` (created by A1.p).
  Options: `--depth quick|standard|deep` (default standard), `max_num_generations` (default 3), `num_reflections`
  (default 3).
* **Output**: `<topic>.json` — a JSON list of ideas with exactly the keys `Name, Title, Short Hypothesis, Related
  Work, Abstract, Experiments, Risk Factors and Limitations` (unchanged contract); the research folder; and, from
  v2, `<RD>/ERRORS.md` and `<RD>/_state/errors/<run_id>/` (events, error records, step and overall reports).

## Prerequisites

1. The legacy skill (`IDEATE_LEGACY_SKILL_DIR`) with an interpreter that has its requirements (`$PY`), its
   `scholar` and `paper_pdf` MCP servers, and keys in the environment or its gitignored `.env`.
2. The `ideate_v2` MCP server registered ([mcp/ideate_v2_mcp/README.md](../mcp/ideate_v2_mcp/README.md)) with `IDEATE_ALLOWED_ROOTS` covering the
   topics folder. Without it the legacy flow still works, but you lose gates-as-contracts, retry ownership and reports.
3. `python scripts/run_checks.py` passes (the contracts and the documentation agree).

## Workflow

**Start or resume a run**

1. `ideate_record_event(run_dir, event_type="RUN_STARTED")` → keep `run_id` and `trace_id`. To resume, reuse the
   `run_id` in `<RD>/_state/errors/latest.json`.
2. `ideate_run_status(run_dir)` → `next`: the Units to run now. `running` means interrupted: record
   `RECOVERY_STARTED` for that Unit and run it again (the rerun equals an uninterrupted run).

**For each Unit `next` names** (in order; independent Units may run one after another in any order)

3. `ideate_get_contract(unit)` when you need its inputs, outputs, commands, checks or error boundary. Read the rules
   file its legacy card points to (legacy `references/…`) at that moment, not all at once.
4. `ideate_record_event(UNIT_STARTED, unit_id, instance, attempt)`.
5. Run the Unit's commands from the contract (legacy `ideate_tools.py …` / `mcp_bridge.py …`). Judgement Units: write
   the draft, submit it through the tool, fix what the tool rejects (once — `RP-MODEL-OUTPUT`). Fan-out Units (A3,
   A7.D, A7.X2): one subagent per batch, then merge; re-dispatch a failed batch once (`RP-FANOUT-BATCH`).
6. Close it: `UNIT_COMPLETED` (with `metrics`: tokens, calls, duration when you have them) or `UNIT_DEGRADED` (with
   the caveat) — or on failure `ideate_record_error` (code `<unit>:<check code>` or an `IDEATE.*` code;
   `parent_error_id` when the cause is upstream), `UNIT_FAILED`, then step 7.
7. `ideate_retry_decision(policy_id = the contract's retry policy for a Unit-internal failure, or RP-UNIT for a
   whole-Unit re-run, requested_by="orchestrator", attempts_done, error)`:
   `retry` → wait `delay_s`, start attempt n+1 · `stop` → fix the input (deterministic failure) · `refuse` → a lower
   level already retried; do not loop · `escalate` / `degrade` → record and continue with what is runnable.

**At each step boundary**

8. `ideate_check_gate(run_dir, gate_id, run_id)` **and** the legacy command in `legacy_check.command`. Both must pass
   (D-10). A WARN (e.g. fewer ready questions than the target) passes but its caveat must be disclosed.

**Before any loop iteration** (re-plan a query, second snowball round, re-fetch targets, a B5 revision, next generation)

9. `ideate_check_loop(loop_id, completed, observed)`. Not allowed → do what `on_exhausted` says (usually: accept with
   a disclosed caveat). Never loop without asking.

**Stage B, per generation k**

10. P0 `question-next` / `question-take` → `gen_k/`. P1 → P5 in order, each closed by its gate
    (`generation=k`). B5: round 1 checks and freezes, round 2 one revision (`ideate_check_loop LOOP-09`), round 3
    the coherence gate. T09 still failing after the forced revision → `LOOP-11`: consume the question as abandoned
    and take the next. B6: append the idea, consume the question, write the body and the journals.

**Finish**

11. `ideate_build_report(run_dir, run_id)` → `status`, `stopped_at`, `root_causes`, `must_disclose`. Every
    must-disclose caveat appears in the idea's Related Work or Risk Factors. Record `RUN_COMPLETED` (or `RUN_FAILED`).
12. Tell the user: ideas added (names), the report's status, root causes with their recovery actions, abandoned
    questions and why, every disclosed caveat. Do not claim a step passed that the report shows otherwise.

## Decision rules

* A Unit runs only when `ideate_run_status` lists it in `next` (its upstream Units are done).
* A step starts only when the gate into it passes (v2 and legacy).
* Deterministic failures (`input_contract`, `check_failed`, `schema`, `environment`, `policy`) are fixed, not retried.
* One retry owner per level; `refuse` is final for that level.
* A loop iterates only when `ideate_check_loop` allows it; a missing measurement means "no".
* Fully automatic: never stop to ask the user mid-run. People intervene afterwards through `<RD>/_human/` entries
  (legacy) and the run's `ERRORS.md`.
* `quick` depth is weak evidence: say so in the ideas and the final message.

## Validation and quality

* After changing contracts or this module: `python scripts/run_checks.py` (validators,
  generated docs, tests, evals). Report its actual summary line, including skipped checks.
* An idea is finished only when the coherence gate passed (or its doubt is in Risk Factors) and `append-idea`
  accepted it.

## Safety and data handling

* The v2 server reads research folders only inside `IDEATE_ALLOWED_ROOTS` and writes only `_state/errors/**` and
  `ERRORS.md`; it has no network access and runs no commands.
* Never print API keys or write them into tracked files; never put payloads or secrets into event `context` or
  error messages (they are redacted, but keep them out).
* Subagents receive only their batch or brief (A1.e sees two paths; A3 scorers never see venue or citations).
* Do not hand-edit an artifact another Unit owns, the legacy ledger, or the idea archive.

## Examples

**Good** — "Generate two ideas on ai_scientist/ideas/eeg_artefacts.md":
RUN_STARTED → status shows A1.p next → A1.p … A4.b with gates frame/a2/a3/a5/a4 (a2-check refused once: A2.c asked
for a re-plan, `ideate_check_loop LOOP-01` allowed it, re-search, pass) → fusion F1–F4 (recon-check WARN: 4 ready of
5, caveat questions-short disclosed) → gen_1 and gen_2 → report `degraded` with caveats `accept-weak`,
`questions-short` in both ideas' Risk Factors → final message lists both ideas and the caveats.

**Bad** — the scholar server returns 429 on Scopus; the agent re-runs `mcp_bridge.py search` three times in a row.
The transport had already retried (`RP-TRANSPORT`); `ideate_retry_decision(RP-TRANSPORT, requested_by=orchestrator)`
would have answered `refuse`. Correct: record `IDEATE.EXTERNAL.UNAVAILABLE` (degraded, caveat `source-failed`),
continue, disclose.

**Bad** — tree-check fails T09; the agent edits `decision_tree.json` priors to `possible` to get through. Priors are
computed floors (only raised by evidence); correct: the one forced revision entering at P2, then the ways out, then
abandon (`LOOP-11`).

## References

| When | Read |
|---|---|
| orientation | [architecture_reference.md](architecture_reference.md) |
| a Unit's contract | [unit_contracts.md](unit_contracts.md), `ideate_get_contract`, ARCHITECTURE.md §4.4 |
| a failure | [error_handling.md](error_handling.md), ARCHITECTURE.md §6.6 runbook |
| changing the system | [migration_guide.md](migration_guide.md) |
| the Unit rules themselves | the legacy skill's `references/search/`, `fusion/`, `planning/`, `research-cycle.md` |
