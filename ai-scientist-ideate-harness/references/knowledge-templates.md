# Point / Line / Plane / Body templates (點 / 線 / 面 / 體)

Card templates for stage A step A7 (and the prescriptive Body in stage B, step B6), preceded by the reading-note
template the cards are built from. The schema — four layers, the required
fields, the diagnostic questions — is the knowledge-organisation method and is kept exactly. What was removed is only
vault plumbing: P-number assignment, cross-session dedup, promotion.

Rules that hold for every card:

1. `status: draft`, plus `provenance` naming the files the card was built from.
2. A field with no source gets `(TBD)` — never blank, never filled from general knowledge.
3. Ids are slugs: `P_draft_{Slug}`, `E_/D_/A_draft_{Topic}`, `F_draft_T{N}_{ThemeSlug}`, `B_draft_{slug}`.
4. Cross-references use `[[P_draft_X]]`. In plain markdown that is just text, and it keeps the cards portable to a
   wikilink-aware knowledge base later.
5. Section headings keep their Chinese label in parentheses; card content is English.
6. Cite papers as `(Author et al., Year) [citation_key]`.

`ideate_tools.py concept-index` reads the YAML frontmatter plus the `[[P_draft_X]]` links in each Point's Inspiration
section, so keep the field names and that section heading unchanged, and keep list fields as YAML lists. Points and
Planes are normally rendered by `build-cards` (last section) rather than typed out.

---

## Reading note — `knowledge/_notes/{citation_key}.md`

Not a card: no frontmatter, no `status`, plain lines, ≤ 18 of them. One per paper read in full, written in Pass 0
(knowledge-passes.md, "Pass 0"). The free lines above the last four may be worded and ordered as suits the paper; the
last four keep exactly these labels, this order, and one line each — `concept-index` collects them by label.

```markdown
# {citation_key} — {short title}
- Problem: {what the paper sets out to solve}
- Method: {how, in one or two lines}
- Data: {name, n subjects / trials, modality; licence if the paper states it}
- Metrics: {primary first}
- Headline: {value, condition, where — [Table III, page image] when read from the page}
- Stated limitations: {the paper's own statements}
- Future work: {the paper's own statements}
- Builds on / argues with {citation keys or names, and on what point}
Claim scope: {main claim + for whom / on what data + how firmly, in the source's own strength of wording}
Assumes: {premises taken for granted and not tested; (TBD) when none can be pointed to in the text}
Disagrees with: {citation_key of an already-read paper whose claim or number conflicts, and why; or none}
Not done: {what the paper visibly did not test, vary or compare}
```

| line | how to fill it from the paper |
|---|---|
| `Claim scope:` | Scope and confidence as the source words them — keep its verb ("causes" / "may contribute to" / "correlates with … in") and its stated population or conditions. Never strengthen a hedge. |
| `Assumes:` | What the method or argument needs to be true but the paper does not check (labels as ground truth, a preprocessing step as harmless, a split as leakage-free, a metric as measuring the construct). |
| `Disagrees with:` | Which paper already read in this knowledge base it conflicts with, by citation key, and the likely reason (data, split, metric, definition). `none` when there is no conflict. |
| `Not done:` | Your observation, in your words, of what the paper visibly did not test, vary or compare. Later stages cite it as `not done in [key] (reading note)`; it is never placed in quotation marks, because the paper did not say it. |

`Assumes:` feeds `signals.assumptions` and `Disagrees with:` feeds `signals.disagreements` of `concept_index.json`
(`Claim scope:` is read by you in B3, when checking that a source really claims what a gap says it claims); `Not done:`
and `Future work:` feed `signals.not_done_and_future_work` as before. `notes_with_claim_fields: "n/N"` in the index
says how many notes carry the three lines. A note written before they existed is valid as it stands and is skipped
for the two new signals — **do not backfill**. The
lines are added to an old note only when a later B3's source check opened that paper's full text — as contradiction
evidence, or for the premise of a `confirm-assumed` gap (knowledge-passes.md, "No backfill").

---

