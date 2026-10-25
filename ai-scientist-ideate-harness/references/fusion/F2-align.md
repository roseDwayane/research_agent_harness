# F2 align — one set of coordinates, and where we stand on it

**Align** is the second step of the fusion block ([README.md](README.md)). Deconstruction left every paper in its own
words: one says "SNR", another "signal-to-noise ratio", a third "SNR" but means something else. Nothing can be compared
until those words sit on one vocabulary, and every claim knows which construct, measure, population, data, split and
method family it is about. The same step puts **us** on those coordinates: which datasets are on this machine, which
method families it can afford. Comparing comes next (collide); here nothing is compared.

| Unit | Decides | Writes (through the tool only) |
|---|---|---|
| [A7.A1 vocabulary](#a7a1) | which words name the same thing; which word means two things | `knowledge/alignment.json` `vocab`; the projection `knowledge/methods_matrix_input.json` |
| [A7.A2 coordinates](#a7a2) | where each claim and assumption sits | `knowledge/alignment.json` `coords` |
| [A7.A3 concept Points](#a7a3) | which shared concepts get a Point card | `knowledge_cards.json` points with `origin: align`, through `build-cards` |
| [B1 lens](#b1) | who is looking, and what this machine holds, on the same concepts | `lens.json`; the projection again |

Inputs for all four: the A7.D records of papers that are evidence (`eligible` and `abstract-only`; an `ineligible`
record is never read here). Nothing in this step opens a full text.

---

<a id="a7a1"></a>
## A7.A1 — vocabulary

### Purpose
One concept per thing the papers name, so that counting and comparing happen on one vocabulary.

### Inputs
`align-terms` collects every word the records use — their `terms` (with a measure's defining sentence) and the names in
their matrix rows (`method_family`, dataset names, `baselines`, `metrics`, `split`) — grouped by spelling, with the papers
that use it, into `knowledge/_work/A7A/terms.json`. Read that file, not the records.

### Method

1. **Concepts.** `{id, kind, name, definition, variants[], family?, not_shared?, equivalence?}`. `id` = `<kind>:<kebab-slug>`
   with `kind` one of method-family · method · construct · measure · dataset · split · population · paradigm ·
   condition (a contrast a result is compared against: missed putts, a low-pressure block, novices as a comparison group). `name` is the
   canonical name (what the matrix prints); `definition` one line in your words; `variants` every other spelling the
   records use. The name and the slug count as spellings already. A `method` may name its `family` (a method-family
   concept). A placeholder dataset ("own recordings", "own simulation") gets `not_shared: true` — it is listed but never
   counted as a benchmark the field shares; say which case in `not_shared_reason` (placeholder · public but used by one
   paper · published but not identifiable).
2. **Which kind a word may go to.** A term keeps its kind (a `measure` term → a measure concept; a `method` term → a method or
   method-family concept); in rows, `method_family` → method-family, data names → dataset, `metrics` → measure, `split` →
   split, `baselines` → method, method-family, condition or population (a baseline is often a contrast condition, not a
   method). A word on the wrong kind is refused (A04).
3. **Granularity.** One method family is a mechanism, not a paper ("ICA cleaning", not "ICA with ICLabel at 0.7"); a split keeps
   its unit — trial-level k-fold, subject-grouped k-fold and "k-fold (unit not stated)" are three concepts, and a bare
   "10-fold CV" is never folded into either of the first two. 10–25 method families is usual. A **measure** is one
   quantity at one scale and normalisation: dB against a single-trial baseline and a raw power change against a block
   baseline are two measures; frequency bands are separate measures when the papers report them separately. Two papers
   whose band edges differ (10–12 Hz vs 11–13 Hz) may share a concept, with the difference written in `equivalence`.
   Give the variants of one measured quantity a shared **`quantity`** (kebab, e.g. `alpha-band-power` on alpha power in dB,
   alpha change from baseline, high-alpha and low-alpha power): the concepts stay apart, but the collision step groups
   claims by quantity, so "less high-alpha before holed putts" (change from baseline) and "no alpha difference" (dB) meet.
   Without it they never do — in the golf acceptance run the field's best-known disagreement was lost this way.
4. **One spelling, one concept.** A spelling claimed by two concepts is refused (A02). When one word means different things in
   different papers — a **false friend** ("SNR" as evoked / baseline power in one paper, as signal / noise variance in
   another) — make two concepts and route the papers that use the other meaning with `overrides: {paper: {word: concept}}`.
5. **Measures two papers define.** When two or more papers give a defining sentence for words that land on one measure, read
   the sentences side by side. Same quantity → `equivalence: {papers: [...all of them...], because: "<why>"}`. Different
   quantity → split it (step 4). Neither written → refused (A05): two papers' "accuracy" are the same thing only if someone
   checked. A05 can only see definitions recorded as terms; whenever you merge operationalisations you know differ (band
   edges in a claim's scope, a measurement taken at a different time), write the `equivalence` anyway and name the
   difference — the collision step must cite it.
6. **Words set aside.** A word that names nothing the review compares (a software package, a lab's code name) goes to
   `unaligned: [{paper, string, reason}]`. A set-aside is **per paper** and wins over the spelling's concept for that paper
   only — the way to say "in this paper, this word is not that concept". A word on no concept and not set aside is refused
   (A03).
7. **Compound words.** A word maps to one concept. A term that names several things ("a priori frequency bands", "experts
   vs novices") should have been split at deconstruction (F1, Terms); if it was not, put it on the concept the paper uses
   it for and note the rest in the concept's definition.

Write `{concepts, overrides, unaligned}` to a file and run `align-set`. It refuses while any check fails and lists them;
on success it writes `knowledge/alignment.json` (`vocab`, `vocab_basis` = the hash of the words it was built from) and
**projects** `knowledge/methods_matrix_input.json` — method-family vocabulary, aliases for datasets, metrics, splits,
baselines and method families, the not-shared datasets, and (once the lens exists) affordability. That file is never written
by hand; `build-methods` reads it and canonicalises every row's names through it.

A revision (a collision judged `incommensurable` sends one back) is `align-set <RD> vocab.json --reason "<why>"`; the
previous vocabulary's hash goes into `history`.

### Done when
`align-check --unit A7.A1` passes: ids, kinds, names, definitions and families well-formed (A01); no spelling on two concepts
(A02); every word on a concept or set aside (A03), on a concept of an allowed kind (A04); every measure that several papers
define has an equivalence covering all of them (A05); overrides name real concepts and words the paper uses (A06); every
set-aside word has a reason and is a word that paper uses (A07); the vocabulary is not older than the
records' words (A08); `methods_matrix_input.json` equals the projection (A13).

### Edge cases (from the golf acceptance run)
- **One word, two roles in one paper** (a measure in the terms, a method family in the rows): an override may map the word
  per origin — `{"multiscale entropy": {"term:measure": "measure:mse", "row:method_family": "method-family:entropy"}}`
  (origins: `term:<kind>`, `row:<field>`, or just `term` / `row`).
- **Constructs no paper names in a word** are allowed when a coordinate needs one (label validity, baseline neutrality):
  give them a definition; they are judgements, and the coordinates that use them say so in `note`.
- **Normalisation not stated** (most abstracts): a concept "… (normalisation not stated)" with the same `quantity`.
- **The same data under several papers**: when the records show that papers report one dataset (same sample, same
  protocol), put them on one dataset concept and write `identity: inferred` plus the evidence in its definition. The
  collision step flags agreements on shared data (`same_data_relations` in the concept index): one dataset reported twice
  is not a replication.
- **`not_shared_reason`**: `placeholder` (own recordings, own simulation) and `unidentified` (published but cannot be
  matched) stay out of the field's conventions and holes; `single-use` (public data one paper used) still counts as a
  benchmark once another paper uses it.
- **`source` of a concept Point** when years tie or are missing: the paper with the fullest account (most units on it).

<a id="a7a2"></a>
## A7.A2 — coordinates

### Purpose
Every claim and every assumption gets six coordinates — `construct`, `measure`, `population`, `data` (a dataset concept),
`split`, `method_family` — each a concept id of that kind or `unstated` (a list when the unit is about several). Collisions
are found on these coordinates, so a unit without them cannot meet anything.

### Method
1. `align-coords <RD> --suggest` writes `knowledge/_work/A7A/coords_suggest.json`: for each unit, the concepts its `text`
   and `scope` name — not its quote, which carries the paper's surrounding words — longest spelling first within each kind
   (so "decoding accuracy" wins over "accuracy", and a method family's spelling never hides a measure's), the paper's own
   overrides first; for data, split and method family the paper's matrix rows as a fallback (`from: row`). An axis with
   several candidates is `ambiguous`.
2. `align-coords <RD> --auto` sets a unit as suggested (`by: auto`) only when no axis is ambiguous **and** a construct or a
   measure was found. Constructs are rarely written out in a claim, so expect to place most units yourself: read
   `coords_suggest.json` whole, not only the ambiguous ones.
3. Write `{unit id: {axes: {...all six...}, note}}` and `align-coords <RD> --apply <file>` (`by: model`; an --apply replaces an
   auto coordinate). Typical judgements: the construct a claim or assumption is about ("expert labels are ground truth" →
   label validity; "high alpha predicts holed putts" → the construct the band is read as), which of two datasets a claim was
   made on, a measure the text implies. An axis may be filled from **the same paper's record** (its data line, another
   unit's scope) — say so in `note` — never from another paper. `unstated` = the paper does not say; `n/a` = the axis does
   not apply to this unit (no split in a non-predictive ANOVA). A guessed concept is neither.

### Done when
`align-check --unit A7.A2` passes: every claim and assumption of an evidence record has coordinates with exactly the six
axes, each a concept of the axis's kind, `unstated` or `n/a`, set `by` auto or model (A09); the units have not changed since (A11).
A unit with neither construct nor measure is a WARN (A10): it will collide with nothing.

<a id="a7a3"></a>
## A7.A3 — concept Points

### Purpose
The Point layer's concept cards — a method, model, measure, construct or paradigm — now from the vocabulary instead of a
re-reading: the old rule "named in at least two shortlisted papers" is counted, not remembered.

### Method
`align-points <RD>` lists the concepts of those kinds that **two or more papers** reach — by their words or by their units'
coordinates — with the papers and units (`knowledge/_work/A7A/point_candidates.json`). Datasets and splits do not become
Points (they surface in the Planes). A method's family is reached whenever the method is. Coordinates count too — the
ones you placed with `--apply` are judgements, so place coordinates before choosing Points, and honestly. Choose the
concepts the topic turns on and write each as a Point in `knowledge_cards.json` with `origin: "align"`, `concept: <id>`,
`unit_refs: [unit ids it is built from]` (units of the candidate's papers; a concept reached by words only, such as a
paradigm, may have none — cite the records in `source_files`), `source` = the earliest of the candidate's papers, and the
six fields from those units and records (knowledge-templates.md, Point; `(TBD)` where they do not support a field).
`plane` stays empty until the Planes exist (reconstruct); `build-cards` writes no theme table while there are no Planes.

Findings Points — a cross-paper result or explanation — are **not** written here: they come from collisions
(`origin: collide`, reconstruct step).

### Done when
`align-check --unit A7.A3`: every Point with `origin: align` names a candidate concept and existing unit ids (A12).

<a id="b1"></a>
## B1 — lens

### Purpose
Where we stand, on the same coordinates: the persona's specialisation and constraints (research-cycle.md §1, layers 2 and 3)
and what this machine holds **today**. Every later judgement about feasibility — B3's feasibility score, B3.5's
"data on this machine" screen, B4's Scope table and compute gate — reads this one file.

### Method
1. `$PY $SK/scripts/ideate_tools.py env-probe <RD> --write [--roots <own data folders>]` with **`PY` = the interpreter the
   experiments will use** (`run_config.json` `python`, or the one `check_env.sh` picks — on this machine the conda env with
   the data packages). The probe reports packages as importable *by the interpreter that runs it*; a bare `python3` may
   be a different environment and report installed packages as missing. Add the folders of the topic's own data to
   `--roots`. It writes `local_environment.probe` into step0; the A1 prose stays as context.
2. Write `{persona: {expert_domain, target_venues, compute, scope}, on_coords: {...}}`:
   - `persona` from step0's A1.v fields and the protocol's slots and outcomes (the layer-1 persona text is verbatim and is not
     copied here); on a topic framed before protocols, from `pico` — `setting` gives `compute`, the rest `scope`;
   - `on_coords` — every **method-family** concept: `{affordable: yes | partial | no, why}`, judged against the compute **and
     the data and sensors the method needs** (eye tracking with no eye tracker is `no` whatever the CPU); every **dataset**
     concept that two or more papers use (not the `not_shared` ones; others may be judged too): `{on_disk: yes | obtainable |
     no, where?, why}`; `yes` names `where` — a path under a data root the probe listed;
   - `own_data` — the topic's own recordings, which no paper names: `[{name, where, what}]`, `where` an existing path.
3. `lens-set <RD> lens.json` validates and writes `<RD>/lens.json` (the probe copied in, with its date) and re-projects
   `methods_matrix_input.json`: a matrix row whose `affordable_here` is `(TBD)` takes the weakest verdict of its families,
   marked `(lens)`.

A re-run of env-probe makes the lens stale (T02): set it again with `--reason`.

### Done when
`align-check --unit B1`: the lens is well-formed and its persona complete (T01); it carries the probe step0 holds (T02); every
method family and every shared dataset has a verdict with a reason, on concepts that exist (T03); an `on_disk: yes` names a
path the probe saw (T04); every own-data entry exists on this machine (T05).

A matrix row's affordability is the lens's alone: deconstruction leaves `affordable_here` `(TBD)` (D08), and the projection
fills every row with the weakest verdict of its families.

---

### Commands
```bash
SK=.claude/skills/ai-scientist-ideate; PY=<the experiments' interpreter>; RD=<topic>_research
$PY $SK/scripts/ideate_tools.py align-terms  $RD                        # -> knowledge/_work/A7A/terms.json
$PY $SK/scripts/ideate_tools.py align-set    $RD vocab.json             # A7.A1
$PY $SK/scripts/ideate_tools.py align-coords $RD --suggest              # A7.A2: the tool's reading
$PY $SK/scripts/ideate_tools.py align-coords $RD --auto                 #        unambiguous ones
$PY $SK/scripts/ideate_tools.py align-coords $RD --apply coords.json    #        the rest, by judgement
$PY $SK/scripts/ideate_tools.py align-points $RD                        # A7.A3 candidates, then build-cards
$PY $SK/scripts/ideate_tools.py env-probe    $RD --write
$PY $SK/scripts/ideate_tools.py lens-set     $RD lens.json              # B1
$PY $SK/scripts/ideate_tools.py align-check  $RD
$PY $SK/scripts/ideate_tools.py build-methods $RD $RD/knowledge/methods_matrix_input.json $RD/knowledge/decon/*.json
```
