# P3 decision tree — what each outcome means, before any outcome exists

**Purpose.** A design has more than two outcomes. Besides "supported" and "refuted" a test can come back uninformative —
an interval that spans both readings, a positive control that fails, too few units — and the instrument or a control can
fail before the test is read at all. The tree writes down every outcome of every deciding experiment, what is learned at
each, which rival dies there, and what paper each end is. Its gate (T09) refuses a design whose **likeliest** outcome for
the primary claim is a weak one: of the four ideas run before this step existed, all four ended exactly there, with the
weakness already written in their own Risk entries.

**Inputs.** `gen_k/argument.json` after P2 (claims, rivals with ids, experiments with roles, falsifiers, `refuted_if`,
controls, power), `gen_k/step8_hypothesis.md`. Nothing else: the tree is a reading of the design, not new evidence.

**Outputs.** `gen_k/decision_tree.json` (schema `ai-scientist-decision-tree/1`), its view `gen_k/decision_tree.md`, and
`claims[].outcomes` in `argument.json` — the tree's projection, never written by hand from here on.

## The tree

- **Nodes** — one per experiment that decides something, with the experiment's own role from `argument.json`
  (`tests`, `control`, `instrument`, `descriptive`; the external check keeps its role and carries `external: true`), in
  licensing order: instruments, the primary claim's positive control **and every control its decision rule takes a number
  from** (a surrogate null that sets the threshold), then its test, then the rest. A control whose failure overrides a
  test may come after it: on that control's `fail` branch the claim keeps its status (with the caveat in the leaf's
  conclusion) or becomes `undecided` — the leaf says which. `precise` / `imprecise` set the status of the node's
  estimate claims only. A node has `experiment`,
  `role`, `claims` (an instrument may serve none; an `external` node's outcome bounds the scope — a boundary or a
  narrower claim — and is exempt from T06's status rule and from the gate's weak branches), `reads` (the statistic and the threshold; a second rule row of the same
  experiment goes into `also_rules`), `checkpoint` (an early go / no-go the experiment stage can use), and its branches. A
  `tests` node with no uninformative outcome says why in `uninformative_closed` (an equivalence design with a margin the
  sample can show, say). One experiment may appear in several nodes (on different paths), and two branches may share a
  leaf.
