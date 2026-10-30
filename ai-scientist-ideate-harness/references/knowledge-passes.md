# Stage A · step A7 — the knowledge base (Point / Line / Plane / Body)

Read this when you reach A7, i.e. after A6 has produced the full texts (or, at `--depth quick`, straight after A5).
Commands assume the `SK`, `PY`, `RD` variables from [scholar-pipeline.md](scholar-pipeline.md) §1 — set them again at
the top of each command block. Card templates and the `build-cards` JSON schema are in
[knowledge-templates.md](knowledge-templates.md).

**Contents:** the four layers and the two rules · Pass 0 themes and reading notes (claim lines, no backfill) · Pass M method & experiment-design matrix ·
Pass 1 Points · Pass 2 Lines · Pass 3 Planes · Pass 4 descriptive Body · full texts that arrive later · index and manifest

The most important step of stage A. It turns N separate papers into one cross-paper structure — **Point / Line /
Plane / Body (點 / 線 / 面 / 體)** — which is what stage B re-reads from a different angle for every generation. The
four-layer schema is the organising method itself and is kept intact; only its original storage and promotion
machinery (a personal Obsidian vault) is gone. Templates: [knowledge-templates.md](knowledge-templates.md).

| Layer | What it is | What stage B uses it for |
|---|---|---|
| **Point** 點 | atomic concept card: a method, model, phenomenon, metric, paradigm or flagship result | the unit a new angle regroups |
| **Line** 線 | a relation between Points: `evolution`, `debate`, `analogy` (+ light relations as patches) | where gaps live: an unresolved debate, a broken evolution chain |
| **Plane** 面 | one card per theme, five diagnostic questions | the thematic grouping for each synthesis |
| **Body** 體 | the whole picture, seven diagnostic questions | descriptive here; prescriptive per idea in stage B |

Your role is to **fill template slots from sources, not to invent structure**. Two rules matter more than the rest:

- A field you cannot support from a paper you actually read gets `(TBD)`. Never leave it blank and never fill it from
  general knowledge. An invented "Findings" line is worse here than anywhere: the novelty judgement of every later
  idea rests on these cards. With abstracts only, expect many `(TBD)`s — especially under Inspiration, which abstracts
  almost never support. A card that is half `(TBD)` is an honest card, not a failed one.
- Every card carries `status: draft` and a `provenance` block naming the files it was built from.

Output tree: `$RD/knowledge/{points,lines,planes,body}/`, plus `_MANIFEST.md` and `concept_index.json`.

Points and Planes are written through a helper so their frontmatter stays consistent and no required field is dropped:

```bash
$PY $SK/scripts/ideate_tools.py build-cards $RD $RD/knowledge_cards.json     # JSON schema: knowledge-templates.md, last section
```

You supply the content as compact JSON; anything you omit is rendered as `(TBD)`. Line cards and the Body are few —
write those by hand from the templates.

## Pass 0 — themes

Read every `step5_full_text/*.md` — introduction, methods, results, limitations — and the abstracts of the remaining
shortlisted papers (at `quick` depth there are no full texts: work from the shortlist abstracts via `list-papers
--file shortlist`). Identify **4–6 themes**. A good theme has a one-sentence intellectual identity, holds at least 2–3
papers, and is distinguishable from its neighbours; "deep learning papers" is a keyword bucket, not a theme. Assign
every shortlisted paper exactly one primary theme and note bridge papers. Record this as a table at the top of
`knowledge/_MANIFEST.md` (`citation_key | theme | methodology | bridge to`), with methodology one of
experimental / computational / review / observational / engineering / theoretical.

With full texts, keep reading notes per paper as you go (`knowledge/_notes/{key}.md`, ≤ 18 lines: problem, method,
datasets, metrics, headline numbers, stated limitations, stated future work, who it builds on / argues with, then the
three claim lines below, and a final line **`Not done:`** — what this paper visibly did not test, vary or compare).
Later passes and stage B read the notes and the cards, not the full texts again, and the `Not done:` lines turn out to
be the richest source of gaps. `Not done:` is your observation of what the paper did not do — later stages may cite it
as that (`not done in [key] (reading note)`), never quote it as the paper's words or as a future-work call, because a
reader who looks the quotation up will not find it in the paper. The datasets line (`Data:`) also records the
dataset's licence when the paper states it: stage B may not use the network, so a licence nobody noted while reading
stays `(licence unverified)` until the journal step.

