# F3 collide — every comparison on the record

**Collide** is the third step of the fusion block ([README.md](README.md)). The units now sit on shared coordinates;
here they are put against each other — paper against paper, and the field against our own conditions — and every
comparison is written down: which units, what relation, on which axes the two sides differ, why. A gap is a kind of
collision result, so the gap list is written here too, once per topic, and every gap points at the collisions it rests
on.

| Unit | Decides | Writes (through the tool only) |
|---|---|---|
| [A7.X1 candidates](#a7x1) | nothing by judgement — which units are compared, by rule | `knowledge/collision_candidates.json` |
| [A7.X2 judgements](#a7x2) | how the units of each candidate relate | `knowledge/collisions.jsonl` (append-only); `Disagrees with:` of the notes (projection) |
| [B3.c lens collisions](#b3c) | where the field's conventions meet this machine; which empty cells matter | the same two files |
| [B3 gaps](#b3) | which collisions are gaps, their move, scores and rank | `step7_gaps.json`; the view `step7_gap_analysis.md` |

Nothing here opens a full text, except B3's source check (one passage per gap that needs it).

---

<a id="a7x1"></a>
## A7.X1 — candidates

`collide-candidates <RD>` lists, from the coordinates, the matrix and the lens:

| type | members | from |
|---|---|---|
| `same-coords` | claims of ≥ 2 papers on one construct, and on one measure (two papers may read one measure as different constructs — a collision to judge) | coordinates |
| `shared-assumption` | assumptions of ≥ 2 papers on one construct or one measure | coordinates |
| `assumption-vs-claim` | one assumption + other papers' claims on its construct or measure | coordinates |
| `numbers` | matrix rows of ≥ 2 papers on one dataset × primary metric × split, with a reported headline | methods matrix |
| `lineage` | rows of ≥ 2 papers in one method family, over ≥ 2 years | methods matrix |
| `convention-vs-lens` | a convention or common practice (matrix §4) + the lens verdicts it runs into (dataset not on disk, family not affordable) | matrix + lens |
| `empty-cell` | a shared dataset × method family nobody reported (matrix §5), on method-family concepts only; at most 30, shared across the datasets | matrix |

Measures are grouped by their `quantity` when the vocabulary gives one (normalisation variants of one quantity meet).
A group whose members all sit in a larger group of the same type is dropped (one comparison, not two). A group larger than
8 is split by the other axis first — a construct group by measure quantity, a measure group by construct — then by data and
method family; a split is taken when at least one part still holds two papers (parts with one paper are dropped: their
units meet the others in their own groups); failing all of these, in year order — never cut. The
paper × paper candidates are capped by depth (quick 0 — listed, not judged; standard 150; deep 400). The cap is shared
across the types so that none is starved: a type smaller than an equal share is kept whole, the others share the rest
(papers-many first within a type); what the cap cuts is listed in `truncated` (the caveat `candidates-cut`). A candidate's id is a hash of its type and members,
so it stays the same until its members change.

<a id="a7x2"></a>
## A7.X2 — judgements

### Method
`collide-plan <RD>` writes batches of 10 unjudged candidates under `knowledge/_work/A7X/`, each member expanded — a unit's
text, kind, strength, scope, `overreach`, quote and where, coordinates, paper, year and basis; a row's data, split,
metrics, method family, baselines and headline — plus the `equivalence` notes of the concepts involved (band edges that
differ, a measurement taken at another time). One subagent per batch; it reads this section and its batch file, writes
`{model, judgements: [{candidate, relations: [...]}]}` to the batch's `answer` path and nothing else, self-checking with
`collide-check <RD> --answer <file>` (never `collide-merge`). Then `collide-merge` in the main session.

**One judgement per candidate, one or more relations in it.** A relation is `{result, sides: [member ids], axes_differ,
reason}`:

| result | when | sides |
|---|---|---|
| `agree` | same thing, same direction (axes, if any, are the conditions it held across) | findings (claims or rows) of ≥ 2 papers |
| `conflict` | opposite results or claims, and which axis explains it is **not** established | findings of ≥ 2 papers; `axes_differ` = the candidate explanations |
| `boundary` | both results hold **at once**, because the papers differ on the named axes — those axes are moderators | findings of ≥ 2 papers; `axes_differ` required |
| `extends` | the later builds on the earlier (the member's `builds_on` says so, or the design visibly carries the earlier one forward — say which) | findings of ≥ 2 papers, **earlier first** |
| `untested-shared` | a premise ≥ 2 papers rely on and none tests: the others' results *use* it | ≥ 1 assumption, plus the other papers' assumptions, or their claims or rows that rest on the premise, ≥ 2 papers |
| `assumption-challenged` | one paper's premise; another paper's result **from the premise's own setting** contradicts it | one assumption + the claims or rows |
| `assumption-at-stake` | one paper's untested premise; other papers' results *show what rides on it* — including a contradicting result from another setting (name the setting axes) | one assumption + the claims or rows |
| `criterion-unmet` | one paper states a criterion (what a valid test must show); another paper's design does not meet it | **the criterion unit first**, then the other paper's units or rows |
| `analogy` | different domains, the same structural role | findings of ≥ 2 papers |
| `incommensurable` | looked comparable, is not — the vocabulary merged things that differ | name the concept in `vocab_issue` |
| `independent` | same coordinates, no relation worth recording | list the members you considered |

**Conflict or boundary.** Both have results that point different ways and papers that differ on some axes. It is a
`boundary` when the difference in those axes is enough to make both results true together (static wet electrodes vs dry
electrodes in motion); it is a `conflict` when the results claim the same thing about the same question and the axes are
only possible reasons. Real pairs differ on several axes; the count does not decide.

**Premises are not findings.** `agree`, `conflict`, `boundary`, `extends` and `analogy` relate claims and rows. A premise
(an assumption unit) is related through `untested-shared`, `assumption-challenged`, `assumption-at-stake` or
`criterion-unmet`; these are the strongest gap sources (confirm-assumed, cause).

A paper in tension with itself (its premise against its own analysis window) is not a collision — every relation joins
two papers; it is recorded at deconstruction as a not-done unit or an `overreach` note, and B3 may build on it there.

A broad construct (one that merges several mechanisms) often yields only `analogy` or `independent`; do not stretch a
relation to have one, and do not call the merge `incommensurable` unless it hides two different quantities.

`independent` is how a candidate is judged when nothing connects its members; without it a judge would invent a relation
to have something to write. It is counted, never projected.

**Axes on which the sides differ** (`axes_differ`): `data`, `population`, `contrast` (what is compared: experts vs
novices, holed vs missed), `measure-definition` (band edges, scale, normalisation), `time-anchor` (the event epochs are
locked to), `baseline`, `split-unit`, `analysis` (statistical model or test), `method-config` (any other setting), `power`
(sample size, trial counts), `claim-strength`, `none`. A relation may add one line of `detail` (the specific values: "10–12
vs 11–13 Hz"). On `agree`, `extends` and the premise results the axes are optional and say under which differing conditions
the relation still holds. `none` = a straight conflict: same data, measure, population, split —
only the result differs. It needs **both claims argued** (`causes`, `shows` or `suggests`) and neither carrying an
`overreach` note; a `may` or `correlates` claim against a `shows` claim, or a verb stronger than its analysis, is a difference
of `claim-strength`. A null at small n is a `shows` with a `power` difference, not a straight conflict.

**Reason** in one to three sentences, in your words; the tool copies each side's quote (or headline) from the records.
Read the members' text, and use general domain knowledge only to understand it (what a high-pass filter does) — the
relation must rest on what the members say; when it leans on such knowledge, say so in `detail`. Each candidate's
`equivalence_notes` are context for the concepts its members share; cite band edges or definitions only where the relation
compares that quantity. A member left out of every relation counts as considered and unrelated.

**Say `incommensurable` when it is.** A judge who sees that a shared concept merges two different quantities records
`incommensurable` with the concept in `vocab_issue` — not `independent` or a softer relation to spare the revision. The
revision is the main session's work, not the judge's; a mismatch judged as something else stays in the vocabulary and
every later count on that concept inherits it (two judges did exactly this on the EEG-quality run: time per IC vs time
per epoch, two kinds of SNR on one concept).

An `incommensurable` judgement goes back to the vocabulary: revise it (`align-set <RD> vocab.json --reason "<collision
id>: …"`), re-set the coordinates it moved, `collide-candidates` again — the affected candidates get new ids and are judged
anew. Until the vocabulary is revised after the judgement, the check fails (H06).

A judgement is never edited: `collide-merge --revise "<why>"` writes new records that `supersede` the old ones. When the
candidates change (a vocabulary or coordinate revision), judgements of candidates no longer listed are retired by
`collide-retire <RD> --reason "<why>"` — one appended record naming them (`retires`); the H07 check fails until then.

### Outputs
`knowledge/collisions.jsonl`, one line per relation: `{collision_id X0001…, candidate, type, result, sides [{id, paper,
kind, quote}], axes_differ, reason, vocab_issue?, evidence_level (full-text | mixed | abstract), model, at, batch,
supersedes?}`. The reading notes' `Disagrees with:` lines are re-rendered from the current `conflict` and
`assumption-challenged` records (`collide-merge` does it), so `concept-index` harvests them as before.

### Done when
`collide-check`: every candidate judged (H01, the cut ones excepted; at quick depth paper × paper candidates are only
listed); sides are members of the candidate and still exist (H02); results, axes and reasons valid, a conflict or boundary
says where the sides differ (H03); a straight conflict rests on argued claims without overreach (H04); side shapes fit the
result — two papers, findings only for agree / conflict / boundary / extends / analogy, an assumption for the premise
results, year order for extends (H05); an
incommensurable judgement was followed by a vocabulary revision (H06); the candidate list is not stale and no judgement
belongs to a candidate that no longer exists (H07); every record names its model (H08).

### Edge cases (from the golf acceptance run)
- **A relation already recorded on another candidate** (overlapping candidates hold the same pair): record it again where it
  belongs; `collide-merge` keeps it as `duplicate_of` the first — the candidate counts as judged, but the relation counts
  once in every view.
- **Shared data**: an agreement between papers that report one dataset is flagged by the tools (`same_data`); say it in
  `reason` too ("same Birmingham sample — not a replication").
- **Lineage candidates** carry the papers' assumptions about that method family as well as their rows, so a later result
  can put an earlier premise at stake there.
- **`criterion-unmet`**: the criterion may be an explicit norm or a methods result that shows which test is valid, stated
  in one or more units of one paper — list all of them first, then the other paper's units or rows (an assumption counts
  as "the other paper's design").
- **`extends` with an undated paper** (`…nd` keys): the year order is not checked; order by `builds_on_keys` / `builds_on`.
- **Two different premises that pull against each other** (one paper tunes on the test set, the other never tunes): there
  is no relation between premises of different content — leave them; B3 may cite both in one gap.
- **A finding plus its reading in one claim** ("higher early power … may indicate relaxation"): treat it as the finding,
  and name `claim-strength` when the readings differ.
- **`untested-shared`** means none of the **members** tests the premise; a member that tests it in another setting makes it
  `assumption-at-stake` with the setting axes.
- **Parallel judges**: name helper files with the batch number (`judge_b07_*`).

<a id="b3c"></a>
## B3.c — lens collisions

`collide-plan <RD> --lens` batches the `convention-vs-lens` and `empty-cell` candidates (few: one subagent or the main
session). Results: `convention-vs-lens` (the convention matters for this topic and this machine cannot follow it as is),
`empty-cell` (the cell is a combination someone would want filled — say who and why in `reason`), or `independent` (it
does not matter). An empty cell is an absence: its gap gets severity ≤ 3 unless another collision supports it (W07).

<a id="b3"></a>
## B3 — gaps, once per topic

### Method
**This section replaces research-cycle.md §3 for a topic on the fusion block** (one gap list per topic, at the research
folder's root, no `## Selected for this generation`, the severity evidence below). Inputs: the current collisions, the
records (units, `#F` future work, `#N` not-done), the lens, the shortlist (`list-papers`, for the counter-evidence
lookup), and a full text only for a source check.

Read the current collisions in this order — the source order of the fusion block: (1) `conflict` with `axes_differ:
[none]`; (2) `untested-shared`; (3) `assumption-challenged` and `assumption-at-stake`; (3b) `criterion-unmet`;
(4) `boundary`; (5) `conflict` on some axis; (6) `extends` (the end of a chain: the next step nobody took);
(7) `convention-vs-lens`; (8) the same not-done item in ≥ 2 papers; (9) `empty-cell`. Write **every** gap that at least
two papers support and that rests on a collision or on the same not-done item in ≥ 2 papers — not two or three: the
planning block picks from the list, and a gap left out here is lost to every idea.

**One gap = one question a study could close.** Split when the remedies differ (a new measurement vs a re-analysis of
existing data); merge when one study would close both. Overlapping designs are fine; say so in the descriptions.
An in-scope item one paper alone supports goes to `single_paper`, an out-of-scope one to `adjacent`.

A gap is `{id GAP_NNN, title, description, type {primary, secondary?}, move, move_reason?, collisions [X…] (the primary
first), not_done [<key>#N…]?, axes, supporting [{key, how}] (≥ 2 papers), counter [{key, why_open}], source_check {key,
where, quote} or a list of them?, why_it_matters, consequence_evidence [ids], severity, novelty, novelty_basis?,
feasibility (1–5), feasibility_basis [lens:<concept> | own:<name>]}`; the rest of the file is `{topic?, gaps, not_gaps
[{collision, why}], single_paper [text], adjacent [text], revisions_needed [{key, where, quote, why}]}`. `axes` uses the
coordinate axes (construct, measure, population, data, split, method_family) and the difference codes of A7.X2.

- **Type** — methodological, population, measurement, temporal (a trend or a stage over time; an error in the time
  anchor of epochs is `measurement`), integration (research-cycle.md §3).
- **Move** — question-craft.md section 3. The defaults come from the gap's **primary collision** (listed first) — adding
  a collision never widens them. Each result suggests: a straight `conflict` → cause / kind /
  perspective; a `conflict` on an axis or a `boundary` → part-whole / apply-wider; `extends` → development;
  `untested-shared` and `assumption-at-stake` → confirm-assumed; `assumption-challenged` → cause / confirm-assumed;
  `criterion-unmet` → add-evidence / apply-wider; `analogy` → apply-wider /
  perspective; `convention-vs-lens` → confirm-assumed / apply-wider; `agree` → add-evidence; `empty-cell` → an extension
  move; recurring not-done → an extension move. Another move needs `move_reason` (W04). Choosing among contradiction
  moves on a conflict: `kind` when a paper says the thing has a property, `part-whole` when a moderator (the differing
  axis) decides, `cause` when a mechanism is claimed, `perspective` when a framework is.
- **Source check** — a contradiction move or `confirm-assumed` needs the paper whose claim or premise it turns on, quoted
  from its **full text** (`{key, where, quote}`, verified like a deconstruction quote). The collision's quotes usually are
  the passage; check them. A premise two papers share may need a check in each (a list). No full text → reclassify as an
  extension move or drop the gap. When the check reads more of a paper than its record holds, revise the record
  (`decon-merge --revise`) — or, when B3 runs where it may not, queue it in `revisions_needed` for the main session.
- **Severity 4–5** needs a citable consequence in `consequence_evidence` that bears on this gap: a `conflict`,
  `untested-shared`, `assumption-challenged`, `assumption-at-stake` or `criterion-unmet` collision that is one of the gap's
  own or shares a supporting paper, or the **same** future-work call (`<key>#F<n>`) in ≥ 2 papers (W06). A gap that rests
  only on an absence (empty cells, recurring not-done) stays ≤ 3 without such a collision (W07).
- **Novelty** is judged against the shortlist; when it leans on knowledge outside the corpus, say so in `novelty_basis`.
  Zero counter-evidence: look once more over the shortlist (`list-papers`) before trusting it.
- **Feasibility** is read off the lens: cite the verdicts (`lens:<concept>`) and the topic's own data (`own:<name>`). The
  weakest cited verdict caps it: yes 5, partial or obtainable 4, no 2 (W08).
- **Every** straight conflict and every premise collision (untested-shared, assumption-challenged, assumption-at-stake,
  criterion-unmet) is either in a gap or set aside in
  `not_gaps` with a reason (W10).

`gaps-set <RD> gaps.json` validates, computes each composite (`severity × 0.40 + novelty × 0.30 + feasibility × 0.30`),
ranks with the tie-break — taken in composite order and grouped while each stays within 0.30 of its group's top (counted
in hundredths, so exactly 0.30 is a tie), each group ordered contradiction move first, then severity — writes
`step7_gaps.json` and renders `step7_gap_analysis.md` (the source order on its first line, each gap's evidence level in
the table). Gap ids are never reused: an id dropped from the list is retired.

There is no `## Selected for this generation`: the planning block picks a question (reconstruct, B3.5), not a gap.

Edge cases: only full texts carry `#N` / `#F` units, so recurring not-done and the same future-work call come from them
alone; abstract papers enter through collisions. Gaps with equal composites are ordered by move class, severity, novelty,
feasibility — the remaining id order carries no meaning. On a contradiction move whose other side has no full text, the
source check on the full-text side suffices; say which side is abstract-only.

### Done when
`collide-check --unit B3`: ids, fields and scores well-formed (W01); collisions current (W02); ≥ 2 supporting papers
(W03); move valid and, off its primary collision's defaults, explained (W04); source checks verbatim from full texts
(W05); severity 4–5 with a consequence that bears on the gap (W06); absence-only gaps at most 3 (W07); feasibility from
the lens and capped by it (W08); the view equals its rendering (W09); no straight conflict or premise collision
unaccounted for (W10).

---

### Commands
```bash
SK=.claude/skills/ai-scientist-ideate; PY=python3; RD=<topic>_research
$PY $SK/scripts/ideate_tools.py collide-candidates $RD
$PY $SK/scripts/ideate_tools.py collide-plan  $RD            # paper x paper -> one subagent per batch
$PY $SK/scripts/ideate_tools.py collide-plan  $RD --lens     # the lens's candidates
$PY $SK/scripts/ideate_tools.py collide-merge $RD            # after each round of answers
$PY $SK/scripts/ideate_tools.py gaps-set      $RD gaps.json
$PY $SK/scripts/ideate_tools.py collide-check $RD
```