- **Branches** — `kind` by role: tests `supported | refuted | uninformative` (supported and refuted at least once);
  instrument and control `pass | fail`; descriptive `precise | imprecise`. A kind may **repeat** with another `if`: two
  refuted outcomes (no effect; the opposite effect, which may be a finding), a degraded `pass` (the impedance stream lost:
  the claim narrows, say how in the leaf), a precise estimate that is near zero vs large. Each branch has `if` (the result
  that takes it, with the falsifier's numbers for tests — T02 reads the branches, not `reads`), exactly one of `next`
  (a node) and `leaf`, a `prior` (`unlikely | possible | likely`) and its `prior_basis`.
- **Prior floors** are computed, not chosen (`tree-prefill` prints them; T09 recomputes them, and any `prior_floor` left
  in the file is ignored): a test's `uninformative` is at least `likely` when its claim is `underpowered`, or `marginal`
  with the literature effect `(TBD)`; at least `possible` when `marginal`; a descriptive node's `imprecise` is at least
  `possible` when its estimate has no `precision_target`; a positive control's `fail` is at least `possible` when
  `positive_expected` holds only under a condition ("only when / if / for", "unless", "holds / comes through … when",
  "if it stays below", "not read", "cannot detect") — a prompt, not a proof: the round-2 critique says in its own words
  whether the planted effect comes through the statistic unconditionally, and rewording `positive_expected` to dodge the
  pattern is the kind of fix the gate exists to refuse. A prior may be raised above its floor, never lowered below it —
  except where a node **above** the branch measured what the floor assumes unknown (a pilot that measures the effect, a
  control that shows the effect of the generator's own size exceeds the threshold): then the branch names it in
  `floor_lifted_by` and its prior is judged from that node. The floors read `power`, so `power.unit` must be the unit the
  test runs on (putts within recordings, not subjects, for a within-recording permutation): a mismatched unit gives a
  floor with the wrong basis — fix `power` at P2, not the floor. Floors the argument cannot see (an instrument whose risk
  the step8 risk table rates medium; a negative control) are yours to raise.
- **Which controls license a test** is read from the argument: the primary claim's positive control
  (`controls.positive` names its experiment) and every experiment its `falsifier` or a `refuted_if` names besides the
  deciding one (a surrogate null, a calibration). A control that supplies a threshold without being named there is
  invisible to `tree-prefill` and T04 — name it in the falsifier ("… above the 95th percentile of E6's sham null").
- **Leaves** — `claims` (each claim's status on this path: `supported | refuted | undecided`, an estimate
  `estimated | imprecise`; it must agree with the branches the path takes, T06), `conclusion` (what we learn, one
  sentence — this becomes the outcome text), `rivals` (`killed`, `alive`: rival ids, or the rival's type for a claim
  without ids; on a null leaf, the rivals that could have produced a false null — power, a bad instrument — and whether
  they are excluded), `answers_question` (`whole | part | none`), `paper` (below), `targets_hit` (P4 fills it), `then`
  (required for `not-publishable`: stop, or which question instead).
- **Subtrees** — a secondary claim read on every path (an estimate map, a second test that runs whatever the primary
  shows) gets its own small tree whose root is listed in `subtrees`; its leaves name only the claims they decide. Drawing
  it under one branch of the primary instead makes its projected outcomes read as conditional on that branch.

What each `paper` means — always about the **primary claim's question**: a **finding** reports the predicted effect (or
its opposite); an **informative-null** says, with a margin the data can show, that the effect the field assumed is not
there; a **boundary** finds where an effect holds and where not; a **rival-finding** shows that a rival explains the
result (drift, artifact, the label) — a finding about the rival; on its leaf the primary claim is `refuted` when the
rival accounts for the effect the claim attributes to its mechanism (the because-clause dies), `undecided` when the
rival explains only part of it; a **descriptive** paper reports an estimate or map,
precise enough to use, with no test decided; a **methods-caveat** can only report that this pipeline or sample could not
decide; **not-publishable** stops the run.

## Method

1. `ideate_tools.py tree-prefill <gen_dir>` → `gen_k/decision_tree.draft.json`: the nodes in licensing order with their
   threshold text and every branch's floor. Link the branches, write the leaves, raise any prior you have reason to.
2. Save it as `gen_k/decision_tree.json`, then `tree-render <gen_dir> --project`: writes `decision_tree.md`, the outcomes
   into `argument.json`, and `based_on` (the hash of `argument.json` without its outcomes, and of step8).
3. `tree-check <gen_dir>`. Before the round-2 critique, answer the four tree questions (research-cycle §5, round 2): which
   is the likeliest leaf and what paper is it; do two leaves of one test say the same; where does the main rival die; what
   is left when the first checkpoint fails.

## Done when

`tree-check` prints no `ERROR`:

| code | what | level |
|---|---|---|
| T01 | every `tests` / `control` / `instrument` experiment of the primary claim is a node of the main tree | ERROR |
| T02 | a test node's supported / refuted branches repeat a number of its falsifier or `refuted_if` | ERROR |
| T03 | every test node has `uninformative`, or `uninformative_closed` | ERROR |
| T04 | on every path the primary claim's instruments, positive control and threshold-supplying controls come before its first test | ERROR |
| T05 | structure: schema, unique ids, the argument's roles, branch kinds (required ones present, `kind` + `if` unique), `next` xor `leaf`, existing experiments and claims, `if`, `reads`, root and subtrees, no cycle, everything reachable, no primary-claim node in a subtree | ERROR |
| T06 | leaves: `paper`, `conclusion`, `answers_question`, the primary claim's status, statuses agree with the path | ERROR |
| T07 | a test whose supported and refuted branches reach the same conclusions decides nothing | WARN |
| T08 | the main rival is killed in at least one publishable leaf whose path passes through the experiment its `ruled_out_by` names | ERROR |
| T09 | **decision gate** (the paper split counts every leaf, an external check's weak leaves included — it is the honest distribution of what the paper would be; only the single-branch rule exempts external nodes): every prior at or above its floor (or lifted by a node above); no `likely` weak outcome of the primary claim (an `uninformative` or `imprecise` branch, or a branch straight into a `methods-caveat` / `not-publishable` leaf); weak papers carry less than half of the tree (the leaf odds from the priors — likely 0.65, possible 0.3, unlikely 0.05, normalised within each node — summed by paper type; `tree-check` prints the split) | ERROR |
| T10 | `claims[].outcomes` equal the projection (`tree-render --project`, which replaces them); a claim in no leaf | ERROR (no leaf: WARN) |
| T11 | a checkpoint before the primary test | WARN |
| T12 | a `not-publishable` leaf has `then` | ERROR |
| T13 | `based_on` matches the current argument and step8 (P1 or P2 changed → rebuild the tree) | ERROR |

## When the gate fails

T09 is a coherence-gate failure: one forced `ReviseHypothesis` (research-cycle §5), entering at **P2** — the tree is redrawn
after it. The ways out, in the order to try them:

1. **Change the design until the weak outcome is at most `possible`**: more independent units (a second dataset of the
   inventory), a statistic the sample can carry, a positive control whose planted effect comes through the statistic
   unconditionally, a checkpoint that stops the run before the expensive part.
2. **Change what the primary claim is**: when no design on this machine can decide the test, a question that is honestly
   descriptive becomes `study: descriptive` with an estimate primary (C21 records the downgrade), or the question is
   narrowed (`original_question`).
3. **Take another question** (PLAN P-D5): when another ready question remains, the generation abandons this one — nothing
   is consumed, the ledger records the abandonment with the reason, and `question-next` passes over it.
4. Only when none of these is possible: finalize with the Risk entry `"Uninformative branch likely: {node, kind, basis}"`.

## Commands

```bash
$PY $SK/scripts/ideate_tools.py tree-prefill $RD/gen_k             # -> gen_k/decision_tree.draft.json
#   write gen_k/decision_tree.json
$PY $SK/scripts/ideate_tools.py tree-render  $RD/gen_k --project   # decision_tree.md, outcomes, based_on
$PY $SK/scripts/ideate_tools.py tree-check   $RD/gen_k             # T01-T13
```
