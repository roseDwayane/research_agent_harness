# P1 Gap2Hypo — the gap decides the form of the hypothesis

**Purpose.** Turn the question taken from the fusion block into a primary hypothesis whose *form* follows from the record
that made the gap — the question's primary collision — and whose rivals are the field's own competing explanations. A
hypothesis written freely from the question's wording tends to keep the question's cheap part ("X differs") and lose the
part the collision is about ("X differs *because of* the axis on which the two sides differ").

**Inputs.** `gen_k/question.json` (the question, its gap, move, collisions and — from the question's section 9 — `varies`,
`targets`, `rival_accounts`, `magnitudes`), `gen_k/step7b_problem.md` (the copy B5 may revise), the gap's entry in
`<RD>/step7_gaps.json`, the question's collisions in `<RD>/knowledge/collisions.jsonl`, `<RD>/lens.json`. Not other
generations' folders: ideas differ because `question-next` picks a different question, not because this step looks at them.

**Fields P2 fills** (experiments, evidence, construction, controls, falsifier, power) are left **out** at P1, never
written as placeholders: C27 reads a `literature_effect` of "(P2)", "(TBD)" or "(write)" alike. `argument.angle` is
`question.json → angle` (the question's axes and title), the same text `consume` records.

**Outputs.** `gen_k/step8_hypothesis.md` — Selected gap summary, Research questions, Hypotheses, Rival explanations (the
template and rules of research-cycle.md §4, unchanged) — and, in `gen_k/argument.json`, the primary claim's `statement`,
`mode`, `warrant`, `expected_direction`, `negation`, `rivals[]` and the new `derivation`. The design fields (experiments,
construction, controls, power) are P2's; P1 leaves them for P2 to write, except `power.literature_effect`, which C27 asks
P2 to fill from the numbers P1 found.

## Method

1. `ideate_tools.py hypo-prefill <gen_dir>` → `gen_k/p1_prefill.json`: the primary collision (the question's first
   collision), its result and differing axes, the default form with the modes it allows, the question's `varies`, the
   rival accounts as rival candidates (ordered: with a record first, not handed to another question, most collisions
   behind them — a Line counts with its collisions —, on an axis the primary collision differs on), the suggested main
   rival (the first of them; a default, not a verdict — the ranking reads records, not the design: an account the
   design holds fixed by construction cannot be the main rival, set it aside with that reason), the magnitudes and the absent number, the attack targets (for
   orientation; P4 uses them).
2. Write the primary hypothesis in the default form, or another form with the reason in `derivation.deviation`:

| primary collision | default form | the hypothesis says | modes | main rival, by default |
|---|---|---|---|---|
| `conflict`, differing on an axis | `moderation` | the varied axis explains the two sides' difference: on the same data, changing only that axis moves the effect by at least the SESOI | test | the other differing axes (rival accounts) |
| `conflict`, `axes_differ = none` | `adjudication` | under the shared conditions, side A's result (or B's) is reproduced | test | chance, power |
| `boundary` | `interaction` | the effect's slope along the condition axis is not zero | test | ceiling, range restriction |
| `untested-shared`, `assumption-at-stake` | `premise-test` | premise P fails under condition C (the effect changes by at least the SESOI) — or, as equivalence, P holds within a stated margin, with a positive control | test, equivalence | P holds after all (the null) |
| `assumption-challenged` | `share` | how much of conclusion Z the violation of P explains (estimated, tested against 0 and against all of it) | estimate, test | reverse cause, a common cause |
| `criterion-unmet` | `evaluation` | judged by the paper's own criterion K, method M does not meet it | test | the criterion operationalised differently |
| `extends` | `increment` | the next step improves on the current best by at least the SESOI (`comparator` required) | test | tuning differences, leakage |
| `convention-vs-lens` | `non-inferiority` | the convention still holds under this machine's conditions | equivalence, test | the condition changes the measure itself |
| none (`not_done`, `empty-cell`) | `estimate` | how large, how reliable — only with `study: descriptive` (C21) | estimate | — |

   The form comes from the primary collision's **result**, never from `varies`. How the parts fit:

   - **Several varied axes** (`varies` lists more than one): one of them carries the primary hypothesis — the one the
     primary collision differs on and the targets depend on most —, the others go to secondary hypotheses or to an
     estimate (`size-open:`). Keep one primary (research-cycle §4).
   - **Which premise.** `premise-test` reads "P fails under C" for an *invariance* premise (the effect is assumed not to
     depend on C: the baseline is neutral, the anchor does not matter) — the test looks for a change. For a *sensitivity*
     premise (X is assumed to index Y: alpha indexes programming demand) the premise fails when the effect does **not**
     change under a manipulation of Y: the decision rule looks for the predicted change, and a null result is read through
     the decision tree's uninformative branch, not as support for either side. Write which kind it is in
     `derivation.note`.
   - **A moderator that is a transform of the outcome** (a baseline normalisation, a re-referencing, a change of units):
     "changing only X moves the effect" may follow by algebra from the definitions — the difference between two
     normalisations *is* the baseline window's own contrast. Say so in `derivation.note`; P2's by-construction step 3
     decides it, and the honest form may then be a `premise-test` of the premise collision behind it (a deviation).
   - **A varied axis no collision differs on** (WARN Y12 at B3.5): the question's condition is then the condition C of a
     `premise-test` of the collision that is there, and the link from the manipulation to the premise ("a longer putt needs
     more programming") is an assumption of the warrant, written as such and checked at P2 (a manipulation check). Note it
     in `derivation.note`; no deviation is needed when the default form fits.
   - **Variant and kind** (question-craft §6) follow the form: `moderation` / `interaction` of an analysis choice or a
     recording condition → `invariance`, kind `fact`; a `premise-test` of an invariance premise over an *observed*
     factor (age, sex, site — not manipulated) or over an *analysis choice* (time zero, reference, baseline) →
     `invariance`, kind `fact`; of a manipulated factor of the world → `cause`; `adjudication` and
     `evaluation` → `none` or `invariance`; `premise-test` of a sensitivity premise by manipulation → `cause` (the
     manipulation check is its first experiment); `share` → `cause`; `increment` → `none` (or `biomarker` for a
     predictor); `estimate` → `estimate`.
   - **The SESOI** comes from the handed-over numbers, converted to the outcome's units; the conversion (F to d_z, % change
     to log power) is a design choice written in `smallest_effect_of_interest` with its basis. With a small n, test H0 = 0
     one-sided and require the point estimate to reach the SESOI (a two-part rule), rather than a minimum-effect test the
     sample cannot carry; P2's `power` says which.

