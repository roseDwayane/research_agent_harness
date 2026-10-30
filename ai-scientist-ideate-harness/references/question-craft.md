# Question craft — is this a question worth asking, and does the study answer it?

Stage A guarantees that an idea is *not already done*. This file adds the two guarantees that novelty does not give:
the question is one somebody has a stake in, and the chain question → method → experiment → claim holds together. It
does so with two artefacts per generation (`gen_{k}/step7b_problem.md`, `gen_{k}/argument.json`), one gate
(`ideate_tools.py argument-check`, checks C1–C24) and one reader who has not seen the hypothesis (the blind
restatement, section 7.2). Nothing here changes the 7-key idea contract: the new material stays in `gen_{k}/`,
and the seven fields only change in how they are composed (section 8).

Rules taken from the books are paraphrased and cite their section: *The Craft of Research*, 4th ed. (**Craft**),
*Designing Clinical Research*, 4th ed. (**DCR**) and Heilmeier's Catechism (**Heilmeier**). Rules that are this
pipeline's own are listed at the end of section 9, which is the index.

**Contents:** §1 how to use this file · §2 problem and question · §3 gap moves · §4 the argument file (§4.4 merged ideas) · §5 gates ·
§6 variants by claim type (§6.5 invariance) · §7 skeptical reader and blind restatement · §8 writing the seven fields ·
§9 sources

---

## 1. How to use this file

Read it once before B3.5 (research-cycle.md §3.5) and come back to the section a step names.

| Step | Read | Produces |
|---|---|---|
| B3 gaps | §3 | the `Move` of each gap |
| B3.5 problem and question | §2 | `gen_{k}/step7b_problem.md`, with `study` in its frontmatter (no `variant`: the primary claim does not exist yet) |
| B4 hypothesis | §4, §6 | `gen_{k}/argument.json` — B4 sets `variant` from the primary claim's form, goes through the angle phrase by phrase (`coverage.angle_parts`) and gives every estimate claim its `estimate_because` — then `argument-render` → `gen_{k}/argument.md` |
| B5 round 1 | §8, §5.2, §7.2 | `gen_{k}/idea_draft.json`; `argument-check --idea idea_draft.json` findings in `reflection_log.md`; the round-1 copies (`argument_r1.json`, `step8_hypothesis_r1.md`, `step7b_problem_r1.md`); at `standard` and `deep`, blind restatement 1 → `gen_{k}/restatement_1.json` |
| B5 round 2 critique and revision | §7.1, §7.2 | answers to the 12 questions and the comparison of restatement 1 in `reflection_log.md`; `reader_doubts` rows; then `argument-check --no-idea` |
| B5 after any revision | §4.2 (`tradeoffs`), §5.1 | one `tradeoffs` row per removal, demotion, mode change, primary change or role change; when the primary claim changed, the by-construction steps and questions 5, 6, 8, 9 and 12 redone for the new claim (research-cycle.md §5) |
| B5 before `FinalizeIdea` (all depths) | §8, §5.2 | `idea_draft.json` rewritten; `argument-check --idea idea_draft.json` |
| B5 before `FinalizeIdea` (standard, deep) | §7.2 | blind restatement 2 → `gen_{k}/restatement_2.json` — **only** when that check prints the C22 warning that the primary claim changed since round 1 |
| B6 finalize | §8 | the seven fields |

The round-by-round schedule is in research-cycle.md §5; this file defines what each step checks and writes.

Five rules hold everywhere in this file:

1. **Every field answers a question a reader will ask.** Each field below names that question. If you cannot say what a
   reader would ask that the field answers, leave it out rather than fill it — a form filled for its own sake produces
   an imitation of an argument, not an argument (Craft, *A Postscript for Teachers*).
2. **The script checks structure; you judge content.** `argument-check` can see that a claim has an experiment. It cannot
   see whether the warrant is reasonable. That judgement is §7.
3. **A gate never stops the run.** A failed gate forces one `ReviseHypothesis`; if it still fails, finalize and record the
   doubt in `Risk Factors and Limitations`. This is the compute gate's behaviour (research-cycle.md §5), on purpose.
   A blind restatement's doubts are answered in the round-2 revision — the reader comes before the scheduled revision
   so that a doubt can still change the design, instead of arriving when the only move left is to file it as a risk.
4. **Check only when the file exists.** A finished `gen_{k}/` without these files predates them: old flow, no backfill.
   An *interrupted* generation is resumed by the two cases of research-cycle.md §3.5 "Resuming": interrupted before
   `argument.json` → restart at B3.5 without redoing B2 or B3; interrupted during B5 (`argument.json` but no
   `idea.json`) → continue from the last fully logged round, or restart B5 at round 1. Whenever a round is redone, the
   round files of the interrupted attempt are deleted first (the list is in section 5.1).
5. **No network.** Evidence for a consequence or a warrant comes from the cards, the notes, the methods matrix and the
   shortlist, through `ConsultKnowledge`; what is cached and installed comes from `ideate_tools.py env-probe` and the
   files in `$RD/datasets/`, both local.

---

## 2. Problem and question — `gen_{k}/step7b_problem.md`

Written after B3 has selected the `(gap, angle)` and before B4. Its job is to settle that the question is worth asking
before any hypothesis is written, because a hypothesis built on a gap nobody cares about cannot be rescued later. "No
paper did X" is an absence; a problem is an absence that costs the field something (Craft 4.2).

Before writing it, once per generation, run `$PY $SK/scripts/ideate_tools.py env-probe $RD --write` and read every file
in `$RD/datasets/` if the folder exists (research-cycle.md §3.5, step 0). The screens, the Scope table,
`external_check.inventory` and the compute gate read this probe, not the `local_environment` prose written at A1,
which may be weeks old and wrong about what is cached.

### 2.1 Template

