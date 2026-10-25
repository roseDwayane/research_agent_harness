# F4 reconstruct — the field rebuilt from its collisions, and the questions worth asking

**Reconstruct** is the last step of the fusion block ([README.md](README.md)). Everything it writes is assembled from what
the earlier steps recorded — records, concepts, collisions, gaps — and every sentence that states something about the
literature cites the id it rests on. Nothing here opens a full text, and nothing here may say what no earlier step
found. It ends with the block's hand-over: a ranked, screened list of research questions.

| Unit | Decides | Writes |
|---|---|---|
| [A7.R1 Lines and findings Points](#a7r1) | which collision groups are promoted | `knowledge/lines/*.md`; findings Points in `knowledge_cards.json` (`origin: collide`) |
| [A7.R2 Planes](#a7r2) | the themes — chosen now, after the collisions | Planes in `knowledge_cards.json`; `build-cards` |
| [A7.R3 descriptive Body](#a7r3) | the field's seven questions | `knowledge/body/B_draft_<topic>_descriptive.md` |
| [B2 synthesis](#b2) | the topic-wide state of the art | `step6_sota_review.md` (research folder root) |
| [B3.5 questions](#b35) | for each selected gap, the problem and one research question | `questions/Q_NNN.md` |
| [F.9 index and views](#f9) | nothing by judgement | `questions/index.json`, `knowledge/fusion_map.md`, `concept_index.json` |

Templates stay those of [../knowledge-templates.md](../knowledge-templates.md) (Line, Plane, Body), research-cycle.md §2
(synthesis) and [../question-craft.md](../question-craft.md) §2 (problem and question); only their sources change.

---

<a id="a7r1"></a>
## A7.R1 — Lines and findings Points

`recon-candidates <RD>` lists what may be promoted (`knowledge/_work/A7R/promotion.json`), grouped by the set of papers
involved (two candidates on the same pair are one disagreement): debate groups (≥ 1 `conflict`, plus the pair's
`boundary` relations, with evidence levels), evolution chains (`extends` linked paper to paper), analogies, and findings
groups (`agree` and `boundary`).

- **Lines.** The escalation rule, read off the records instead of the full texts: a standalone card when the relation
  rests on ≥ 3 units or collisions, or is a major axis of disagreement; a debate needs ≥ 2 named sides; an **evolution**
  card needs a chain of ≥ 3 papers, or 2 when the later paper says it builds on the earlier (`builds_on`) — otherwise a
  patch. One question, one card: when a pair both conflicts and extends, the debate card carries the lineage as context.
  The rest are patches; a patch between papers that have no Point may cite unit ids in free text. **No fixed count** —
  the old "expect 2–5" is gone; the material decides. Each card's frontmatter adds
  `collisions: [X…]`: a debate cites ≥ 1 `conflict` or `boundary` collision, an evolution ≥ 1 `extends`, an analogy ≥ 1
  `analogy`. A debate whose conflicts all rest on abstracts is refused: an abstract-only side cannot stand alone. The
  sections are written from the collisions' sides and reasons and the members' units, each claim with its id.
- **Findings Points** (a cross-paper result or explanation) are promoted from `agree` / `boundary` groups: a Point in
  `knowledge_cards.json` with `origin: "collide"`, `collisions: [X…]` (≥ 2 papers, not abstracts only), `claim_type:
  empirical` or `conceptual`, the six fields from the sides' units. A `boundary` gives a Point with its condition in the
  core claim. When a concept Point (A7.A3) already states that result as its core claim, add the `collisions` to it
  instead of writing a second card.
- **Premise collisions** (untested-shared, assumption-challenged, assumption-at-stake, criterion-unmet) have no card type
  of their own: they live in the Planes' Q3 / Q5, the Body's Q5, patches (`depends_on`, `caused_by`) and the gap list.

`recon-check --unit A7.R1`: Lines cite current collisions of the right result (J01); debates have two sides and not only
abstracts (J02); findings Points rest on agree / boundary collisions of ≥ 2 papers (J03).

Edge cases: a lineage is one connected group of `extends` relations (a branching tree is one lineage; it counts as ≥ 3
papers when the group has three). An analogy escalates to a card only as a major cross-theme axis; otherwise a patch
line `` `A` ↔ analogy ↔ `B` (X…) `` in free text. Patch lines count for the coverage check. A findings Point resting only
on shared-data agreements is a WARN (J03): one dataset reported twice — say so in the card. B2 may cite abstract-level
agreements in Consensus if it marks them "(abstract level)".

<a id="a7r2"></a>
## A7.R2 — Planes

Themes are chosen **here**, after the collisions (not while reading, as Pass 0 did): each with a one-sentence identity,
distinguishable from its neighbours, and drawn along the seams the collision groups and Lines show — 4–6 for a corpus of
dozens of papers, fewer for a small one (at most one theme per two papers). A theme holds ≥ 2 papers; a one-paper theme
only for a paper that collides with no other (J05). Every evidence paper (eligible or abstract-only) sits in exactly one Plane's `member_papers`; `member_points` name
existing Points. The five questions:

- Q1 from the records' `problem` lines; Q2 the member Points; Q4 from the methods matrix (as before);
- **Q3** cites the Lines and collisions among the theme's papers;
- **Q5** cites only the papers' own `#L` / `#F` units and `conflict`, `boundary` and premise collisions — it records what is
  open, not gaps (those are in step7).

Then `build-cards` (it writes the paper–theme table now that Planes exist) and `build-methods` again (the family × theme
table follows the Planes).

`recon-check --unit A7.R2`: every evidence paper in exactly one Plane, member Points exist (J05); Q3 and Q5 cite existing
ids or say `(TBD)` (J06); every `conflict`, `boundary` and premise collision lands in a Line, a Plane's Q3 / Q5, the
Body's Q3 / Q5 — the gap list does not count: the field's picture must hold them (J04). A Plane's Q5 cites only `#L` /
`#F` units, debate Lines and conflict, boundary or premise collisions (J06).

<a id="a7r3"></a>
## A7.R3 — descriptive Body

The seven questions as before (knowledge-passes.md, Pass 4), with **Q3** (how the methods evolved) citing evolution Lines
and `extends` collisions and **Q5** (dependencies and conflicts) citing debate Lines and conflict collisions. Q6 reads the
matrix's conventions and `(NR)` rates — with fewer than ~5 full-text experiments those are a few papers' habits, and Q6
says so. `recon-check --unit A7.R3` (J07).

<a id="b2"></a>
## B2 — synthesis, once per topic

`step6_sota_review.md` at the research folder's root, in the template of research-cycle.md §2, with `scope: topic` in its
frontmatter (no generation, no angle; one key per line, or several on one line as the older template has them): one
`## Theme` section per Plane (J08). **Consensus** cites `agree` / `boundary` collisions or
findings Points; **Debates** cites `conflict` / `boundary` collisions or debate Lines; Key results, "A. Experimental
designs" and "B. Reported numbers" come from matrix rows (`exp_id`s) as before. It adds nothing the collisions did not
find — where there is none, `(TBD)`. Its readers are the planning block (designs, expected magnitudes) and the writeup
(Related Work). The paper–theme mapping may point to `knowledge/_MANIFEST.md` (generated) instead of repeating it by hand.
`recon-check --unit B2` (J08).

<a id="b35"></a>
## B3.5 — questions

One file per question, `questions/Q_NNN.md`, in the template and under the rules of [../question-craft.md](../question-craft.md)
§2 (common ground → condition → consequence ladder → three-step sentence → one research question → four screens → key
terms → definitions). What changes:

- **Frontmatter:** `question: Q_NNN` (= the file name), `gap`, `move` (= the gap's), `study: analytic | descriptive`,
  `axes`, `collisions` (the gap's collisions the question rests on — a subset of the gap's), `status: ready | abandoned |
  screen_unresolved`, `abandoned_reason` when abandoned, `original_question` when the wording was rewritten (with the screen
  the first wording failed), `narrowed` when the question answers only part of its gap (what was dropped and why — usually
  the data), `date`. No `generation`, no `angle`.
- **`study`.** `descriptive` only for how large, how reliable or how distributed something is, with no comparison and no
  null. A robustness question that tests whether an assumed effect survives (a sensitivity analysis of a premise) is
  `analytic`; so is a prediction judged against a permutation null or a baseline. The label binds B4 (C21).
- **1 Common ground** cites what the field holds or routinely does: `agree` / `boundary` collisions, findings Points, or
  `untested-shared` collisions (a practice everyone follows untested).
- **2 Condition** cites the gap's own collisions (or its `not_done` units). Its numbers come from B2's "Reported numbers"
  or the matrix rows.
- **3 Consequence** — every rung's `evidence:` cites ids or is `(TBD)`, under question-craft §2.2: consequence collisions
  (conflict, the premise results), debate Lines, the same future-work call (`#F`) in ≥ 2 papers, an untested matrix
  convention. A reading note's `#N` is the reader's observation and never evidence that anyone else asks (Y05).
- **6 Screens.** "Already settled?": first `questions-prefill <RD> GAP_NNN`, which lists the `agree` / `boundary`
  collisions on the constructs of the gap's primary collision (its measures when no construct is stated), the gap's own
  collisions excluded; the basis weighs **each** listed id — bears on it, or does not and why — or says "no agree /
  boundary collision on these coordinates"; plus the `raw` lookup and the matrix rows (`claim_tested`), as before. "Data on
  this machine?": passes on data on disk **or obtainable** (a lens verdict `obtainable`: say what fetching it takes and
  that its licence is checked at the journal step); cite the lens (`lens:<concept>`) or the topic's own data
  (`own:<name>`). When the data forces a narrower question than the gap, say so in `narrowed`.

**Which gaps, how many.** Take the gaps in `step7_gaps.json` rank order and write questions until `max(max_num_generations,
3) + 2` are `ready` (step0's `max_num_generations`; 3 when absent — the index records which), or the gaps run out. A gap
may carry two questions when their `axes` differ (one gap, two angles; the move is the gap's); never more. A question that fails a screen gets one rewrite (question-craft §2); still failing → `status:
abandoned` with the screen and the reason, kept, and the next gap — the question file is the record of it (for this block, research-cycle §3.5's `## Abandoned` line in
step7 is replaced by it). If no question is ready at the end, keep the one that
failed the fewest screens as `screen_unresolved` (the planning block writes it into Risk Factors).

<a id="b35-handover"></a>
**9 For the planning block** (every `ready` question; PLAN_ideate_planning §5). The planning block may not reopen full
texts or judge collisions, yet it has to name whom the study attacks, which other explanations it must rule out, and what
effect size it can expect — all three are fusion records. Run `questions-handover <RD> Q_NNN` (it writes
`knowledge/_work/B35/handover_Q_NNN.json`, one entry per unit: the units on the sides of the question's and its gap's
conflict, boundary and premise collisions and the other such collisions they sit in — each with its `role`: `holder` of a
premise, `challenger` of one, or a `side` of a conflict or boundary; the claims of the papers involved that sit in no such
collision (`claims_without_collision`, with the `extends` lineages they ride on); the axes the collisions differ on; the
debate Lines; the gap's counter-evidence; the matrix rows of the papers involved or cited), choose, and append one section
with one ```json block:

~~~markdown
## 9. For the planning block
```json
{"varies": ["time-anchor"],
 "targets": [{"id": "T1", "papers": ["cookeetal2014"], "claim_units": ["cookeetal2014#C1"], "strength": "shows",
              "weakness": {"collision": "X0018", "type": "conflict", "axes": ["time-anchor", "reference"]},
              "evidence_level": "full", "holds": "less frontal-central high alpha precedes holed putts"}],
 "rival_accounts": [{"id": "RA1", "account": "the band differs because the reference differs, not the lock",
                     "axis": "reference", "basis": ["X0018"]}],
 "magnitudes": [{"exp_id": "cookeetal2014#E1", "value": "F(1,18) = 5.53-6.81, high alpha, Fz F3 F4 Cz",
                 "relation": "same", "n": "20 golfers"}]}
```
~~~

- **varies**: the `axes_differ` code(s) the question varies (the question's own `axes` use the alignment's vocabulary;
  this names the same choice in the collisions' vocabulary; a code none of its collisions differ on is a WARN). Rival
  accounts are the other axes.
- **targets** (1–5, usually 2–4): a sentence a paper holds — the side that loses or stands untested, never the evidence
  against it. `claim_units` are claims or assumptions (`#C`, `#A`), never a reading note's `#N`; at least one of them is on
  a side of the weakness collision, and in a premise collision (untested-shared, assumption-challenged,
  assumption-at-stake) that unit is the `#A` that holds the premise. A target may **bundle** a claim with the premise it
  rides on (`["careyetal2024#C1", "careyetal2024#A3"]`) — the usual way to reach a claim from `claims_without_collision`.
  `strength` is the source's own verb: of its claim, the weakest when it bundles several, `null` when it holds assumptions
  only. `weakness` is that collision (`type` = its result, `axes` = its axes_differ), or `{"overreach": "<unit>"}` for a unit
  the deconstruction marked `overreach` and that is in no collision; when both exist, take the collision and say the
  overreach in `holds`. A null result can be a target (what is attacked is that the null was read as an absence); both
  sides of one debate can be targets when the question tests both. `evidence_level` is `abstract` when any of its papers
  is abstract-only; `holds` says the sentence in one line, at its strength. Order them by how much the question depends on
  them: the planning block attacks T1 first, and an abstract-only target sends its paper to the full-text top-up
  (PLAN_ideate_planning F-M4): `tier1 <RD> --targets` adds them (first targets, then the most-attacked; at most 5 per
  topic) to the A6 candidates; the new full texts make those records stale (`decon-plan`), and the usual staleness passes
  rewrite what rests on them — the section 9 that changed `evidence_level` included (Y11 says so).
- **rival_accounts** (≥ 1): the other explanations of the condition — one per differing axis that the question does not
  vary, and the other side of each debate Line. `basis` = collision, Line or gap ids (a gap id points at its
  counter-evidence); `axis`, when given, is one the basis collisions (or the Lines' collisions) differ on, never one in
  `varies`. An explanation that no record holds (a confound only the question's `narrowed` note names) gets `basis: []`
  and `unrecorded: "<why there is no record>"` — a WARN, and the planning block treats it as the study's own conjecture.
- **magnitudes**: the reported numbers bearing on the question — `exp_id`, `value` as the row reports it, `relation`
  `same` (on the question's coordinates) or `neighbour` (the effect being decomposed, a power reference), optional
  `quantity` and `n` (strings). `magnitude_absent` names the number nobody has reported (the share, the spread across
  specifications, the within-participant slope) — required when every row is a neighbour, welcome beside `same` rows. No
  number at all: the string `(no reported number: this is an absence)`.

The section is optional for a question written before it existed (a WARN); a section that is there is checked (Y11–Y13).
The index carries `targets`, `rival_accounts` and `magnitudes`, and `question-take` copies them into
`gen_k/question.json`.

`questions-index <RD>` checks every question and writes `questions/index.json`. `recon-check --unit B3.5`: frontmatter and
move (Y01), the eight sections (Y02), common ground cited (Y03), condition = the gap's (Y04), ladder evidence and known ids
(Y05), screens complete, ready means passed, abandoned has a reason, the settled screen weighs each prefilled collision (Y06),
≤ 2 per gap with different axes (Y07), the data screen reads the lens (Y10), section 9's targets (Y11), rival accounts (Y12)
and magnitudes (Y13).

**More questions later** (PLAN F-D15): when the planning block has used every ready question, write questions for the next
ranked gaps (new ids only) and re-index; if the gaps are used up too, say so — a broader search on a copy of the topic is
the next step.

Edge cases: on this block the lens replaces B3.5's step-0 env-probe (question-craft §2): read `lens.json → local`; if the
machine was probed after the lens was set, `align-check` fails (T02) — set the lens again first. A question's `axes` are a
subset of its gap's (Y01). When the settled screen has many prefilled collisions, weigh them in a section
`## 6a. Settled-screen detail` and let the table cell point there. The `raw` lookup greps titles and abstracts: search
spelling variants too (artefact / artifact, α / alpha). A rung backed by one paper's call only is written `(TBD)` with that
call named, not as evidence.

<a id="f9"></a>
## F.9 — index and views

- `questions/index.json`: per question its gap and the gap's rank, status, move, axes, study, collisions, title, research
  question and screen results; `target_ready`, `ready`, `gaps_without_question`. Ready questions first, by gap rank. It is
  the block's hand-over: the planning block takes one ready question per idea — `question-next <RD>` names it (a ready
  question nobody consumed; a gap no idea used first, then axes not used on that gap, then a gap no idea borrowed from,
  then rank), `question-take <RD> Q_NNN` copies it to `gen_k/step7b_problem.md` (B5 revises the copy, never the topic's
  file) with `gen_k/question.json`, and B6 consumes it with `consume <RD> --question Q_NNN`. `link-run` then points the
  run at the topic's synthesis, gap list and question file. Only ledger entries that consumed a question count: a topic
  copied onto the block inherits entries whose `GAP_NNN` named the old per-generation analysis's gaps, and on a
  fusion-block topic `consume` takes `--question` only.
- `knowledge/fusion_map.md` (`fusion-map <RD>`): construct × measure rows with the papers and what the collisions found
  there (consensus, disputed, boundary, premises). A view — never edited.
- `concept-index` adds, when collisions exist, `consensus`, `boundary_conditions`, `premises`, `incommensurable`,
  `conflicts_by_axis` and `collision_coverage` to `signals`; the older keys stay.

`recon-check --unit F.9`: the index is current (Y08); a ready question or one kept unresolved exists, and a shortfall with
gaps left unasked is a WARN (Y09); the map is its rendering (J10).

---

### Commands
```bash
SK=.claude/skills/ai-scientist-ideate; PY=python3; RD=<topic>_research
$PY $SK/scripts/ideate_tools.py recon-candidates  $RD        # A7.R1: what may be promoted
#   write knowledge/lines/*.md, findings Points + Planes in knowledge_cards.json, the descriptive Body
$PY $SK/scripts/ideate_tools.py build-cards       $RD $RD/knowledge_cards.json
$PY $SK/scripts/ideate_tools.py build-methods     $RD $RD/knowledge/methods_matrix_input.json $RD/knowledge/decon/*.json
#   write step6_sota_review.md (B2)
$PY $SK/scripts/ideate_tools.py questions-prefill $RD GAP_001  # B3.5, per gap
$PY $SK/scripts/ideate_tools.py questions-handover $RD Q_001  # B3.5, per ready question: candidates for section 9
#   write questions/Q_NNN.md
$PY $SK/scripts/ideate_tools.py questions-index   $RD
$PY $SK/scripts/ideate_tools.py fusion-map        $RD
$PY $SK/scripts/ideate_tools.py concept-index     $RD
$PY $SK/scripts/ideate_tools.py recon-check       $RD
```
