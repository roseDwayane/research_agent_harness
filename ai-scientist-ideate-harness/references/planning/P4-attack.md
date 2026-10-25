# P4 attack-type Related Work — whose sentence the study tests, and with what

**Purpose.** The original FinalizeIdea asks Related Work for "the most relevant related work and how the proposal
**clearly distinguishes** from it, and is not a trivial extension". A survey with one closing sentence ("this proposal
differs by …") does not do that — and every idea written before this step did exactly that: none of 16 named a single
experiment of its own. An attack-type Related Work is built the other way round: each paragraph takes one sentence a
paper holds, the record on which that sentence loses or stands untested, the experiment of this study that tests it, and
what the study will say in either outcome. It is written after the decision tree, because "what we say if it lands" and
"what we say if it misses" are leaves of that tree.

**Inputs.** `gen_k/question.json → targets` (from the question's section 9: the sentence as deconstruction units with
verified quotes, its strength, the weakness collision, the evidence level), `gen_k/argument.json` (experiments and
roles), `gen_k/decision_tree.json` (leaves), the round-1 novelty lookups in `reflection_log.md` (for the closest work),
`<RD>/knowledge/decon/`, `<RD>/knowledge/collisions.jsonl` (agree collisions for what to concede), `<RD>/step3_shortlist.json`.

**Outputs.** `gen_k/attack_plan.json` (schema `ai-scientist-attack/1`), `gen_k/related_work.md` — the text of the idea's
`Related Work` field, which P5 copies verbatim — and `targets_hit` on the decision tree's leaves.

## The plan

```json
{"schema": "ai-scientist-attack/1", "idea": "…", "generation": 3, "question": "Q_004",
 "common_ground": ["X0152", "X0230"],
 "targets": [{"id": "T1", "order": 1, "papers": ["careyetal2024"], "claim_units": ["careyetal2024#C1", "careyetal2024#A2"],
              "strength": "shows", "weakness": {"collision": "X0214", "type": "assumption-at-stake", "axes": ["time-anchor", "baseline"]},
              "evidence_level": "full", "holds": "holed putts show greater central beta suppression (against a −3 to −2.5 s baseline)",
              "weapon": ["E2"], "lands_on": ["L3"],
              "if_miss": {"leaf": "L5", "say": "the baseline is neutral within 0.5 dB: Carey's contrast stands as reported"},
              "concede": "the contrast replicates within the dataset (X0230)"}],
 "closest": {"papers": ["…"], "lookup": "round 1: list-papers --file raw --grep '…' (n hits)", "distinction": "…"},
 "related_work": [{"role": "common-ground", "text": "…"}, {"role": "T1", "text": "…"}, {"role": "closest", "text": "…"}]}
```

- **targets** — the handed-over targets, kept as the fusion block recorded them (`claim_units`, `weakness`); a target the
  hand-over lacks is added with `added_because` and a weakness that is a current conflict, boundary or premise collision
  (or an `overreach` unit). `order` 1 is attacked first — the claim the primary test bears on most directly. Two targets
  at least at `standard` and `deep`: the claim tested and the strongest competing position.
- **weapon** — the experiments (role `tests`, `control` or `descriptive`) that test the sentence; **lands_on** — the
  publishable leaves where the blow lands, on a path through the weapon; **if_miss** — another leaf and what the study
  then says about the target. An attack never assumes the win: an informative-null leaf is usually where it misses, and
  "the premise survives this test" is a sentence worth printing. When several leaves would carry the miss, name the
  likeliest informative one — the miss leaf is chosen for its odds as much as for its meaning (R04 reads both).
- **concede** — what the target got right: an agree or extends collision that holds the target's own units, or the
  paper's own limitation and future-work units (`#L`, `#F`) — `attack-prefill` lists both. A paragraph that only takes away reads as a strawman.
- **closest** — the most similar retrieved work, the lookup that found it, and the one-sentence difference. P4 runs that
  lookup itself (`list-papers <RD> --file raw --grep '…'`, titles and abstracts of everything the search returned) and
  logs it in round 1 of `reflection_log.md` — it is the round's novelty check (research-cycle §5), not a later one.
- **related_work** — the paragraphs in order: `common-ground` (what the field holds, citing papers), one per target
  (`role` = its id), `closest` (with the literature-base line the old rule asked for).

## Writing a target's paragraph

1. **What it holds**, at its own strength — `(Author et al., Year) [key]`; a `suggests` or `may` is reported as such, and
   tested, never "refuted" (R03).
2. **What it rests on** — the weakness in words: the axis on which the two sides differ, the premise nobody tested. Cite
   the other side of the collision when it is a paper.
3. **How this study tests it** — the weapon by its id (`E2 crosses the training and test reference on the same epochs`),
   only the axis it varies.
