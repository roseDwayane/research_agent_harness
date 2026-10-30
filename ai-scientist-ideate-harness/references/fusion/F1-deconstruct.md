# F1 deconstruct — each paper on its own

**Deconstruct** is the first step of the fusion block ([README.md](README.md)). It takes every shortlisted paper apart
into small, addressable units — each with the place in the paper it comes from and a verbatim quote that a tool checks —
and decides whether a paper read in full still belongs in the review. It looks at **one paper at a time**: who agrees
or disagrees with whom is the collision step's question, and answering it while reading makes the answer depend on the
reading order.

| Unit | Decides | Writes (through the tool only) |
|---|---|---|
| A6 full text | nothing by judgement — which papers have a readable full text | `pdfs/`, `step5_full_text/`, `step5_full_text/figure/`, `access_level` ([../scholar-pipeline.md](../scholar-pipeline.md) §7) |
| [A7.D deconstruct](#a7d) | what each paper claims, assumes, reports as limits and future work, did not do; its main experiments and its vocabulary; full-text eligibility | `knowledge/decon/<key>.json`; the view `knowledge/_notes/<key>.md` |

A6 is unchanged; its rules stay in [../scholar-pipeline.md](../scholar-pipeline.md) §7 (full text, depth levels,
degraded paths). It answers "is there a readable text"; whether the paper, once read, belongs in the review is A7.D's
`eligibility`.

---

<a id="a7d"></a>
## A7.D — deconstruct

### Purpose
One record per shortlisted paper: its claims (with the strength and scope the paper gives them), the premises it relies
on without testing, its stated limitations and future work, what it visibly did not do, its main experiments as
methods-matrix rows, and its own words for methods, measures, datasets, splits, populations, constructs and paradigms.
A full-text paper also gets an eligibility verdict.

### Inputs
For paper `<key>`: `step5_full_text/<key>.md` when A6 obtained it (with `step5_full_text/figure/index.json` for numbers
in tables and plots), otherwise its title and abstract from `step3_shortlist.json`; the protocol's framework, outcomes
and criteria (`step0_session_config.json → protocol`; `pico` on a topic framed before 2026-10-16) with A3's criteria
amendments (`screening_scores.json`; an eligibility verdict reads the criteria as amended). Nothing else: not
another paper's record or note, not `knowledge/`, not `gen_*`. The batch file `decon-plan` writes holds all of it.

### Method

**Basis.** A paper with a full text is deconstructed from the full text (`basis: full-text`); every other paper from its
title and abstract (`basis: abstract`). A record written from the abstract while a full text exists is refused (D02).

**Reading a full text for the record.** Reading twenty full texts end to end is neither affordable nor necessary. Read
the abstract, the last paragraph of the introduction (contributions), the method section's headings and first
paragraphs, the results tables and their captions, then limitations / discussion / future work in full; `grep -n` the
protocol's outcome terms to catch what the skim missed; then the parts only the experiment rows need (statistics, compute,
code and data availability, ablations, how thresholds were chosen). A number in a table or plot — or in a table the
conversion scrambled — comes from the page image (`figure/index.json` names the file), cited as `[Table III, page
image]`. One pass: the experiment rows are written now, not in a second reading.

**Eligibility** (`eligibility`):
- `eligible` — read in full and inside the protocol.
- `ineligible` — read in full and outside it: name the criteria (`IN*` not met, `EX*` met) in `criteria` and say why in
  `reason`. An ineligible record has **no units and no experiments**: the paper keeps its key and its record, and is not
  evidence anywhere downstream. The shortlist is not edited (S-D14).
- `abstract-only` — no full text; exactly when `basis` is `abstract`.

**Units.** Ids are `<key>#<letter><n>`, numbered from 1 per kind.