## Point — `knowledge/points/P_draft_{Slug}.md`

```markdown
---
id: P_draft_{Slug}
type: point
name: "{Full canonical name}"
description: "{one-sentence claim}"
tags: []                    # add low_confidence / needs_fulltext when they apply
domain: []                  # AI / Neuroscience / Signal Processing / …
field: []                   # BCI / CV / Compression / …
status: draft
created: YYYY-MM-DD

# relations (filled by Pass 2 patches)
parent:
parts: []
depends_on: []
caused_by: []
causes: []

# cross-layer
related_lines: []
related_planes: []          # the Plane id of its theme

# point-specific
source: ""                  # citation_key of the defining paper
year:
claim_type: methodological  # theoretical | empirical | methodological | conceptual

provenance:
  source_files: []          # e.g. step5_full_text/songetal2021.md, step3_shortlist.json#paper_012
  generated_at: YYYY-MM-DD
---

# {Full canonical name}

> **Core claim (核心主張)**: {one-sentence assertion}

## Source (來源)
- Authors / year / venue:
- citation key: ``
- Also appears in: {other shortlisted papers that name this concept — this is what qualified it as a Point}

## Purpose (目的)
{1–2 sentences: what problem does this concept answer?}

## Core claim, expanded (核心主張・展開)
{3–5 sentences}

## Method (方法)
{3–5 sentences: how it works}

## Findings (發現)
{specific results — numbers, datasets, comparisons, each with its citation key}

## Inspiration (啟發)
- **Inspired by**: [[P_draft_X]] — {how}
- **Inspired**: [[P_draft_Y]] — {how}
```

The six fields — Source, Purpose, Core claim, Method, Findings, Inspiration — are the minimum.

---

## Line — three standalone sub-types

Only relations that pass the escalation threshold (≥ 3 paragraphs of source material, or a major cross-theme axis;
debates also need ≥ 2 named sides) get a card. Everything else is a line in `lines/frontmatter_patches.md`.

The original templates closed each Line with a "what this means for the vault owner" section. Here that section is
**Relevance to this topic**, read against the protocol's slots and outcomes (the PICO of older topics) — it is the hook the gap analysis picks up.

### Evolution — `knowledge/lines/E_draft_{ChainTopic}.md`

```markdown
---
id: E_draft_{ChainTopic}
type: line
relation_type: evolution
endpoints: []               # Point ids in chronological order
status: draft
provenance: {source_files: [], generated_at: YYYY-MM-DD}
---
# {Chain title}
## Full chain (完整鏈條)
## Mechanism of each step (每一步的機制)
## Counter-examples and exceptions (反例與例外)
## Relevance to this topic (對本題的意義)
{Where does the chain stop? What would the next step be, and has anyone taken it?}
```

### Debate — `knowledge/lines/D_draft_{Topic}.md`

```markdown
---
id: D_draft_{Topic}
type: line
relation_type: debate
endpoints: []               # Point ids on each side
status: draft
provenance: {source_files: [], generated_at: YYYY-MM-DD}
---
# {Debate title}
## Axis of disagreement (爭論軸)
## Positions (兩派／三派主張)
## Evidence compared (證據對比)
{side by side: datasets, metrics, numbers, citation keys}
## Proposed resolutions (解套提案)
{only resolutions the papers themselves propose; otherwise (TBD)}
## Relevance to this topic (對本題的意義)
{What experiment would settle it? Is it affordable on CPU / Apple MPS?}
```

### Analogy — `knowledge/lines/A_draft_{Topic}.md`

```markdown
---
id: A_draft_{Topic}
type: line
relation_type: analogy
endpoints: []               # Point ids mapped across domains
status: draft
provenance: {source_files: [], generated_at: YYYY-MM-DD}
---
# {Analogy title}
## Structure mapping table (結構映射表)
## Why it is an isomorphism (為什麼是同構)
## Limits of the mapping (映射的極限)
## Relevance to this topic (對本題的意義)
```

### Patches — `knowledge/lines/frontmatter_patches.md`

