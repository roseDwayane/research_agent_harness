# P5 packaging — title, short hypothesis and abstract, written last

**Purpose.** The title and the abstract are what a reader meets first, and they are written last: they wrap what P1–P4
decided and may add nothing of their own. Written first (the old flow drafted all seven fields in round 1) they become a
background narrative — every abstract of the 16 ideas before this step ran 277–343 words, over the contract's "about 250"
— and the title has to be repaired afterwards (C20). Written last, each abstract sentence can name the record it rests on.

**Inputs.** `gen_k/argument.json` (the question, `key_terms`, `coverage`, the primary claim, `construction`),
`gen_k/decision_tree.json` (leaves and their odds), `gen_k/attack_plan.json` (targets, `related_work`), `<RD>/lens.json`
(the target venue's readers, A1.v).

**Outputs.** `gen_k/packaging.json` (schema `ai-scientist-packaging/1`) and, through `pack-render`, the `Title`,
`Short Hypothesis`, `Abstract` and `Related Work` of `gen_k/idea_draft.json` (Related Work is the attack plan's text,
copied; `Name`, `Experiments` and `Risk Factors and Limitations` are kept as they are — composed from `argument.json` as
research-cycle §6 says: on the first pass `pack-render` writes placeholders for them; compose them into the draft, and
any later `pack-render` keeps them).

## The packaging

```json
{"schema": "ai-scientist-packaging/1", "idea": "…", "generation": 3,
 "title": "Does the baseline window decide the holed-minus-missed alpha difference before a putt?",
 "short_hypothesis": ["<the research question, word for word>", "<Although … because …>",
                      "<what is tested, what only estimated, why this setting>", "<why no simpler route answers it>"],
 "abstract": [{"move": "context", "text": "…", "sources": ["X0152", "careyetal2024"]},
              {"move": "gap", "text": "…", "sources": ["T1", "X0214"]},
              {"move": "approach", "text": "…", "sources": ["E2", "E5"]},
              {"move": "outcomes", "text": "If …; if …", "sources": ["L3", "L5"]},
              {"move": "contribution", "text": "…", "sources": ["C1"]}],
 "by_leaf": {"L3": {"title": "…", "result_sentence": "… by {{shift}} dB (95% CI {{ci}}) …"}}}
```

- **title** — the key terms of the **tested** part of the question (question-craft §8; C20 still applies: a term that
  is only estimated is not in the title). A question form is welcome when the attack is a contrast ("Stroke onset or ball
  contact?"). At most about 20 words; never a result.
- **short_hypothesis** — the four sentences of question-craft §8, as a list (the "about 120–150 words" guide counts
  sentences 2–4; the research question is copied whole whatever its length): the research question word for word; the
  primary claim (P1); tested vs estimated, from `coverage`; why no simpler route answers it, consistent with
  `construction.computable_without_experiment`.
- **abstract** — one item per sentence, each with its `move` and the `sources` it rests on (ids never printed in the
  text):
  - `context` — what the field holds (common-ground collisions, units, papers);
  - `gap` — the sentence under attack and the record that undermines it (targets, collisions);
  - `approach` — the design: data, the one axis varied, the control (experiment ids);
  - `outcomes` — what each reading means: "If …, …; if …, …" — at least two leaves with different readings of the
    primary claim, one of them publishable; a weak leaf only as one outcome among others;
  - `contribution` — what either outcome gives the reader.
  The moves come in this order, all five present, each as often as it needs (two context sentences, two approach
  sentences are normal); one sentence per item, each item resting on sources of its own move's kind; 150–250 words; no
  results ("we show", "results reveal"). When the decisive readings are not the likeliest (the tree failed its gate and
  no way out was taken), the outcomes say so — "more likely, …" with the likeliest weak outcomes as conditionals; the
  tree's odds may be stated in words ("about one chance in eight"). A because-clause the argument marks as a conjecture
  stays one in the short hypothesis ("…, because, we conjecture, …").
- **by_leaf** — for each reading of the primary claim (supported, refuted, undecided) its likeliest publishable leaf,
  and the likeliest `methods-caveat` leaf — each with odds of 5 % or more, at most four (`pack-prefill` lists them): the title that leaf's paper would carry and its
  result sentence with `{{name}}` slots for the numbers. After the experiments, the writeup stage takes the leaf that was
  reached instead of inventing a story (PLAN §6.3) — a methods-caveat paper needs its title as much as a finding does.
- **tree_gate** — written by `pack-render`: `passed`, or `failed: <the T09 finding>`. A failed gate means the Risk Factors
  carry `"Uninformative branch likely: …"` (P3, "When the gate fails"); attack-check's R04 WARN says the same and is
  acknowledged here, not repaired.

Write for the target venue's readers (`lens.json`): their vocabulary, their first objection. Say the measure in words
("the hit-minus-miss difference in band power"), not the code's names. What the trial's blind editor asked for:

- **One name per thing.** A window, a control, a contrast is named once and called that everywhere — "the test window
  (before contact)" and "the control window (before the stroke)", not three variants. The design's own coinages ("planted
  shift", "contact alignment") are defined on first use or replaced by plain words.
- **Feasibility in plain words.** When the likeliest outcome is undecided, say it as a feasibility statement ("with four
  participants, an undecided result is the most likely outcome; it would still show whether this check can be run"),
  not as odds a reader cannot trace.
- **The abstract and the short hypothesis agree.** The comparator, the threshold and its kind (a point estimate or an
  interval bound) are the same in both — and the same as `argument.json`.

## Done when

`pack-check <gen_dir> --idea gen_k/idea_draft.json` prints no `ERROR` (and `attack-check … --idea` neither):

| code | what | level |
|---|---|---|
| K01 | the abstract is 150–250 words | ERROR |
| K02 | every abstract item has sources that exist; the printed text carries no internal ids (E-, X-, GAP_, Q_ ids, `[keys]`, `#units`, and this generation's leaf and rival ids; electrode names such as C3 or T7 are not ids); one sentence per item | ERROR (more than one sentence: WARN) |
| K03 | the five moves, in order (a move may repeat); every context, gap, approach and outcomes item rests on sources of its kind | ERROR |
| K04 | no result wording | WARN |
| K05 | the outcomes name two readings of the primary claim, one publishable; a weak leaf only conditionally ("if", "whether", "would") | ERROR (conditional: WARN) |
| K06 | a title, at most about 20 words, stating no result | ERROR (length: WARN) |
| K07 | the required leaves (the likeliest publishable leaf of each reading of the primary claim and the likeliest methods-caveat leaf, odds ≥ 5 %) have a title and a result sentence with a `{{name}}` slot; by_leaf holds no other kind of leaf | ERROR |
| K08 | the idea's Title, Short Hypothesis, Abstract and Related Work are the packaging's and the attack plan's text | ERROR |
| K09 | four short-hypothesis sentences, the first the research question word for word | ERROR |
| K10 | `based_on` matches the argument, the tree and the attack plan | ERROR |
| K11 | with `--idea`: no pipeline vocabulary in the idea (leaf ids, "the tree", rounds, env-probe, gen / Q / GAP ids); no Risk entry said twice | WARN |

## When something fails

- A wording fix (a title term, a sentence too long, a stray id) is repaired here and costs no revision (research-cycle §5,
  round 3, as for C20).
- An outcome sentence that cannot be written without overclaiming — the leaves say less than the abstract wants — means the
  tree is right and the abstract is wrong: say what the leaves say.
- The abstract will not fit 250 words: the approach usually carries the definitions that belong in `Experiments`; cut there.

## Commands

```bash
$PY $SK/scripts/ideate_tools.py pack-prefill $RD/gen_k                                   # -> gen_k/packaging.draft.json
#   write gen_k/packaging.json
$PY $SK/scripts/ideate_tools.py pack-render  $RD/gen_k                                   # -> idea_draft.json (4 fields)
$PY $SK/scripts/ideate_tools.py pack-check   $RD/gen_k --idea $RD/gen_k/idea_draft.json  # K01-K10
$PY $SK/scripts/ideate_tools.py attack-check $RD/gen_k --idea $RD/gen_k/idea_draft.json  # R07: the Related Work is the plan's
$PY $SK/scripts/ideate_tools.py argument-check $RD/gen_k --idea $RD/gen_k/idea_draft.json # C20 on the title, the rest
```
