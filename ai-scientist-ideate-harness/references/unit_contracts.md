# Unit contracts — index

The full 27-field specification of every Unit is in [ARCHITECTURE.md §4.4](../ARCHITECTURE.md#44-unit-specifications);
this page is the compact index an implementer needs while working. Both are rendered from the same source
([`contracts/`](../contracts/)) by `scripts/render_docs.py`, so they cannot disagree.

## How to read a contract

| Field | Rule |
|---|---|
| `requires` | Units that must be `done` before this one runs; staleness flows along these edges |
| Required inputs | Artifact ids (`ART-…`) the Unit reads; each has one producing Unit per part, or is external |
| Outputs | Artifacts the Unit owns; writing anything else refuses its `done` in the legacy ledger |
| Retry policy | The level that may retry its failures (`RP-…`); no other level retries them |
| Verdict | Design verdict (KEEP, MERGE, SPLIT, REFACTOR, OPTIONAL, REMOVE, TBD) — reasons in ARCHITECTURE.md §5 |

Replacing a Unit's implementation keeps its id, its outputs and its parts; a schema change adds fields only (or bumps
the schema version); every check code keeps a counter-example; a Unit that others revise keeps its declared revision
interface. Run `python scripts/validate_contracts.py` after any edit to `contracts/`.

## Index