```markdown
- `P_draft_X` ← `depends_on`: `[P_draft_Y]`  (source: songetal2021 §II)
- `P_draft_X` ← `parent`: `P_draft_Z`  (source: leeetal2019 related work)
```

Apply each patch to the target Point's frontmatter too.

---

## Plane — `knowledge/planes/F_draft_T{N}_{ThemeSlug}.md`

One per theme from Pass 0.

```markdown
---
id: F_draft_T{N}_{ThemeSlug}
type: plane
name: "{Theme title}"
member_points: []           # Point ids in this theme
member_papers: []           # citation keys assigned to this theme
adjacent_planes: []
status: draft
provenance: {source_files: [], generated_at: YYYY-MM-DD}
---
# Theme {N}: {Theme title}

## Q1 What problem does it solve? (解決什麼問題)
## Q2 Core concepts (核心概念有哪些)
{the member Points, one line each}
## Q3 Relations among the concepts (概念之間關係)
{the Lines and patches whose endpoints lie inside this theme}
## Q4 Dominant methods (常用方法)
{designs, datasets, baselines, metrics, evaluation protocol; how this shifted over the years}
## Q5 Common errors / open problems (常見錯誤)
{only the papers' own limitation and future-work statements and the Pass 2 debates — quoted or closely paraphrased,
 each with a citation key. No invented pitfalls.}

## Promote / demote judgement (升格／降格判斷)
{Is this really one theme? Should it split or merge?}
## Relation to other Planes (與其他 Plane 的關係)
```

---

## Body

### Descriptive — `knowledge/body/B_draft_{topic_slug}_descriptive.md` (stage A, one per topic)

```markdown
---
id: B_draft_{topic_slug}_descriptive
type: body
body_role: descriptive
modules: []                 # the Plane ids
feedback_loops: []
based_on: []
status: draft
provenance: {source_files: [], generated_at: YYYY-MM-DD}
---
# {Topic}: the field as it stands

## Q1 What is the field trying to achieve?
## Q2 Main research lines
## Q3 How the methods evolved
## Q4 Inputs and outputs of each line — data and metrics
## Q5 Dependencies and conflicts between lines
## Q6 How the field evaluates and iterates
## Q7 The real problem it claims to solve
```

### Prescriptive — `gen_{k}/body/B_draft_{idea_Name}.md` (stage B, one per idea)

The original seven questions, unchanged, answered from the locked gap and the final hypothesis.

```markdown
---
id: B_draft_{idea_Name}
type: body
body_role: prescriptive
modules: []                 # the Planes this idea touches
feedback_loops: []
based_on: [B_draft_{topic_slug}_descriptive]
gap: GAP_00N
angle: "{the angle of this generation}"
status: draft
provenance: {source_files: [], generated_at: YYYY-MM-DD}
---
# {Idea Title}: research plan

## Q1 Core goal of the plan (計畫核心目標)            ← gap summary + RQ1 framing
## Q2 Main work items (主要工作項)                    ← IN scope + conceptual framework
## Q3 Ordering — what precedes what (前置／後置)      ← experiment order and dependencies
## Q4 Input / output of each stage (每階段 I/O)       ← per experiment: data in, metric out
## Q5 Cross-stage influence (階段間互相影響)          ← risk table: each risk as a cross-stage dependency
## Q6 Feedback loops (回饋循環)                        ← mitigations + what result would redirect the plan
## Q7 What real problem does it solve? (解決什麼真實問題) ← motivation + target-venue audience

## Risks and alternative paths (風險與替代路徑)       ← the risk table, verbatim
## Target outputs (連到的 Outputs)                     ← the recommended venues
```

Do not confuse Plane Q5 (pitfalls of a theme, sourced from the papers) with Body Q5 (how the stages of *this* plan
affect each other, sourced from the risk assessment).

---

## `build-cards` input

`ideate_tools.py build-cards <research_dir> knowledge_cards.json` renders the Point and Plane templates above from
compact JSON, so the frontmatter is always well-formed and no required field can be forgotten. Any content key you
leave out is rendered as `(TBD)` — which is the correct output when the sources do not support it.

