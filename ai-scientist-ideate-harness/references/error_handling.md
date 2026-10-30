# Error handling — operating guide

Design and rationale: [ARCHITECTURE.md §6](../ARCHITECTURE.md#6-error-handling-debugging-and-traceability).
The taxonomy's single source is [`ideate_v2/errors.py`](../ideate_v2/errors.py); its tables are rendered into
[unit_contracts.md](unit_contracts.md#retry-policies-and-error-codes) and served as `ideate://errors/taxonomy`.

## Decide in this order

1. **Is it deterministic?** `input_validation`, `input_contract`, `schema`, `environment`, `check_failed`, `policy`
   → do not retry. Fix the input, the environment or the upstream Unit, then re-run what `next` names.
2. **Who owns the retry?** Ask `ideate_retry_decision(policy_id, attempts_done, requested_by, error)`.
   * a network request inside a script Unit → `RP-TRANSPORT` (the transport retries; the orchestrator never adds a loop)
   * a rejected model or subagent answer → `RP-MODEL-OUTPUT` / `RP-FANOUT-BATCH` (the Unit's tool feeds back once)
   * a gate's forced revision → `RP-GATE-REVISION` (once; then record the doubt)
   * a whole Unit after its own retries are spent → `RP-UNIT` (orchestrator; 2 attempts; then escalate)
   `refuse` means a lower level already retried — record the error and move on.
3. **Degrade or stop?** A failure the Unit can live with becomes a caveat (`severity: degraded`, `caveat: <code>`,
   `must_disclose` when the idea's reader must know). A failure that makes downstream work meaningless is `fatal`.
4. **Record it** with `ideate_record_error`. Set `parent_error_id` when the cause is upstream (an `input_contract` or
   `stale` error found here, caused there). Use an `idempotency_key` when the call itself may be retried.

## Codes

* v2 codes: `IDEATE.<AREA>.<NAME>` (closed list; an unknown code is refused).
* Unit check codes: `<unit>:<code>`, e.g. `A2.c:R03`, `P3:T09`, `A6.c:F12`. The prefix must name a Unit; the code
  keeps its legacy meaning (codes repeat across Units: T01 in B1 and P3, R03 in A2.c and P4, K01 in A4.k and P5).

## Lifecycle per Unit instance

```
UNIT_STARTED (attempt n) -> TOOL_* -> UNIT_COMPLETED | UNIT_DEGRADED | UNIT_PENDING | UNIT_FAILED | UNIT_CANCELLED
UNIT_FAILED -> RETRY_SCHEDULED -> UNIT_STARTED (attempt n+1)       or  RETRY_EXHAUSTED / ESCALATED
UNIT_STARTED (interrupted) -> RECOVERY_STARTED -> UNIT_STARTED (attempt n+1)
```

`ideate_record_event` refuses an out-of-order transition (`IDEATE.STATE.LIFECYCLE`): a second start while an attempt
is open, an attempt number that does not advance, a completion without a start, any event after the run ended.

## Reports and status

`ideate_build_report(run_dir, run_id)` writes `steps/<STEP>.json`, `overall.json`, `_state/errors/latest.json` and
`ERRORS.md`. Step status precedence: `stopped` (fatal) › `failed` › `incomplete` › `degraded` › `done` › `todo`.
Only the latest attempt of each Unit instance counts; earlier attempts stay as history. Root causes are the active
errors (severity ≥ degraded) whose `parent_error_id` chain ends at themselves; everything else is reported as
propagated.

## What never to do

* Retry a deterministic failure, or retry at a level that does not own the policy.
* Edit an artifact another Unit owns, or the legacy ledger.
* Put payloads or secrets into `context` / `message` (they are redacted, but do not rely on it).
* Lower a gate to WARN to get past it — record the caveat and let the owner decide (OQ-04 is open on exactly this).