<!-- BEGIN GENERATED:contract-index (scripts/render_docs.py - do not edit by hand) -->
| Unit | Name | Step | Kind | Requires | Required inputs | Outputs | Retry policy | Verdict |
|---|---|---|---|---|---|---|---|---|
| A1.p | Protocol | STEP-S1 | model | - | ART-topic | ART-step0.frame | RP-MODEL-OUTPUT | KEEP |
| A1.q | Query strategy | STEP-S1 | hybrid | A1.p | ART-step0.frame, ART-topic | ART-step0.strategy | RP-MODEL-OUTPUT | KEEP |
| A1.e | Protocol evaluation | STEP-S1 | subagent | A1.p, A1.q | ART-topic, ART-protocol-view | ART-protocol-eval | RP-GATE-REVISION | KEEP |
| A1.v | Context | STEP-S1 | model | - | ART-topic | ART-step0.context | RP-MODEL-OUTPUT | REFACTOR |
| A2.s | Retrieval | STEP-S2 | script | A1.p, A1.q, A1.e | ART-step0.frame, ART-step0.strategy | ART-query-instances | RP-TRANSPORT | KEEP |
| A2.m | Merge | STEP-S2 | script | A2.s | ART-query-instances, ART-step0.strategy | ART-raw-papers, ART-paper-ids | RP-TRANSPORT | KEEP |
| A2.c | Per-query check | STEP-S2 | hybrid | A2.m | ART-raw-papers, ART-query-instances, ART-step0.frame, ART-step0.strategy | ART-relevance-check | RP-MODEL-OUTPUT | KEEP |
| A3.b | Bibliometrics | STEP-S3 | script | A2.s, A2.m, A2.c | ART-raw-papers | ART-bibliometrics | RP-TRANSPORT | KEEP |
| A3.g | Mechanical gate | STEP-S3 | script | A3.b | ART-bibliometrics, ART-step0.frame | ART-gate | RP-NONE | KEEP |
| A3 | Scoring and shortlist | STEP-S3 | fanout | A3.g, A3.b | ART-raw-papers, ART-step0.frame, ART-gate, ART-bibliometrics | ART-screening-scores, ART-shortlist, ART-screening-results, ART-screening-all | RP-FANOUT-BATCH | KEEP |
| A5 | Snowball | STEP-S4 | script | A3 | ART-shortlist, ART-bibliometrics, ART-raw-papers, ART-step0.frame, ART-step0.strategy | ART-snowball, ART-paper-ids | RP-TRANSPORT | KEEP |
| A4.k | Citation keys | STEP-S5 | script | A3, A5 | ART-shortlist, ART-bibliometrics | ART-citation-keys, ART-shortlist.citation_key | RP-NONE | KEEP |
| A4.b | BibTeX | STEP-S5 | script | A4.k | ART-citation-keys, ART-shortlist | ART-bib | RP-TRANSPORT | KEEP |
| A6.d | Fetch full texts | STEP-F1 | script | A4.b | ART-shortlist, ART-step0.frame, ART-citation-keys | ART-tier1, ART-pdfs, ART-fetch-log | RP-TRANSPORT | REFACTOR |
| A6.c | Convert full texts | STEP-F1 | script | A6.d | ART-pdfs, ART-shortlist, ART-citation-keys, ART-tier1 | ART-fulltext, ART-shortlist.access_level | RP-TRANSPORT | REFACTOR |
| A7.D | Per-paper deconstruction | STEP-F1 | fanout | A4.b, A6.c | ART-shortlist, ART-step0.frame | ART-decon | RP-FANOUT-BATCH | KEEP |
| A7.A1 | Vocabulary | STEP-F2 | hybrid | A7.D | ART-decon | ART-alignment.vocab, ART-methods-input | RP-MODEL-OUTPUT | KEEP |
| A7.A2 | Coordinates | STEP-F2 | hybrid | A7.A1 | ART-decon, ART-alignment.vocab | ART-alignment.coords | RP-MODEL-OUTPUT | KEEP |
| A7.A3 | Concept points | STEP-F2 | hybrid | A7.A2 | ART-alignment.vocab, ART-alignment.coords, ART-decon | ART-cards.points-align | RP-MODEL-OUTPUT | OPTIONAL |
| B1 | Lens | STEP-F2 | hybrid | A7.A1, A1.v | ART-step0.context, ART-step0.frame, ART-alignment.vocab, ART-decon | ART-lens, ART-step0.probe, ART-methods-input.affordable | RP-MODEL-OUTPUT | KEEP |
| A7.X1 | Collision candidates | STEP-F3 | script | A7.A2, B1 | ART-alignment.coords, ART-alignment.vocab, ART-methods-matrix, ART-lens, ART-decon | ART-collision-candidates | RP-NONE | KEEP |
| A7.X2 | Collision judgement | STEP-F3 | fanout | A7.X1 | ART-collision-candidates, ART-decon | ART-collisions.paper | RP-FANOUT-BATCH | KEEP |
| B3.c | Lens collisions | STEP-F3 | hybrid | A7.X1, B1 | ART-collision-candidates, ART-lens, ART-methods-matrix | ART-collisions.lens | RP-MODEL-OUTPUT | KEEP |
| B3 | Gap list | STEP-F3 | hybrid | A7.X2, B3.c | ART-collisions.paper, ART-collisions.lens, ART-decon, ART-lens | ART-gaps | RP-MODEL-OUTPUT | KEEP |
| A7.R1 | Lines and findings points | STEP-F4 | hybrid | A7.X2, B3 | ART-collisions.paper, ART-gaps, ART-decon | ART-lines, ART-cards.points-collide | RP-MODEL-OUTPUT | KEEP |
| A7.R2 | Planes | STEP-F4 | hybrid | A7.R1 | ART-lines, ART-collisions.paper, ART-decon, ART-cards.points-collide | ART-cards.planes | RP-MODEL-OUTPUT | KEEP |
| A7.R3 | Descriptive body | STEP-F4 | model | A7.R2 | ART-cards.planes, ART-lines, ART-collisions.paper | ART-body-descriptive | RP-MODEL-OUTPUT | OPTIONAL |
| B2 | Synthesis (SOTA) | STEP-F4 | model | A7.R2 | ART-collisions.paper, ART-cards.planes, ART-lines, ART-methods-matrix | ART-sota | RP-MODEL-OUTPUT | KEEP |
| B3.5 | Research questions | STEP-F4 | hybrid | B3 | ART-gaps, ART-collisions.paper, ART-decon, ART-lens, ART-raw-papers | ART-questions | RP-MODEL-OUTPUT | KEEP |
| F.9 | Index and views | STEP-F4 | script | B3.5 | ART-questions, ART-gaps | ART-questions-index | RP-NONE | KEEP |
| P0 | Take a question | STEP-P0 | script | F.9 | ART-questions-index, ART-questions | ART-gen.question | RP-NONE | KEEP |
| P1 | Gap2Hypo | STEP-P1 | hybrid | P0 | ART-gen.question, ART-gaps, ART-collisions.paper, ART-lens | ART-gen.p1 | RP-MODEL-OUTPUT | REFACTOR |
| P2 | Experiment design | STEP-P2 | hybrid | P1 | ART-gen.p1, ART-methods-matrix, ART-sota, ART-lens, ART-step0.probe | ART-gen.p2 | RP-MODEL-OUTPUT | REFACTOR |
| P3 | Decision tree | STEP-P3 | hybrid | P2 | ART-gen.p1, ART-gen.p2 | ART-gen.tree | RP-GATE-REVISION | REFACTOR |
| P4 | Attack-type Related Work | STEP-P4 | hybrid | P3 | ART-gen.question, ART-gen.p2, ART-gen.tree, ART-decon, ART-collisions.paper, ART-shortlist, ART-raw-papers | ART-gen.attack | RP-MODEL-OUTPUT | REFACTOR |
| P5 | Abstract and title packaging | STEP-P5 | hybrid | P4 | ART-gen.p2, ART-gen.tree, ART-gen.attack, ART-lens | ART-gen.packaging | RP-MODEL-OUTPUT | REFACTOR |
| B5 | Reflection | STEP-B5 | hybrid | P5 | ART-gen.packaging, ART-gen.p2, ART-gen.tree, ART-gen.attack | ART-gen.reflection, ART-gen.idea | RP-GATE-REVISION | REFACTOR |
| B6 | Finalize | STEP-B6 | hybrid | B5 | ART-gen.idea, ART-step0.context | ART-ideas-archive, ART-step0.consumed, ART-gen.body-prescriptive, ART-gen.journals | RP-NONE | SPLIT |
<!-- END GENERATED:contract-index -->