The three claim lines sit directly before `Not done:`, in this order, each on **one line** with exactly this label
(`concept-index` matches the label at the start of a line, as it does for `Not done:`):

```
Claim scope:      {the main claim, its scope and its confidence, at the strength the paper itself words it}
Assumes:          {premises the paper takes for granted and does not test}
Disagrees with:   {citation_key of an already-read paper it conflicts with, and why they differ; or none}
Not done:         {what this paper visibly did not test, vary or compare}
```

- **`Claim scope:`** — state what is claimed, for which population / data / conditions, and how firmly. Keep the
  source's own verb: "causes", "may contribute to" and "correlates with … in" are three different claims, and a note
  that upgrades a hedge makes a later contradiction-type gap attack something the paper never said (Craft of
  Research 6.6.4). Take it from the abstract's last sentences and the conclusion, not from the title.
- **`Assumes:`** — what the method or the argument needs to be true but the paper never checks: a label taken as ground
  truth, a preprocessing step taken as harmless, a split taken as leakage-free, a metric taken as measuring the
  construct. Write only premises you can point to in the text (a method step, a sentence); none visible → `(TBD)`.
  The same premise recurring across papers is what B3 reads as an untested convention.
- **`Disagrees with:`** — a claim or a number that conflicts with a paper you have **already read in this knowledge
  base**, named by citation key, plus the likely reason (different data, split, metric, definition). It need not be a
  disagreement the paper states itself; a conflict you see between two notes counts, and says so ("not stated by
  either paper"). No conflict → `none`. Never name a paper outside the shortlist: the key is what B3 follows back.

These lines exist because a gap built on `Not done:` alone is an absence — nobody did it — which says nothing about
whether anyone should. A conflict between two papers, or a premise everybody shares and nobody tested, is a condition
the field already has a stake in (research-cycle.md §3; question-craft.md section 3).

**No backfill.** A knowledge base whose notes were written before these lines existed is left as it is — do not reopen
full texts to add them. `concept-index` skips notes without them silently and reports the coverage
(`notes_with_claim_fields`, see "Index and manifest"). The one exception is on demand: when a later B3's source check
opens a paper's full text — to cite it as contradiction evidence, or to quote where it states or relies on the premise
of a `confirm-assumed` gap — add the three lines to **that paper's** note, from that full text, then re-run
`concept-index`; the look has already been paid for, and without the lines the next generation would repeat it. Only
the papers opened that way are touched; nothing else in stage A is repeated.

**Numbers in tables and figures come from the page image.** When a headline number sits in a table or a plot — or the
converted text shows the table scrambled — open the page from `step5_full_text/figure/index.json` (the caption tells
you which file) with the Read tool and take the number from there, citing it as `[Table III, page image]`. Do not write
"values lost in conversion" when the page image exists.

Twenty full texts are well over 100k words; reading them end to end is neither affordable nor necessary. Read each
paper *for the note*: abstract, the last paragraph of the introduction (contributions), the method section's headings
and first paragraphs, the results tables and their captions, then limitations / discussion / future work in full.
`grep -n` for the outcome terms (the protocol's outcomes and outcome axes) to catch anything the skim missed.

## Pass M — method & experiment-design matrix (方法與實驗設計矩陣)

The reading notes say what each paper did; nothing yet says how the *field* runs its experiments — which datasets
everyone shares, which split is standard, which baselines are expected, how often a statistical test is reported.
Pass M turns the notes into one row **per main experiment** so those questions become counts. It runs once per topic,
right after Pass 0, because Plane Q4 and Body Q4/Q6 are then written from it instead of from memory, and stage B filters
it by angle instead of re-reading `_notes/` for every idea.

1. **Fix the vocabulary first.** Write `knowledge/methods_matrix_input.json` with `vocab.method_family` — 10–25 tags,
   each with a one-line definition, covering the method families the themes contain — and `aliases` for the dataset,
   baseline, metric and split names that appear under several spellings. Counting only works on one vocabulary, and it
   has to exist before the rows do. Give splits a canonical set that keeps the *unit* apart — trial-level k-fold,
   subject-grouped k-fold and "k-fold (unit not stated)" are different claims about leakage, and a bare "10-fold CV"
   must not be aliased to either of the first two.
2. **Rows.** One per main experiment (a synthetic ground-truth test and a downstream test are two rows), at most 4 per
   paper; exactly one per abstract-only paper. Start from the reading note; open the full text only for what the note
   does not settle — stats (tests, CIs, repeats), compute, code/data availability, ablations, and how thresholds or
   hyperparameters were chosen (leakage). `grep -n` beats re-reading; table and plot values come from the page images
   in `step5_full_text/figure/` (see Pass 0). Write rows in batches under
   `knowledge/methods_batches/` (one file per batch).

   **Fan it out** when subagents are available — it is the one step of A7 that parallelises cleanly, and doing it in
   the main session would pull every full text through your context. Proven split (97 papers, 17 full texts: ~5 min
   wall-clock, ~0.5M subagent tokens): three agents for the full-text papers (5–6 papers each, reading note first, full
   text only by `grep`) and two for the abstract-only papers (~40 each, one row per paper, never `(NR)`). Give every
   agent the same brief: the path of this section and of the schema (knowledge-templates.md, "`build-methods`
   input"), the vocabulary file (read-only), its paper list, its own output file, and the rule that it must not run
   `build-methods` (it rewrites the shared outputs). Then build once yourself. Without subagents, write the full-text
   rows in the session and the abstract rows in batches of ~20 from `list-papers --file shortlist --ids`.
3. **`(TBD)` vs `(NR)`.** `(NR)` means "read in full, not reported" and is itself evidence (a field that rarely reports
   stats); `(TBD)` means "not verified". Abstract rows never carry `(NR)`.
4. **Build.**

```bash
$PY $SK/scripts/ideate_tools.py build-methods $RD $RD/knowledge/methods_matrix_input.json $RD/knowledge/methods_batches/*.json
```

   It refuses to write on structural errors and lists every shortlisted paper without a row — fix and re-run until it
   writes, then read its warnings (unknown vocabulary usually means a missing alias or a missing tag).
5. **Read the result.** Skim `knowledge/methods_matrix.md` §3–§5. Section 5 (structural holes) is facts, not gaps —
   do not copy it into Plane Q5; B3 weighs it. Check three things that the build cannot: (a) placeholders such as "own
   recordings" or "own simulation" go under `not_shared_datasets`, or they appear as the field's shared benchmark;
   (b) the `(NR)` share of `stats` is plausible — if it is near zero, agents probably wrote "(NR) - …" reasons that an
   older build did not count, or wrote a narrative instead of the tag; (c) any row that ran a method as a *step* (PREP's
   channel criteria inside a pipeline audit) carries that method's family tag too, or the holes grid shows an empty
   cell that is not empty.

Schema, field rules and the rendered sections: [knowledge-templates.md](knowledge-templates.md), "`build-methods` input".

Skipped when `knowledge/methods_matrix.json` exists. A knowledge base built before Pass M existed has none — run Pass M
on its own (steps 1–5, then fold it into Plane Q4 via `build-cards` and re-run `concept-index`); nothing else in stage A
needs repeating.

At `quick` depth there are no full texts: write one abstract row per paper anyway (it is cheap and stage B still reads
it), and expect `build-methods` to omit conventions and holes.

## Pass 1 — Points

A concept becomes a Point only if **both** hold:

1. it is named in **≥ 2 shortlisted papers** in their methods/results/consensus material (a concept that appears only
   in one side of an argument may be fringe). A preprint and its journal version count as one paper;
2. it is a method, a model, a phenomenon, a metric, a paradigm, or a flagship empirical result.

Do not stop at methods. A **cross-paper finding or explanation** — "rejection helps only below a baseline-accuracy
threshold", "artifacts can carry class information", a trade-off several papers report from different sides — is a
first-class Point (`claim_type: empirical` or `conceptual`), and in practice such Points seed more gaps than the
method cards do, because a finding is something a new experiment can confirm, bound or overturn.

"Named in ≥ 2 shortlisted papers" counts the papers that *use or discuss* the concept, not only the one that introduced
it: a snowballed classic with no abstract of its own still qualifies when two papers you read name it (that is what
made it a hub). Its card is then sourced from what those papers say about it, tagged `needs_fulltext`.

Drop dataset names (infrastructure — they surface in the Plane), generic ML techniques everyone knows (CNN, dropout),
and terminology only one paper uses. When unsure — or when abstracts only hint at a concept that the topic clearly
turns on — include it with the tag `low_confidence`.

Fill all six fields — **Source / Purpose / Core claim / Method / Findings / Inspiration** — from the full text where
available, otherwise from the abstract with the tag `needs_fulltext`. "Inspiration" (inspired-by / inspired) names
other Point ids as `[[P_draft_X]]`; `concept-index` reads those links as edges, so they are the only structure a
`quick` run has.

Progress line: `Pass 1 (Points): {themes} themes, {candidates} candidates → {new} drafts, {skipped} skipped`.

## Pass 2 — Lines

Relations come from two places: what the papers say about each other (related-work and discussion sections state
evolution and disagreement outright) and the Inspiration fields from Pass 1.

| The text says | Relation | Goes to |
|---|---|---|
| requires, builds on, depends on | dependency | `lines/frontmatter_patches.md` |
| is-a, part-of, subtype, shares | hierarchy | patches |
| causes, leads to, mitigates, fixes | causal | patches |
| evolved from, extends, scales, lineage | **evolution** | candidate `E_draft_*.md` |
| versus, contradicts, outperforms, disputes | **debate** | candidate `D_draft_*.md` |
| analogous to, parallels, cross-domain | **analogy** | candidate `A_draft_*.md` |

How a relation maps onto a Point's frontmatter — the direction is the part that goes wrong, so read each as a sentence
about the card you are editing ("**this Point** … the listed Point"):

| Relation in the text | Key on the card | Reads as | Example |
|---|---|---|---|
| X builds on / requires Y | `depends_on: [Y]` on X | this Point depends on Y | Autoreject `depends_on` cross-validation |
| X is a kind of / part of Y | `parent: Y` on X (and `parts: [X]` on Y) | this Point's parent is Y | FASTER `parent` statistical thresholding |
| Y causes / leads to X | `caused_by: [Y]` on X (and `causes: [X]` on Y) | this Point is caused by Y | accuracy inflation `caused_by` class-correlated artifacts |
| X appears in Line L | `related_lines: [L]` on X | — | — |

Default to a patch line. Escalate to a standalone card only when the relation is unpacked across **≥ 3 paragraphs** of
source material, or it is a major axis of disagreement across themes; a debate card additionally needs **≥ 2 named
sides**. Expect 2–5 standalone cards; more usually means over-eager escalation.

Patch format: ``- `P_draft_X` ← `depends_on`: `[P_draft_Y]`  (source: songetal2021 §II)``. Apply each patch by adding
the relation to that Point's entry in `knowledge_cards.json` (`parent`, `parts`, `depends_on`, `caused_by`, `causes`,
`related_lines`) and re-running `build-cards` — never by editing the rendered card, which the next rebuild overwrites.

Reading the thresholds: "≥ 3 paragraphs" means three paragraphs of source material *across all the papers you read*
that are about this relation — not three in one paper. A debate's "named sides" are two or more identifiable
positions, each backed by at least one shortlisted paper you can cite. Papers rarely argue with each other by name: a
side is normally a *group of papers whose results point the same way* (rejection helps: A, B — rejection does not: C,
D, E), reconstructed by you. That is intended. "Some argue…" with nobody to cite is not a side.

Skipped at `--depth quick`: without full texts there is no material to derive evolution or debate from.

## Pass 3 — Planes

One Plane per theme. Five questions: **Q1** what problem does this theme solve · **Q2** core concepts (the member
Points) · **Q3** relations among them (the Lines whose endpoints lie inside the theme; at `quick` depth, the
Inspiration links) · **Q4** dominant methods · **Q5** common errors / open problems.

Write Q4 from `methods_matrix.md` — the theme's rows in the family × theme table, its datasets, splits, baselines and
metrics, and the conventions they follow — citing `exp_id`s. The matrix already counted; Q4 says what the counts mean.

Q5 is the place most prone to invention. Source it only from the papers' own limitation and future-work statements and
from the debates found in Pass 2, quoted or closely paraphrased with citation keys. The gap analysis runs later, in stage B, and draws
on these Planes — so Q5 records what the papers say is open, and must not pre-empt it with gaps of your own.

## Pass 4 — descriptive Body

One card, `body/B_draft_{topic_slug}_descriptive.md`, `body_role: descriptive`. `{topic_slug}` is the topic file's
stem, or — when that is generic, like `topic` — a short slug of the topic title (`eeg_quality_vs_accuracy`). For a
descriptive Body `based_on` stays empty, `modules` lists the Plane ids, and `feedback_loops` names the field's own
loops (benchmark → method → benchmark), not yours. Stage A knows the field, not yet what
to do about it, so the seven questions are asked of the field as it stands:

| # | Question (descriptive reading) | Draws on |
|---|---|---|
| 1 | What is this field trying to achieve? | protocol (slots, outcomes) + Plane Q1s |
| 2 | What are its main research lines? | the Planes → `modules` |
| 3 | How did the methods evolve over time? | evolution Lines |
| 4 | What goes in and comes out of each line — data and metrics? | Plane Q4, `methods_matrix.md` §3 |
| 5 | Where do the lines depend on or conflict with each other? | debate Lines, cross-theme patches |
| 6 | How does the field evaluate and iterate — its benchmark culture? | Plane Q4/Q5, `methods_matrix.md` §4 and reporting habits |
| 7 | What real problem does it claim to solve? | introductions of the core papers |

Written at **every** depth. At `quick` it is thin — Q3 and Q5 depend on Lines that do not exist, so they are mostly
`(TBD)` — but it takes minutes, it is the entry point stage B reads first, and every prescriptive Body points back to
it through `based_on`.

## Full texts that arrive later

The user may drop hand-fetched PDFs into `pdfs/` (named as the **Worth fetching by hand** list in `_access_log.md`
says) after the knowledge base already exists. "Skip a step whose output exists" would then ignore them: the PDFs get
converted, but the cards never learn what is in them. So when `fulltext-status` reports a paper as `full-text` or
`full-text-plain` that has **no reading note** in `knowledge/_notes/`, fold it in:

1. `pdf2md.sh` and `fulltext-status` (both skip what is already done);
2. write the reading note for each new paper, including its `Claim scope:` / `Assumes:` / `Disagrees with:` lines and
   its `Not done:` line (Pass 0); then replace its abstract row in the
   methods matrix with full-text rows (a new batch file, and delete the old row) and re-run `build-methods`;
3. revise `knowledge_cards.json` where the full text changes something — fill `(TBD)` fields of Points sourced from
   that paper, drop its `needs_fulltext` tag, add Points it newly justifies, update the Plane's Q4/Q5 — then re-run
   `build-cards`; add or amend Line cards if it states an evolution or a disagreement; re-run `concept-index`;
4. note the addition in `_MANIFEST.md`.

Ideas already finalized are not rewritten; the next generation sees the richer base. If a newly read paper contradicts
a finalized idea's novelty claim, say so in the Finish report — that is worth more than the idea.

## Index and manifest

```bash
$PY $SK/scripts/ideate_tools.py concept-index $RD
```

Builds `knowledge/concept_index.json` by projecting the cards: nodes (Points), edges (Lines, patch relations and
Inspiration links), Planes, Bodies, and a `signals` block — `isolated_points`, `plane_pairs_without_any_line`,
`open_debates`, `evolution_chain_ends`, `not_done_and_future_work` (every `Not done:` / `Future work:` line of the
reading notes, by paper), `assumptions` (every `Assumes:` line, by paper) and `disagreements` (every `Disagrees with:`
line, by paper) — both built the same way as `not_done_and_future_work` — `claim_type_counts`, `dangling_references`,
and `methods` (Pass M's conventions, `(NR)` rates,
empty dataset × method-family cells and affordability counts; `available: false` if Pass M has not run). Stage B reads this instead of re-reading every card. Fix
any `dangling_references` (an id that matches no Point) before moving on.

The output also carries `notes_with_claim_fields: "n/N"` — how many of the N reading notes have the three claim lines.
Notes without them are skipped silently, so on a knowledge base built before the lines existed `assumptions` and
`disagreements` are empty or thin and the ratio is low. That means "not recorded", not "the field has no shared
premises and no conflicts"; B3 then falls back to its earlier source order (research-cycle.md §3). Do not backfill to
raise the ratio (Pass 0, "No backfill").

An evolution Line links its endpoints as an ordered chain; a debate or analogy links every endpoint to every other.
`signals.evolution_chain_ends` lists where each chain currently stops.

The index also carries `structure_reliable`. It is `false` when there are no Line cards — then "isolated" and
"unlinked" only mean that nothing was analysed, not that the field has a hole there.

`build-cards` owns the paper–theme table inside `_MANIFEST.md` (between its `theme-table` markers) and leaves everything
else in the file alone, so re-running it is safe. Around that block, finish `_MANIFEST.md` with per-pass counts, how many fields are `(TBD)`, and the known limitations of this run
(how many papers were abstract-only, which sources failed, whether the snowball recovered anything).