| Kind | Letter | What | Quote |
|---|---|---|---|
| `claim` | C | a claim the paper makes. **C1 = its principal finding**: the result the paper headlines (abstract results, the conclusion's first sentence), not the closing implication and not the title. A closing interpretation ("neural activity may explain …") is its own claim at its own, usually weaker, strength. Each claim carries `strength` and `scope` | required |
| `assumption` | A | a premise the method or argument needs and the paper does not test: a label taken as ground truth, a preprocessing step taken as harmless, a split taken as leakage-free, a metric taken as measuring the construct. Only premises you can point to — a method step or a sentence | required: where it is stated or relied on |
| `limitation` | L | a limitation **the paper states** | required |
| `future` | F | future work **the paper calls for** | required |
| `not-done` | N | what the paper visibly did not test, vary or compare — **your observation**, cited later as `not done in [key] (reading note)`, never as the paper's words | none (refused if present) |

- Every unit has `id`, `kind` and **`text`** (your one-line statement of the unit; required, never empty); a quoted
  unit adds `where` and `quote`; a claim adds `strength` and `scope`.
- **`strength`** keeps the source's own verb, on one scale: `causes` · `shows` · `suggests` · `may` · `correlates`.
  "Causes", "may contribute to" and "correlates with … in" are three different claims; a record that upgrades a hedge
  makes a later contradiction attack something the paper never said (Craft of Research 6.6.4). `decon-check` warns when
  a `causes` / `shows` claim quotes a hedging sentence (D17). Mapping the paper's verb:

  | the paper writes | strength |
  |---|---|
  | causes, leads to, drives, is responsible for (with a manipulation behind it) | `causes` |
  | shows, demonstrates, finds, establishes, improves / reduces (a measured result) | `shows` |
  | suggests, indicates, is consistent with, supports, points to | `suggests` |
  | may, might, could, can potentially, is likely to | `may` |
  | correlates with, is associated with, predicts (without a manipulation) | `correlates` |

  Strength belongs to the claim as the paper words it, not to how convincing you find the evidence.
  - **Mixed verbs** in one sentence ("reflect … and could underlie"): the weaker one.
  - **A null** ("did not find", "was not supported") is a claim like any other: `shows`, with the null in `text`
    ("no QE difference between holed and missed putts").
  - **A verb stronger than the analysis** ("predicted success" from a group-level ANOVA): keep the paper's verb and say
    what the analysis actually was in the optional `overreach` field of the claim (one line). The collision step reads it
    as the `claim-strength` axis.
- **How many claims.** A full text: the principal finding plus every distinct result or interpretation another paper
  could agree or disagree with — typically 3–8; not every statistic. An abstract: 1–3.
- **Nulls are claims.** A tested effect the paper reports absent ("no outcome effect in beta or theta") is a claim
  (`shows`, the null in `text`) — the collision step can only compare what was recorded, and a null is often half of the
  field's clearest disagreement.
- **A premise stated as an interpretation.** When the paper reads its result through a premise it does not test ("band
  power before the stroke indexes preparation"), record the premise as an assumption as well as the interpretive claim:
  the collision step finds premises shared by several papers only among assumption units.
- **A paper in tension with itself** (a premise its own analysis window violates; a conclusion wider than its design) is
  a `not-done` unit or an `overreach` note on the claim: the collision step joins two papers, never one with itself.
- **Assumption and limitation together.** When the paper concedes a premise it also relies on (time zero at ball
  contact puts the movement in the epoch), record both: the assumption (what the analysis needs) and the limitation
  (what the paper concedes) are different statements; they may quote the same sentence.
- **`scope`** = `{population, data, conditions}`: for whom, on what data, under which conditions the claim is made — as
  the paper states it; a part it does not state is `(TBD)`, but not all three.
- **`where`**: section, page or table (`"Sec. 4.2"`, `"Table III, page image"`); `"abstract"` for an abstract record.
- **`quote`**: 4–60 words copied from the source, contiguous. Line breaks, hyphenation, ligatures and markdown emphasis
  do not matter (the check compares letters and digits only); every word and number does. A quote the check cannot
  find is refused (D05) — copy, do not paraphrase. A quote may span a comma or a clause boundary (punctuation is
  ignored); it may not skip words in the middle — quote the shorter contiguous part that carries the unit. Converted
  text has seams the check does not forgive: running page headers and footers inserted mid-sentence ("03
  frontiersin.org Carey et al. 10.3389/…") and columns read out of order. Quote a stretch that does not cross one.
- An **abstract record** has 1–3 claims (an abstract states its main findings, not more) and usually no other units.

**Summary** — the free lines of the old reading note, one line each: `problem`, `method`, `data` (name, n subjects /
trials, modality; the licence when the paper states it — stage B never goes online, so a licence nobody notes now stays
"(licence unverified)"), `metrics` (primary first), `headline` (value, condition, where), `builds_on` (who it builds on or
argues with, by name or key, as the paper says). All six keys are required; write `(TBD)` when the source does not say
— an empty or missing key is refused (D01).

**Experiments** — the paper's main experiments as methods-matrix rows, in the `build-methods` schema
([../knowledge-templates.md](../knowledge-templates.md), "`build-methods` input"), `exp_id` `<key>#E<n>`, `evidence` equal
to the basis: 1–4 rows for an eligible full-text paper, exactly 1 for an abstract-only paper. `(NR)` (read in full, not
reported) only on full-text rows; `(TBD)` (not verified) otherwise. `method_family`, dataset, baseline, metric and split
names are written as the paper writes them — the alignment step maps them onto one vocabulary. `affordable_here` stays
`(TBD)` (or is left out), whatever the batch context says about the machine — the lens fills it per method family
([F2-align.md](F2-align.md#b1)); a value here is refused (D08). **`(NA)`** (read in full,
the field does not apply to this design — a split or leakage control in a non-predictive ANOVA) is a third tag beside
`(NR)` and `(TBD)`; it is counted apart from `(NR)` so the field's reporting habits are not inflated, and like `(NR)` it
needs the full text.
Required in a row: `exp_id`, `citation_key`, `evidence`; every other field may be left out (rendered `(TBD)` by
`build-methods`). A list field (`method_family`, `factors`, `baselines`, `ablations`, `metrics`, `not_done`) is a list —
`["(TBD)"]` when unknown, never a bare string. `method_family` tags are short kebab-case names in your own words until
the alignment step exists; it maps them onto one vocabulary later, so prefer the plainest name ("ica", "artifact-rejection")
over a coined one.

**Terms** — the paper's vocabulary: `{term, kind, definition?, where?}` with `kind` one of method · measure · dataset ·
split · population · construct · paradigm. For a **measure**, add the sentence that defines it as `definition` (verbatim,
checked like a quote): two papers' "SNR" or "accuracy" are the same thing only if their definitions say so, and the
alignment step decides that from these sentences. A split keeps its unit ("10-fold CV over trials", "leave-one-subject-out").
**One term per thing**: "a priori frequency bands" is one term per band, each with its edges as `definition`; "experts vs
novices" is two population terms — the alignment step maps a word to one concept.

**An answer, complete** (a full-text paper; an abstract answer has `"basis": "abstract"`, verdict `abstract-only`,
`where: "abstract"`, 1–3 claims and exactly one row):

```json
{"citation_key": "smithetal2020", "basis": "full-text", "model": "claude-opus-5-5",
 "eligibility": {"verdict": "eligible", "reason": "scalp EEG, automated rejection, decoding before / after"},
 "summary": {"problem": "does automated artifact rejection change motor-imagery decoding",
             "method": "automated rejection before a CSP + LDA decoder", "data": "own MI EEG, 20 subjects (licence (TBD))",
             "metrics": "decoding accuracy", "headline": "+4.2 percentage points with rejection [Abstract]", "builds_on": "(TBD)"},
 "units": [
  {"id": "smithetal2020#C1", "kind": "claim", "text": "automated rejection improves MI decoding accuracy",
   "strength": "shows", "scope": {"population": "20 subjects", "data": "motor-imagery EEG", "conditions": "(TBD)"},
   "where": "Abstract", "quote": "automated artifact rejection improves decoding accuracy in motor imagery EEG"},
  {"id": "smithetal2020#A1", "kind": "assumption", "text": "one expert's labels are ground truth",
   "where": "Sec. 1", "quote": "whose labels we treat as ground truth for all comparisons"},
  {"id": "smithetal2020#L1", "kind": "limitation", "text": "healthy young adults, one session",
   "where": "Sec. 5", "quote": "Our sample was limited to healthy young adults recorded in a single session"},
  {"id": "smithetal2020#F1", "kind": "future", "text": "test across sessions and devices",
   "where": "Sec. 5", "quote": "test whether the gain holds across sessions and devices"},
  {"id": "smithetal2020#N1", "kind": "not-done", "text": "no subject-grouped split; folds over trials only"}],
 "experiments": [
  {"exp_id": "smithetal2020#E1", "citation_key": "smithetal2020", "evidence": "full-text", "where": "Sec. 1",
   "role": "comparison-study", "method_family": ["artifact-rejection"], "split": "10-fold CV over trials",
   "data": [{"name": "own MI EEG", "n": "20 subj", "modality": "EEG", "preproc": "(NR)"}],
   "baselines": ["no cleaning"], "metrics": ["accuracy"], "stats": "(NR) - point estimate only", "headline": "+4.2 pp",
   "not_done": ["no subject-grouped split"]}],
 "terms": [
  {"term": "SNR", "kind": "measure", "where": "Sec. 1",
   "definition": "defined as the ratio of evoked power to pre-stimulus baseline power"},
  {"term": "10-fold cross-validation over trials", "kind": "split"}]}
```
An ineligible answer keeps `summary` (`(TBD)` lines are fine) and has `"units": [], "experiments": []`, with
`eligibility: {"verdict": "ineligible", "criteria": ["EX1"], "reason": "…"}`.

### Edge cases (from the golf acceptance run)
- **No abstract** (title only): one claim at most, quoted from the title, strength `may` or `suggests`; `summary.problem`
  says "(no abstract)".
- **Eligibility on a topic without protocol criteria** (framed before protocols, `pico` only): an ineligible paper names
  the pico slot(s) it falls outside of in `criteria` (`population`, `intervention`, …). Off-population but on-method papers
  (a simulation, a clinical benchmark) stay eligible when the protocol's outcomes concern their method; say so in `reason`.
- **How many claims**: more than 12 from one full text is a WARN (D18) — usually statistics recorded one by one.
- **Definitions** may be short when the definition is the edges ("Alpha Low (8–10 Hz)": 2 words / 8 characters suffice).
  Not every measure has a definition in the paper (AUROC, balanced accuracy): leave `definition` out then.
- **Text broken by the layout** (columns interleaved, footnotes or headers mid-sentence): quote the longest contiguous
  stretch of at least 4 words that carries the unit; when none exists, quote the nearest sentence that states the same
  result and say so in `where` ("Sec. 4, sentence broken by layout").
- **"can"**: "X can match Y" after the paper showed it → `shows`; "X can be used to …" as a proposal → `may`. A review's
  "most studies find …" → `shows`, with the scope "studies reviewed".
- **`role`**: a tool, software or data resource paper is `resource`.
- **Designs that are not splits**: a between-group or pre/post comparison goes in `design_choices`; `split` is for
  evaluation splits of predictive work and is `(NA)` for a non-predictive design.
- **`builds_on_keys`** (optional, in `summary`): the citation keys of shortlisted papers this paper says it builds on or
  argues with. The collision step shows them to the judges, so `extends` can rest on a key instead of an author-year
  that may be another version of the paper (D19 checks the keys).
- **The quote carries what the text asserts.** When the text joins two clauses of the source ("less working memory and
  more motor programming"), the quote covers both, or the unit is split in two; a quote that stops before the clause the
  text adds lets a later step cite evidence that does not say it (golf50: daouetal2018#C3, quoted only "a decrease in
  working memory and action monitoring", was used in X0038 for its motor-programming reading). The verbatim check cannot
  see this: word overlap between text and quote flags half of all units, so the self-check is yours — reread each quote
  against its text before handing in.
- **Parallel subagents**: name helper files with the batch number (`decon_b2_*`) — they share one scratch folder.
- **A paper leaves the shortlist** (a screening change after the block began; A4.k retires its key): `decon-plan` moves
  its record to `knowledge/decon/_withdrawn/`, removes its note and sets a pending answer aside under `answers/_withdrawn/`;
  a paper that comes back gets the same record again. The later steps then see it gone: its coordinates and overrides
  are dropped at the next `align-set` / `align-coords`, and the collisions on it are retired with their candidates
  (closed_loop_sensory_modulation, 2026-10-19: 144 papers after PLAN_ideate_search §14.4 made only EX criteria soft).

### Fan-out
`decon-plan` writes one batch file per subagent under `knowledge/_work/A7D/` — full-text batches of 6, abstract
batches of 40 — listing only papers with no record or a stale one. Brief each subagent with: this file's path, its batch
file, and the rule that it writes one answer per paper to the path the batch names and changes nothing else (it runs
`decon-check <RD> --answer <file>` on its own answers, never `decon-merge`, `build-methods` or `concept-index`). The answer
is the record **with** `citation_key`, `basis` and `model` (the model that wrote it) and **without** `schema`,
`source_sha`, `at`, `history` (the tool adds them) — the example below. Full-text batches go to a model no lower than the main session's; abstract batches may go one tier lower
(PLAN_ideate_fusion F-D17). Then `decon-merge` once in the main session; a refused answer is listed with its problems — send
only those papers back.

### Outputs
`knowledge/decon/<key>.json` (`ai-scientist-decon/1`: the answer plus `basis`, `source_sha`, `at`, `history`) and, for
every **eligible full-text** record, `knowledge/_notes/<key>.md` — a **view** in the old note's labels and order (`Claim scope:`
from C1, `Assumes:` from the A units, `Not done:` from the N units, `Future work:` from the F units), so `concept-index`
and stage B read it as before — a note still means "read in full and used as evidence", so an ineligible paper gets none
(its record holds the reason) and `notes_with_claim_fields` is not diluted. `Disagrees with:` is `(TBD)` until the collision step projects it. Never edit a note; edit
the record (`decon-merge --revise`) and re-render.

The methods matrix is built straight from the records:
`build-methods $RD $RD/knowledge/methods_matrix_input.json $RD/knowledge/decon/*.json`, where `methods_matrix_input.json`
is the alignment step's projection of the vocabulary ([F2-align.md](F2-align.md#a7a1)) — never written by hand.

### Done when
`decon-check <RD>` passes: every record parses and matches its file name and the shortlist (D01); its basis is the full
text whenever one exists (D02); unit ids are well-formed and unique (D04); every quoted unit has `where` and a verbatim
quote, a not-done unit has none, and every measure definition is verbatim (D05); claims carry a strength from the scale
and a scope (D06); the eligibility verdict fits the basis, and an ineligible paper names protocol criteria and carries no
units or rows (D07); experiment ids, evidence and counts are right and an abstract row has no `(NR)` (D08); every eligible
paper has a main claim (D09); no record is stale against its source (D11); every shortlisted paper has a record (D12);
every eligible full-text record has a note equal to its rendering and no other record has one (D13); terms have a kind (D14); every record names its model (D16). Warnings:
more than three claims from an abstract (D10), no terms (D14), a strong verb on a hedging quote (D17).

### When something fails
A refused answer is not written; `decon-merge` exits 1 and lists the problems per paper — re-dispatch those papers. A
full text that changes (a better conversion, a hand-fetched PDF) makes the record stale (D11); `decon-plan` lists it again
and the new record is written with the old one's hash in `history`. A current record is replaced only through
`decon-merge --revise "<why>"`. A knowledge base with hand-written notes and no `knowledge/decon/` is frozen: `decon-merge`
refuses to run there.

### Commands
```bash
SK=.claude/skills/ai-scientist-ideate; PY=python3; RD=<topic>_research
$PY $SK/scripts/ideate_tools.py decon-plan  $RD
#   (one subagent per batch: knowledge/_work/A7D/batch_NNN.json -> knowledge/_work/A7D/answers/<key>.json)
$PY $SK/scripts/ideate_tools.py decon-check $RD --answer $RD/knowledge/_work/A7D/answers/<key>.json   # subagent self-check
$PY $SK/scripts/ideate_tools.py decon-merge $RD
$PY $SK/scripts/ideate_tools.py decon-check $RD
$PY $SK/scripts/ideate_tools.py build-methods $RD $RD/knowledge/methods_matrix_input.json $RD/knowledge/decon/*.json
```