## Retry policies and error codes

<!-- BEGIN GENERATED:error-taxonomy (scripts/render_docs.py - do not edit by hand) -->
**Categories** (ideate_v2/errors.py)

| Category | Retryable by default | Default severity | Meaning |
|---|---|---|---|
| input_validation | no | error | a tool or MCP call received arguments that violate its input schema |
| input_contract | no | fatal | an upstream artifact is missing or violates its contract |
| stale | no | error | an input changed after the Unit's done; re-run the upstream chain, not a retry |
| external_service | yes | degraded | a network service failed (429, 5xx, timeout, missing key) |
| tool_invocation | no | error | a CLI command could not start or crashed without a check finding |
| model_output | yes | error | a model or subagent answer was rejected by the Unit's tool |
| schema | no | error | a file on disk or a script output does not match its schema |
| state | no | error | ledger or lifecycle state is inconsistent (malformed line, illegal transition) |
| environment | no | fatal | a package, binary, data root or credential is missing on this machine |
| timeout | yes | error | an operation exceeded its time limit |
| cancelled | no | error | an operation was cancelled by its caller |
| interrupted | yes | error | a Unit began and never finished (crash, kill, power loss) |
| check_failed | no | error | the Unit's own done_when checks failed |
| budget | no | error | a token, cost or time budget was exceeded |
| policy | no | error | a rule refused the action (path outside the allowed roots, loop bound, nested retry) |
| human | no | warning | an intervention through _human/ changed a decision |
| internal | no | fatal | an unexpected exception in v2 itself (a bug) |

**v2 codes** (Unit check codes are namespaced `<unit>:<code>`, category `check_failed`)