4. **What each outcome means** — the landing leaf's conclusion and the if_miss sentence, in prose.
5. An abstract-only target says so ("from the abstract only"); it is never the first target unless its full text was
   sought (`fulltext_tried`, PLAN F-M4).

The field is 150–450 words (citation keys not counted), most of it in the target paragraphs: the common ground near 100 words (a WARN above 120), the
closest work near 80. Cite only shortlisted papers (R08); a classic the search did not retrieve is named in words.

What the trial's blind reviewer asked for (golf, 2026-10-18), now rules:

- **The common ground reports the field as it is, nulls and directions included.** "Pre-putt EEG differs with outcome
  across laboratories" pooled an alpha decrease, a beta effect and an alpha *null*; read each unit's text and sign, and
  say where studies disagree in direction instead of listing them as agreeing.
- **The outcome sentences say no more than the leaves.** "The residual would cancel" claimed more than the leaf ("the
  nuisance signals do not track outcome"); paraphrase the leaf's conclusion, at its strength.
- **Every part of the question that the tree decides gets its outcome in the text.** A question with two parts (does the
  nuisance track outcome; how much of the contrast it accounts for) needs both said, or the second part reads as dropped.
- **A retrieved paper that bears directly on a target but was excluded at screening** (it is in `step2_raw_papers.json`,
  not in the shortlist — often in a reduced or quick copy of a topic) is rescued before it is cited: `screen-rescue <RD>
  <id> --reason "…"` (A3), which reads it again, blind; R08 then accepts it. Dropping the most direct prior evidence to
  satisfy R08 is the wrong repair.
- **The literature-base line** of the closest paragraph takes its numbers from `<RD>/fusion_caveats.json` (`must_disclose`)
  or STATUS.md: papers screened, read in full, abstract-only.
- **A target the design tests only in part** (another window, another population, another headset) says the untested part
  in its paragraph; an optional `untested_part` in the plan records it.
- **Handed-over targets the design cannot test** go into `dropped: [{"id": "T3", "why": "…"}]` (R01), and the paper may
  move into the common ground.

## Done when

`attack-check <gen_dir>` (and, once P5 has written the draft, `attack-check <gen_dir> --idea idea_draft.json`) prints no
`ERROR`:

| code | what | level |
|---|---|---|
| R01 | targets present (one: WARN), ids and `order` 1…n; a handed-over target keeps its units and weakness, or is in `dropped` with a `why`; an added one says why | ERROR (one target: WARN) |
| R02 | `claim_units` are deconstruction units with a quote; `papers` are theirs | ERROR |
| R03 | a hedged target (`may`, `suggests`, `correlates`) is not "refuted" in its paragraph | WARN |
| R04 | the weapon is a tests / control / descriptive experiment; `lands_on` is a publishable leaf reached through it; the leaves the attacks land on or miss into carry under half of the tree (the tree's odds) | ERROR (the mass: WARN) |
| R05 | `if_miss` is another leaf with a sentence | ERROR |
| R06 | `evidence_level` is the deconstruction's; an abstract-level target says so in its paragraph and is not first without `fulltext_tried` | ERROR |
| R07 | paragraphs common-ground → targets → closest; each target's paragraph cites its keys and names its weapon ids; the closest is cited, with its lookup and distinction; the idea's Related Work is this text (with `--idea`); 150–450 words | ERROR (length: WARN) |
| R08 | every cited key is in `step3_shortlist.json` | ERROR |
| R09 | every target has `concede` | WARN |
| R10 | the weakness is a current conflict, boundary or premise collision, or a marked overreach | ERROR |
| R11 | `based_on` matches the argument and the tree (P1–P3 changed → rebuild the plan) | ERROR |
| R12 | the tree's `targets_hit` are the plan's `lands_on` (`attack-render`) | ERROR |

## When something fails

- A target with no weapon: the study does not test that sentence — move it into the common ground (it is background), or
  drop it; do not keep an attack the design cannot deliver.
- Every landing leaf is weak (the tree's gate T09 failed and was not resolved): the attack cannot land anywhere a paper
  can say it — resolve the gate first (P3, "When the gate fails").
- The question has no section 9 (an older question): add targets with `added_because`, from the gap's collisions.

## Commands

```bash
$PY $SK/scripts/ideate_tools.py attack-prefill $RD/gen_k     # -> gen_k/attack_plan.draft.json
#   write gen_k/attack_plan.json
$PY $SK/scripts/ideate_tools.py attack-render  $RD/gen_k     # related_work.md, targets_hit into the tree, based_on
$PY $SK/scripts/ideate_tools.py attack-check   $RD/gen_k     # R01-R12
```