```json
{"points": [{
    "slug": "CCSDS_123",                       "name": "CCSDS 123.0-B predictive compression",
    "description": "one-sentence claim",        "claim_type": "methodological",
    "source": "barriosetal2024", "year": 2024,  "also_in": ["zhengetal2023"],
    "plane": "F_draft_T1_Predictive",           "tags": ["needs_fulltext"], "domain": ["Signal Processing"], "field": ["Compression"],
    "purpose": "…", "core_claim": "…", "expanded": "…", "method": "…", "findings": "… with citation keys",
    "depends_on": ["P_draft_Y"],
    "inspired_by": [{"id": "P_draft_X", "how": "…"}], "inspired": [{"id": "P_draft_Z", "how": "…"}],
    "source_files": ["step3_shortlist.json#paper_012"]}],
 "planes": [{
    "n": 1, "slug": "Predictive", "name": "Predictive lossless coding",
    "member_points": ["P_draft_CCSDS_123"], "member_papers": ["barriosetal2024"], "adjacent_planes": ["F_draft_T2_Resilience"],
    "q1": "…", "q2": "…", "q3": "…", "q4": "…", "q5": "… quoted limitations with citation keys",
    "judgement": "…", "relations": "…", "source_files": []}]}
```

Two optional top-level maps feed the paper–theme table, which `build-cards` writes into `knowledge/_MANIFEST.md` itself
(between `theme-table` markers — write the rest of the manifest around that block, do not hand-write the table):
`"methodology": {"<citation_key>": "experimental | computational | review | observational | engineering | theoretical"}`
and `"bridges": {"<citation_key>": "T3"}` for papers that also matter to another theme. A shortlisted paper that no
Plane lists under `member_papers` shows up as **UNASSIGNED** — every paper needs a theme.

Ids are derived as `P_draft_{slug}` and `F_draft_T{n}_{slug}`; use those exact ids in `plane`, `member_points`,
`inspired_by` and so on. Re-running overwrites the cards it renders and leaves hand-written Lines and Bodies alone.

---

## `build-methods` input — the method & experiment-design matrix (Pass M)

`ideate_tools.py build-methods <research_dir> knowledge/methods_matrix_input.json [knowledge/methods_batches/*.json]`
validates and normalises one row **per main experiment** and renders `knowledge/methods_matrix.{json,md}`. Several input
files are concatenated, so the rows can be written in batches (and resumed batch by batch); `vocab` and `aliases`
normally live in the first file only.

```json
{"vocab": {"method_family": {
    "robust-statistical-thresholding": "bad channels / epochs flagged by robust z or SD cut-offs on hand-crafted features"}},
 "aliases": {
    "dataset":  {"PhysioNet EEGMMIDB": ["EEGBCI", "EEG Motor Movement/Imagery Dataset", "C64"]},
    "baseline": {"no cleaning": ["raw", "uncleaned"]},
    "metric":   {"F1": ["F1 score", "macro F1"]},
    "split":    {"LOSO": ["leave-one-subject-out"]}},
 "not_shared_datasets": ["simulated EEG (own)", "own recordings (not public)"],
 "experiments": [{
    "exp_id": "ahmedetal2026#E1",  "citation_key": "ahmedetal2026",  "evidence": "full-text",
    "where": "Sec. 3-4, Fig. 6",
    "role": "comparison-study",
    "problem": "which classical alignment best reduces inter-subject mismatch for a new user",
    "method_family": ["data-alignment"],
    "core_idea": "compare RPA / EA(alpha) / CORAL(lambda) in front of one CCA decoder",
    "pipeline": "alignment -> CCA decoder",
    "novel_vs_prior": "(NR)",
    "design_choices": "alpha, lambda swept 1e-4..1e4 and picked on the target subject -> oracle bound",
    "claim_tested": "no single alignment is best for every subject",
    "factors": ["alignment method (4)", "alpha / lambda sweep (9 levels)"],
    "data": [{"name": "Reichert2020 covert attention", "n": "18 subj x 168 trials", "modality": "EEG 14 ch", "preproc": "1-12.5 Hz, 50 Hz"}],
    "split": "LOSO",
    "leakage_control": "default parameters leakage-free; swept results labelled oracle",
    "baselines": ["no alignment", "subject-dependent decoder"],
    "ablations": ["(NR)"],
    "metrics": ["accuracy", "Cohen's dz"],  "metric_notes": "chance 50%",
    "stats": "paired t-test, Cohen's dz, 95% CI; 18 subjects",
    "headline": "EA alpha=100 +3.44 pt vs none, p~0.024 (oracle) [Sec. 4]",
    "compute": "(NR)",  "code_data": "(TBD)",
    "affordable_here": "yes - classical methods, CPU minutes",
    "not_done": ["no cross-dataset alignment", "no shift metric before/after alignment"]}]}
```