| Code | Category | Meaning |
|---|---|---|
| IDEATE.INPUT.INVALID | input_validation | arguments do not match the tool's input schema |
| IDEATE.INPUT.UNKNOWN_ID | input_validation | no Unit, step, gate, loop or policy with that id |
| IDEATE.PATH.DENIED | policy | the path resolves outside every allowed root |
| IDEATE.PATH.NOT_A_RUN_DIR | input_validation | the directory is not a research folder |
| IDEATE.FILE.TOO_LARGE | policy | a file exceeds the read limit |
| IDEATE.ARTIFACT.MISSING | input_contract | a required artifact is absent |
| IDEATE.ARTIFACT.UNREADABLE | schema | a required artifact does not parse |
| IDEATE.EXTERNAL.UNAVAILABLE | external_service | a network service did not answer usefully (429, 5xx, timeout, missing key) after the transport's own retries |
| IDEATE.UNIT.INTERRUPTED | interrupted | a Unit attempt began and never finished |
| IDEATE.LEDGER.MALFORMED | state | a ledger line does not parse |
| IDEATE.STATE.LIFECYCLE | state | an event violates the lifecycle (e.g. UNIT_COMPLETED without UNIT_STARTED) |
| IDEATE.STATE.LOCK_TIMEOUT | timeout | a file lock could not be taken in time |
| IDEATE.GATE.FAILED | check_failed | a handover gate has ERROR findings |
| IDEATE.LOOP.BOUND_REACHED | policy | a declared loop reached its bound |
| IDEATE.RETRY.EXHAUSTED | policy | the owning retry policy has no attempts left |
| IDEATE.RETRY.NESTED | policy | a level tried to retry an error owned by another level |
| IDEATE.TOOL.TIMEOUT | timeout | a tool handler exceeded its time limit |
| IDEATE.OUTPUT.SCHEMA | schema | a tool produced output that violates its own output schema |
| IDEATE.INTERNAL | internal | unexpected exception |
| IDEATE.UPSTREAM.NOT_DONE | input_contract | a Unit was asked to run before an upstream Unit it requires is done |
| IDEATE.UNIT.OUTPUT_MISSING | check_failed | a Unit finished without leaving an artifact its contract names |
| IDEATE.TOOL.FAILED | tool_invocation | a skill command exited non-zero without a check finding |
| IDEATE.ENV.MISSING | environment | a package, binary, key or data root the Unit needs is missing |
| IDEATE.WORKER.OUTPUT | model_output | a Claude worker's files were rejected by the Unit's tool or checks |
| IDEATE.WORKER.FAILED | tool_invocation | a Claude worker could not complete (no result, crash) |
| IDEATE.BUDGET.EXCEEDED | budget | a worker reached its cost or turn budget |

**Retry policies** (one owner per level)

| Policy | Owner | Max attempts | Retries on | Backoff | On exhaustion | Applies to |
|---|---|---|---|---|---|---|
| RP-NONE | orchestrator | 1 | - | none | stop | deterministic failures: input_contract, check_failed, environment, policy, schema of a script Unit |
| RP-TRANSPORT | unit-transport | 2 | external_service, timeout | 2.0s x2.0, cap 30.0s, full jitter | degrade | one network request inside a script Unit (rate limit, 5xx, timeout); a source failing twice running is benched and retried once (A2.s) |
| RP-MODEL-OUTPUT | unit-tool | 2 | model_output, schema | none | error | a model or subagent answer the Unit's tool rejects: the findings are fed back once |
| RP-FANOUT-BATCH | unit-tool | 2 | model_output, timeout, interrupted | none | error | a fan-out batch (A3, A7.D, A7.X2) with no or invalid answer is re-dispatched once; a single invalid item is returned for re-scoring |
| RP-UNIT | orchestrator | 2 | interrupted, timeout, external_service | 30.0s x2.0, cap 300.0s, full jitter | escalate | re-running a whole Unit instance after its own retries are spent; never for deterministic failures |
| RP-GATE-REVISION | unit | 2 | check_failed | none | degrade | a gate's single forced revision (A1.e, the B5 gates): round 2 is final; the doubt is recorded |
<!-- END GENERATED:error-taxonomy -->