3. **Rivals from the field's accounts.** Every rival account the question hands over becomes a rival of the primary claim
   (`rivals[].account = "RA2"`) or is set aside in `derivation.set_aside` with the reason (`{"account": "RA4", "why": "…"}`
   — for instance, the design holds that axis fixed). Every rival of the primary claim carries an id `R1`, `R2`, … (the
   decision tree names which rival each leaf rules out). The main rival is, by default, the suggested one; a main rival
   that is none of the field's accounts is allowed, and the round-2 critique says why a reader of the target venue would
   reach for it first. An account marked `unrecorded` (no record holds it) is the study's own conjecture: keep it as a
   rival when the design can address it, say so when it cannot; as the main rival it draws a WARN asking the same. The
   hand-over cannot give rivals that come from the study's own manipulation — block order, a hit rate that changes with
   the condition, a detector that depends on the stroke — add them yourself (no `account`). Rivals of secondary claims
   need ids only when the decision tree names them. Leave `ruled_out_by` for P2 to fill: until P2 the rival is not yet
   addressed, and `argument-check` is run after P2 (`hypo-check` before it).
4. **Direction and size from the field's numbers.** `expected_direction.basis` reads the handed-over magnitudes first: a
   `same` row is evidence for `settled:` or `contested:`, never for `unknown:`. `power.literature_effect` (written at P2)
   compares the smallest detectable effect with them; `(TBD)` is left only when the question hands over no number, or
   only neighbouring ones (then a WARN — say which neighbour is the closest reference). `magnitude_absent` is what the
   study would report for the first time; name it in the hypothesis when the form is `share` or `estimate`.
5. The rest of research-cycle.md §4 for P1's part — one primary hypothesis, mode, H0, the expected direction and its basis,
   `negation` and the by-construction check's first two steps (the formulas exist only after P2: steps 3–6 are P2's).

`derivation` on the primary claim (question-craft.md §4.1):

```json
"derivation": {"gap": "GAP_004", "move": "confirm-assumed", "primary_collision": "X0156", "form": "premise-test",
               "deviation": null,
               "note": "a sensitivity premise: the programming reading predicts a change with distance",
               "set_aside": [{"account": "RA4", "why": "population is held fixed: one novice sample"}]}
```

## Done when

`hypo-check <gen_dir>` prints no `ERROR` (C25–C27 alone; `argument-check` runs them too, once P2 has written the design,
and prints a `NOTE C25` when they ran and found nothing):

| check | what | level |
|---|---|---|
| C25 | the primary claim has `derivation`; its gap and move are the question's; `primary_collision` is one of the question's collisions (not the first: WARN); the form is the default one or carries a `deviation`; the primary claim's mode is one the form allows; `increment` names its `comparator` | ERROR (first-collision: WARN) |
| C26 | every rival of the primary claim has an id `R<n>`, once; every handed-over rival account is a rival's `account` or set aside with a `why`; no unknown account ids; a main rival that is no account (when accounts with a record exist), or carries an unrecorded one | ERROR (main rival: WARN) |
| C27 | a `test` primary claim whose direction basis is `unknown:` although `same` numbers were handed over; `power.literature_effect` `(TBD)` although numbers were handed over | ERROR (only neighbouring numbers: WARN) |

## When something fails

- The question has no section 9 (a question written before it existed): `hypo-prefill` says so; C26 and C27 have nothing
  to compare and stay silent; C25 still applies. Prefer adding section 9 to the question on the fusion side first.
- The question's `varies` drew a WARN Y12 at B3.5 (the question varies an axis none of its collisions differ on — golf50
  Q_005): see "A varied axis no collision differs on" above; when even the premise reading does not hold, narrow the
  question in `step7b_problem.md` (part 5, `original_question`) before P2.
- `question.json` was taken before the question had a section 9, or before `varies` / `magnitude_absent` were copied:
  read them from the generation's `step7b_problem.md` §9.
- A form whose mode the data cannot carry (a `premise-test` with no positive control possible): write the deviation and
  the form that fits; the decision tree (P3) will price the uninformative branch.

## Commands

```bash
$PY $SK/scripts/ideate_tools.py hypo-prefill   $RD/gen_k            # -> gen_k/p1_prefill.json
#   write step8_hypothesis.md (P1 part) and the primary claim's P1 fields in argument.json
$PY $SK/scripts/ideate_tools.py hypo-check     $RD/gen_k            # C25-C27 alone (P2 not written yet)
$PY $SK/scripts/ideate_tools.py argument-render $RD/gen_k           # argument.md shows the derivation and the rival ids
```