| field | rule |
|---|---|
| `exp_id` | `<citation_key>#E<n>`; a paper has **≤ 4** rows (its main experiments, not every table); an abstract-only paper has **exactly 1** |
| `evidence` | `full-text` when `step5_full_text/<key>.md` exists and was read, else `abstract` |
| `role` | `proposes-method` / `comparison-study` / `benchmark` / `dataset` / `analysis` / `review` |
| `method_family` | tags from `vocab.method_family` only — the topic's own list, fixed once at the start of Pass M. On the fusion block the rows come from A7.D records, written in the reader's own words before any vocabulary exists; the alignment step maps them (references/fusion/F1-deconstruct.md) |
| `data[].name`, `baselines`, `metrics`, `split` | canonical names; put every variant spelling under `aliases` so counts are right. `metrics`: primary first |
| `affordable_here` | starts with `yes` / `partial` / `no`, then the reason, judged against `local_environment` in `step0_session_config.json` |
| `not_done` | the reading note's `Not done:` line split into items; for abstract rows `(TBD)` |
| `theme` | optional — derived from the Planes' `member_papers` in `knowledge_cards.json` |
| `not_shared_datasets` | top level: placeholder dataset names ("own recordings", "own simulation") — listed in the dataset table, but kept out of the conventions and the holes grid, which are about benchmarks the field actually shares |

Kinds of empty, never interchangeable:

- **`(TBD)`** — not verified: abstract only, or the note does not say and the full text was not checked.
- A short reason may follow either tag — `"(NR) - point estimates only, no CI"` — and still counts as that tag. Prefer
  it: the reason is what B3 quotes.
- **`(NA)`** — read in full, and the field does not apply to this design (a split in a non-predictive ANOVA). Counted
  apart from `(NR)`; on an abstract row it becomes `(TBD)` like `(NR)`.
- **`(NR)`** — read in full, and the paper does not report it (no statistical test, no compute, no baseline). Only valid
  on full-text rows — `build-methods` turns an `(NR)` on an abstract row back into `(TBD)`. The share of `(NR)` per field
  is reported as the field's *reporting habit*; "12 of 20 experiments report no statistical test" is methodological evidence.

Omitted fields are rendered as `(TBD)`. `build-methods` refuses to write (exit 1) on a malformed `exp_id`, a duplicate,
a key not in the shortlist, `full-text` without a full text, > 4 rows per paper or > 1 row for an abstract-only paper; it
warns on unknown vocabulary, a role outside the list, an `affordable_here` without a verdict, and an abstract row for a
paper that has a full text. Every shortlisted paper without a row is listed.

`methods_matrix.md` sections: 1 overview table · 2 Method Development (family × theme, evolution by family and year) ·
3 Experiment Design (datasets with the splits used on them, splits, baselines, metrics, reporting habits, stats /
compute / affordability) · 4 conventions (share of full-text experiments; `convention` ≥ 50 %, `common` ≥ 25 %) ·
5 structural holes (dataset × method-family grid over datasets used by ≥ 2 papers; fields not reported) · 6 row details.
Sections 4–5 are computed from full-text rows only and are omitted when there are none.