```markdown
---
topic: "…"   generation: k   gap: GAP_00N   angle: "…"   date: YYYY-MM-DD
move: confirm-assumed        # the selected gap's Move (section 3)
study: analytic        # analytic | descriptive — from the form of the question; fixed here
# evidence: abstracts-only   # add at depth quick (2.4)
---
# Problem and question — {the gap in one sentence}
## 1. Common ground
What the field currently believes or routinely does. 2–3 sentences, each with a citation key.
## 2. Condition
The fact that breaks the common ground: something not known, a contradiction, or an assumption nobody tested.
Cite a methods-matrix `exp_id` or a card. Numbers come from B2 "B. Reported numbers". For an absence, write what is
missing and the nearest reported number, or `(no reported number: this is an absence)`. If a source tested the premise
in a narrow setting, say `tested only in {setting} [key#exp]` — never `untested`.
## 3. Consequence — So-what ladder
Q1 (what this study answers)
  → because Q1 is unanswered, Q2 cannot be answered        evidence: …
  → Q3 (optional)                                          evidence: …
Stop at the rung where a reader of {target_venues} stops asking "so what?" and asks "what do we do about it?".
## 4. Three-step sentence
I am studying ____ because I want to find out (how / why / whether) ____
in order to help {venue readers} understand ____.
[optional fourth step: so that ____ — a practical application may appear only here]
## 5. Research question
One sentence, a question. If it has two parts, the part the study will test comes first; a part no claim will cover
does not belong in it. (B4 adds `Ladder rung: n` on the next line when `variant` is `biomarker`.)
## 6. Screens
| Screen | Result | Basis |
|---|---|---|
| Is the answer already settled in the literature? | no / partly | the `raw` lookup (terms, hit counts) and the methods-matrix rows whose `claim_tested` bears on it |
| Can the answer be derived from textbook knowledge, the definitions involved or a few lines of algebra? | no / partly | the derivation attempted, in 1–3 lines: what follows without data, what does not |
| Could data on this machine settle it? | yes | the dataset and the measure, checked against `env-probe` and `$RD/datasets/` |
| Does the answer feed a larger question that someone other than you has asked? | yes | the rung of section 3 it feeds and that rung's evidence (citation keys) |
## 7. Key terms
4–5 terms. They must recur in the hypothesis, the experiments and the claims. Use the words the experiments
naturally use.
## 8. Definitions
For each term the argument hangs on: the operational definition used here · other definitions in the literature
(citation keys) · why this one.
```

### 2.2 Rules

Each section exists because a reader asks the question in the right-hand column.

| Section | Rule | Reader question it answers |
|---|---|---|
| frontmatter `study` | `descriptive`: the question asks how large, how reliable or how distributed something is and asserts no direction or comparison. Anything else is `analytic`. It is read off the form of the question and fixed here, before any claim exists: only a `descriptive` study may have a `mode: estimate` primary claim (C21), so the label cannot be picked later to let a failing test claim out of its checks. Changing it afterwards is a question rewrite (`original_question`, section 4.2). | "Is this study testing something or measuring something?" |
| 1 Common ground | State a belief or practice the field holds, not background. It is there to be broken by section 2 (Craft 16.2). | "What did we think before this?" |
| 2 Condition | Label it with the gap's `Move` (section 3). It must be a specific not-knowing or misunderstanding, tied to an `exp_id` or a card — not "little work exists" (Craft 4.2.2). An absence has no reported number by definition: write what is missing and the nearest reported number, or `(no reported number: this is an absence)`. A premise that one source tested in a narrow setting is `tested only in {setting} [key#exp]`, never `untested` — playing down the one earlier test is the quickest way to overstate the gap. | "What exactly is wrong or missing?" |
| 3 Consequence | Write each rung as a **larger question** that stays unanswerable while the one below it is open: the answer to Q1 helps answer Q2, and Q2 matters more than Q1 (Craft 4.2.2). "This is important" is not a rung. At most three rungs. | "So what?" (Craft 4.2.1, 16.3.3; Heilmeier 5) |
| 3 evidence | **Every rung needs evidence.** Accepted: future-work calls in ≥ 2 papers, an `open_debates` entry, a recent call for papers of a target venue, or a convention in the methods matrix that every paper follows and none tested. With only your own judgement, write `(TBD)` on that rung and add a `Risk Factors` entry "Significance not supported by the literature: {rung}". **Say whose words the evidence is.** A `Not done:` line of a reading note is the note-writer's observation: cite it as `not done in [key] (reading note)`, never inside quotation marks and never as a future-work call. A future-work call comes from a `Future work:` or `Stated limitations:` line or from the full text. A conclusion you draw from a paper's number is labelled as this study's inference, not as the paper's finding. | "Who else says this matters?" |
| 4 Three-step sentence | Step 2 is the condition, step 3 the consequence (Craft 3.4, 4.2.2). Keep practical benefit out of step 3; it may appear in the optional fourth step, and only when it passes 2.3. | "What are you trying to do, and for whom?" (Heilmeier 1) |
| 5 Research question | Prefer *how* / *why*: they invite deeper thinking than who / what / when / where (Craft 3.3.7); in this pipeline they also keep the study informative whichever way the result falls. *Whether* is allowed when section 3 says what a "yes" changes and what a "no" changes. One sentence. A compound question ("how far …, and what sets …") is judged part by part: the part the study will test comes first, an either/or part counts as a *whether* and needs both outcomes under the ladder, and a part no claim will cover does not belong in the question — a question wider than its test is what a reader later calls overselling (`coverage`, section 4.2). | "What is the question?" |
| 6 Screens | Four screens; drop or reshape a question that fails one (Craft 3.3.7 for the first, third and fourth). **Settled in the literature** — passes on `no` or `partly`, fails on `yes`. Basis: the `raw` lookup with its terms and hit counts (B3's lookup may be reused only when the question's key terms are unchanged) **and** the methods-matrix rows whose `claim_tested` bears on it (`list-methods`) — a grep reads titles and abstracts, so a miss alone shows only that the words are absent. A narrow earlier test gives `partly: tested only in {setting} [key#exp]`. **Derivable** — passes on `no` or `partly`, fails on `yes`. Basis: the derivation attempted, in 1–3 lines. `partly`: name the derivable part — it may be a check or an estimate of size, never the primary claim, because an answer that textbook knowledge or the definitions already give is settled in another field even when no paper in `raw` says so. **Data on this machine** — passes on `yes`; fails when no obtainable data could decide it. Basis: the dataset and the measure, checked against `env-probe` and `$RD/datasets/`. **Feeds a larger question someone else has asked** — passes on `yes`; fails when every rung above Q1 is `(TBD)`. Basis: the rung it feeds and that rung's citation keys — your own ladder is not evidence that anyone else cares. The book notes that the dead-end judgement can be wrong; treating it as a screen with a fixed failure path, and the derivability screen, are this pipeline's rules. What happens after a failed screen is in research-cycle.md §3.5: one rewrite attempt, then the next documented gap from B3.5, and never abandon the last one. Nothing is consumed. | "Is this worth anyone's time?" |
| 7 Key terms | Take them from sections 2 and 5, not from the topic's general vocabulary. Fewer than 4 means the question is too general: narrow it (Craft 12.1.2). Use the words the experiments naturally use. Never reword an `Experiments` entry to satisfy C10: change the key term, or leave the WARN — wording bent for a check makes the check confirm itself. | "Will I recognise the same study in every section?" |
| 8 Definitions | **Required** when the research question contains a term the field defines in more than one way. In this repo: *signal quality*, *learnability*, *reliability*, *biomarker*. A reader who defines the term differently rejects the claim without reading the evidence (Craft ch. 10 Quick Tip). | "What do you mean by X?" |

Reshaping the question to fit the data this machine can reach is routine with existing data (DCR ch. 13), but it is a
change of question. Any change to the wording of section 5 after B3.5 — whatever the cause: data, budget, a coherence
finding, a reader's doubt, or wording alone — is recorded in `original_question` (section 4.2).

### 2.3 The applied test — a rule for the fourth step (Craft 4.2.4)

A practical problem (what should be done) contains a research problem (what must be understood first); the study
answers the second (Craft 4.1). This is a writing rule for the optional fourth step of the three-step sentence, not a
screen: for a measurement study the practical aim is the research answer written as a table, so as a screen it could
not fail. Before a practical benefit goes into the fourth step, fill in:

> (a) If readers want to achieve ______ (the goal in the fourth step),
> (b) would they think they could do it once they knew ______ (the question in step 2)?

A practical benefit appears in the fourth step only when the honest answer is "yes". Otherwise the application is
tacked on: leave the fourth step out and keep step 3 a question about understanding. Reader question: "does knowing
this actually get me what you promise?"

### 2.4 Depth `quick`

There are no Lines and no reading notes, so sections 1–3 rest on abstracts. Write the file anyway, add
`evidence: abstracts-only` to the frontmatter, and write at most **two** rungs in section 3 — a third rung built on
abstracts is a guess. Both blind restatements (section 7.2) are skipped at this depth, and `reader_doubts` is `[]`.

---

## 3. Gap moves

Every gap in `step7_gap_analysis.md` gets a `Move`: how the gap relates to what the sources claim (Craft 6.3). It
answers the reader question "what are you doing to the existing literature — adding to it, or correcting it?". The five
gap types (methodological, population, measurement, temporal, integration) stay; `Move` is a second, independent label.

| Class | `Move` | The source … and this study … |
|---|---|---|
| extension | `add-evidence` | supports a claim with weak or old evidence; supplies stronger evidence |
| extension | `confirm-assumed` | assumes or speculates that something holds; tests it |
| extension | `apply-wider` | shows something in one setting; shows whether it holds in others |
| contradiction | `kind` | says A is a kind of B, or has property B; shows it is not (or the reverse) |
| contradiction | `part-whole` | relates the parts of something one way; shows they relate differently |
| contradiction | `development` | describes an origin or a trend; shows it did not arise or develop that way |
| contradiction | `cause` | says X causes Y; shows it does not, is not sufficient, or both follow from a third factor |
| contradiction | `perspective` | analyses the topic within one framework; a different framework shows a different fact |

- **Extension vs contradiction.** A contradiction move resolves something the field finds inconsistent or wrong; an
  extension adds data on a point the field already accepts. Readers rank the first above the second (Craft 8.2.2), which
  is why B3 breaks near-ties in favour of contradiction moves (research-cycle.md §3).
- **A contradiction needs the source to have said it.** Before building on a contradiction move, confirm in the full text
  that the source makes the claim being contradicted, and cite the page or passage. Refuting a position nobody holds is
  a common failure (Craft 4.3.2, 6.2).
- **A contradiction is a problem only if it costs something.** "Source says X, I say Y" becomes a research problem when
  holding X leads the field to misunderstand a larger issue — that larger issue is the first rung of the So-what ladder.
- **An absence gap gets its Move from what the sources do with the premise.** A gap documented only from `Not done:`
  lines can be labelled `confirm-assumed` or `add-evidence` with equal ease, so decide by test: a source states or
  visibly relies on the premise → `confirm-assumed`; one tested it narrowly → `apply-wider` or `add-evidence`;
  neither → an absence with no stake, severity at most 3. The test and the one full-text look it allows are in
  research-cycle.md §3.
- **A confirmatory study is an extension, not a non-gap.** Repeating a result while avoiding a named weakness of the
  earlier work is `add-evidence`; state the weakness in the gap's Description (DCR ch. 2, Novel).

---

## 4. The argument file — `gen_{k}/argument.json`

Written at the end of B4, after `step8_hypothesis.md`. It is the argument laid out so that a script can check it: the
claim, its reasons, the evidence each reason needs (Craft 9.1), and the side-by-side comparison of what the question
is about with what the study will actually measure (DCR ch. 9, Fig. 9.1). `ideate_tools.py argument-render <gen_dir>`
writes the human-readable `argument.md` from it; never edit `argument.md` by hand.

### 4.1 Schema `ai-scientist-argument/1`

```jsonc
{
  "schema": "ai-scientist-argument/1",
  "idea": "<Name>", "generation": 3, "gap": "GAP_002", "angle": "…",
  "variant": "none | biomarker | cause | equivalence | estimate | invariance",   // set at B4 from the primary claim's form (section 6)
  "study_sentence": "design + main predictor + main outcome + population, in one sentence",
  "question": "the research question of step7b section 5, word for word",
  "original_question": null,                       // or {"text": "…", "changed_because": "data: … | budget: … | coherence: … | restatement: … | wording only: …"}
  "key_terms": ["…", "…", "…", "…"],               // 4–5, same list as step7b section 7
  "coverage": {
    "question": "whole | part",        // does the PRIMARY claim, by its falsifier, answer the whole research question?
    "tested_part": "…",                // required when part: the part the primary claim tests, in the question's words
    "untested": [                      // required (non-empty) when part: every other part of the question
      {"part": "…", "terms": ["temporal coverage", "ceiling"], "by": "C2"}   // by = a non-primary claim that estimates or tests it (or a list of them)
    ],
    "angle": "whole | part",           // does the study cover the angle named in step7b's frontmatter?
    "angle_parts": [                   // the angle, phrase by phrase: every content word of `angle` appears in some part
      {"part": "dose-response of quality metrics", "by": "C2"},      // by = a claim id, an experiment id, or "none"
      {"part": "coupling of quality metrics", "by": "none"}          // any "none" → angle is "part"
    ],
    "angle_dropped": "…"               // required when part: which part of the angle no claim or experiment covers, and why
  },
  "external_check": {
    "synthetic": true,                 // the primary claim's evidence comes from simulated, injected or planted signals or effects
    "real_data": "E8",                 // when synthetic: the experiment tying the result to real recordings of the phenomenon;
                                       //   or "none: <why, per candidate>"; "not applicable" when synthetic is false
    "datasets": ["EEGMMIDB"],          // independent datasets (different site or amplifier) that carry the primary claim
    "second_dataset": "E9",            // when datasets has one entry: the experiment repeating the primary contrast on a second
                                       //   independent dataset; or "none: <why, per candidate>"; "not applicable" with two or more
    "inventory": ["~/mne_data/MNE-lee2019-mi-data: task runs only, no rest",
                  "$RD/datasets/nemar_screening.md: ds004148 has eyes-open/closed rest, 60 subjects"]
  },
  "claims": [{
    "id": "C1", "hypothesis": "H1", "primary": true,
    "kind": "fact | definition | cause | evaluation | action",
    "mode": "test | estimate | equivalence",
    "statement": "Although …, … because …",       // mode estimate: one plain sentence — what is estimated, in whom, to what precision
    "reasons": ["…"],
    "evidence": [{"experiment": "E3",
                  "measure": "…, with the path from the raw value to the number the decision rule reads (per channel → epoch → subject)",
                  "would_show": "…",
                  "refuted_if": "the E3 result that counts against the claim, with its threshold",
                  "can_fail": "yes: <why the measure could come out otherwise> | no: <why it cannot>"}],
    "construction": {
      "predictor_formula": "dose = a * RMS_r * c",                      // the manipulated dose, contrast or predictor: a formula, or its support (channels, band, window, labels)
      "outcome_formula":   "floor_r = min a : AUC[S(x_i + a*RMS_r*c), S(x_j)] >= 0.75",   // the number the falsifier reads
      "shared_terms": ["RMS_r"],                                         // every symbol or support present in both; [] only after comparing
      "computable_without_experiment": "no: … | partly: <which part, from which existing data> | yes: …",
      "free_quantity": "the quantity the design does not fix, on which the result depends"
    },
    "warrant": "When <general circumstance>, then <general conclusion>",
    "warrant_basis": "citation_key or exp_id; else (field convention) or (TBD)",
    "outcomes": {"if_supported": "we learn …", "if_not": "we learn …"},
    "negation": {"text": "the claim reversed", "verdict": "contestable | direction-settled | obviously-false | trivial"},   // null allowed for mode estimate
    "expected_direction": {"direction": "what you expect before any data",          // mode test only
                           "basis": "settled: <citation, textbook physiology or physics, algebra of construction> | contested: <who holds each side> | unknown: <why nothing predicts it>"},
    "estimate_because": null,                      // mode estimate only: "descriptive: … | size-open: … | by-construction: <the test given up, and what a reader loses>"
    "smallest_effect_of_interest": null,           // with direction-settled: the magnitude below which the result changes nothing, and its basis
    "falsifier": "the E3 result that counts as refutation, with its threshold",   // null for mode estimate
    "rivals": [{"type": "chance | bias | reverse-cause | confounding | selection | incorporation | leakage | other",
                "how": "how it would arise in this study, concretely",
                "ruled_out_by": "E5, or a named control; else (not addressed)",
                "main": true,                      // exactly one rival of the primary claim; false or absent on the others
                "id": "R2",                        // planning block (planning/P1-gap2hypo.md): R1, R2, … on the primary claim
                "account": "RA1"}],                //   … and the fusion block's rival account it carries, when it carries one
    "controls": {"negative": "a comparison expected to show no association, aimed at the main rival",   // "controls": null for mode estimate
                 "negative_can_move": "yes: <the control acts on the data the measure is computed from> | no: <…>",
                 "positive": "a comparison showing the pipeline detects a known effect",
                 "positive_expected": "the value the falsifier's statistic returns for the planted effect, with the derivation"},
    "baseline_predictor": null,                    // the existing predictor a new measure must beat, or null
    "comparator": null,                            // what the contrast in `falsifier` is against; required with a baseline
    "derivation": {"gap": "GAP_004", "move": "confirm-assumed",   // planning block, primary claim: how the gap decided the
                   "primary_collision": "X0156", "form": "premise-test",   //   form (planning/P1-gap2hypo.md); absent on
                   "deviation": null,                             //   older generations; `note`: which premise, a
                   "note": null,                                  //   transform moderator, a link assumption
                   "set_aside": [{"account": "RA4", "why": "…"}]},
    "scope": {"internal": "on these data we may claim …",
              "external": "generalises to …; does not generalise to …",
              "limits": ["…"]},
    "power": {"unit": "subjects", "n": 109, "clusters": "4 datasets",                // "power": null for mode estimate
              "min_detectable": "r >= 0.27 at 80% power, two-sided alpha = 0.05",
              "literature_effect": "r ~ 0.4 [key2024]; else (TBD)",
              "verdict": "adequate | marginal | underpowered"},
    "precision_target": null                       // mode = estimate: the confidence-interval width aimed for
  }],
  "representation": {
    "sample":    {"target": "…", "accessible": "…", "concern": "…"},
    "predictor": {"phenomenon": "…", "variable": "…", "precision": "…", "accuracy": "…",
                  "validity": "face | content | construct | predictive | criterion: the basis"},
    "outcome":   {"phenomenon": "…", "variable": "…", "precision": "…", "accuracy": "…", "validity": "…"}
  },
  "experiments": [{"id": "E0", "role": "instrument | tests | control | descriptive | release", "claims": ["C1"]}],
  "tradeoffs": [{"gate": "compute | coherence | restatement | none",   // what caused it: compute gate / an argument-check finding / a reader doubt or mismatch / none of these (critique, the 12 questions, the author's choice)
                 "ids": ["C4", "E7"],                                  // ids of argument_r1.json this row accounts for; [] for a dataset, condition class or analysis with no id
                 "change": "what was removed, demoted or replaced",
                 "because": "…",
                 "lost": "what a reader can no longer learn from the study; or 'nothing: <why>'",
                 "still_answers_question": true,
                 "covers_gap": true,                                   // does the study still address the gap as B3 described it?
                 "covers_angle": true,                                 // … and the angle?
                 "why": "the reasons for the three booleans"}],
  "reader_doubts": [{"source": "restatement-1 | restatement-2",
                     "doubt": "one separable doubt of the blind reader",
                     "level": "design | wording",
                     "response": "fixed | not-fixed",
                     "how": "fixed: what changed, naming the experiment or claim id for a design doubt; not-fixed: data: … | budget: … | conflict: …"}]   // [] at depth quick
}
```

The file on disk is plain JSON: no comments, and each `a | b | c` above is replaced by one of its values. On a
`mode: estimate` claim `falsifier`, `controls` and `power` are `null`, never `""` — an empty string reads as a field
somebody forgot, `null` as one that does not apply.

**Ids are retired, never reused or renumbered.** Once `argument_r1.json` exists (end of round 1), a claim id or an
experiment id that is dropped stays dropped: gaps (`E0, E1, E3`) are valid, and the experiment stage keeps E-ids as
written. C19 matches the round-1 ids against the current ones, so a reused id would hide a removal.

### 4.2 Field rules

**Top level**

| Field | Rule | Reader question it answers |
|---|---|---|
| `variant` | One of `none`, `biomarker`, `cause`, `equivalence`, `estimate`, `invariance` (section 6). Always present. Set at B4 from the form of the primary claim — it cannot be set earlier, because the claim does not exist at B3.5 — and updated by every `ReviseHypothesis` that changes that form. | "Which extra rules apply to this claim?" |
| `study_sentence` | Design, main predictor, main outcome and population in one sentence. It can be hard to write; the effort clarifies the design (DCR ch. 1). Treat a sentence that will not come as a sign the design is still undecided (this pipeline's reading). | "What kind of study is this?" |
| `question` | Copied verbatim from `step7b_problem.md` section 5. | "What is being asked?" |
| `original_question` | `null`, or `{"text", "changed_because"}`. Filled whenever the question's wording changed after B3.5, **whatever the cause** (DCR ch. 13 for the data case): `text` is the earlier wording, and `changed_because` starts with one of `data:`, `budget:`, `coherence:`, `restatement:`, `wording only:` and then gives the reason. C16 enforces the shape: a bare string, an object without `changed_because`, or a reason without one of the five prefixes is an ERROR and does not count as a record (so it also fails the two checks that ask for one, C16 and C21). A one-word change counts — C16 compares the question with `argument_r1.json`, because a question that drifts by a word per revision ends up promising a different study with no record of it. | "Is this the question you set out to answer?" |
| `key_terms` | The 4–5 terms of step7b section 7. Each must appear in `question`, in a `statement` and somewhere in the `Experiments` field (Craft 12.1.2, 13.4). | "Is it one study from start to end?" |
| `coverage` | Always present (C20). `question`: does the primary claim, by its falsifier, answer the `whole` research question or a `part`? With `part`, `tested_part` names the tested part in the question's words and `untested` lists every other part with the `terms` that name it and `by`, the non-primary claim that estimates or tests it. `by` may be a list when several secondary claims carry one part. `angle`: does the study cover the angle named in step7b's frontmatter? It is **decided at B4 by going through the angle phrase by phrase**, not as one verdict: `angle_parts` lists the angle's phrases — every content word of `angle` must appear in one of them — each with `by`, the claim or experiment that covers it, or `none`. Any `none` makes `angle` `part`, and `angle_dropped` then says which part no claim or experiment covers, and why. A part of the angle left out at B3.5 or B4, before any round, counts exactly like one cut later: `angle_dropped`, the Finish line, and the `consume` note. Two backstops run because both verdicts are self-assessed (C20): when `question` is `whole`, every key term that is in the question must also be in the primary claim's statement, falsifier or evidence; and a part said to be covered by a claim or experiment whose text contains none of the part's words is listed for the round-2 critique, which quotes what covers it or changes `by` to `none`. Rules: (1) a part of the question that no claim covers may not stay in the question — narrow the question (step7b section 5, RQ1, `question`) and fill `original_question`; (2) `question: "part"` is legal only while every untested part is carried by a named secondary claim, and `Title` and `Short Hypothesis` then say which part is tested (section 8); (3) `terms` are the words that name the untested part — C20 looks for them in the `Title`, and finding one is an ERROR repaired in the draft at once (a wording repair, section 5.2); (4) `angle: "part"` is reported at Finish and noted in the ledger at `consume` (research-cycle.md §6). | "Does the tested claim answer the whole question, or which part — and is the study still looking through the lens it was chosen for?" |
| `external_check` | Always present (C23). `synthetic`: `true` when the primary claim's evidence comes from simulated, injected or planted signals or effects. Then `real_data` names the experiment that ties the result to real recordings of the phenomenon, or is `none: <why, per candidate>`; `not applicable` when `synthetic` is false. `datasets`: the independent datasets (different site or amplifier) that carry the primary claim. With one entry, `second_dataset` names the experiment that repeats the primary contrast on a second independent dataset, or is `none: <why, per candidate>`; `not applicable` with two or more. `inventory` lists what was looked at and why each candidate does or does not serve, one entry per candidate in the form `<path or dataset>: <why>`: the `env-probe` data roots and every document in `$RD/datasets/`. "No data" may only be said after looking at the disk, and C23 holds a `none:` answer to that: no inventory, an entry without its reason, a document (`.md`, `.txt`, `.csv`, `.tsv`) of `$RD/datasets/` that no entry names, or a non-empty data root of the probe that no entry names (a path below it counts) is an ERROR. The reason per candidate meets the standard of a `not-fixed` doubt — a concrete obstacle; "no strength scale for real artifacts" is answered by a direction-only or rank check on real artifacts, which needs none. **A synthetic study is not let through on a first "none":** in round 1 (before `argument_r1.json` exists) `real_data: none:` is an ERROR, so the scheduled round-2 revision must try once to add the experiment; if it still cannot, the `none:` is then a WARN that becomes a Risk entry (`"No real-data validation: …"`), as a `second_dataset: none:` is from the start (`"Single dataset: …"`). `synthetic` is not a matter of taste: C23 warns when it is `false` while the study sentence, the predictor formula or a measure of the primary claim speaks of injected, simulated, synthetic or planted signals. A result that holds only inside its own injection model, or on one amplifier, is the first thing a reviewer of a simulation study objects to. | "Does this hold outside the model, or the one dataset, it was built in?" |
| `reader_doubts` | One row per separable doubt of a blind reader (section 7.2), at least one per restatement file that exists (C22); `[]` at depth `quick`. `source`: `restatement-1` or `restatement-2`. `level`: `design` when answering the doubt changes an experiment's data, measure, statistic, control or decision rule, or the primary claim; `wording` when rewriting the seven fields is enough; when unsure, `design`. `response`: `fixed` or `not-fixed`, with `how`. `not-fixed` needs in `how` the concrete obstacle, and `how` starts with its kind: `data:` (absent on this machine, as `env-probe` shows), `budget:` (which experiment, what cost) or `conflict:` (with which claim). "No gate forced a revision", "out of scope" and "future work" are not reasons (C22 ERROR). A `design` doubt marked `fixed` names in `how` the experiment or claim id that changed — a sentence added to an entry is a wording fix. A reader that states no doubt still gets one row (section 7.2). When the reader numbers its doubts, there is at least one row per number (C22). | "What did a reader who did not know the intended answer object to, and what was done about it?" |
| `experiments` | One row per `Experiments` entry. `role`: `instrument` builds or validates a tool the others need; `tests` bears on a claim; `control` isolates a mechanism or rules out a rival (ablation, injection, negative or positive control); `descriptive` reports or estimates without testing; `release` packages data or code. `tests` and `control` rows name at least one claim. A `descriptive` row that supplies the evidence of a `mode: estimate` claim names that claim too — every claim must be listed by a `tests`, `control` or `descriptive` row (C5). | "What is each experiment for?" |
| `tradeoffs` | One row for every revision that removes or demotes a claim, an experiment, a dataset, a contaminant or condition class, or an analysis; that changes a claim's `mode` or which claim is primary; or that changes an experiment's role — **whoever asked for it**. Promotions get a row too (`lost: "nothing: …"`). `gate` says what caused it: `compute` (the compute gate), `coherence` (an `argument-check` finding), `restatement` (a reader doubt or mismatch), `none` (the critique, the 12 questions, the author's choice). `ids` lists the claim and experiment ids of `argument_r1.json` the row accounts for; `[]` for a dataset, condition class or analysis that has no id. `lost` says what a reader can no longer learn from the study, or `nothing: <why>`. Three booleans, with their reasons in `why`: `still_answers_question` (false → rewrite the question or abandon, section 5.1; C16), `covers_gap` (does the study still address the gap as B3 described it? false → C19 ERROR), `covers_angle` (false → `coverage.angle` must be `part`). **B4 counts too**: a hypothesis, dataset, condition class or analysis that the by-construction check, the derivability screen or the budget removed while `step8_hypothesis.md` was first written gets its row then (`gate: none`, `ids: []`, since nothing has an id in `argument_r1.json` yet), and it is listed under "Claims set aside at B4" in step8 (research-cycle.md §4); a claim that B4 keeps as an estimate instead of a test records that in its own `estimate_because`. Empty list only when nothing was removed, demoted or re-roled at B4 or since round 1 (C19 compares with `argument_r1.json`: ids gone, `mode`, `primary`, `kind`, a claim that no longer reads as the same claim, an experiment's role or the claims it serves). A cut that leaves no row is invisible afterwards: nobody reading the argument can tell that the study once reached further, or why it stopped. | "What did the study once reach for, why did it stop, and is it still the study the gap and the angle called for?" |

Experiment ids are the `E<digits>` token at the start of an `Experiments` entry. New entries are written
`E3 [tests C1] …` — id first, then the role tag (section 8). `argument-check` also reads `**E0 …**` and `E3: …`
(existing archives) and the bracketed spelling `[E3 · tests C1]`, but do not write the last one: the experiment
stage recognises an id only at the very start of an entry and would renumber such a list. `evidence.experiment`,
`ruled_out_by` and `experiments[].id` use the bare id, `E3`.

**Per claim**

| Field | Rule | Reader question it answers |
|---|---|---|
| `primary` | Exactly **one** claim is `true`. Power and the main outcome are judged on it; the others are secondary (DCR ch. 2, ch. 5). This also holds for an idea merged from several generations (section 4.4). | "What is the one thing this study stands or falls on?" |
| `kind` | The five kinds need different support (Craft 8.1): `fact` — evidence that the situation is as stated; `definition` — reasoning about shared or distinguishing features; `cause` — facts connected so that one follows from the other, with rivals excluded; `evaluation` — stated criteria of judgement; `action` — a chain of the other four plus feasibility. Most ideas here are `fact` or `cause`. | "What sort of evidence should I expect?" |
| `mode` | `test`: a hypothesis exists — needs `falsifier` and `power.min_detectable`. `estimate`: descriptive or measurement-validity work — no H0/H1, fill `precision_target` instead (DCR ch. 5, ch. 6). `equivalence`: the claim is "no difference" — needs a margin fixed in advance and `controls.positive` (section 6.3). The primary claim may be `estimate` only when step7b declares `study: descriptive` (C21); turning a test claim into an estimate after round 1 is a demotion and needs a `tradeoffs` row (C19), and every estimate claim, from B4 on, says why it is one (`estimate_because`, C21) — otherwise relabelling is the cheapest way to take a claim that is true by construction out of C7 and C17. | "Is this a test or a measurement?" |
| `estimate_because` | **This pipeline's own rule.** Required on every `mode: estimate` claim (C21). It starts with one of: `descriptive:` — the quantity has no direction to test (how large, how reliable, how distributed); `size-open:` — the direction is settled and only the size is unknown; `by-construction:` — a test was planned or possible and was given up because its result was fixed in advance: say which test, and what a reader can no longer learn. A `by-construction:` value is listed by the check, judged in the round-2 critique (could a magnitude test with `direction-settled` replace it?) and reported at Finish under "scope given up". In a `study: analytic` generation where estimates outnumber tested claims, C21 says so. This is the record of a demotion made at B4, before `argument_r1.json` exists and before C19 can see anything. | "Why is this not tested?" |
| `expected_direction` | **This pipeline's own rule.** Required on every `mode: test` claim (C7). `direction`: what you expect the result to be before any data. `basis` starts with `settled:` (a citation, textbook physiology or physics, or the algebra of `construction` gives the direction), `contested:` (name who holds each side) or `unknown:` (why nothing predicts it). If you can name the direction and a settled basis, `negation.verdict` is `direction-settled`, not `contestable` — C7 raises when the two disagree. The verdict alone was a self-assessment nobody had to justify; this field asks the question the verdict depends on. | "Did you already know which way it would come out?" |
| `statement` | `mode: test` and `equivalence`: the working-claim form, *Although* {what the field holds, or a limit you concede}, {the claim} *because* {the main reason} (Craft 8.2.1). The *although* clause is step7b's common ground; the *because* clause is `reasons[0]`. A *because* clause that no evidence row with a decision rule bears on is a conjecture, not a tested reason: write "which we conjecture is because …" and list it in `scope.limits`. `mode: estimate`: one plain sentence — what is estimated, in whom, to what precision; an estimate has no thesis to set against a concession, and forcing the form yields a description of the design dressed as a reason. | "What do you claim, against what, on what ground?" |
| `reasons` | Statements that would make a reader accept the claim if they were shown to be true. Each needs an `evidence` row or a `warrant_basis`. | "Why should I believe it?" |
| `evidence` | Which experiment, which measure, and what result would count. A claim of fact cannot rest on reasoning alone — it needs a measured result (Craft ch. 11 Quick Tip). `measure` states the path from the raw value to the number the decision rule reads (per channel → epoch → subject), with each aggregation — two aggregation orders give two different numbers, and the test reads only one. | "What will you show me, and what exactly is the number?" |
| `evidence.refuted_if` | The result of this experiment that counts against the claim, with its threshold. Required on a row whose experiment has role `tests` for this claim, unless the claim's `falsifier` names that experiment id (C2). When several `tests` experiments bear on one claim, the one the falsifier names **first** decides; every other one needs its own `refuted_if` — being mentioned in the falsifier ("E6 is reported alongside") is not a rule. An experiment that "tests" a claim with no result that would count against it only illustrates it: give it a rule, or change its role to `descriptive`. | "What would this experiment have to show for you to back down?" |
| `evidence.can_fail` | **This pipeline's own rule.** Required on every row of a `kind: cause` claim and of the primary claim (not for `mode: estimate`). Write where the manipulation or the contrast acts — channels, band, time window, labels, subjects — and where the measure is computed, then `yes: …` or `no: …`: could this measure have come out otherwise? It is `no` in two cases: the measure is computed outside what the manipulation touches (the null result is guaranteed), or it is computed on exactly what the manipulation removes or what defines the other side of the contrast (the effect is guaranteed). A claim needs at least one `yes` row (C17). Answer from the two locations and from `construction`, not from how convincing the experiment feels: a cell that begins `yes:` and ends "for this family the answer is nearer to no" is a `no`. | "Could this experiment have told you that you were wrong?" |
| `construction` | **This pipeline's own rule.** Required on the primary claim and on every `kind: cause` claim, unless `mode: estimate` (C17). `predictor_formula`: the manipulated dose, contrast or predictor, as a formula or as its support (channels, band, window, labels). `outcome_formula`: the number the falsifier reads. `shared_terms`: every symbol or support present in both, each spelled as it appears in both formulas; `[]` only after comparing (C18). Write quantities as subscripted symbols (`RMS_r`, `x_i`, `sigma_bg`): the check reads both formulas, and a subscripted symbol that is in both and not in the list is an ERROR, an all-capitals token (`RMS`, `R01`) a WARN to answer in question 8 — a list left empty no longer passes by itself. `computable_without_experiment`: substitute the predictor formula into the outcome formula and simplify — if what remains contains only quantities already measurable in existing data (the clean recordings, a published table), the answer is `yes: …` or `partly: <which part, from which existing data>`; otherwise `no: …`, and with a non-empty `shared_terms` a `no:` says what happens to each shared term in the substitution (C17 warns when the answer does not mention it). `yes` fails (C17): the result follows from existing data or algebra, so no experiment tests the claim. `partly`: the computable part is excluded from the falsifier and named in `Short Hypothesis` sentence 4 (section 8). `free_quantity`: the quantity the design does not fix, on which the result depends — if you cannot name one, the result is fixed. The formulas are written in `step8_hypothesis.md` first (section 4.3). `can_fail` alone was a yes/no cell that could be filled by gesture; the formulas make the algebra happen before the check runs. | "Is the result fixed before the experiment runs?" |
| `warrant` | The general principle that makes this evidence relevant to this claim: "When <general circumstance>, then <general conclusion>". The reason must be an instance of the circumstance and the claim an instance of the conclusion (Craft 11.3, 11.4). | "Why does that measurement count as evidence for that claim?" |
| `warrant_basis` | Where the principle comes from: a citation key, an `exp_id`, `(field convention)` or `(TBD)`. `(TBD)` does not fail the gate, but section 7.1 question 7 will ask about it. | "Does this field accept that inference?" (Craft 11.4) |
| `outcomes` | What is learned if the claim is supported **and** what is learned if it is not. The two must differ, and neither may be "nothing" (DCR ch. 2, Relevant). | "Is the study informative either way?" |
| `negation` | Reverse the claim and judge the reverse. `contestable`: a competent reader could hold it. `direction-settled`: the direction follows from textbook knowledge, an idealised model or algebra; the size or location on real data does not — the commonest case on a measurement topic, and one that is neither contestable nor trivial. `obviously-false` or `trivial`: the original claim needs no argument (Craft 8.2.2, which uses the reversal only to gauge how significant a claim is, and notes that some self-evident claims have been contradicted successfully). Passing verdicts: `contestable` and `direction-settled` (C7). Using the reversal as a blocking check for claims that are true by construction is this pipeline's rule. The verdict is a self-assessment and tends to come out optimistic, so it is asked again twice: of the author through `expected_direction` (a direction with a settled basis is `direction-settled`), and of the design through `construction` (C17, C18). On a `mode: estimate` claim `negation` may be `null` and C7 does not read it — an estimate asserts no direction; why it is an estimate is `estimate_because`. | "Would anyone disagree — and about what, the direction or the size?" |
| `smallest_effect_of_interest` | The magnitude, in outcome units, below which the result would change nothing, with its basis (`design choice: …` or a citation key). Required when `negation.verdict` is `direction-settled` and `mode` is `test` or `equivalence` (C7); optional otherwise. When the direction is known in advance, "different from zero" is a test nobody can lose. | "How large must it be to matter?" |
| `falsifier` | A concrete result with a threshold fixed now ("AUC < 0.55 in E3", "CI of the difference includes 0"). A hypothesis written after the data are seen generates hypotheses; it does not test one (DCR ch. 5). (a) With `direction-settled`, the threshold is `smallest_effect_of_interest`, never zero (C7). (b) The statistic keeps the sign the mechanism predicts — an absolute value only when the claim itself is unsigned, and then `scope.limits` says why (C17 warns when the primary claim's falsifier or a measure takes an absolute value and no limit mentions it); an absolute value cannot tell the predicted direction from its opposite, and it changes what a planted effect returns (`controls.positive_expected`). (c) When several `tests` experiments bear on the claim, name the deciding one first; each of the others has its own `refuted_if` (C2). (d) `null` for `mode: estimate`. | "What result would make you withdraw the claim?" |
| `rivals` | Other explanations for the same result. For an association the basic four are `chance`, `bias`, `reverse-cause`, `confounding` (DCR ch. 9, Table 9.1). `selection` = conditioning on a shared effect, e.g. keeping only subjects above an accuracy cut (DCR ch. 9); spectrum and verification problems of a test study (DCR ch. 12) are also filed under `selection` — that is this pipeline's shorthand, the book treats them as separate biases. The type list beyond the basic four is this pipeline's composition. Give `how` in terms of this study, not in general. `ruled_out_by` names an experiment id or a control, or is `(not addressed)` — which is allowed (except below) and is copied to `Risk Factors` at finalize. Leave out a type that cannot arise in this design — no "not applicable" rows; the exception is the four types C8 demands on a cause claim, where `ruled_out_by` says why it cannot arise (`design: the factor is assigned`). | "What else could produce this result?" (Craft ch. 10 Quick Tip) |
| `rivals.main` | Boolean. Exactly one rival of the primary claim has `true` (primary claims with `mode` `test` or `equivalence`; C24): the explanation a skeptical reader of the target venues reaches for first. It may not be `(not addressed)`. A rivals table can be complete by type and still omit the one objection every reviewer will raise; naming it forces the negative control to be aimed at it. | "What is the first thing a reviewer will say instead?" |
| `rivals.type = incorporation` | The two sides of a contrast share a component, so part of the result is built in: a predictor that is part of how the outcome is defined (DCR ch. 12), or — this pipeline's extension to cause claims — a manipulation applied to exactly the support a measure is computed on. **Test every claim for it, whatever its kind**: write out both formulas (or both supports: channels, band, window, labels) and look for a shared term — on the primary claim and on cause claims these are the two formulas of `construction`, and a non-empty `shared_terms` requires this rival (C18). On the primary claim and on any `kind: cause` claim, `(not addressed)` is an ERROR (C18), not a note for `Risk Factors`: writing the weakness down without changing the design is how a built-in result reaches the paper. There, `ruled_out_by` names the experiment (`E<n>`) that separates the shared component, or starts with `design:` and says which part of the endpoint was removed — an experiment that re-expresses the built-in part in other units does not separate it. | "Is the result partly true by construction?" |
| `rivals.type = leakage` | **This pipeline's own addition; none of the three books lists it.** Every experiment here is a machine-learning experiment, and train/test leakage (subject overlap across splits, preprocessing fitted on test data, a threshold tuned on the evaluation set) is its most common source of bias, so it gets its own name instead of hiding under `bias`. | "Did the model see the answer?" |
| `controls` | `negative`: an outcome or manipulation that should show nothing if the claimed explanation is right — fixed in advance (DCR ch. 8; ch. 12 Example 12.1). `positive`: the same pipeline recovering an effect known to exist. The negative control is aimed at the `main` rival unless another experiment already rules that rival out, and it states the value the falsifier's statistic returns when the control behaves as expected — not always zero. A check aimed at a rival nobody raises is an `instrument` step, not a control. `negative_can_move` (this pipeline's own rule; required on the primary claim and on a `kind: cause` claim when `controls.negative` is filled): does the control act on the data the measure is computed from? `yes: …` / `no: …`. A control that cannot reach the measure — noise in channels the decoder never reads — returns "no effect" whether the claim is right or wrong, so it controls nothing (C17). `positive_expected` (this pipeline's own rule; required when `controls.positive` is filled on the primary claim, a `kind: cause` claim or a `mode: equivalence` claim; C17): the value the falsifier's statistic returns for the planted effect, with the derivation through that statistic (absolute values, ranks, thresholds, clipping, ceilings) and the condition under which it holds. A positive control whose planted value cannot come back out of the statistic fails for a reason that has nothing to do with the claim: when the falsifier, a measure or the outcome formula takes an absolute value, a rank, or clips, `positive_expected` must say what that does to the planted value (`|d + k| − |d|` equals `k` only when `d ≥ 0`) — C17 warns when it does not. A primary `test` claim with no positive control at all is listed by C17 and becomes a Risk entry: nothing then shows the pipeline would find the effect if it were there. The whole `controls` object is `null` on a `mode: estimate` claim. | "Would your pipeline show an effect where there is none? Would it find one of that size if it were there?" |
| `baseline_predictor` | For a new measure: the existing, cheaper predictor it must add to (DCR ch. 12). `null` when not applicable. When set, an `evidence` row **of this claim** must name it in its `measure` — the full name, or an alias given in parentheses, e.g. `calibration accuracy (M_cal)` (C15). | "What does this tell me that I did not already know?" |
| `comparator` | Required when `baseline_predictor` is set: what the contrast in `falsifier` is against. It must be the baseline predictor, named first (the check reads only what comes before the first comma, semicolon or "and") — **the falsifier of a claim with a baseline predictor is the increment over that predictor** (section 6.1, rung 3). A contrast against a weaker comparator (generic quality, chance, an intercept-only model) may only be a secondary claim: winning it shows nothing the baseline did not already show. Measuring the baseline and then reporting the increment as a secondary, two-sided comparison does not satisfy this (C15). | "Better than what?" |
| `scope` | `internal`: what may be claimed about these data. `external`: where it generalises and where it does not. `limits`: conditions under which the claim holds (Craft 8.3; DCR ch. 1). The writeup may not claim beyond it. | "How far does this go?" |
| `power` | From `ideate_tools.py power` (below). `min_detectable` records the sidedness. `null` on a `mode: estimate` claim — `precision_target` carries the number there. | "Could this study have detected the effect at all?" |
| `precision_target` | `mode = estimate` only: the confidence-interval width aimed for, and the width the available n gives. An estimate claim produces a `Risk Factors` entry only when this field says the interval is wider than the aim. | "How precisely will you know it?" |

**`power`.** The sample size is fixed by the public datasets, so work backwards: given n, what is the smallest effect
detectable at 80 % power (DCR ch. 6, "What to do when sample size is fixed")?

```bash
$PY $SK/scripts/ideate_tools.py power --mode corr      --n 109            # smallest detectable |r|
$PY $SK/scripts/ideate_tools.py power --mode two-group --n1 54 --n2 55    # smallest detectable standardized difference
$PY $SK/scripts/ideate_tools.py power --mode paired    --n 109            # same, paired design
$PY $SK/scripts/ideate_tools.py power --mode paired    --n 109 --sided 1  # one-sided decision rule (default --sided 2)
$PY $SK/scripts/ideate_tools.py power --mode equivalence --n 109          # smallest margin at which equivalence can be shown (two one-sided tests); or --n1 --n2
$PY $SK/scripts/ideate_tools.py power --mode paired    --n 109 --effect 0.5   # largest SD at which an effect of 0.5 raw units is detectable
$PY $SK/scripts/ideate_tools.py power --mode estimate  --n 109 --sd 0.08  # total width of the 95 % confidence interval
```

- Match the command to the decision rule: `--sided 1` when the falsifier is one-sided, `--mode equivalence` for a
  `mode: equivalence` claim. A two-sided figure pasted under a one-sided rule, or a `paired` figure standing in for an
  equivalence test, answers a different question from the one the claim asks.
- **Never a placeholder `--sd`.** When no source reports the spread of the outcome, omit `--sd` and report the result in
  SD units; when `smallest_effect_of_interest` is in raw units, add `--effect <that value>` (not for `corr`) and record
  in `min_detectable` the largest SD at which that effect is detectable. `--sd 1.0` only restates the SD-unit figure
  with a raw unit attached, which says nothing about whether the effect can be seen. With the SD `(TBD)` the verdict
  is `marginal`, as for a `(TBD)` literature effect.
- `unit` is the **independent** unit. For EEG work that is `subjects`, never trials or epochs: thousands of epochs from
  20 subjects are 20 units. When subjects come from several datasets, name them in `clusters`; the effective sample
  size then lies between the number of clusters and the number of subjects (DCR ch. 6, Clustered samples; ch. 11).
- `literature_effect` comes from B2 "B. Reported numbers" with its citation key, or is `(TBD)`. Never invent one.
- `verdict`: `adequate` when the literature effect is at least `min_detectable`; `marginal` when it is between about
  0.7 × and 1 × `min_detectable` (roughly 50–80 % power), or when the literature effect is `(TBD)`; `underpowered` below
  that. These thresholds are this pipeline's own, not the book's. Three levels only — the calculation is a normal approximation and understates the needed sample when n < 30, so a
  finer verdict would be false precision.
- If you change the hypothesis to gain power (a continuous outcome, a paired design, a larger expected effect), check
  that the new hypothesis still answers the research question (DCR ch. 6) and record the change in `tradeoffs`.

**`representation`.** Write the question next to the plan and ask three things (DCR ch. 9, Fig. 9.1): does the *sample*
stand for the population the question is about; does the measured *predictor* stand for the phenomenon; does the
measured *outcome* stand for the phenomenon. `precision` (repeatable?), `accuracy` (close to the truth?) and `validity`
(does it measure the intended thing at all?) are three separate properties — a perfectly repeatable score can measure
the wrong thing (DCR ch. 4). `validity` names the kind and its basis: `face`, `content`, `construct`, `predictive` or
`criterion`. Prefer a measure the field has already validated, so the result is comparable with earlier work (DCR
ch. 4). Reader question: "is the thing you measured the thing you are talking about?" A proxy that quietly replaces the
phenomenon is how a study ends up answering a different question from the one it states (DCR ch. 1, Fig. 1.5).
For a factor the experimenter assigns (an injected dose, a condition label), write `assigned` for `precision` and
`accuracy` — they carry no information there — and put the effort into `validity`: does the assigned factor stand for
the phenomenon the question names?

### 4.3 Split with `step8_hypothesis.md`

`step8_hypothesis.md` stays the narrative working draft: research questions, hypotheses, operational definitions,
scope, framework diagram, risks, rival explanations, traceability, and the by-construction formulas, which are written
there first (research-cycle.md §4) and copied into `construction`. Some fields have no place in step8 and are written
first in `argument.json`: `study_sentence`, `variant`, `warrant`, `warrant_basis`, `outcomes`, `negation`,
`representation`, `coverage`, `external_check`, `reader_doubts`, `tradeoffs`. Everything else is extracted from step8,
and step8 wins a disagreement: fix the JSON. After every `ReviseHypothesis`, update `argument.json` and re-run
`argument-render` before the next `argument-check`.

### 4.4 An idea merged from several generations

When the user merges ideas of several generations into one idea with several hypotheses, the merged idea is still one
argument: name **one** primary claim and make the others secondary — three co-equal primaries fail C1 and leave no
rule for what the study concluded. Give the merged idea a generation folder of its own, the next free `gen_{k}/`, with
its `step7b_problem.md`, its `argument.json` and the merged 7-key idea as `idea.json`. `argument-check $RD/gen_{k}`
then runs as for any generation, and `link-run` finds the folder by the idea's `Name` and fills `problem` and
`argument`. Without such a folder, `link-run` writes `generation_dir`, `problem` and `argument` as `null` and the
later stages take their old path.

---

## 5. Gates

Two gates, both with the compute gate's behaviour: force one `ReviseHypothesis`, then finalize regardless and record
the doubt — plus a reader whose doubts must be answered (section 7.2). None of them asks the user anything.

### 5.1 Worth-it check (after a compute-gate revision) and what a cut leads to

When the compute gate (research-cycle.md §5) has forced a revision and the experiments were scaled down, answer in
`reflection_log.md`:

1. Does the reduced sample still stand for the original population?
2. Does the reduced measurement still stand for the original phenomenon?
3. What is the primary claim's `power.verdict` now? (Re-run `power`.)
4. Does the research question need rewording?

Which changes get a `tradeoffs` row, and what the row holds, is in section 4.2 (`tradeoffs`): every revision that
removes, demotes or re-roles something writes one, whichever gate — or none — asked for it. Three outcomes follow from
a row's booleans:

- `covers_angle: false` → set `coverage.angle` to `part` and say in `angle_dropped` what is no longer covered (C19).
  The idea goes on; the loss is reported at Finish and noted in the ledger, so a later generation can take up the rest.
- `covers_gap: false` → C19 ERROR: the study no longer addresses the gap it was selected for. Restore what was cut,
  or abandon the pair (below).
- `still_answers_question: false` → choose one:
  - **Rewrite the question** to the one the reduced study really answers, in `step7b_problem.md` section 5 and in
    `question`, and fill `original_question` with the old wording and the reason; or
  - **Abandon this `(gap, angle)`** — do not `consume` it. What happens next is in research-cycle.md §5: the next
    documented gap of this generation restarts from B3.5 in the same `gen_{k}/`, and the last remaining gap is never
    abandoned — rewrite its question instead. List the abandoned pair in the Finish report with the reason.

Before a restart in the same `gen_{k}/` — after an abandoned pair, or when a resumed generation redoes B4 or round 1
(research-cycle.md §3.5, "Resuming") — delete `idea_draft.json`, `step8_hypothesis_r1.md`, `step7b_problem_r1.md`,
`argument_r1.json`, `restatement_1.json` and `restatement_2.json`: they belong to the attempt that ended, and C16, C17,
C19, C21, C22 and C23 would otherwise compare the new argument with the old one, and the old reader's file would count
as the reader of a draft it never saw. (`cp -n` does not overwrite, so a stale copy survives unless it is deleted.)

Keeping the original question while running the reduced experiments is **not** an option: the idea would promise one
study and deliver another. Reader question: "after everything you cut, is this still worth doing?" Designing a study is
a negotiation, and a step that is sometimes skipped is deciding whether what remains is still worth having (DCR ch. 1,
Trade-offs).

### 5.2 Coherence gate — `argument-check`

```bash
$PY $SK/scripts/ideate_tools.py argument-check $RD/gen_{k} [--idea <idea.json> | --no-idea] [--json]
```

Run it three times: in round 1 with `--idea …/idea_draft.json`, on the draft the first reader is about to see; after
the round-2 revision with `--no-idea`, because the draft is stale until round 3 rewrites it; and before `FinalizeIdea`
with `--idea …/idea_draft.json`. Without either flag the idea file is `gen_{k}/idea.json`, then
`gen_{k}/idea_draft.json`. With `--no-idea` the parts of C3, C10 and C20 that read the seven fields (`Experiments`, `Title`,
`Short Hypothesis`) are skipped, and each prints one `NOTE` line saying so; all of them run in the pre-finalize pass. Output is one line per finding — `ERROR C7 C2: …`, `WARN C10: …` (check id, then claim id when one
applies). Exit code 1 = at least one ERROR, 0 = none, 2 = bad input: no `argument.json` in the folder (an old
generation: follow the old flow), or an `argument.json`, idea file, `argument_r1.json` or restatement file that cannot
be read (a restatement file must be the reader's JSON object with its `biggest_doubt`), or a value in
`argument.json` of a shape the script cannot read. Exit 2 is never a reason to revise the hypothesis; fix the file.

Besides `argument.json` and the idea file it reads the following, **each only when it exists**, so a generation
written before these files keeps working:

| File | Used by | When absent |
|---|---|---|
| `gen_{k}/argument_r1.json` (the round-1 copy) | C16, C17, C19, C21, C22; C23 reads only whether it exists | the comparisons with round 1 are skipped; C23 treats the run as round 1 |
| `gen_{k}/step7b_problem.md` — the line `study: <word>` in its first 40 lines | C21 | file absent → `NOTE C21`; line absent → treated as `analytic` |
| `gen_{k}/step7b_problem_r1.md` — the same line in the round-1 copy | C21 | the study is taken to have been what it is now |
| `gen_{k}/restatement_1.json`, `restatement_2.json` — the file's existence, its `tested_part` and its `biggest_doubt` | C22 | no C22 finding about a reader |
| the idea file: `Experiments`, `Title`, `Short Hypothesis` | C3, C10, C20 | see `--no-idea` above |
| `$RD/step0_session_config.json` → `local_environment.probe` (present or not, and its non-empty `data_roots`) | C23 | ignored |
| `$RD/datasets/` — the names of its `.md`, `.txt`, `.csv` and `.tsv` files | C23 | nothing to name in the inventory |

The round-1 copies are frozen once, at the end of round 1, and never overwritten:
`cp -n $RD/gen_{k}/step7b_problem.md $RD/gen_{k}/step7b_problem_r1.md; cp -n $RD/gen_{k}/step8_hypothesis.md $RD/gen_{k}/step8_hypothesis_r1.md; cp -n $RD/gen_{k}/argument.json $RD/gen_{k}/argument_r1.json`.
They are what the later checks measure a revision against.

The checks and their levels are this pipeline's own; the rule each one enforces is cited in section 4.2 or 6.

| # | Check | Level |
|---|---|---|
| C1 | `claims` has exactly one `primary: true` | ERROR |
| SCHEMA | the file has the required keys and every enumerated field holds an allowed value — among them `variant`, `negation.verdict`, `tradeoffs[].gate`, the `reader_doubts` fields, `coverage.question` and `coverage.angle`; `tradeoffs[].ids`, `construction.shared_terms` and `external_check.datasets` (non-empty) are lists; `covers_gap`, `covers_angle` and `external_check.synthetic` are booleans | ERROR |
| C2 | every `mode: test` claim has a `falsifier` and at least one `evidence` row; every `mode: estimate` claim has a `precision_target`; for a `test` or `equivalence` claim, every experiment with role `tests` that lists the claim has a decision rule — it is the first experiment the `falsifier` names (the deciding one), or it has an evidence row of the claim with `refuted_if`; a later mention in the falsifier is not a rule | ERROR |
| C3 | every `evidence.experiment` and every `experiments[].id` matches an entry of the idea's `Experiments` | ERROR |
| C4 | every experiment has a `role`; a `tests` or `control` experiment names at least one claim | ERROR |
| C5 | no orphan claim — each claim is listed by an experiment whose role is `tests`, `control` or `descriptive` | ERROR |
| C6 | `outcomes.if_supported` and `outcomes.if_not` are both non-empty and differ | ERROR |
| C7 | not read on a `mode: estimate` claim. `negation.verdict` is `contestable` or `direction-settled`; with `direction-settled` on a `test` or `equivalence` claim, `smallest_effect_of_interest` is filled and the `falsifier` does not compare with zero ("includes / overlaps / crosses / spans 0", "≤ 0", "= 0", "at most zero", "not positive"; "below 0.5" and "p > 0.05" are not such comparisons); a `test` claim has `expected_direction` with a `direction` and a `basis` starting `settled:`, `contested:` or `unknown:`, and a `settled:` basis does not sit beside the verdict `contestable` | ERROR |
| C8 | a `kind: cause` claim's `rivals` cover `chance`, `bias`, `reverse-cause` and `confounding`, and one experiment has `role: control` | ERROR |
| C9 | a `mode: equivalence` claim has `controls.positive` and a `falsifier` that states the margin | ERROR |
| C10 | every `key_terms` entry appears in `question`, in at least one `statement` and in the `Experiments` entries read as one text (a term may be split across two entries) | WARN |
| C11 | all three `representation` blocks are filled and each `validity` gives a basis | WARN |
| C12 | the primary claim's `power.verdict` is not `underpowered` | WARN |
| C13 | lists every rival whose `ruled_out_by` is `(not addressed)`, one line per rival with the start of its `how` | WARN |
| C14 | lists every claim whose `warrant_basis` is `(TBD)`, and the primary claim when its `warrant_basis` is exactly `(field convention)` | WARN |
| C15 | when `baseline_predictor` is not null: an `evidence[].measure` of the same claim names it (every word of the name, or its parenthesised alias), and `comparator` starts with it — the falsifier is the increment over the baseline | ERROR |
| C16 | `original_question` is null or `{text, changed_because}` with `changed_because` starting `data:`, `budget:`, `coherence:`, `restatement:` or `wording only:` — any other shape is an ERROR and counts as null; no `tradeoffs` row has `still_answers_question: false` while `original_question` is null; and `question` does not differ from the one in `argument_r1.json` (dashes, quotes and whitespace aside) while `original_question` is null | ERROR |
| C17 | on a `kind: cause` claim and on the primary claim (not `mode: estimate`): every evidence row has `can_fail`, and at least one is `yes`; `construction` is present with both formulas; `computable_without_experiment` starts with `no`, `partly` or `yes`, and `yes` fails; `free_quantity` is filled; with a negative control, `controls.negative_can_move` is `yes`; with a positive control (also on any `mode: equivalence` claim), `controls.positive_expected` is filled. Listed as WARN: `partly`; a `no:` that does not mention a shared term; a primary `test` claim with no positive control; a statistic that takes an absolute value, a rank or a clip while `positive_expected` does not say what that does to the planted value; an absolute value on the primary claim with no `scope.limits` entry about it; a primary claim whose `id`, `statement` or `mode` changed since `argument_r1.json` while `construction` or `positive_expected` is word for word the same | ERROR (the listed cases → WARN) |
| C18 | no `incorporation` rival with `ruled_out_by: (not addressed)` on the primary claim or on a `kind: cause` claim, and its `ruled_out_by` names an experiment of `experiments[]` or starts with `design:`; on a claim with `construction`, every `shared_terms` entry occurs in both formulas, non-empty `shared_terms` come with an `incorporation` rival, and no subscripted symbol (`RMS_r`) occurs in both formulas without being listed; an unlisted all-capitals token in both (`RMS`, `R01`) is asked about | ERROR (the all-capitals token → WARN) |
| C19 | revision ledger. Rows: every `tradeoffs` row has `lost`; none has `covers_gap: false`; none has `covers_angle: false` while `coverage.angle` is not `part`. Ledger (when `argument_r1.json` exists): every claim of round 1 that is gone, or whose `mode`, `primary` flag or `kind` changed, or whose statement no longer reads as the same claim (no key term and almost no word in common — a reused id), and every experiment of round 1 that is gone, whose `role` changed, or that now serves other claims, is listed in the `ids` of a `tradeoffs` row | ERROR |
| C20 | coverage. `coverage` is present; `question: "part"` has a `tested_part` and a non-empty `untested`, each item's `by` naming a non-primary claim (or several); `angle: "part"` has `angle_dropped`; `angle_parts` is present, each part's `by` is a claim id, an experiment id or `none`, any `none` comes with `angle: "part"`, and every content word of `angle` appears in some part. With an idea file: no `untested[].terms` entry occurs in the `Title`. Listed as WARN: with `question: "whole"`, a key term that is in the question but not in the primary claim's statement, falsifier or evidence; an angle part none of whose words occurs in the text of the claim or experiment said to cover it; a `Short Hypothesis` that does not contain the research question as `argument.json` words it | ERROR (the listed cases → WARN; without an idea file → NOTE) |
| C21 | estimate guard. Every `mode: estimate` claim has `estimate_because` starting `descriptive:`, `size-open:` or `by-construction:`. A primary claim with `mode: estimate` needs `study: descriptive` in `step7b_problem.md`; and when round 1's primary was not an estimate, `original_question` is filled. Listed as WARN: each `by-construction:` estimate; estimates outnumbering tested claims in a `study: analytic` generation; an estimate primary in a study that `step7b_problem_r1.md` declared `analytic` | ERROR (the listed cases → WARN; no step7b → NOTE) |
| C22 | reader doubts. Every `restatement_<n>.json` that exists has at least one `reader_doubts` row with `source: restatement-<n>`, and at least as many rows as the reader numbered doubts. A `not-fixed` row's `how` starts `data:`, `budget:` or `conflict:` (SCHEMA) and does not say "no gate", "not forced", "out of scope" or "future work"; a `design` doubt marked `fixed` names the experiment or claim id that changed. With `coverage.question: "whole"`, the latest reader's `tested_part` says "all of it" — unless `original_question` records a change made for `restatement:` or `coherence:`. Lists every row with `response: not-fixed`. When `restatement_1.json` and `argument_r1.json` exist, the primary claim changed since round 1 (`id`, `statement`, `mode`, `falsifier`, `comparator` or `baseline_predictor`) and there is no `restatement_2.json`: the second blind restatement is due | ERROR (the two lists → WARN) |
| C23 | external check. `external_check` is present; with `synthetic: true`, `real_data` — and with one entry in `datasets`, `second_dataset` — names an experiment of `experiments[]` with role `tests`, `control` or `descriptive`, or is `none: <why>` with an `inventory` whose every entry reads `<path or dataset>: <why>` and which names every document of `$RD/datasets/` and every non-empty data root of the probe. `real_data: none:` is an ERROR in round 1 (no `argument_r1.json` yet). Listed as WARN: a `none:` that meets these conditions; `synthetic: false` while the study sentence, the predictor formula or a measure of the primary claim speaks of injected, simulated, synthetic or planted signals; a session config without `local_environment.probe` | ERROR (the listed cases → WARN) |
| C24 | main rival. On a primary claim with `mode` `test` or `equivalence`, exactly one rival has `main: true`, and it is not `(not addressed)` | ERROR |
| C28 | the planning block's later files (decision tree, attack plan, packaging) were built on the current `argument.json` (their `based_on`); a revision entering at P1 or P2 redoes them, never patches them ([planning/README.md](planning/README.md)) | ERROR |
| C25–C27 | the planning block's P1, only for a generation that took a question from the fusion block (`gen_k/question.json`): the primary claim's `derivation` (C25), the field's rival accounts as rivals with ids (C26), the handed-over numbers in the direction and the power (C27). Defined in [planning/P1-gap2hypo.md](planning/P1-gap2hypo.md) | ERROR (some → WARN, listed there) |

C15 reads only the claim's own `evidence[].measure` rows, not the idea's `Experiments`: an entry there is long enough
to contain any word. C17 and C18 exist because C7 rests on a verdict the author assigns; they ask the same question —
is the result fixed before the experiment runs? — from the design itself. C19 and C21 ask whether a claim escaped
that question by being cut or relabelled an estimate, and C20, C23 and C24 whether what is left is anchored: to the
whole question, to data outside the model or the one dataset it was built in, and to the rival a reviewer raises
first. C22 does the same for the one reader who did not know the intended answer. Several fields these checks read
are self-assessments (`coverage`, `shared_terms`, `negation.verdict`, `external_check.synthetic`, a doubt's
`response`), so each is asked a second time from text the author did not write for the purpose: the claim's own
statement and measures, the two formulas, the reader's file, the names of the files on the disk. A field that any
non-empty text satisfied was a form, not a check.

- **ERROR in round 1** → fixed in the scheduled round-2 revision. This does **not** use the gate's forced revision.
- **ERROR after the round-2 revision** (the `--no-idea` run) → repaired at once when it is bookkeeping (a missing
  `tradeoffs` or `reader_doubts` row); otherwise it goes to round 3.
- **ERROR in the pre-finalize run** → the next action is forced to `ReviseHypothesis`, once, however many findings
  there are. This is the gate's one forced revision.
- **Wording repairs cost no revision.** A finding that reads only the seven fields — C20's "Title names an untested
  term" (ERROR) and "Short Hypothesis does not contain the research question" (WARN) — is repaired in
  `idea_draft.json` at once and the check is run again, like a missing `tradeoffs` row or a `wording` doubt of
  restatement 2. It never uses the forced revision, and a draft is not finalized with one standing.
- **Blind-restatement failures (section 7.2).** After restatement 1, a mismatch or a doubt is input to the scheduled
  round-2 revision and uses no forced revision. After restatement 2, a mismatch on any criterion or a doubt of level
  `design` counts as a failure of this gate: together with any ERROR of the pre-finalize run it is served by the same
  one forced revision.
- **Fix the argument, not the JSON.** An ERROR on C2, C7, C15, C17, C18, C21, C23 or C24 means the claim, the
  experiment or the control must change — give the experiment a decision rule, state the falsifier against a
  magnitude, move the control to where the measure is computed or aim it at the main rival, make the falsifier the
  increment over the baseline (C15), restore a testable primary claim, add the experiment that reaches real data — not
  that a field should be edited until the check passes.
- **WARN** → listed in `reflection_log.md` and judged in the round-2 critique (section 7.1); a WARN never forces a
  revision. Six kinds reach `Risk Factors and Limitations` at finalize whatever the critique decides (the same list as
  research-cycle.md §5): C13 items (rivals not addressed); a C17 `partly` (the computable part, also named in
  `Short Hypothesis` sentence 4); C17 "no positive control"; C21 "Primary claim downgraded to an estimate"; C22
  `not-fixed` doubts, as `"Blind restatement unresolved: …"`; C23 `none:` answers, as `"No real-data validation: …"`
  or `"Single dataset: …"`. (Power that is not `adequate` also becomes an entry; it comes from `power.verdict`, not
  from a WARN.) Three kinds ask for an answer written in the round-2 critique instead of a risk entry: the C20 lines
  (quote what covers the term or the angle part, or change `coverage`), the C18 all-capitals line and the C17 lines
  about the statistic and about a rewritten primary claim (question 8 and question 6), and the C21
  `by-construction:` line (question 4). The one WARN that asks for an action is C22's "run the second blind
  restatement".
- **Still failing after the forced revision** → finalize anyway and add to `Risk Factors and Limitations`:
  `"Coherence unresolved: {check id and what it says}"`, one entry per remaining ERROR.

### 5.3 Rounds

The budget is stated once, in research-cycle.md §5 "Round cap", and applies here unchanged: `num_reflections` rounds
(3 by default) plus at most one for each gate — compute and coherence — so at most `num_reflections` + 2 (5 with the
default); both gates failing in the same round are served by one revision and add one round; a forced revision that
lands in a round already planned as a revision adds nothing. Blind restatements: at most 2 per `(gap, angle)`
attempt, and none follows a forced revision made in the finalize round or after it — the loop must end. The loop
never touches the network.

---

## 6. Variants by claim type

The primary claim's form decides which extra rules apply. `variant` lives in `argument.json` and is set at B4, when
the primary claim is written — step7b is finished before any claim exists, so it carries only `study` (section 2.2).
Every `ReviseHypothesis` that changes the form of the primary claim updates it; when the new value is `biomarker`, B4
or the revision adds the `Ladder rung: n` line to step7b section 5.

| Primary claim reads like | `variant` | `kind` / `mode` |
|---|---|---|
| "measure X predicts / discriminates / stands for Y" | `biomarker` | `fact` / `test` or `estimate` |
| "X produces, drives or explains Y" | `cause` | `cause` / `test` |
| "X makes no difference to Y", "A is as good as B" | `equivalence` | `fact` / `equivalence` |
| "how large / how reliable / how distributed is X" | `estimate` | `fact` / `estimate` |
| "X is / is not the same across recordings, sessions, sites or conditions" | `invariance` | `fact` / `test`, `equivalence` or `estimate` |
| none of these | `none` | — |

### 6.1 Biomarker / test claims (DCR ch. 12)

Reader questions: "is it the same thing measured twice?", "compared with what I already have, why bother?"

A measure's usefulness is established in steps of increasing stringency. The ladder is adapted from DCR ch. 12,
Table 12.1: the book's row on the costs, risks and acceptability of a test is left out (it does not apply to offline
analyses), and a rung for added value over the existing predictor is inserted, following the book's passage on what a
new test adds; placing it before the decision rung is this pipeline's reading. At B4, state in `step7b_problem.md` section 5 which rung this study reaches
(`Ladder rung: n`). **Never claim a rung the study does not reach**, and do not claim rung n when rung n−1 is unknown
for this measure — say so in `scope.limits` instead.

| Rung | Question | Design it needs | Report |
|---|---|---|---|
| 1 | Is it reproducible? | repeated measurement of the same subjects (across sessions, across splits) | within-subject variability, coefficient of variation, distribution of differences — not a correlation coefficient. (ICC is this pipeline's addition for continuous EEG measures; the book lists agreement, kappa, coefficient of variation and the distribution of differences.) |
| 2 | Is it accurate? | comparison against a reference standard | sensitivity, specificity, ROC, interval likelihood ratios, with confidence intervals |
| 3 | What does it add? | comparison against the existing predictor | the increment: reclassification, or gain when added to a model that already has the baseline. This increment is the claim's `falsifier` (`comparator` = the baseline). |
| 4 | Does it change a decision? | decisions with and without the measure | proportion of decisions that change |
| 5 | Does it improve outcomes? | outcomes with and without use of the measure | usually out of reach for this pipeline → OUT scope |

A statistically significant association between measure and outcome is far from enough to call the measure useful;
studies of this kind are judged on descriptive parameters and their confidence intervals, not on p-values (DCR ch. 12).
So a biomarker claim at rung 1 or 2 is usually `mode: estimate`.

Five traps, each written into `rivals` with a concrete `how` (the `type` column is this pipeline's filing, not the
book's classification):

| Trap | `type` | What to check |
|---|---|---|
| Incorporation | `incorporation` | The measure is part of how the outcome is defined. Apply the two-formula test of section 4.2 (`rivals.type = incorporation`). |
| Existing predictor | (uses `baseline_predictor`, `comparator`) | `baseline_predictor` is **required**. In BCI work the usual one is calibration-phase accuracy. A measure that only restates it adds nothing, so the falsifier is the increment over it; beating a weaker comparator (generic quality, chance) may only be a secondary claim (C15). |
| Spectrum | `selection` | How the sample's range of easy and hard cases compares with real use. Comparing only extreme groups overstates accuracy. |
| Cut-point overfitting | `bias` | Fix thresholds in advance, or derive them on one set and validate on a separate one. |
| Verification | `selection` | Whether the reference standard exists for all subjects or only for a selected part. |

### 6.2 Cause / mechanism claims

Reader question: "what else explains it, and how did you exclude that?"

- `rivals` must cover the basic four (C8) **and** `leakage`.
- At least one isolating experiment with `role: control`. In order of strength: direct manipulation (injection,
  ablation) > dose–response > several comparison groups whose biases point in different directions (DCR ch. 8) >
  statistical adjustment. The ordering is this pipeline's own; only the third item is taken from the book.
- One negative control: an outcome that should not move, or a manipulation that should do nothing (DCR ch. 12,
  Example 12.1).
- **Could each result have come out otherwise?** For every evidence row and for the negative control, write where
  the manipulation acts and where the measure is computed (channels, band, time window, labels), then fill `can_fail`
  and `controls.negative_can_move` (section 4.2). A manipulation applied to the exact support of the measure must move
  it; a control applied where the measure is not computed cannot move it. Neither tests the claim (C17). The usual
  repair: measure the effect on something the manipulation does not define (a held-out decoder's accuracy instead of
  the index the noise was aimed at), and place the negative control inside the data the measure reads but outside the
  claimed mechanism (same channels, off-band; same band, shuffled labels).
- Write `construction` (section 4.2): the formula of the manipulation, the formula of the number the falsifier reads,
  their shared terms, and whether the result could be computed without running the experiment (C17). This is the
  two-formula test for `incorporation` done in writing; a shared term requires that rival (C18).
- Push the positive control's planted effect and the negative control's expected behaviour through the statistic the
  falsifier reads, and write the values that come out (`controls.positive_expected`, `controls.negative`). A statistic
  that takes an absolute value, a rank or a threshold does not return the planted value unchanged (C17).
- Aim the negative control at the `main` rival (C24).
- Consistency, strength, dose–response and plausibility are positive evidence for cause. Consistency and a
  dose–response relation can also arise from reverse causation or confounding; a strong association makes confounding
  (and chance) less likely but does not exclude it (DCR ch. 9) — they support, they do not replace the control.
- With observational association only, the verb in `statement` is "is associated with", not "causes" or "drives".

### 6.3 Equivalence / negative-result claims

Reader question: "did you find nothing, or could you not have found anything?"

- `mode: equivalence`, with the margin written before any result and labelled a design choice.
- `controls.positive` is required (C9). When the aim is to find no difference, a careless study succeeds more easily:
  noisy measurement and small samples all push towards "no effect", so the usual protection of the null hypothesis is
  gone (DCR ch. 6; ch. 11). The positive control shows the pipeline would have found an effect of the margin's size;
  `controls.positive_expected` gives the value it returns under the falsifier's statistic (C17).
- `power` comes from `power --mode equivalence`: the smallest margin at which equivalence can be shown with this n.
  A margin smaller than that cannot be demonstrated, whatever the data say.
- `Short Hypothesis` first says why a reasonable reader would expect an effect, then that the study tests whether it is
  there (the framing of Craft 10.3.2).

### 6.4 Estimate / measurement claims

Reader question: "how precisely do you know it?"

- `mode: estimate`. No H0/H1 — a descriptive study needs no hypothesis (DCR ch. 5). `statement` is one plain
  sentence; `falsifier`, `controls` and `power` are `null`.
- Fill `precision_target` from `power --mode estimate`: the confidence-interval width the available n gives. With an
  unknown SD, omit `--sd` and add `--effect <the width aimed for>`.
- If the same data will also answer an analytic question ("what predicts X?"), that question is a separate claim with
  its own `power` — otherwise the question of greater interest ends up underpowered (DCR ch. 6).
- **An estimate claim may be primary only when step7b declares `study: descriptive`** (C21). An estimate claim is
  outside C7 and C17 (the script reads neither for it, and its `negation` may be `null`), so the switch is the
  easiest way to make a by-construction problem disappear from the gate. Therefore **every estimate claim says why it
  is one** — `estimate_because`, starting `descriptive:`, `size-open:` or `by-construction:` (section 4.2; C21). This
  holds from B4 on: a hypothesis that the by-construction check or the derivability screen turns into an estimate
  before round 1 leaves no trace in `argument_r1.json`, and this field is its record. After round 1, turning a test
  claim into an estimate is also a demotion with a `tradeoffs` row (C19). The switch stays legitimate for a secondary
  claim whose direction is settled and whose size is open (`size-open:`); with `by-construction:` the field says what
  test was given up and what the reader lost, and the round-2 critique asks whether a magnitude test
  (`direction-settled` with a `smallest_effect_of_interest`) could replace it.

### 6.5 Invariance / reproducibility claims

Reader question: "is the difference more than the instrument's own noise, and a difference of what?"

- Repeated measurement of the same units. Report the distribution of differences, not a correlation — this is rung 1
  of section 6.1, without the biomarker rules (no baseline predictor, no increment).
- **The noise term must be exposed to the same nuisance variation as the contrast, apart from the factor under test.**
  Two blocks separated in time are compared with two blocks separated in time, not with interleaved halves: an
  interleaved odd/even baseline understates how much any two stretches recorded minutes apart differ, and a positive
  result then shows non-stationarity, not the claimed factor. This understated noise is usually the `main` rival (C24).
- **Name the factor that actually differs between the conditions** (eye state, run order, session). A claim about
  "recordings" in general needs more than one kind of difference; with one, the claim is about that factor.
- A claim of sameness is `mode: equivalence` and follows section 6.3.

---

## 7. Skeptical reader and blind restatement

The gate checks structure. These two steps check content, and they exist because the author of an argument is its
least critical reader (Craft 10.1).

### 7.1 The 12 questions (round 2 critique; all depths)

No new action type. In round 2, after the quality / novelty / feasibility critique and the comparison of restatement 1
(section 7.2), answer each question in `reflection_log.md` in one to three sentences, as a reader who wants the idea
to be wrong. Answers come from `step7b_problem.md`, `step8_hypothesis.md` and `argument.json` **and from derivations
written in the log** — the algebra that question 8 asks for is in none of the three files until you do it. A question
you cannot answer is what this round's `ReviseHypothesis` fixes.

1. *Problem.* In one sentence with no jargon: what is this study trying to do, and why is it hard?
2. *Problem.* Why is this a problem at all — is the consequence really that large?
3. *Problem.* Who cares, and what changes if it succeeds — and would a reader act on the *if not* outcome, or is it only
   "not shown here"?
4. *Claim.* Is the claim stated too strongly? Name an exception.
5. *Claim.* Why is this answer better than the alternatives, and does it conflict with something well established?
   Then, for the primary claim and every test claim: before any data, which direction do you expect, and from what —
   a citation, textbook physiology or physics, or the algebra of `construction`? If you can name the direction and
   its basis, `expected_direction.basis` is `settled:` and `negation.verdict` is `direction-settled`.
6. *Evidence.* Is the evidence accurate, precise enough, sufficient, representative, and from a source the field
   trusts — and does the positive control return its expected value under the decision rule's own statistic?
7. *Warrant.* Why does this measurement count as evidence for this claim? Does the field accept that inference, and is
   there a competing inference that fits better? If `warrant_basis` is `(field convention)`, name who accepts it.
8. *Warrant.* Is the reason a genuine instance of the circumstance the warrant describes? Answer for each evidence row;
   then redo the by-construction algebra in the log — substitute the predictor formula into the outcome formula — and
   correct `construction` if it does not hold.
9. *Alternatives.* What other causes would produce the same result — and is the negative control aimed at the most
   plausible of them (`main`)?
10. *Alternatives.* What is the most obvious counterexample?
11. *Alternatives.* Would a reader define a key term differently, and does the claim survive their definition?
12. *Progress.* Halfway through, which number tells us whether we are on course? Write the answer down: it is the
    candidate `gate_check` for the experiment stage. State its tolerance and compare it with the smallest effect of
    interest and with the positive control's planted effect: a tolerance as large as either cannot tell on course
    from off course.

Groups and sources: problem 1–3 (Craft 10.1; Heilmeier 1, 5) · claim 4–5 (Craft 10.1, 8.3) · evidence 6 (Craft 9.4) ·
warrant 7–8 (Craft 11.4, 11.6) · alternatives 9–11 (Craft ch. 10 Quick Tip) · progress 12 (Heilmeier 9). The added
clauses of questions 3, 5, 6, 7, 8, 9 and 12 are this pipeline's own.

Questions 3, 4, 5, 7, 8 and 9 re-examine fields the author filled optimistically by default — `scope`, `warrant`,
`negation.verdict` and `expected_direction`, `rivals`, `construction`, `coverage`. If an answer contradicts the field,
change the field. The same critique answers every `WARN` that asks for an answer (section 5.2): for a C20 line, quote
the sentence that covers the key term or the angle part, or change `coverage`; for a C21 `by-construction:` line, say
under question 4 whether a magnitude test could replace the estimate.

**When the revision changes the primary claim, the questions about it are asked again.** The 12 questions are answered
before the round-2 revision, so a primary claim that the revision creates — a new statement, mode, statistic or
falsifier — has been examined by none of them. In the same round, after the revision and before the `--no-idea`
check, re-answer questions 5, 6, 8, 9 and 12 for the claim as it now stands, under a log heading
`Primary claim changed — questions 5, 6, 8, 9, 12 again`, and rewrite `expected_direction`, `negation.verdict`,
`construction`, `can_fail`, `controls.positive_expected`, `controls.negative` and `rivals[].main` from those answers
(research-cycle.md §5, round 2 step 2). C17 lists a primary claim whose `id`, `statement` or `mode` changed while
`construction` or `positive_expected` did not.

### 7.2 Blind restatement (after round 1, and again before `FinalizeIdea` if the primary claim changed; `standard` and `deep` only)

How well a reader who only skimmed the text can restate its argument predicts how well the final readers will
understand it (Craft 13.6). The reader here is a subagent that knows nothing of the hypothesis: the only step in
stage B where someone who does not know the intended answer looks at the design. This section is the single
definition of the brief and the comparison; research-cycle.md §5 points here.

**When.** At most two per `(gap, angle)` attempt, none at depth `quick`.

- **Restatement 1 — end of round 1**, on the first `idea_draft.json`, after the round-1 `argument-check` and the
  round-1 copies. It comes before the scheduled revision on purpose: a design defect a reader finds after the last
  revision can only be written down as a risk, and writing a weakness down is not fixing it. Its mismatches and
  doubts are input to the round-2 `ReviseHypothesis`.
- **Restatement 2 — in the finalize round**, on the rewritten draft, **only if** the pre-finalize `argument-check`
  prints the C22 warning that the primary claim changed since round 1 (its `id`, `statement`, `mode`, `falsifier`,
  `comparator` or `baseline_predictor` differs from `argument_r1.json`). The first reader saw a claim that no longer
  exists, so the new one needs a reader of its own; an unchanged primary claim does not.
- No restatement follows a forced revision made in the finalize round or after it. (A compute-gate revision that
  was applied early and coincides with the scheduled round-2 revision is not one of these: restatement 2 still runs
  in the finalize round when C22 asks for it.)

**The brief.** Spawn one subagent. Give it **only** `idea_draft.json` — no other `gen_{k}/` file, no topic file, no
summary of the hypothesis, no hint of the expected answer, no tool but reading that file, no network. A reader told
what to find will find it. The brief, verbatim:

```
Read the file <absolute path>/idea_draft.json. It is a research proposal in seven fields. Read nothing else.
Using only what the file says, return one JSON object with exactly these five keys. Each value is plain text;
use as many sentences as you need.
  "research_question": the question the proposal sets out to answer, ending in a question mark.
  "tested_part": which part of that question the experiments put to a test with a stated pass/fail rule -
      "all of it", or the part that is tested and what is left untested or only described.
  "primary_claim": the claim the study would make if it succeeds.
  "falsifying_experiment": which experiment (by its id) would refute that claim and what result would do so;
      "none" if no experiment could.
  "biggest_doubt": your doubts about whether these experiments can support that claim, most serious first;
      number them if there are several.
Do not improve or rewrite the proposal. If the file does not let you answer a key, say so in its value.
```

Write the returned object to `gen_{k}/restatement_<n>.json` unchanged and log the path, not a copy — `argument-check`
reads the file (C22: that it exists, what its `tested_part` says, how many doubts its `biggest_doubt` numbers), and a
paraphrase in the log is the author's reading of the reader. A file that is not the reader's object with a
`biggest_doubt` is bad input (exit 2).

**The comparison** — four criteria plus two cross-checks, one verdict each:

| # | Criterion | Reader's key vs | Match | Mismatch |
|---|---|---|---|---|
| 1 | phenomenon | `research_question` vs step7b section 5 | the same thing is to be explained or measured | a different or broader / narrower object |
| 2 | setting | same | the same population, data or setting | another, or none recoverable |
| 3 | kind of question | same | the same kind: how / why / whether / how far / how large | a *why* read as a *whether*, a test read as a description |
| 4 | coverage | `tested_part` vs `coverage` | `coverage.question` is `whole` and the reader says "all of it"; or it is `part` and the reader names the same tested part | the reader says the test is narrower than the question while `coverage.question` is `whole`; names a different part; or cannot tell which part is tested |
| + | claim | `primary_claim` vs the primary `statement` | same subject, direction and comparison | otherwise |
| + | decision rule | `falsifying_experiment` vs `falsifier` | same experiment and threshold | another experiment, another threshold, or "none" |

Verdict line in `reflection_log.md`: `restatement <n>: phenomenon ok | setting ok | kind ok | coverage MISMATCH (…) |
claim ok | rule ok`. Any mismatch is a mismatch. Criterion 4 exists because the first three cannot say "the question
is wider than the claim that is tested" — the reading under which a proposal oversells. A coverage mismatch is
repaired by narrowing the question (`original_question`, with `changed_because` starting `restatement:`) or by
declaring `coverage.question: "part"` and rewriting `Title` and `Short Hypothesis` (section 8). Criterion 4 is also
checked by the script, so it cannot be waved through as a match: with `coverage.question: "whole"`, a latest reader
whose `tested_part` does not say "all of it" is an ERROR of C22 until one of those two repairs is made.

**The doubts.** Split `biggest_doubt` into separable doubts and write one `reader_doubts` row for each (section 4.2),
with `source: restatement-<n>` — at least one row per restatement file, and at least one per doubt the reader
numbered (C22). A doubt is not a C-check finding and not a rival; this field is its home, so that it cannot exist in
`idea.json` alone. A reader that states no doubt still gets one row, so the file is accounted for:
`doubt: "none stated"`, `level: wording`, `response: fixed`, `how: "nothing to answer"`.

- `level`: `design` when answering the doubt changes an experiment's data, measure, statistic, control or decision
  rule, or the primary claim; `wording` when rewriting the seven fields is enough; when unsure, `design`.
- `response: fixed` — `how` says what changed; for a `design` doubt it names the experiment or claim id that changed
  (C22), because "noted in the entry" changes no design. `response: not-fixed` — `how` gives the concrete obstacle
  and starts with its kind: `data:` (absent on this machine, as `env-probe` shows), `budget:` (which experiment, what
  cost) or `conflict:` (with which claim). "No gate forced a revision", "out of scope" and "future work" are not
  reasons — the script refuses them (C22). "The objection is right" is answered by changing the design, not by
  agreeing in the log.
- Every `not-fixed` row becomes one `Risk Factors and Limitations` entry, `"Blind restatement unresolved: …"`
  (section 8), and is listed in the Finish report.

**What follows.**

- After restatement 1: every mismatch and every doubt is answered by the round-2 `ReviseHypothesis` — fixed in the
  design, or `not-fixed` with its obstacle. This uses no forced revision. (With `num_reflections` = 2 there is no
  scheduled revision, and a mismatch or a `design` doubt counts as a coherence-gate failure.)
- After restatement 2: add the `reader_doubts` rows; fix a `wording` doubt in the draft at once and re-run
  `argument-check`. A mismatch on any criterion, or a doubt of level `design`, is a failure of the coherence gate
  (section 5.2): together with any ERROR of the pre-finalize run it is served by the gate's one forced
  `ReviseHypothesis` and adds no round of its own. After that revision nothing is restated again — when the primary
  claim changed in it, C22 still prints "run the second blind restatement", and the answer is the entry
  `"Coherence unresolved: the primary claim was not restated after the forced revision"`: record what is left
  — a mismatch as `"Coherence unresolved: blind restatement read the question as {…}"`, a doubt as `not-fixed` — and
  finalize.

`idea_draft.json` is kept after finalize, because it is what the last reader saw; `gen_{k}/idea.json` stays the
canonical final copy.

---


On the fusion block the comparison has one cross-check more: the experiment the reader says would refute the claim is
the decision tree's primary test node (planning/P3-decision-tree.md). A reader who names another experiment has read the
design differently from the tree — a mismatch on the `rule` criterion.

## 8. Writing the seven fields

Keys, order and types are unchanged, and `validate` / `append-idea` behave as before. What changes is where each
field's content comes from. Everything not listed here stays in `gen_{k}/`.

| Field | Compose it from | Reader question it answers |
|---|---|---|
| `Name` | unchanged | — |
| `Title` | The `key_terms` of the **tested** part of the question. A reader who meets the same terms in the title, the claim and the experiments sees one study (Craft, Quick Tip: Titles). A part that is only estimated is named after a marker ("…, with a descriptive map of …") or not at all: the title may promise only what the primary claim tests (C20 looks for the `coverage.untested[].terms` in it: an ERROR, repaired in the draft at once and re-checked — a title edit needs no `ReviseHypothesis`; with `coverage.question: "whole"` it lists every key term the primary claim's own text does not contain, and says when the Title names it). | "What is this about, specifically?" |
| `Short Hypothesis` | **Four sentences**, about 120–150 words (a guide, not a check): (1) the research question, word for word as `argument.json` has it (C20); (2) the primary claim — *Although … because …* for a test or equivalence claim, with the definitions left to `Experiments`; (3) what is tested and what is only estimated (from `coverage`), and why this setting — data, population, measure; (4) why no simpler route answers it — consistent with `construction.computable_without_experiment`: when that is `partly`, the sentence says which part existing data already answer. State the aim in concrete terms and do not oversell it (DCR ch. 19). Detail stays in `step8_hypothesis.md`; a sentence that carries the operational definitions is how the field doubles in length. | "What is new, and why do you expect it to work this way?" (Heilmeier 3, 4) |
| `Related Work` | Open with the common ground and the condition that breaks it (step7b sections 1–2), then the existing rules: gap evidence, counter-evidence, SOTA numbers, `(Author et al., Year) [citation_key]`. | "How is it done today, and where does that stop?" (Heilmeier 2; Craft 16.2) |
| `Abstract` | (A generation that took a question from the fusion block: written last, at P5 — context → gap → approach → outcomes → contribution, each sentence with its sources; [planning/P5-package.md](planning/P5-package.md).) In order: common ground → condition → consequence → approach → expected contribution. This is the context + problem + launching-point pattern: it announces what will be tested, **not results** — there are none yet (Craft, Quick Tip: Abstracts; 16.1–16.4). | "Why should I read on?" |
| `Experiments` | Each entry starts with its id, then a role tag — `E3 [tests C1] …`, `E0 [instrument] …`, `E5 [control C1] …`, `E1 [descriptive C2] …` (a `descriptive` entry names a claim only when it supplies that claim's evidence) — matching `experiments[]` in `argument.json`. The id comes first because the experiment stage reads it from the start of the entry; an id dropped in a revision is retired, not reused, so the list may have gaps. The negative control and the positive control are **separate entries**. Then the existing content: change, dataset, baselines, metric, convention followed. A `tests` entry states its decision rule with the threshold. Every compute figure is labelled `timed` or `estimated`. For human data, state the dataset's licence and whether its original consent covers this secondary use, **once per dataset, in the first entry that loads it**; write `(licence unverified)` when it cannot be established offline (DCR ch. 14) — the journal step looks it up (research-cycle.md §7). One line, no gate. The instrument entry that fixes the decision rules says how a third party can verify they were fixed first: a commit hash made before any analysis, or an external timestamp the user must create. Otherwise the entry says "fixed before analysis, not externally timestamped" and the word "pre-registered" is not used — a locked plan nobody can check is a promise. Use the words that come naturally; never reword an entry for C10 (section 2.2). | "What is each experiment for, by what rule is it read, and may you use these data?" |
| `Risk Factors and Limitations` | In this order, so that what a gate or a reader left open is not lost among routine limits: (a) labelled entries — `Blind restatement unresolved: …` (one per `not-fixed` row of `reader_doubts`), `Coherence unresolved: …`, `Compute budget uncertain: …`, `No real-data validation: …`, `Single dataset: …` (from `external_check`), `Primary claim downgraded to an estimate: …` (C21), `Question screen unresolved: …`, `Question narrowed from: …`, `Decision rules not externally timestamped: …`; (b) rivals with `ruled_out_by: (not addressed)` — one entry per distinct `how`, naming every claim it applies to, so one limit shared by two claims is one entry; (c) power of `test` / `equivalence` claims whose `power.verdict` is not `adequate`; an estimate claim only when its `precision_target` says the interval is wider than the aim; (d) the `scope.external` limits; the part of the result existing data already give (C17 `partly`); a primary test claim without a positive control (C17); `(licence unverified)` once per dataset; any `(TBD)` rung of the So-what ladder ("Significance not supported by the literature: …"); (e) the rows of step8's risk table. Every entry of (a)–(c) comes from `argument.json` or a gate note — a risk is never added to the idea alone. | "What could make this wrong, and what does it not show?" (Heilmeier 6) |

`idea_draft.json` is written in round 1, rewritten before finalize and kept afterwards; `idea.json` is the last draft
plus the labelled entries above. When `coverage.angle` is `part`, `consume` is called with
`--angle "<angle> [not covered: <angle_dropped, short>]"` (research-cycle.md §6), so a later generation can see that
the rest of the angle is free.

---

## 9. Sources

Paraphrased, never quoted. Use this table to check a rule against its source.

| Rule in this file | Source |
|---|---|
| Three-step sentence; three of the four screens (settled, undecidable, dead end); prefer how / why (§2) | Craft 3.4, 3.3.7 |
| A practical problem contains a research problem; the applied test, as a rule for the fourth step only (§2.3) | Craft 4.1, 4.2.4 |
| Problem = condition + consequence; the consequence is a larger question (§2.2) | Craft 4.2, 4.2.2 |
| Ask "so what?" until the reader asks what to do; a reader who never stops is the wrong audience (§2.1) | Craft 4.2.1, 16.3.3 |
| Gap moves: three of agreement, five of disagreement (§3) | Craft 6.3 |
| Make sure the source really claims what you contradict (§3) | Craft 4.3.2, 6.2 |
| Record a source's claim with its context and strength (the reading-note lines `Claim scope:` …) | Craft 6.6.4 |
| Parts of an argument; storyboard of claim → reasons → evidence needed (§4) | Craft ch. 7, 9.1 |
| Five kinds of claim, each needing different support (`kind`) | Craft 8.1 |
| Working claim with *although* and *because* (`statement`) | Craft 8.2.1 |
| Reversal test; new data < resolving a puzzle < overturning the settled (`negation`, §3) | Craft 8.2.2 |
| Limiting conditions and hedges (`scope`) | Craft 8.3 |
| Evidence: accurate, precise, sufficient, representative, authoritative (§7.1 q6) | Craft 9.4 |
| Questioning your own argument as a hostile reader (§7.1 q1–5) | Craft 10.1 |
| Presenting the expectation you could not support as the hypothesis tested (§6.3) | Craft 10.3.2 |
| Three predictable objections: other causes, counterexamples, definitions (§7.1 q9–11, §2.2 s8) | Craft, Quick Tip after ch. 10 |
| Logic and tests of a warrant; reason as an instance of the warrant (`warrant`, §7.1 q7–8) | Craft 11.3, 11.4, 11.6 |
| A claim of fact needs evidence, not reasoning alone (`evidence`) | Craft, Quick Tip after ch. 11 |
| Four or five key terms running through the whole text (§2.2 s7, C10) | Craft 12.1.2, 13.4 |
| Skim, then have someone restate it (§7.2, both restatements) | Craft 13.6 |
| Abstract patterns; introduction = context + problem + response; title from key terms (§8) | Craft, Quick Tips: Abstracts, Titles; 16.1–16.4 |
| Forms without the question behind them breed imitation (§1 rule 1) | Craft, A Postscript for Teachers |
| One-sentence description of a study (`study_sentence`) | DCR ch. 1 |
| Research question → study plan → actual study; internal and external validity (`representation`, `scope`) | DCR ch. 1, Fig. 1.5 |
| After the concessions, decide whether the plan is still worth doing (§5.1) | DCR ch. 1, Trade-offs |
| FINER; Relevant = imagine each outcome; Novel includes confirmation (`outcomes`, §3) | DCR ch. 2, Table 2.1 |
| Precision, accuracy, validity; kinds of validity; prefer validated measures (`representation`) | DCR ch. 4 |
| Good hypothesis: simple, specific, in advance; one primary; descriptive studies need none; post hoc hypotheses (`mode`, `primary`, `falsifier`) | DCR ch. 5 |
| Fixed sample size → smallest detectable effect; a hypothesis changed for power must still answer the question (`power`) | DCR ch. 6; appendices 6A, 6C, 6D |
| Clustered samples and effective sample size (`power.unit`) | DCR ch. 6; ch. 11 |
| Equivalence designs lose the null hypothesis's protection (§6.3) | DCR ch. 6; ch. 11 |
| A descriptive study that also asks an analytic question (§6.4) | DCR ch. 6 |
| Dummy risk factors; two or more control groups (`controls`, §6.2) | DCR ch. 8 |
| Five explanations of an association; conditioning on a shared effect; positive evidence for cause (`rivals`, §6.2) | DCR ch. 9, Table 9.1 |
| Three questions: sample, predictor, outcome (`representation`) | DCR ch. 9, Fig. 9.1 |
| Ladder of questions about a test (adapted: the cost / risk row dropped, an added-value rung inserted); association is not usefulness (§6.1) | DCR ch. 12, Table 12.1 |
| Incorporation, spectrum, verification bias; cut-point overfitting; validation set; added value (§6.1, `baseline_predictor`) | DCR ch. 12 |
| Pre-specified endpoint expected to show no association (`controls.negative`) | DCR ch. 12, Example 12.1 |
| The question is often altered to fit existing data (`original_question`; recording every change of wording, whatever the cause, is this pipeline's extension) | DCR ch. 13 |
| Research on existing de-identified data; consent scope (§8 `Experiments`) | DCR ch. 14 |
| Specific aims in concrete terms, without overstatement (§8 `Short Hypothesis`) | DCR ch. 19 |
| Is the warrant appropriate to this field (`warrant_basis`) | Craft 11.4 (11.4.4) |
| No jargon; how it is done today; what is new; why it should succeed (§8 `Short Hypothesis`); who cares; risks; mid-term measures (§7.1, §8) | Heilmeier 1, 2, 3, 4, 5, 6, 9 |
| `leakage` as a rival type (§4.2) | none — this pipeline's addition |
| The rival-type list beyond the basic four; filing spectrum and verification under `selection` and cut-point overfitting under `bias` (§4.2, §6.1) | none — this pipeline's addition |
| `incorporation` extended from test studies to cause claims (a manipulation on the measure's own support); `evidence.can_fail`, `controls.negative_can_move` (§4.2, §6.2) | none — this pipeline's addition (the test-study case is DCR ch. 12) |
| `comparator`: the falsifier is the increment over the baseline predictor (§4.2, §6.1) | this pipeline's rule, built on DCR ch. 12 (what a new test adds) |
| Checks C1–C24 and their ERROR / WARN levels (§5.2) | none — this pipeline's addition |
| The reversal test used as a blocking check, with the verdict `direction-settled` and `smallest_effect_of_interest` (a settled direction is tested as a magnitude); the dead-end screen with a fixed failure path (§4.2 `negation`, §2.2) | this pipeline's use of Craft 8.2.2 and 3.3.7 |
| The derivability screen: an answer that textbook knowledge, the definitions or a few lines of algebra give is not a research question (§2.2) | none — this pipeline's addition |
| `construction` (two formulas, shared terms, computable without the experiment, free quantity); `controls.positive_expected` (the planted effect pushed through the decision rule's statistic); `evidence.refuted_if` (§4.2, §6.2) | none — this pipeline's addition |
| `rivals.main` and the negative control aimed at it (§4.2, C24) | none — this pipeline's addition (the objection itself: Craft, Quick Tip after ch. 10) |
| `coverage` (question and angle, whole or part); the title promises only the tested part; `tradeoffs` rows for every cut, with `lost`, `covers_gap`, `covers_angle` (§4.2, §5.1, §8) | this pipeline's extension of DCR ch. 1, Trade-offs |
| `external_check`: a route from synthetic evidence to real recordings, and from one dataset to a second (§4.2, C23) | this pipeline's rule, on DCR ch. 1 (external validity) |
| `reader_doubts`; the fourth comparison criterion (coverage); the reader placed before the scheduled revision (§7.2, C22) | this pipeline's use of Craft 13.6 |
| `study: descriptive` as the condition for an estimate primary claim (§2.2, §6.4, C21) | this pipeline's rule, on DCR ch. 5 (descriptive studies need no hypothesis) |
| `invariance` variant: noise term under the same nuisance variation as the contrast; name the factor that differs (§6.5) | this pipeline's addition (the reporting rule is rung 1 of DCR ch. 12, Table 12.1) |
| Whose words the evidence is: a `Not done:` line is the note-writer's, an inference from a paper's number is this study's (§2.2) | this pipeline's rule, in the spirit of Craft 6.6.4 |
| Decision rules "fixed before analysis" must be verifiable by a third party, or not called pre-registered (§8 `Experiments`) | this pipeline's rule, on DCR ch. 5 (hypotheses stated in advance) |
| `estimate_because` on every estimate claim; `expected_direction` and its three bases; `coverage.angle_parts` (the angle phrase by phrase) and the key-term backstop of `coverage.question`; one row per numbered doubt, the `data:` / `budget:` / `conflict:` obstacle, the "none stated" row; the inventory that must name what is on the disk, and `real_data: none:` refused in round 1 (§4.2, §6.4, §7.2, C7, C20–C23) | none — this pipeline's addition |
| Rules added to cells that open with a book citation, and are not the book's: the compound-question rule and "a part no claim covers does not belong in the question" (§2.2 row 5); `tested only in {setting}` and `(no reported number: this is an absence)` (§2.2 row 2); the Move test for an absence gap (§3); the aggregation path in `evidence.measure`; the conjectured *because* clause and the plain-sentence statement of an estimate (`statement`); the sign-keeping falsifier, the deciding experiment named first (`falsifier`); `--sided`, `--mode equivalence`, `--effect` and "never a placeholder `--sd`" (`power`); `assigned` for `precision` and `accuracy` (`representation`); the licence line once per dataset and the ordered Risk list (§8); questions 5, 6, 8, 9 and 12 asked again when the revision changes the primary claim (§7.1) | none — this pipeline's addition |
| `power.verdict` thresholds; at most three rungs (two at `quick`); ICC at rung 1; the order of isolating experiments; "a sentence that will not come = design undecided" (§4.2, §2, §6) | none — this pipeline's addition |
