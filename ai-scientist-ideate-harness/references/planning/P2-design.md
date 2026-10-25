# P2 design — the experiments that can refute P1's hypothesis

**Purpose.** Decide which data, which measure, which number decides, which control aims at which rival, and what the
sample can detect — for the hypothesis P1 wrote, not for a hypothesis found afterwards in the experiments.

**Inputs.** P1's part of `gen_k/step8_hypothesis.md` and of `gen_k/argument.json` (claims, rivals with ids, derivation),
the methods matrix ("A. Experimental designs" of `<RD>/step6_sota_review.md`, `knowledge/methods_matrix.json`), the
handed-over `magnitudes` in `gen_k/question.json`, `<RD>/lens.json`, the env-probe, `$RD/datasets/`.

**Method.** research-cycle.md §4 from "Operational definitions" on, unchanged: operational definitions, Scope (IN / OUT,
licence lines), conceptual framework, risk table, the by-construction check's six steps (steps 1–2 may already sit in
P1's part), external check, power, traceability with the experiment ids `E0…` and each `tests` experiment's decision rule.
`argument.json` then gets experiments, evidence (with `refuted_if`), construction, controls, falsifier, power, scope,
representation, external_check — question-craft.md §4. What is new:

- **Order.** P2 reads P1 and writes nothing of P1's: a rival's `ruled_out_by` is filled here (P1 left it empty), a
  rival P2 discovers is added with the next free id and recorded in step8. Changing the hypothesis is a revision that
  enters at P1 (PLAN_ideate_planning §1.8; research-cycle §5).
- **The compute gate runs here** (research-cycle §5, "Compute gate": it may be applied to the experiment list early), so
  that P3 prices a design that fits the machine.
- **The power against the field's numbers.** `power.literature_effect` compares the smallest detectable effect with the
  handed-over `magnitudes` (C27); a conversion between units is a design choice written with its basis.
- **Refutation needs a margin the data can show.** A `refuted_if` that every non-significant result satisfies ("p >
  0.05", "inside the null") cannot tell an absent effect from an undetected one; give it the bound the sample can reach
  (an equivalence margin, an upper confidence bound below the SESOI), or the decision tree has to split refuted from
  uninformative by itself — and its gate will price the split.
- **`power.unit` is the independent unit of the claim's scope.** research-cycle §4 counts independent units — subjects,
  not trials — because the claim is about people. A claim scoped to *these recordings* (a within-recording contrast
  whose null shifts putts within each recording) is powered over the putts within them, and its `scope.external` then
  says it does not generalise to golfers; a claim about golfers is powered over golfers, whatever the test resamples.
  Choose the scope first, the unit follows; the decision tree's floors read this field.
- **Estimate claims are claims too**: `argument-check` asks them for `warrant`, `rivals` (may be `[]` with a reason in
  the statement) and `scope`, like any claim (question-craft §4.1).
- **Checkpoints.** An experiment whose interim number tells early whether the work is on track carries
  `"checkpoint_reads": "<the number and its tolerance>"` in `experiments[]` (optional; the answer to the skeptical-reader
  question 12 belongs here). The decision tree makes it a checkpoint node, and the experiment stage can take it as a
  `gate_check`.
- **Leave `outcomes` to P3.** The decision tree writes `claims[].outcomes` (`tree-render --project`); until it exists,
  write `"outcomes": {}` — `argument-check` then prints a NOTE C6 instead of an error.
- **The log starts at P1.** Round 1 of B5 is P1 → P5, so `reflection_log.md` opens with `## Round 1/N` before P1 and
  P2's compute-gate line goes there.
- **A `partly` computable part that is the decision rule's own numerator** (a ratio design: the age slope over the
  injected dose) cannot be "excluded from the decision rule" (research-cycle §4, step 3): say which part existing data
  give and why the rule still needs the experiment — the C17 WARN is then answered in the round-2 critique, not silenced.

**Done when.** `argument-check <gen_dir> --no-idea` has no `ERROR` that belongs to the design (C1–C24 except those that
read the seven fields, C25–C27), and the compute gate's line is in the log.

```bash
$PY $SK/scripts/ideate_tools.py power ...                       # research-cycle §4
$PY $SK/scripts/ideate_tools.py argument-render $RD/gen_k
$PY $SK/scripts/ideate_tools.py argument-check  $RD/gen_k --no-idea
```
