# Stage B — the research cycle (runs once per generation)

One generation = one new idea. Each generation re-reads the *same* stage A evidence from a *different angle*, finds
the gaps visible from there, states the problem and the research question behind one gap, turns that question into a
hypothesis and an argument, refines both in a short reflection loop, and finalizes a 7-key idea. Nothing in stage B
re-reads full texts (the exceptions are listed in §3): its inputs are the knowledge cards, `concept_index.json`, the
methods matrix (`knowledge/methods_matrix.json`), the reading notes and the shortlist. That is what keeps N generations
affordable.

**A topic on the fusion block** (framed with a protocol; `questions/index.json` exists) runs B1–B3.5 **once per topic**
([fusion/README.md](fusion/README.md)); a generation is then only B4–B6:

```
generation k:   question-next <RD>  →  question-take <RD> Q_NNN   → gen_k/step7b_problem.md (a copy) + gen_k/question.json
                → the planning block, five steps in a fixed order (planning/README.md):
                  P1 Gap2Hypo        hypo-prefill → step8 (RQ, hypotheses, rivals) + claims, derivation → hypo-check
                  P2 design          the rest of §4 below (planning/P2-design.md); compute gate here
                  P3 decision tree   tree-prefill → decision_tree.json → tree-render --project → tree-check (T09 gate)
                  P4 attack          attack-prefill → attack_plan.json → attack-render → attack-check
                  P5 packaging       pack-prefill → packaging.json → pack-render → pack-check
                → B5 reflection around the five steps (§5, "On the fusion block") → B6 finalize (consume --question Q_NNN,
                  or consume --question Q_NNN --abandoned "<reason>" when the decision gate could not be passed)
```

Everything below is unchanged for that path except where a section says so (§4: P1 + P2; §5: the rounds; §6: the fields
P4 and P5 write); for an older topic the generation runs B1–B6 as follows.

```
generation k:   B2 sota (angle) → B3 gaps (pick an unconsumed (gap, angle))
                → B3.5 env-probe → problem and question → gen_k/step7b_problem.md   (screens fail → next (gap, angle))
                → B4 hypothesis               → gen_k/step8_hypothesis.md + gen_k/argument.json
                  └─ reflection loop r = 1..3: ConsultKnowledge | ReviseHypothesis | FinalizeIdea   (no network)
                       round 1  lookups → idea_draft.json → argument-check → round-1 copies (*_r1)
                                → blind restatement 1
                       round 2  restatement comparison + skeptical-reader questions → ReviseHypothesis
                                → argument-check --no-idea
                       round 3  idea_draft.json → compute gate (+ worth-it check) → coherence gate (argument-check)
                                → blind restatement 2 (only if the primary claim changed) → FinalizeIdea
                → B6 finalize: append idea, prescriptive Body, journal recommendations, consume (gap, angle)
```

Two gates sit in the loop, plus a reader whose doubts must be answered. Both gates behave the same way: a failure
forces one `ReviseHypothesis`; if the idea still fails, it is finalized anyway and the doubt is written into
`Risk Factors and Limitations`. The reader — an independent subagent that sees only the draft — runs before the
scheduled revision, so that what it objects to can still be fixed in the design; a doubt that cannot be fixed is
recorded with the concrete obstacle. None of the three is a human checkpoint. The templates, the schema and the question lists these steps use are in
[question-craft.md](question-craft.md) — read its section 1 before B3.5.

All files of generation k go to `$RD/gen_{k}/`. Numbering continues across runs: if `gen_1`…`gen_3` exist, start at
`gen_4`.

## Contents

§1 **B1** persona · §2 **B2** sota · §3 **B3** gaps · §3.5 **B3.5** problem and question · §4 **B4** hypothesis ·
§5 **B5** reflection loop (rounds, compute gate, trade-off rows + worth-it check, blind restatement, coherence gate) ·
§6 **B6** finalize ·
§7 journal recommendations

---

## 1. B1 — persona, three layers

Adopt this for the whole of stage B. Layer 1 is the original system-prompt persona, **unchanged** (reproduced here
so you do not need to open the 9 KB reference for it); layers 2 and 3 are appended, not substituted.

**Layer 1 — verbatim:**

> You are an experienced AI researcher who aims to propose high-impact research ideas resembling exciting grant proposals. Feel free to propose any novel ideas or experiments; make sure they are novel. Be very creative and think out of the box. Each proposal should stem from a simple and elegant question, observation, or hypothesis about the topic. For example, they could involve very interesting and simple interventions or investigations that explore new possibilities or challenge existing assumptions. Clearly clarify how the proposal distinguishes from the existing literature.
> 
> Ensure that the proposal does not require resources beyond what an academic lab could afford. These proposals should lead to papers that are publishable at top ML conferences.

```
[2 · specialised] For this session you are specifically an expert in {expert_domain}, proposing work targeted at
                  {target_venues}.

[3 · constraints] Compute budget: every experiment must run on CPU / Apple MPS within minutes to hours. Ideas that
                  need GPU-days will fail at the experiment stage.
                  Scope ({framework}): {slot}={value} · … · outcomes O1…On
```

`expert_domain` and `target_venues` (A1.v) and the scope come from `step0_session_config.json`; the scope is the
protocol's framework slots and outcomes (`protocol.framework`, `protocol.outcomes`, A1.p — references/search/A1-frame.md), or the
`pico` block of a topic framed before 2026-10-16. Wherever this file says "the PICO", read "the protocol's slots and outcomes".

The persona is a stance, not a file: nothing is written for it. Where layer 1's generic wording ("publishable at top ML
conferences") disagrees with layer 2, layer 2 wins — an on-board compression topic is aimed at aerospace and
remote-sensing venues, and the idea should be framed for them.

The one part of the original system prompt that is *not* verbatim is the tool block, because the action set changed
(§5). Replace the `{tool_descriptions}` / `{tool_names_str}` portion with the three actions described there; the
`FinalizeIdea` description and the IDEA JSON schema stay word for word.

---

## 2. B2 — sota, angle-specific synthesis

**Choose the angle first — before looking for gaps.** In practice this, together with the `also_uses` steering below, is
what keeps two ideas apart; the ledger only records the outcome and would not by itself stop two generations from
converging. An angle is a lens that regroups the same Points — for example *measurement side* vs
*model side*, *data efficiency*, *robustness under shift*, *evaluation methodology*, *cross-domain transfer*,
*deployment constraints*. Read `ideate_tools.py consumed $RD` and the existing ideas in `<topic>.json`, then pick an
angle that has not been used. The angle is what makes this generation's idea differ from the last one, so choose it
for contrast, not convenience.

**Inputs:** descriptive Body → Planes → the Points and Lines relevant to the angle → `knowledge/methods_matrix.json`
for designs and numbers — filter it with `ideate_tools.py list-methods $RD --family … --theme … --dataset …
[--evidence full-text]` → `_notes/` only for what a row does not carry. Open full texts only to verify a specific figure. After a `quick` run there are no Lines and no notes: work from the Body, the
Planes, the Points and `list-papers --file shortlist`.

Write `gen_{k}/step6_sota_review.md`. Synthesis, not summary: say what the field *knows, disputes and is heading
toward* as seen from this angle, not what each paper says.

```markdown
---
session_id: "YYYYMMDD"   step: 6
topic: "…"   generation: k   angle: "…"   date: YYYY-MM-DD
total_papers: N   themes: N   full_text_papers: N   abstract_only_papers: N
---
# State-of-the-art review — angle: {angle}
## Executive summary                       2–3 paragraphs
## Methodology legend                      table: Color | Methodology | Count (the six classes below, 0 when absent)
## Theme {n}: {title}                      one section per Plane that matters from this angle
### Consensus                              each claim needs ≥ 2 papers and, where available, the numbers
### Debates                                both sides with citations → link the D_draft card
### Dominant methods
### Key results                            table: Study | N | Data | Method | Primary Outcome | Metric | Result
## Cross-theme analysis
### Methodological trends over time
### Converging findings
### Diverging findings
### Theme interactions                     how the themes depend on each other; bridge papers
## Experiments in this literature
### A. Experimental designs                how the field tests claims
### B. Reported numbers                    where the bar currently is
## Paper–theme mapping                     table: Citation Key | Theme | Methodology | Bridge?
```

The `session_id` / `step` / `themes` keys, the methodology legend, the four cross-theme subsections, the `N` and
`Primary Outcome` columns and the mapping table keep the archived engine's layout of this file
(`archived/scholar_research`, `it_legacy.py`), so a reader of the old files can read the new one. `session_id` is
step0's; `N` is the sample size (participants, trials or recordings; `(TBD)` when the row does not say), `Primary
Outcome` the outcome measure and `Metric` the statistic reported for it. Methodology is one of the archived classes,
with their colours: experimental (🔴 Red), computational (🟠 Orange), review (🟡 Yellow), observational (🟢 Green),
engineering (🔵 Cyan), theoretical (🟣 Purple). The mapping table lists every paper the review cites, one row each;
a pointer to `knowledge/_MANIFEST.md` may follow it but does not replace it.

The two experiment subsections serve different consumers and are kept apart on purpose:

- **A. Experimental designs** — datasets and splits, baselines everyone compares against, ablation conventions,
  evaluation protocol, statistical tests, typical compute. This feeds the idea's `Experiments` field: the tree search
  can only execute steps that are concrete, and the most reliable source of concrete steps is how the field already
  runs its experiments. Take it from the matrix: the angle's rows, the conventions they follow (`methods_matrix.md` §4)
  and their reporting habits (§3), citing `exp_id`s — the matrix is the topic-wide record, this subsection is its
  angle-specific reading.
- **B. Reported numbers** — current best results per benchmark with citation keys, from the rows' `headline`. This
  feeds `Related Work` and the hypothesis's expected magnitude. Never invent a number; a missing one is `(TBD)`.

The `Key results` table's rows are matrix rows too (Study = `exp_id`). If `methods_matrix.json` does not exist (a
knowledge base built before Pass M), run Pass M first — knowledge-passes.md — rather than rebuilding designs from notes.

If `full_text_papers` is 0 (a `quick` run), put a warning line directly under the frontmatter: the synthesis rests on
abstracts, so methodological claims are unverified.

---

## 3. B3 — gaps

> **Topic on the fusion block** (framed with a protocol; `knowledge/decon/` exists): B3 runs **once per topic** as
> [fusion/F3-collide.md](fusion/F3-collide.md#b3) describes — every gap, at the research folder's root
> (`step7_gaps.json`, view `step7_gap_analysis.md`), each resting on collisions, no `## Selected for this generation`.
> A generation then picks its `(gap, angle)` from that list with the ledger rules below and writes no gap analysis of
> its own. Everything else in this section is for older topics.

Find what the field has **not** done, as visible from this generation's angle. A real gap lives *between* papers:
where one study's limitation meets another's assumption, where a method proven in one theme was never tried in
another, where several papers ask for the same future work. One paper's limitation is not a field-level gap.

**Structural signals** come from `knowledge/concept_index.json → signals`, a projection of the knowledge cards. **Check `structure_reliable` first.** When it is `false` (no Line cards — a `quick` run),
`isolated_points` and `plane_pairs_without_any_line` only say that nothing was linked; they say nothing about the
field, and reading them as "under-explored directions" manufactures gaps. In that case derive gaps from the text of
the Planes (especially Q5), the SOTA review's debates, and what the abstracts explicitly leave open.

| Signal | Points towards |
|---|---|
| `open_debates` | a study design that would settle the disagreement |
| `plane_pairs_without_any_line` | an integration gap — two themes nobody has connected |
| `isolated_points` | an under-explored direction (or a mis-filed Point — check) |
| `claim_type_counts` skew | methodological monoculture, e.g. all empirical, nothing theoretical |
| an evolution Line that simply stops | the next step nobody took |
| Plane Q5 entries repeated across papers | a recognised but unaddressed problem |
| `disagreements` | two read papers whose claims or numbers conflict — a contradiction-type gap (check the source first, below) |
| `assumptions` repeated across papers | a premise the field relies on and nobody has tested |
| `methods.dataset_family_empty_cells` | a method family never run on a dataset the field shares (population / methodological gap — check the rows first: an empty cell can be a missing dataset alias or a missing `method_family` tag on a row that did run it) |
| `methods.nr_rates_full_text` high for a field | a reporting habit, e.g. most experiments report no statistical test or no leakage control (methodological / measurement gap) |
| `methods.conventions_full_text` | the protocol an idea must follow to be comparable — and a convention every paper shares is an assumption nobody has tested |

**Source order.** Work through the sources in this order: (1) the `Disagrees with:` lines of the reading notes
(`signals.disagreements`) and `open_debates`; (2) `Assumes:` lines that recur across papers (`signals.assumptions`);
(3) the `Not done:` lines, read across papers — several papers not doing the same thing is a gap;
(4) `evolution_chain_ends` — what is the next step of this chain, and has anyone taken it; (5) future-work calls that
recur across papers (Plane Q5); and only then (6) unlinked Plane pairs, of which most are uninteresting — check each
before building on it. Disagreements and untested assumptions come first because a gap taken from `Not done:` is an
absence: that nobody did something does not show that anyone needs it done, whereas a contradiction or a shared
assumption is something the field already cares about.

**Fallback to the earlier order.** Read `notes_with_claim_fields` (`"n/N"`) in `concept_index.json`. When the key is
missing, when n/N is below one half, or when `structure_reliable` is `false`, sources (1) and (2) are too sparse to
lead: use the order this skill used before those note lines existed — (1) `Not done:` lines across papers,
(2) `evolution_chain_ends`, (3) recurring future-work calls, (4) open debates, (5) unlinked Plane pairs. Do this
without asking; say which order was used in the first line of `step7_gap_analysis.md`. Older knowledge bases are not
backfilled: the three lines (`Claim scope:`, `Assumes:`, `Disagrees with:`) are added on demand, to one paper's note
only, for any gap — whatever its move — whose source check below opened that paper's full text.

Matrix signals (`signals.methods`) count only what the rows record; with many abstract rows (`counts`) they
under-report, so weigh them after the reading-note sources above, and cite the `exp_id`s behind any you use.

Work through the five gap types — **methodological, population** (datasets / settings for ML topics), **measurement,
temporal, integration** — without forcing a gap where the evidence is thin.

Document **2–3 gaps** in `gen_{k}/step7_gap_analysis.md`, each with:

- **Description** — concrete enough to suggest a study ("no study evaluates X under Y on Z"), not "more work needed".
- **Type** — primary, and secondary if any.
- **Move** — one of the eight moves in question-craft.md section 3: an *extension* move (`add-evidence`,
  `confirm-assumed`, `apply-wider`) or a *contradiction* move (`kind`, `part-whole`, `development`, `cause`,
  `perspective`). Type says where the hole is; Move says what the study does to the source claim, so the two are
  separate fields and every gap has both. **A gap documented only from `Not done:` lines is an absence, and an
  absence takes whichever extension label is convenient unless it is tested:** (a) a source states the premise or
  visibly relies on it → `confirm-assumed` (source check below); (b) a source tested it, but in a narrow setting →
  `apply-wider` or `add-evidence`, naming that test as counter-evidence (`tested only in {setting} [key#exp]`);
  (c) neither → an absence with no stake: nobody is shown to need it, so its severity is at most 3.
- **Supporting evidence** — ≥ 2 papers by citation key, each with *how* it reveals the gap (limitation statement,
  implicit boundary, contradiction, future-work call, methodology absence).
- **Counter-evidence** — papers that partly address it and why the gap stays open. Zero counter-evidence means either
  real novelty or something missed: run one more `ConsultKnowledge`-style lookup over the shortlist before trusting it.
- **Source check** (contradiction moves and `confirm-assumed`) — before building on "the source says A, and A is
  wrong", confirm that the source really claims A: open that paper's full text and quote the page or paragraph. A
  note line or an abstract is not enough, because arguing against a position nobody holds is the cheapest way to
  produce a worthless study. `confirm-assumed` gets the same single look, for the same reason turned round: quote
  where the source states the premise or relies on it, because "they assume it" is otherwise your reading of a note.
  Stage B opens a full text for three reasons only: this check for a contradiction move, this check for
  `confirm-assumed`, and verifying a specific figure (§2). If no full text was obtained for the source, or the
  passage does not say A, reclassify a contradiction gap as an extension move or drop it; a `confirm-assumed` gap
  whose premise cannot be quoted falls under (c) of the Move test. When the look was made, add the three note lines
  to that paper's note (the fallback paragraph above).
- **Why it matters** — against the PICO, plus the consequence: the larger question that stays unanswered while this
  gap is open, with its evidence when there is any (see Severity below).
- **Priority score**, arithmetic written out:

```
composite = severity × 0.40 + novelty × 0.30 + feasibility × 0.30
e.g. 5 × 0.40 + 4 × 0.30 + 3 × 0.30 = 2.00 + 1.20 + 0.90 = 4.10
```

Severity — 5: the field cannot advance without it … 1: negligible. **A severity of 4 or 5 needs a citable
consequence**: name the evidence in *Why it matters* — the kinds that count are listed in question-craft.md
section 2 (for example the same future-work call in two or more papers, an `open_debates` entry, or a convention in
the methods matrix that every paper follows and none tests). It must come from the local evidence; do not search the
network for it. Without such evidence the severity is at most 3, because the score is otherwise only your own opinion
that the gap is important. Novelty — 5: nobody has tried … 1: well covered (then it is probably not a gap). The
exception is confirmatory work: a repeat that avoids a named weakness of the earlier studies, or that re-tests a
result the field found surprising, scores novelty 3 — write the weakness it avoids in the Description.
**Feasibility is scored against this machine, not a generic lab**: 5 = runs on CPU / Apple MPS in minutes-to-hours
with public or synthetic data; 3 = needs substantial but attainable resources; 1 = needs data, hardware or timescales
that are out of reach.

**Tie-break.** The formula and its weights do not change. When two gaps' composites differ by 0.3 or less, the one
with a contradiction move ranks above the one with an extension move; if both have the same class of move, the higher
severity ranks first. A claim that resolves a disagreement changes what readers believe, while one that only adds
data to an accepted view does not, and a 0.3 difference is within the noise of these 1–5 scores.

Keep gap ids stable across generations: if this generation rediscovers a gap already in an earlier
`gen_*/step7_gap_analysis.md`, reuse its `GAP_00N` instead of minting a new id. The ledger depends on it.

### Picking the gap — the `(gap, angle)` ledger

This replaces the human "lock one gap" checkpoint. The consumed unit is the **pair** `(gap_id, angle)`, not the gap:
one gap may yield several ideas as long as each attacks it from a different angle. Recording the gap alone would let a
second visit produce a near-duplicate of the first idea.

1. Read `ideate_tools.py consumed $RD`.
2. Prefer the highest-priority gap (composite, then the tie-break above) that has **never** been used.
3. If every gap has been used, take the highest-priority gap with the **fewest** angles so far, and require this
   generation's angle to differ from all angles recorded for it.
4. State the choice and the reason at the end of `step7_gap_analysis.md` (`## Selected for this generation`).

`also_uses` may only name a gap that is written up in some generation's `step7_gap_analysis.md`; an "adjacent
opportunity" without a write-up is described in words instead, so every id in the ledger resolves to a document.

An idea often borrows from its neighbours — it attacks GAP_001 but needs GAP_002's control condition. Record that at
finalize with `--also-uses GAP_002`. When a later generation picks GAP_002, read the `also_uses` entries in the ledger
and steer its angle away from what was already borrowed, or the two ideas converge on the same experiments.

The pair is written to the ledger at finalize (§6), not now — a generation that fails should not consume anything.
The same holds for a pair that is abandoned at B3.5 or after a revision's trade-off rows (§5): it is not consumed, so a later
generation may pick it again.

Gaps outside the PICO are listed as "adjacent opportunities" and not ranked.

## 3.5 B3.5 — problem and question

> **Topic on the fusion block:** B3.5 runs once per topic, one file per question in `questions/` — see
> [fusion/F4-reconstruct.md](fusion/F4-reconstruct.md#b35) (frontmatter, citations, the pre-filled settled screen, how many
> questions, abandonment as `status: abandoned` in the question file). The template, the four screens and the rewrite rule
> below still apply; a generation copies its question into `gen_k/step7b_problem.md` and starts at B4.

**When.** After the `(gap, angle)` is selected and before any hypothesis is written. A gap says something is missing;
this step decides whether the missing thing is worth asking about and can be answered, which is cheaper to find out
now than after three reflection rounds.

**Step 0 — what is on this machine (once per generation, before anything else in B3.5).**

```bash
$PY $SK/scripts/ideate_tools.py env-probe $RD --write      # data roots + packages → local_environment.probe
```

Then read every file in `$RD/datasets/` if the folder exists (dataset screens made for this topic). `env-probe` lists
what is cached under the data roots and which packages import in this interpreter, prints a `stale:` line for every
entry of the A1 prose that no longer holds, and stores the result as `local_environment.probe` in
`step0_session_config.json`. The prose keys A1 wrote stay as context, but stage A may be weeks old: the screens
below, the Scope table of §4, `external_check.inventory` and the compute gate of §5 read the probe, not the prose.
It touches no network.

**Output.** `gen_{k}/step7b_problem.md`, from the template in question-craft.md section 2 and under its rules. Its
frontmatter declares `study: analytic | descriptive` from the form of the question — `descriptive` when the question
asks how large, how reliable or how distributed something is and asserts no direction or comparison; only then may
the primary claim be an estimate (C21), and changing it later is a question rewrite. In
short, its eight parts are: common ground (what the field believes or does, with citation keys) → the condition that
breaks it (typed by the gap's Move, citing an `exp_id` or a card) → the consequence as a So-what ladder of at most
three rungs, each rung a larger question with its evidence → the three-step sentence → **one research question, as a
question** (prefer *how* / *why*; a *whether* question must say what a yes and what a no would each change; if the
question has two parts, the part the study will test comes first, and a part no claim will cover does not belong in
it) → the screens → 4–5 key terms → the definitions of any term the argument hangs on. A ladder rung without
evidence is written `(TBD)`, not argued for. For an absence, part 2 says what is missing and the nearest reported
number, or `(no reported number: this is an absence)`. The file does not name a `variant`: that follows from the form
of the primary claim, which does not exist yet — B4 sets it in `argument.json` (§4).

**Screens.** Fill the table in the file; each row needs its basis, not only a verdict.

| Screen | Passes on | Basis that must be written | Fails when |
|---|---|---|---|
| Is the answer already settled in the literature? | `no`, `partly` | the `raw` lookup (terms, hit counts; B3's lookup may be reused only when the question's key terms are unchanged) **and** the methods-matrix rows whose `claim_tested` bears on it (`list-methods`). A narrow earlier test gives `partly: tested only in {setting} [key#exp]` — never `no` | `yes` |
| Can the answer be derived from textbook knowledge, the definitions involved or a few lines of algebra? | `no`, `partly` | the derivation attempted, in 1–3 lines: what follows without data, what does not. `partly`: name the derivable part — it may be a check or an estimate of size, never the primary claim | `yes` |
| Could data on this machine settle it? | `yes` | the dataset and the measure, checked against the step-0 probe and `$RD/datasets/` | no obtainable data |
| Does the answer feed a larger question that someone other than you has asked? | `yes` | the rung of part 3 it feeds and that rung's evidence (citation keys) | every rung above Q1 is `(TBD)` |

The second screen exists because a `raw` lookup can only show that the *words* are absent from this literature: an
answer settled in another field, or by the definitions themselves, never appears there, and a study whose direction
is known in advance was passing on "0 hits". The applied test is no longer a screen — it could not fail for a
measurement study; it remains the rule for the optional fourth step of the three-step sentence (question-craft.md
section 2.3).

**When a screen fails.** First try once to rewrite the research question so that it passes (narrow it, or keep only
the part that is neither settled nor derivable). If it still fails, abandon this
`(gap, angle)`: add a line under `## Abandoned` at the end of `step7_gap_analysis.md` (pair, which screen, why), pick
the next pair by the ledger rules of §3 among this generation's documented gaps, and write `step7b_problem.md` again
for it. Nothing is consumed, and the abandoned pair goes into the final report (§6). When no documented gap is left,
do not stop and do not ask: keep the pair that failed the fewest screens, continue to B4, and add
`"Question screen unresolved: {screen and why}"` to `Risk Factors and Limitations` at finalize.

**`quick` depth.** There are no Lines and no reading notes, so parts 1–3 rest on abstracts. Write the file anyway,
add `evidence: abstracts-only` to its frontmatter, and give the ladder at most two rungs.

**Resuming.** Two cases, told apart by which files exist. In both, step 0 is run again, B2 and B3 are not redone,
and a `gen_{k}/` whose idea is already in the archive is left as it is; nothing is backfilled.

- **`step8_hypothesis.md` but no `argument.json`** — interrupted before the argument was written (or started before
  this step existed and never finalized): resume from here — write `step7b_problem.md`, then bring
  `step8_hypothesis.md` in line with §4. First delete what the interrupted attempt left in `gen_{k}/`:
  `idea_draft.json`, `step8_hypothesis_r1.md`, `step7b_problem_r1.md`, `argument_r1.json`, `restatement_1.json`,
  `restatement_2.json`.
- **`argument.json` but no `idea.json`** — interrupted during B5. Read `reflection_log.md` and find its last
  `## Round r/N` heading. If that round ends with its ACTION block (the round was logged to the end), continue with
  round r+1 on the files as they stand: the round-1 copies and `restatement_1.json` belong to this attempt and are
  kept. Otherwise — the last round is incomplete, or there is no log — delete the same six files and **restart B5 at
  round 1**, keeping `step7b_problem.md`, `step8_hypothesis.md` and `argument.json`; continue the log under a
  `# Resumed — B5 restarted at round 1` heading. Never redo round 1 on top of an old `argument_r1.json`: `cp -n` does
  not overwrite, so the checks would compare the new argument with the interrupted attempt, and the old
  `restatement_1.json` would count as the reader of a draft it never saw.

The six files belong to one attempt; the checks of the next must neither read its draft nor compare against its
round-1 copies.

---

## 4. B4 — hypothesis

**On the fusion block** this section is two steps: **P1** (Selected gap summary, Research questions, Hypotheses, Rival
explanations — with the form derived from the question's primary collision, rival ids and the field's accounts:
[planning/P1-gap2hypo.md](planning/P1-gap2hypo.md)) and **P2** (everything from Operational definitions on:
[planning/P2-design.md](planning/P2-design.md)). `outcomes` are not written here: the decision tree
([planning/P3-decision-tree.md](planning/P3-decision-tree.md)) writes them, before B5 starts.

Turn the research question of B3.5 into a specification precise enough to design experiments from. "X improves Y"
is not useful; "X applied to P under C improves Y by at least Z (metric M) over baseline B" is. Get as close to the
second form as the evidence allows. Before the Scope table is written, read the step-0 probe
(`local_environment.probe`) and the files in `$RD/datasets/` (§3.5): what the study can load, and which second
dataset or real recording exists, is decided from what is on the disk. Write `gen_{k}/step8_hypothesis.md`:

- **Selected gap summary** — id, type, move, priority, 2–3 sentences with citations.
- **Research questions** — RQ1 is the research question of `step7b_problem.md` part 5, word for word. RQ2… are the
  **1–3 sub-questions** that must be answered to answer RQ1; there is no fixed ladder. When the gap's feasibility
  score is low, narrow the *scope* of the sub-questions (fewer datasets, one setting, a pilot) — do not turn a *how* /
  *why* question into a *whether* question, because that keeps the cheap part of the study and drops the part that
  made it worth doing.
- **Hypotheses** — put **one primary hypothesis first** and mark it as primary; every other hypothesis is secondary.
  Power, the main outcome and the falsifier are judged on the primary one, and several parallel "main" hypotheses
  leave no rule for what the study concluded. Each hypothesis has a **mode**:
  - `test` — a directional, falsifiable hypothesis. State H0 explicitly, name the statistical test, and quantify the
    expected magnitude only where §2 "B. Reported numbers" supports one (cite it). The statistic of the decision
    rule keeps the sign the mechanism predicts — an absolute value only when the claim itself is unsigned, because
    an unsigned statistic cannot tell the predicted effect from its opposite. When the direction is already settled
    by textbook knowledge, an idealised model or algebra (the derivability screen said `partly`), the hypothesis
    states a **magnitude**: the smallest effect of interest in outcome units, with its basis, is the threshold —
    never zero, since rejecting zero would then only confirm what was known. For every `test` hypothesis write,
    before the decision rule, **which direction you expect and from what** — a citation, textbook physiology or
    physics, the algebra of the by-construction check; or that the literature is split (who holds each side); or
    that nothing predicts it. This becomes `expected_direction` in `argument.json`, and a direction with a settled
    basis makes the claim `direction-settled` whatever the first verdict was (C7).
  - `estimate` — a descriptive or measurement-validity question. Write no H0/H1 and no *Although … because …*: one
    plain sentence stating the quantity to be estimated, in whom, and the confidence-interval width the available
    sample gives. Forcing a hypothesis test onto a question that asks "how large" or "how reliable" produces an
    arbitrary threshold. An estimate may be the **primary** hypothesis only when `step7b_problem.md` declares
    `study: descriptive` (C21) — otherwise switching a claim to `estimate` is the cheapest way to take it out of the
    checks that ask whether it can fail. **Every estimate hypothesis says why it is one**, in one line that becomes
    `estimate_because`: `descriptive:` (the quantity has no direction to test), `size-open:` (the direction is
    settled, only the size is unknown) or `by-construction:` (a test was given up because its result was fixed in
    advance — name the test and what a reader can no longer learn). C21 requires the field on every estimate claim.
  - `equivalence` — the claim is that an effect is *absent* (a negative-result study). Some such questions have no
    prior number to anchor on. State a pre-registered equivalence margin or decision threshold (e.g. "AUC < 0.55",
    "within 1 accuracy point of random rejection"), label it as a design choice, not as a literature-derived value,
    and plan a positive control: the same pipeline must detect an effect where one is known to exist, since a careless
    study finds "no difference" more easily than a careful one.

  For the primary hypothesis compute what the fixed sample can detect — the result goes into `argument.json`:

  ```bash
  $PY $SK/scripts/ideate_tools.py power --mode corr      --n 109              # smallest detectable |r|
  $PY $SK/scripts/ideate_tools.py power --mode two-group --n1 54 --n2 55      # smallest detectable standardized difference
  $PY $SK/scripts/ideate_tools.py power --mode paired    --n 109              # same, paired design
  $PY $SK/scripts/ideate_tools.py power --mode estimate  --n 109 --sd 0.08    # total width of the confidence interval
  $PY $SK/scripts/ideate_tools.py power --mode paired    --n 109 --sided 1    # a one-sided decision rule
  $PY $SK/scripts/ideate_tools.py power --mode equivalence --n 109            # smallest margin at which equivalence can be shown
  $PY $SK/scripts/ideate_tools.py power --mode paired    --n 109 --effect 0.5 # SD unknown: largest SD at which a raw effect of 0.5 is detectable
  ```

  (`--alpha 0.05 --power 0.80 --conf 0.95 --sided 2` are the defaults; `--json` for machine-readable output.) Use
  `--sided 1` when the decision rule is one-sided and `--mode equivalence` for an equivalence claim, so the figure
  describes the test that will be run. When no source reports the SD of the outcome, omit `--sd`, report the result
  in SD units and add `--effect <smallest effect of interest>`: "detectable only if the SD is at most …" is an
  answer, whereas a placeholder `--sd 1.0` prints a number that answers nothing. `n` counts
  **independent units** — subjects, not trials or epochs. The output is a rough normal-approximation estimate and
  understates the needed sample when n < 30; use it for a three-level verdict (adequate / marginal / underpowered)
  against the effect the literature reports, not as an exact figure.
- **Operational definitions** — from `step7b_problem.md` part 8: for each term the argument hangs on, the definition
  used here in measurable form, the other definitions found in the literature, and why this one.
- **Scope** — IN table (population/data, intervention/method, comparison, primary and secondary outcomes, setting,
  design, timeframe) and OUT table where every exclusion has a rationale a reviewer would accept. For every
  human-subject dataset in the IN table add one line: its public licence, and whether the original consent covers
  this kind of secondary analysis. Take it from the reading notes (`Data:` line), the methods matrix or the
  dataset's local documentation; when it cannot be found there, write `(licence unverified)` — the journal step (§7)
  looks it up, since this loop may not. The line is written **once per dataset**, is not a gate, and appears once in
  `Experiments`: in the first entry that loads the dataset (§6).
- **Conceptual framework** — a short description plus an ASCII diagram of the moving parts.
- **Risk assessment** — 3–5 rows: `Risk | Likelihood | Impact | Mitigation`.
- **Rival explanations** — a separate table: `Explanation | How it would arise here | Ruled out by (experiment or
  control) | Main?`. List what else could produce the predicted result: chance, bias, reverse cause, confounding,
  selection, incorporation (the index shares a component with the outcome it predicts), train/test leakage. Leave
  out a type that cannot apply to this design (no "not applicable" rows), except the types question-craft.md
  section 6 makes mandatory for the kind of claim, where the last column says why (`design: the factor is
  assigned`). A rival that no experiment addresses is written `(not addressed)` — it then goes into
  `Risk Factors and Limitations`, which is better than leaving it for a reviewer to find. **Mark exactly one rival
  of the primary hypothesis as the main rival**: the explanation a skeptical reader of the target venues reaches for
  first. It may not be `(not addressed)` (C24), and the negative control is aimed at it unless another experiment
  already rules it out — a control aimed at a rival nobody raises is an instrument step, not a control.
- **By-construction check** — for the primary hypothesis and every causal one, done on paper in this file before
  anything goes into `argument.json`. Six steps, each written out, because a `can_fail: yes` that only gestures at
  the algebra passed the check on a claim whose result was mostly fixed in advance:
  1. Write the formula — or the support: channels, band, time window, labels — of the manipulated dose, contrast or
     predictor, and of the number the decision rule reads.
  2. List every term or support the two share (incorporation), spelled as it appears in both. Write quantities as
     subscripted symbols (`RMS_r`, `sigma_bg`): the check reads both formulas and raises on a symbol that is in both
     and missing from the list (C18), so an empty list has to be true.
  3. Substitute one formula into the other and simplify. Could the result be computed from existing data — the clean
     recordings, a published table — without running the experiment? Answer `no`, `partly` (which part, from which
     data) or `yes`. `yes` means no experiment tests the claim: change the claim. `partly`: that part is excluded
     from the decision rule and is named in `Short Hypothesis` sentence 4 (§6). A `no` with shared terms says what
     happens to each of them in the substitution. **Whatever this step removes is written down**: every candidate
     hypothesis that it — or the derivability screen, or the budget — drops or turns into an estimate is listed in
     this file under a heading `Claims set aside at B4` (the claim, the reason, what a reader loses), gets a
     `tradeoffs` row (`gate: none`, `ids: []`) when it is dropped and an `estimate_because: "by-construction: …"`
     when it is kept as an estimate, and is reported at Finish under "scope given up". A cut made before round 1 is
     as lost to the reader as one made after it, and no later check can see it — `argument_r1.json` already lacks
     it.
  4. For each planned result: where the manipulation acts, where the measure is computed, whether the measure could
     have come out otherwise (`can_fail`), and the quantity the design leaves free on which the result depends. A
     measure computed on exactly what the manipulation removes must move; a control applied where the measure is not
     computed cannot move. Neither tests anything: change the measure or move the control.
  5. Push the positive control's planted effect and the negative control's expected behaviour **through the decision
     rule's own statistic** — its absolute values, ranks, thresholds, clipping and ceilings — and write the values
     that come out (the negative control's is not always zero). A planted effect that the statistic cannot return
     makes the control unpassable: through an absolute value, `|d + k| − |d|` equals the planted `k` only when the
     unplanted difference `d` is not negative, so write the condition under which the control can pass (C17 lists a
     `positive_expected` that ignores an absolute value, a rank or a clip in the statistic). An absolute value on a
     signed mechanism is justified in the Scope limits, or the sign is kept. Then check the noise or within-condition term: it must be exposed to the same
     nuisance variation as the contrast, apart from the factor under test — two blocks separated in time are
     compared with two blocks separated in time, not with interleaved halves.
  6. When an existing predictor is available (in BCI work, calibration accuracy), the hypothesis's decision rule is
     the **increment over that predictor** — not a win over a weaker comparator with the increment reported on the
     side.

  The six steps belong to a claim, not to a round: **when a `ReviseHypothesis` changes the primary claim — its
  statement, mode, statistic or decision rule — they are redone here for the new claim** (§5, round 2 step 2).

  The results go into the claim's `construction` block, `can_fail`, `controls.positive_expected` and
  `controls.negative` of `argument.json`. Recording such a weakness as a risk while leaving the decision rule
  unchanged is not a fix; the coherence gate treats it as an error (C15, C17, C18; question-craft.md section 4).
- **External check** — when the primary hypothesis's evidence comes from simulated, injected or planted signals, name
  the experiment that ties the result to real recordings of the phenomenon; when one dataset carries the primary
  hypothesis, name the experiment that repeats the primary contrast on a second independent dataset (another site or
  amplifier). If there is none, write `none:` with the reason **per candidate** after looking at the disk: list what
  was looked at — the probe's data roots and every file in `$RD/datasets/` — and why each candidate does or does
  not serve. "Results hold only inside the injection model" and "one dataset, one amplifier" are the objections a
  reviewer raises first, and neither can be answered after the design is fixed. The inventory has one entry per
  candidate, `<path or dataset>: <why it does or does not serve>`, and it must name every document in
  `$RD/datasets/` and every non-empty data root of the probe — the check compares it with the disk (C23), so "no
  dataset supplies X" cannot be written without opening the screening notes that list the candidates. The reason is
  a concrete obstacle, as for a `not-fixed` doubt: "no strength scale for real artifacts" is not one, because a
  direction-only or rank check on real artifacts needs no scale. **A synthetic study must try**: `real_data: none:`
  is an ERROR in the round-1 check, so the scheduled round-2 revision either adds the experiment or keeps `none:`
  with the obstacle per candidate; only then is it finalized with a `"No real-data validation: …"` risk entry. A
  single dataset's `none:` is finalized with `"Single dataset: …"`. Whether the evidence is synthetic is a fact about
  the design — an injection, a simulation, a planted effect — not a label to choose (C23 warns on `synthetic: false`
  beside such words).
- **Numbers from the topic file.** A topic may quote the user's own preliminary, unpublished measurements. Use them to
  motivate the question, never as a literature value and never as the basis of an expected magnitude — label any
  threshold you derive from them as a design choice, and respect the topic's own instructions about quoting them.
- **Traceability** — `Element | Source | Evidence`, tying each RQ, the primary hypothesis's direction and magnitude,
  and each scope decision back to a gap statement or a cited number. Two more kinds of row: **every planned
  experiment → the hypothesis it tests** (or its role when it tests none: instrument check, control, descriptive,
  release), and **every claim's scope → the data and conditions that support that scope**. Give the experiments their
  ids here (`E0`, `E1`, …); the same ids are used in `argument.json` and in the idea's `Experiments` field. Every
  experiment with role `tests` needs a decision rule with a threshold — in the hypothesis's falsifier, or as that
  experiment's own "refuted if" (C2); one that has none is `descriptive`. When several experiments test one
  hypothesis, name the deciding one first in the falsifier and give each of the others its own "refuted if" — a
  mention in the falsifier is not a rule (C2) — and give the path from the raw value to the number the
  rule reads (per channel → epoch → subject, with each aggregation).

**Then write `gen_{k}/argument.json`** (schema `ai-scientist-argument/1`; fields and rules in question-craft.md
section 4) and render it:

```bash
$PY $SK/scripts/ideate_tools.py argument-render $RD/gen_{k}      # writes gen_{k}/argument.md
```

`argument.json` holds only the structure the checks need — one claim per hypothesis, its evidence (each row with
`can_fail`, and `refuted_if` where it tests), warrant, falsifier and `comparator`, the `construction` block, rivals
(one marked `main`), controls, scope and power, the representation block, the experiment list with roles, and at the
top level `variant`, `coverage`, `external_check`, `reader_doubts` and `tradeoffs`. Most of it is extracted from
`step8_hypothesis.md`, and where the two disagree `step8_hypothesis.md` is right and the JSON is corrected. A few
fields have no place in step8 and are written first in `argument.json`: `study_sentence`, `variant`, `warrant`,
`warrant_basis`, `outcomes`, `negation`, `representation`, `coverage`, `external_check`, `reader_doubts`,
`tradeoffs` (question-craft.md section 4.3) — writing them there is not "inventing content"; the by-construction
formulas, by contrast, are written in step8 first. On a `mode: estimate` claim `falsifier`, `controls` and `power`
are `null`, not empty strings, `negation` may be `null`, and `estimate_because` is required; a `mode: test` claim
carries `expected_direction`. After every `ReviseHypothesis` update the JSON and run `argument-render` again, so
`argument.md` is never stale.

**`variant` is set here**, from the form of the primary claim — `none | biomarker | cause | equivalence | estimate |
invariance` (question-craft.md section 6) — and updated by every `ReviseHypothesis` that changes that form. It could
not be declared at B3.5, because the primary claim did not exist then. When it is `biomarker`, add the line
`Ladder rung: n` under part 5 of `step7b_problem.md`. `coverage` says whether the primary claim, by its falsifier,
answers the whole research question or a named part, and whether the study covers the angle; a part of the
question that no claim covers may not stay in the question. **The angle is decided here, phrase by phrase**: split
the angle of step7b's frontmatter into its phrases and write for each, in `coverage.angle_parts`, the claim or
experiment that covers it, or `none`. One `none` makes `coverage.angle` `part` with `angle_dropped` — and a part of
the angle left out now, before any round, counts exactly like one cut by a later revision: it is reported at Finish
and noted at `consume` (`--angle "… [not covered: …]"`, §6). An angle named "dose-response and coupling" whose
experiments contain no coupling analysis cannot be answered `whole` once the phrases are listed (C20).

`step8_hypothesis.md` is then the working draft of the reflection loop, with `argument.json` as its checkable summary.

---

## 5. B5 — reflection loop

**On the fusion block** (a generation with `gen_k/question.json`) the rounds wrap the five planning steps; everything else
in this section — one decision per round, the gates' single forced revision, the blind reader, the round cap — holds:

- **Round 1** = P1 → P5 the first time: P1, P2 (compute gate), P3 (tree), P4 (attack plan → Related Work), P5
  (packaging → Title, Short Hypothesis, Abstract; then compose `Experiments` and `Risk Factors and Limitations` from
  `argument.json` as §6 says, into the same `idea_draft.json`). Checks, pasted into the log: `argument-check --idea
  idea_draft.json`, `tree-check`, `attack-check --idea idea_draft.json`, `pack-check --idea idea_draft.json`. Freeze the
  round-1 copies — the three of below plus `decision_tree_r1.json` and `attack_plan_r1.json` (`cp -n`). The round's
  lookups as always: the shortlist and `raw` novelty checks (P4's closest-work lookup is one) and the `excluded` lookup.
  Blind restatement 1 on `idea_draft.json`.
- **Round 2** = the critique: the 12 questions, the restatement comparison (its cross-check: the reader's "which
  experiment would refute it" is the tree's primary test node), and **the four tree questions** — which is the likeliest
  leaf and what paper is it; do two leaves of one test say the same; where does the main rival die; what is left when the
  first checkpoint fails (answer 12 lives in a checkpoint node). Then **one** `ReviseHypothesis` whose ARGUMENTS name
  `enters: P1 | P2 | P3` — the earliest step it changes — and the steps from there to P3 are redone (the tree is redrawn
  from `tree-prefill`, never patched; `argument-check` C28 and `tree-check` T13 refuse a stale tree). A publishable leaf or
  a target of the round-1 copies that disappears gets its `tradeoffs` row (T14, R13). Then `argument-check --no-idea`,
  `tree-check`. At this point C28 reports the attack plan and the packaging as stale — expected: round 3 rebuilds them;
  only a stale tree is an error to fix in round 2. A change to an operational definition (step7b part 8) is recorded
  as a `tradeoffs` row (`ids: []`, the term, the old and the new definition), as `original_question` records part 5.
- **Round 3** = P4 and P5 again on the revised design (`attack-render`, `pack-render`; Experiments and Risk recomposed),
  the compute gate, then the **coherence gate**: `argument-check`, `tree-check`, `attack-check` and `pack-check`, all with
  the draft. An ERROR of any of them is a coherence-gate failure and shares its one forced revision (entering at the step
  the finding belongs to); a wording finding of P5 (K02, K06, a title term of C20) is repaired in place and costs nothing.
  Blind restatement 2 as below. `FinalizeIdea`.
- **The decision gate (T09)** is part of the coherence gate. When it still fails after the forced revision, take the ways
  out of P3 ("When the gate fails") in order; the third — another ready question remains — means the generation is
  abandoned: `consume --question Q_NNN --abandoned "<the gate's finding>"`, nothing appended, and the next generation
  takes the next question. Otherwise finalize with `"Uninformative branch likely: …"` in Risk Factors (`packaging.json →
  tree_gate` says when).

The original ideation loop, kept: numbered rounds, **one decision per round**. Lookups are cheap and local, so a round
may run several `ConsultKnowledge` queries before it decides; what is limited to one per round is the decision that
changes state — `ReviseHypothesis` or `FinalizeIdea`. (The original allowed one action of any kind per round because
each search was a slow network call; that reason is gone, and with three rounds a strict one-action rule leaves no room
for the lookups this section requires.) Append every round to
`gen_{k}/reflection_log.md` — a `## Round r/N` heading, a short critique (quality, novelty, feasibility), then the
action block in the original format —

```
ACTION:
<exactly one of "ConsultKnowledge", "ReviseHypothesis", "FinalizeIdea">

ARGUMENTS:
<JSON>
```

— because a single declared action per round is what keeps the refinement disciplined, it gives the gates
below something to attach to, and a log on disk lets the user audit why an idea changed. (The original reflection
prompt opens with "In your thoughts, first carefully consider…"; read that as "in the reflection log". Treat the
prompt as the checklist for what each round's critique covers, not as text to recite.) What changed is that **no action touches the network**: stage A already did the
literature work, so reflection is refinement against local evidence only.

| ACTION | ARGUMENTS | What it does |
|---|---|---|
| `ConsultKnowledge` | `{"query": "…", "scope": "cards \| notes \| shortlist \| excluded \| raw"}` | Look the question up locally. `cards`/`notes`: `grep -ril "<word>" $RD/knowledge` — bear in mind these are your own sentences, so a hit there confirms little. `shortlist`/`excluded`/`raw`: `ideate_tools.py list-papers $RD --file raw --grep 'bit error "fixed huffman"'` — bare words match at the start of a word and must all occur; a quoted string is an exact phrase. Searching `raw` (every record the search returned, screened out or not) is the most honest novelty check. Typical use: "has anyone already combined X with Y?" The matches become `{last_tool_results}`. A miss on a methodological question ("does anyone sweep the strength?") is weak evidence — `--grep` reads titles and abstracts only, and a method is usually described in the full text; say so wherever the miss is used. |
| `ReviseHypothesis` | `{"reason": "…", "revision": {…changed parts…}}` | Rewrite parts of `step8_hypothesis.md`; keep the spirit of the idea unless there is a glaring problem. **Glaring** means one of: an `ERROR` of C7, C15, C17, C18, C21 or C24; the round-1 `ERROR` of C23 (`real_data: none:` on synthetic evidence); a `construction.computable_without_experiment` of `yes` or `partly` on the primary claim; a blind-restatement mismatch; a reader doubt of level `design`. With any of these the primary claim itself may change, because keeping a claim whose result is fixed in advance and recording the doubt is not a fix; without one, the claim stays and the revision works around it. Then bring `argument.json` in line and run `argument-render` (§4). **When the primary claim changes** (its `id`, `statement`, `mode`, `falsifier`, `comparator` or `baseline_predictor` — what C22 reports): write the `tradeoffs` row; redo the six by-construction steps of §4 for the new claim in `step8_hypothesis.md`; redo the derivability screen for it in the log; re-answer questions 5, 6, 8, 9 and 12 for it after the revision; and rewrite `expected_direction`, `negation.verdict`, `construction`, `can_fail`, `controls.positive_expected`, `controls.negative` and `rivals[].main` from those answers. A claim created by a revision has otherwise been examined by nobody. |
| `FinalizeIdea` | `{"idea": {…7 keys…}}` | Verbatim from the original prompt — schema and field descriptions unchanged (ideation-reference §2.5). |

Always include one lookup with scope `excluded`. Relevance was scored once, against the PICO, before this angle
existed — so a paper that bears only on the outcome this idea hinges on may have been screened out. If the lookup
finds one, handle it as [search/A3-screen.md](search/A3-screen.md#rescue) says ("Rescuing a paper later"); if it contradicts the
novelty claim, that is the most valuable thing the loop can find — revise.

Write each round into `reflection_log.md` as you go, not reconstructed afterwards: the log is only evidence of how the
idea changed if it was written while it changed.

**Rounds** — `num_reflections` = 3 by default (the original script's default was 5, so its reflection prompt's example
reads "Round 2/5"; here it reads "Round 2/3"). There is one schedule for every depth; the two blind-restatement steps
are skipped at `quick`.

- **Round 1 — draft, lookups, first check, first reader.**
  1. Lookups: the shortlist novelty check and the `excluded` check. B3's counter-evidence lookup and B3.5's lookups
     count — do not repeat them. Log the lookups as a table (query, scope, hits, what it shows).
  2. Write the 7-key draft to `gen_{k}/idea_draft.json`, composed as in §6 (question-craft.md section 8). It is a
     draft for the checks and for the reader; `idea.json` stays the canonical final copy.
  3. Run the first coherence check and paste its output into the log:

     ```bash
     $PY $SK/scripts/ideate_tools.py argument-check $RD/gen_{k} --idea $RD/gen_{k}/idea_draft.json
     ```

     Every `ERROR` line must be fixed by the round-2 revision. Round 2 is a revision anyway, so this adds no round
     **and does not use the coherence gate's forced revision** — that one belongs to the pre-finalize run. `WARN`
     lines are for the round-2 critique to judge.
  4. Freeze the round-1 copies. They are what the log's "what changed and why" is checked against, and
     `argument_r1.json` is what C16, C17, C19, C21 and C22 compare the final argument with (and C23 takes its absence
     to mean "round 1"), so they are written once and never overwritten (`cp -n`):

     ```bash
     cp -n $RD/gen_{k}/step7b_problem.md   $RD/gen_{k}/step7b_problem_r1.md
     cp -n $RD/gen_{k}/step8_hypothesis.md $RD/gen_{k}/step8_hypothesis_r1.md
     cp -n $RD/gen_{k}/argument.json       $RD/gen_{k}/argument_r1.json
     ```

     From here on a claim id or an experiment id is **retired, never reused or renumbered**: a removed `C4` or `E7`
     leaves a gap in the numbering (`E0, E1, E3` is valid — the experiment stage keeps the ids as written), because
     an id that changes meaning between the round-1 copy and the final argument makes the ledger check (C19)
     compare two different things.
  5. (`standard`, `deep`) **Blind restatement 1** on `idea_draft.json` (below). Save the reader's JSON verbatim as
     `gen_{k}/restatement_1.json`. The reader comes here, before the only scheduled revision, because it is the one
     step in stage B where someone who does not know the intended answer looks at the design — after the revision
     its doubts could only be filed as risks.

  The round's ACTION block is `ConsultKnowledge` with the last query; the check and the restatement are not actions.
- **Round 2 — critique and the scheduled revision.**
  1. Critique: quality, novelty and feasibility as before; the comparison of restatement 1 with the files on the
     four criteria and two cross-checks of question-craft.md section 7.2, one verdict per criterion; the reader's
     `biggest_doubt` split into separable doubts (one per number, when the reader numbered them); an answer to every
     `WARN` of round 1 that asks for one (question-craft.md section 5.2: for a C20 line, the quoted sentence that
     covers the key term or the angle part, or the change to `coverage`); and **the 12 skeptical-reader questions**
     of question-craft.md section 7.1, one short answer each. Answers come from `step7b_problem.md`, `step8_hypothesis.md`,
     `argument.json` **and from derivations written in the log** — some answers (question 8's by-construction
     algebra) are in none of the files until they are worked out. The answer to question 12 (which interim number
     shows the work is on track, and with what tolerance) is kept in the log: it is the candidate go/no-go check for
     the experiment stage.
  2. `ReviseHypothesis`, preceded by any lookup the revision needs — **one** revision that answers every round-1
     `ERROR`, every restatement mismatch, every doubt (fixed in the design, or `not-fixed` with the concrete
     obstacle; "no gate forced a revision", "out of scope" and "future work" are not obstacles) and every field a
     question contradicted. It may edit `step8_hypothesis.md`, `argument.json`, and parts 3–8 and the frontmatter of
     `step7b_problem.md`; editing part 5 is a question rewrite and fills `original_question`, whatever caused it.
     It writes one `tradeoffs` row per removal, demotion, mode change, primary change or role change (below), one
     `reader_doubts` row per doubt, and updates `variant` and `coverage` (the angle parts included). Two things it
     may not skip:
     - **A round-1 `ERROR` of C23 on `real_data: none:`** — the revision adds an experiment that ties the synthetic
       result to real recordings (a direction-only or rank check on real artifacts counts), or keeps `none:` and
       writes, for every candidate of the inventory, the concrete obstacle. Opening the files of `$RD/datasets/`
       is part of this; it is a local read.
     - **A changed primary claim** — if the revision changes the primary claim's statement, mode, statistic or
       decision rule, then in this same round, after the rewrite: redo the six by-construction steps of §4 for the
       new claim in `step8_hypothesis.md`; redo the derivability screen for it; re-answer questions 5, 6, 8, 9 and
       12 under the log heading `Primary claim changed — questions 5, 6, 8, 9, 12 again`; and rewrite
       `expected_direction`, `negation.verdict`, `construction`, `can_fail`, `controls.positive_expected`,
       `controls.negative` and `rivals[].main` from the answers. The questions of step 1 examined the claim that
       was about to be replaced; this is the only place the new one is examined before a reader sees it.
  3. Render and check again; paste the output:

     ```bash
     $PY $SK/scripts/ideate_tools.py argument-render $RD/gen_{k}
     $PY $SK/scripts/ideate_tools.py argument-check  $RD/gen_{k} --no-idea
     ```

     `--no-idea` because the draft is stale until round 3 rewrites it, and the script must not read it; the parts of
     C3, C10 and C20 that need the seven fields are skipped, each with a `NOTE` line, which is expected. An `ERROR` here is
     repaired at once when it is bookkeeping (a missing `tradeoffs` or `reader_doubts` row); otherwise it goes to
     round 3.
- **Round 3 — the pre-finalize sequence, then `FinalizeIdea`.** In order, each result logged:
  1. Rewrite `idea_draft.json`. Re-read the operational definitions in `step7b_problem.md` part 8, in
     `step8_hypothesis.md` and in the `Experiments` entries and make them one text — a definition that drifted
     between the files during the revision is otherwise carried into the idea.
  2. Compute gate against the step-0 probe; the worth-it check if the gate forces a revision.
  3. Coherence gate: `argument-check $RD/gen_{k} --idea $RD/gen_{k}/idea_draft.json`. A finding that reads only the
     seven fields — C20 "Title names …" (`ERROR`), "Short Hypothesis does not contain the research question"
     (`WARN`) — is a wording defect: repair `idea_draft.json` at once and run the check again. It costs no revision
     and is not carried into step 5.
  4. (`standard`, `deep`) **Only if** step 3 printed `WARN C22 … run the second blind restatement` — the primary
     claim is no longer the one the first reader saw: **blind restatement 2** on the new draft →
     `gen_{k}/restatement_2.json`; compare it as in round 2; add `reader_doubts` rows with `source: restatement-2`.
     A doubt of level `wording` is fixed in the draft now. Then run step 3 again.
  5. Decide. Failures are: the compute gate; any `ERROR` of step 3; a restatement-2 mismatch on any criterion; a
     restatement-2 doubt of level `design`. No failure → `FinalizeIdea`. Any failure whose gate has not yet used its
     forced revision → this round's decision is **one** `ReviseHypothesis` that serves all of them (restatement
     failures use the coherence gate's forced revision). In the next round repeat steps 1–3 only — no restatement
     follows a forced revision of the finalize round; if C22 still prints "run the second blind restatement", the
     answer is the entry `"Coherence unresolved: the primary claim was not restated after the forced revision"`.
     Then: a gate that has already forced its one revision does not force another — record what is left
     (`"Coherence unresolved: …"`, `"Compute budget uncertain: …"`, doubts as `not-fixed`) and `FinalizeIdea`. A gate
     that fails **for the first time** in that next round (the revision added an experiment that breaks the budget,
     say) may still use its own forced revision: one more round of steps 1–3, then `FinalizeIdea` whatever is left.

With `num_reflections` > 3 the extra rounds (lookups and revisions) go between round 2 and the finalize round;
restatement 1 stays after round 1, restatement 2 stays in the finalize round and is still triggered by comparison
with `argument_r1.json`. With `num_reflections` = 2 there is no scheduled revision: restatement-1 mismatches and
`design` doubts then count as coherence-gate failures. The compute gate may also be applied earlier, to the
experiment list in `step8_hypothesis.md`, so that its revision coincides with round 2; that is then the scheduled
revision, not a forced revision of the finalize round, and restatement 2 still runs in the finalize round when C22
asks for it.

`step8_hypothesis.md` always holds the current version. For `FinalizeIdea`, write the idea to `gen_{k}/idea.json`
(the canonical copy — either the bare 7-key object or the `{"idea": {...}}` wrapper is accepted) and have the log
point at it rather than repeating it. Round 1 is the hypothesis draft itself. Rounds 2…N use `idea_reflection_prompt`
(ideation-reference §2.4) verbatim, with `Round k/N` and `{last_tool_results}` set to the last `ConsultKnowledge`
output or `No new results.`. The last round must be `FinalizeIdea`. In each reflection, critique quality, novelty and
feasibility, and do at least one `ConsultKnowledge` novelty check before finalizing — it is cheap, and an idea that
collides with a shortlisted paper is the most common way ideation fails.

**Termination** is your judgement plus two mechanical gates and the reader. There is deliberately no similarity
threshold against the shortlist: the only similarity measure at hand is a title-overlap score built for
deduplication, and using it to judge whether an *idea* resembles a *paper* would give a false sense of precision.

**Compute gate** (replaces the "scope approved" checkpoint). Before `FinalizeIdea`, check every entry of
`Experiments` against the budget: small models, public or synthetic data of modest size, CPU / Apple MPS, minutes to
hours — and against `local_environment.probe` of this generation (step 0 of §3.5), **not against the prose A1 wrote**,
which may be weeks old: a dataset is "cached" only if the probe lists it, a package "installed" only if the probe
found it. A missing probe → run `env-probe --write` first. Prefer datasets that are cached and libraries that are
installed, and if an experiment needs a missing package or a download, say so in that entry. Every compute figure in
an entry is labelled `timed` or `estimated`, and the gate's log line says which — a count multiplied by a guessed
per-item cost is an estimate, and a gate passed on estimates should read as one. When an entry reuses a published
design, its matrix row's `affordable_here` is the first check. If any entry fails, the next action is forced to
`ReviseHypothesis` — once. If that revision lands in a round that was going to be a revision anyway, no round is
added; only when the gate fails at the final round does it add one beyond N. If it still fails after that revision,
finalize anyway and add `"Compute budget uncertain: {which experiment and why}"` to `Risk Factors and Limitations`.

**Trade-off rows** (every `ReviseHypothesis`, whatever caused it — and B4, for what was dropped while the
hypothesis was first written: `gate: none`, `ids: []`, §4). Write one row in `tradeoffs` of `argument.json`
for every revision that removes or demotes a claim, an experiment, a dataset, a contaminant or condition class, or an
analysis; that changes a claim's `mode` or which claim is primary; or that changes an experiment's role. A promotion
gets a row too (`lost: "nothing: …"`). The fields — `gate`, `ids`, `change`, `because`, `lost`,
`still_answers_question`, `covers_gap`, `covers_angle`, `why` — are defined in question-craft.md section 4. `gate`
names what caused the change: `compute`, `coherence` (an `argument-check` finding), `restatement` (a reader doubt or
mismatch) or `none` (the critique, the 12 questions, your own choice) — a cut that no gate forced needs its row most,
because nothing else records that the study once reached for it. `ids` lists the ids of `argument_r1.json` the row
accounts for; C19 raises an `ERROR` for every claim or experiment of the round-1 copy that is gone, or whose `mode`,
`primary` flag, `kind` or role changed, for a claim that no longer reads as the same claim under its id, and for an
experiment that now serves other claims, without a row listing its id. Turning a `test` claim into an `estimate` is a
demotion: it takes the claim out of C7 and C17, so it needs its row and its `estimate_because`, and the primary
claim may be an estimate only when `step7b_problem.md` declares `study: descriptive` (C21) — a study relabelled
`descriptive` after round 1 is finalized with a `"Primary claim downgraded to an estimate: …"` risk entry. What a row's three booleans lead to:

- `still_answers_question: false` → exactly two outcomes are allowed:
  - **Rewrite the question** to the one the reduced study really answers: update `step7b_problem.md` part 5 and RQ1,
    set `question` in `argument.json` to the new text, and fill `original_question` (`text`, `changed_because`
    starting with `data:`, `budget:`, `coherence:`, `restatement:` or `wording only:`). This is part of the same
    revision, not a new round.
  - **Abandon the `(gap, angle)`**: nothing is consumed; add the pair and the reason under `## Abandoned` in
    `step7_gap_analysis.md`, pick the next pair as in §3.5, and restart from B3.5 in the same `gen_{k}/`. Before
    restarting, delete `idea_draft.json`, `step8_hypothesis_r1.md`, `step7b_problem_r1.md`, `argument_r1.json`,
    `restatement_1.json` and `restatement_2.json`: they describe the abandoned pair, and the checks of the new one
    must not compare against them. The other working files are overwritten; `reflection_log.md` is continued under a
    `# Restart — {gap}, {angle}` heading, with round numbering starting again at 1. Allowed only while a documented
    gap of this generation is still unabandoned; otherwise rewrite the question.

  Keeping the original question while running the reduced experiments is not allowed. The coherence gate enforces it
  (C16) — and C16 also raises when the question's wording differs from `argument_r1.json` while `original_question`
  is null, so a rewording for coherence is recorded like any other.
- `covers_gap: false` → the study no longer addresses the gap B3 described (C19 `ERROR`): restore what was cut in the
  same revision, or abandon the pair as above. Nothing else clears it.
- `covers_angle: false` → set `coverage.angle` to `part` and say in `coverage.angle_dropped` which part of the angle
  no claim or experiment covers and why. The idea is still finalized; the dropped part is reported at Finish and
  noted in the ledger (§6), so a later generation can see that it is free.

**Worth-it check** (follows every revision the compute gate forced). Shrinking the experiments until they fit the
budget can leave a study that no longer answers its question, and nothing else in the loop would notice. After the
revision, answer in the log:

1. Does the reduced sample still represent the population the question is about?
2. Do the reduced measurements still represent the phenomenon the question is about?
3. What is the primary claim's `power.verdict` now? (re-run `ideate_tools.py power` with the new n)
4. Does the research question have to be reworded?

The answers decide the booleans of that revision's trade-off rows (`gate: "compute"`), with the outcomes above.

**Blind restatement** (`standard` and `deep`; skipped at `quick`, where `reader_doubts` is `[]`). An independent
reader — one subagent that is given the path of `idea_draft.json` and **nothing else**, no other file from
`gen_{k}/`, no hint of the intended answer, no tool but reading that file — restates what the draft asks, which part
of it is tested, what it claims and which experiment would refute it, and lists its doubts. The brief (verbatim), the
five keys it returns, the comparison on four criteria plus two cross-checks, the definition of a doubt's `level`
(`design` / `wording`) and where each doubt goes are defined in **question-craft.md section 7.2, which is the only
definition** — this file does not repeat them, because two descriptions of the comparison had drifted apart. What
this file fixes is when the reader runs and what its output does:

- **Restatement 1** — end of round 1, on the first draft, at `standard` and `deep` always. Its mismatches and doubts
  are input to the round-2 revision: every one is answered there with a `reader_doubts` row (`fixed`, or `not-fixed`
  with the concrete obstacle).
- **Restatement 2** — in the finalize round, only when C22 reports that the primary claim changed since
  `argument_r1.json`. A mismatch on any criterion or a `design` doubt is a failure of the coherence gate.
- At most **2** restatements per `(gap, angle)` attempt, and none follows a forced revision made in the finalize
  round or after it.
- The script reads the reader's file as well as its existence (C22): the number of doubts it numbers, and its
  `tested_part` — a reader who says only part of the question is tested contradicts `coverage.question: "whole"`,
  and that is an `ERROR` until the question is narrowed or the coverage declared.
- The reader's JSON is written to `restatement_<n>.json` unchanged; the log records the path and the verdict line
  (`restatement <n>: phenomenon ok | setting ok | kind ok | coverage MISMATCH (…) | claim ok | rule ok`), not a copy.
- A doubt left `not-fixed` becomes a `"Blind restatement unresolved: …"` entry of `Risk Factors and Limitations`
  (§6) and is reported at Finish — it is never written into `idea.json` alone.

The subagent reads one JSON file and uses no other tool, so the loop still does not touch the network.

**Coherence gate.** The same check as in rounds 1 and 2, now on the rewritten draft:

```bash
$PY $SK/scripts/ideate_tools.py argument-check $RD/gen_{k} --idea $RD/gen_{k}/idea_draft.json
```

It prints one line per finding — `ERROR C7 C2: …` (check id, then the claim id when there is one) or `WARN C10: …` —
and exits 1 when there is any `ERROR`, 0 otherwise. Exit 2 means bad input — `argument.json` is missing, or it, the
idea file, `argument_r1.json` or a `restatement_<n>.json` cannot be read — and is never a reason to revise the
hypothesis: fix the file and run it again. Besides `argument.json` and the idea file it reads, **each only when it
exists**: `argument_r1.json` (C16, C17, C19, C21, C22; C23 reads whether it exists), the `study:` line of
`step7b_problem.md` and of `step7b_problem_r1.md` (C21), `restatement_1.json` / `restatement_2.json` (C22),
`local_environment.probe` of `$RD/step0_session_config.json` and the file names in `$RD/datasets/` (C23). The checks C1–C24 are listed in question-craft.md section 5. They test structure only: that every claim has an
experiment and a falsifier and every `tests` experiment a decision rule (C2), that a causal claim has its rivals and
a control, that a result could have come out otherwise and cannot be computed without the experiment (C17, C18),
that a claim with an existing predictor is decided by the increment over it (C15), that nothing was cut or demoted
without a row (C19, C21), that the question, the title and the tested claim cover the same ground (C20), that a
reader's doubts were answered (C22), that synthetic or single-dataset evidence has a route outward (C23) and that
the first rival a reviewer would raise is addressed (C24). Whether a warrant is *reasonable* is judged by the round-2
questions, not by the script.

- Round-1 `ERROR`s are fixed in the scheduled round-2 revision and do not use the gate's forced revision. The forced
  revision belongs to this pre-finalize run: any `ERROR` here, a restatement-2 mismatch or a restatement-2 `design`
  doubt → the next action is forced to `ReviseHypothesis` — once, however many findings there are.
- Fix the argument, not the JSON: an `ERROR` on C2, C7, C15, C17, C18, C21, C23 or C24 means the claim, the decision
  rule, the experiment or the control has to change, not that a field is edited until the check passes.
- After that revision, rewrite `idea_draft.json` and run `argument-check` once more. No blind restatement follows a
  forced revision of the finalize round.
- A finding that reads only `Title` or `Short Hypothesis` (C20) is a wording repair in the draft, made at once; it is
  never a reason for the forced revision and never finalized as it stands.
- Still an `ERROR` → finalize anyway and add `"Coherence unresolved: {check ids and their text}"` to
  `Risk Factors and Limitations`. An unresolved restatement mismatch is recorded the same way
  (`"Coherence unresolved: blind restatement read the question as …"`); an unresolved doubt is a `reader_doubts` row
  with `response: not-fixed`.
- `WARN` lines never force a revision. Six kinds are written into `Risk Factors and Limitations` at finalize (§6;
  the same list as question-craft.md section 5.2): C13 (a rival marked `(not addressed)`; one line per rival, with
  its `how`), C17 with `partly` (the part of the result that existing data already give), C17 "no positive control",
  C21 (`"Primary claim downgraded to an estimate: …"`), C22 (a doubt `not-fixed`), C23
  (`"No real-data validation: …"`, `"Single dataset: …"`). A `power.verdict` other than `adequate` on a `test` or
  `equivalence` claim also becomes an entry; it is read from the field, not from a `WARN`. The C20, C18 and other C17
  and C21 `WARN`s ask for an answer in the round-2 critique. The one `WARN` that asks for an action is C22's "run
  the second blind restatement" (round 3, step 4).

A `gen_{k}/` without `argument.json` (a generation finalized before this file existed) is not checked and not
backfilled; a generation without `argument_r1.json`, restatement files or a probe is checked without the parts that
read them.

**Round cap** (the one statement of the budget; question-craft.md section 5.3 and SKILL.md point here).
`num_reflections` is 3 by default. Each gate — compute and coherence — may force at most one revision, so each adds
at most one round: a generation runs at most **`num_reflections` + 2** rounds (5 with the default 3). When both gates
fail in the same round, the single revision of that round serves both and counts as one added round; a gate that
fails for the first time in the round after that revision may still use its own (round 3, step 5). The round-2
revision that fixes round-1 `ERROR`s and answers restatement 1 is part of the default schedule and is not a gate's
forced revision, and neither is a compute-gate revision applied early so that it coincides with it. After a gate has
used its forced revision, a further failure of that gate is recorded in `Risk Factors and Limitations`, not revised
again. Wording repairs in `idea_draft.json` and bookkeeping repairs in `argument.json` (a missing row) are made at
once and count as nothing. A restart after an abandoned pair begins a new count, of rounds and of restatements.

---

## 6. B6 — finalize

### Mapping the hypothesis to the 7-key idea

**On the fusion block**: `Related Work` is the attack plan's text (P4, `attack-render` → `related_work.md`), `Title`,
`Short Hypothesis` and `Abstract` are the packaging's (P5, `pack-render`) — both copied verbatim into `idea.json`, never
edited there (R07, K08). `Experiments` and `Risk Factors and Limitations` are composed as below; the Risk list's group 1
gains `"Uninformative branch likely: {node, kind, basis}"` when `packaging.json → tree_gate` is `failed`. The rows below
for the four packaged fields describe the older path.

The keys, their order and their types do not change; only how each field is composed does. `key_terms`, claims and
experiment roles below are those of `argument.json`; "part n" is a part of `step7b_problem.md`. Details and examples:
question-craft.md section 8.

| IDEA JSON field | Composed from | How |
|---|---|---|
| `Name` | written at finalize | unchanged |
| `Title` | `key_terms`, `coverage` | built from the key terms of the **tested** part, so the title names the question rather than the method alone and promises only what the primary claim tests. A part that is only estimated is named after a marker ("…, with a descriptive map of …") or not at all (C20: a title that names an untested term is an `ERROR`, repaired in the draft at once) |
| `Short Hypothesis` | part 5, the primary claim, `coverage`, IN scope, `construction` | **four sentences, about 120–150 words**: (1) the research question, word for word as `argument.json` has it; (2) the primary claim — "Although …, … because …", with the definitions left to `Experiments`; (3) what is tested and what is only estimated (from `coverage`), and why this setting; (4) why no simpler route answers it — consistent with `construction.computable_without_experiment`: when that is `partly`, the sentence says which part existing data already answer. Sub-questions, H0 and secondary hypotheses stay in `gen_{k}/` |
| `Related Work` | parts 1–2, then gap supporting / counter evidence + the angle's SOTA, incl. "B. Reported numbers" | opens with the common ground and the condition that breaks it; the rest follows the rules below, unchanged |
| `Abstract` (≈ 250 words) | parts 1–3, IN scope, the primary claim's `outcomes` | in this order: common ground → condition → consequence → approach → expected contribution. **No results** — none exist yet |
| `Experiments` (list of strings) | IN scope + conceptual framework + "A. Experimental designs" (from the methods matrix) + `experiments` and `controls` | every entry starts with its id, then a role tag: `E3 [tests C1] …`, `E0 [instrument] …`, `E5 [control C1] …`, `E1 [descriptive C2] …`. The negative control and the positive control are each an entry of their own, not a clause inside another entry |
| `Risk Factors and Limitations` (list of strings) | gate notes + `reader_doubts` + `external_check` + rivals + power + scope + risk table | in the order given under the table |
| — | H0, secondary hypotheses, sub-questions, operational definitions, traceability, OUT scope, `step7b_problem.md`, `argument.json`, journals | stay in `gen_{k}/` — **not** in the JSON |

`Risk Factors and Limitations` has one entry for each of these that applies, **in this order** — what a gate or a
reader left open comes first and carries its label, so it cannot be mistaken for a routine limitation:

1. Labelled entries: `"Blind restatement unresolved: …"` (one per `reader_doubts` row with `response: not-fixed`,
   with the obstacle from its `how`), `"Coherence unresolved: …"`, `"Compute budget uncertain: …"`,
   `"No real-data validation: …"` and `"Single dataset: …"` (the `none:` reasons of `external_check`),
   `"Primary claim downgraded to an estimate: …"` (C21: the study was analytic in round 1),
   `"Question screen unresolved: …"`, `"Question narrowed from: {original_question.text}"` (a question rewritten for
   any cause), `"Decision rules not externally timestamped: …"` (see the `Experiments` rule below).
2. Rival explanations whose `ruled_out_by` is `(not addressed)` (the C13 findings) — **one entry per distinct
   `how`**, naming the rival, how it would arise and every claim it applies to; the same limit on two claims is one
   entry, not two.
3. Power: every `test` or `equivalence` claim whose `power.verdict` is not `adequate` — with the smallest detectable
   effect and the effect the literature reports. An estimate claim gets an entry only when its `precision_target`
   says the interval is wider than the aim; "the SD is unknown" on every estimate claim is not an entry.
4. The external-validity limits from the primary claim's `scope` — what the result may not be generalised to;
   `(licence unverified)` once per dataset; a So-what rung left `(TBD)`:
   `"Significance not supported by the literature: {rung}"`; the part of a result that existing data already
   give (C17 `partly`); and a primary test claim that has no positive control (C17).
5. The risk-table rows.

One entry per distinct risk: a doubt both blind readers raise, or a reader doubt that is also the power or single-dataset
entry, is written once (naming both sources). The fields are read by people outside this pipeline: no leaf ids, "the
tree", rounds, env-probe or file names — the study's own terms (`pack-check` K11 warns).

Every entry of groups 1–3 has its source in `argument.json` (`reader_doubts`, `external_check`, `original_question`,
`rivals`, `power`) or in a gate's log line. A risk that exists only in `idea.json` is not allowed: add the row to
`argument.json` first, or the idea lists a rival its own argument does not.

The role tag is the new convention for an `Experiments` entry. The roles are `instrument`, `tests`, `control`,
`descriptive`, `release`; `tests` and `control` name the claim ids they serve, and so does a `descriptive` entry that
supplies the evidence of an estimate claim (`E1 [descriptive C2]`). **The id is the first token of the entry and the
tag follows it** — the experiment stage reads the id from the start of the entry, and a list whose entries start with
a bracket is renumbered there, which shifts every id by one against `argument.json`. The id must be the one used in
`argument.json`, because `argument-check` (C3) matches the two. Earlier archives start entries as `**E0 …**` or
`E3: …`; they stay valid and are not rewritten.

In `Related Work`, cite every paper as `(Author et al., Year) [citation_key]` — the key is not decoration. A shortlist
routinely holds several papers that collapse to the same prose citation (two different "Zhang et al., 2025" is
common; that is exactly why keys carry `a`/`b` suffixes), so author and year alone cannot say which paper supports the
claim. The key also lets the writeup stage `\cite{}` straight from the idea without searching again. Cite only papers
that are in `step3_shortlist.json`; if a claim needs a classic that the search did not retrieve, say so in words
("the JPEG-LS standard, not retrieved in this search") rather than citing it as if it had been read.

Each `Experiments` entry names the exact algorithmic change, the dataset (and how to obtain or synthesise it), the
baselines, and the metric — and, where it follows a field convention, which one ("LOSO split as in [ahmedetal2026]"),
so a reviewer can see the result is comparable. The licence and consent line from the Scope table of §4 (or
`(licence unverified)`) appears **once per dataset**, in the first entry that loads it — the same sentence in seven
entries adds nothing. Entries use the words the experiments naturally use: never reword one to satisfy C10 — change
the key term, or leave the `WARN`. The instrument entry that fixes the decision rules says how a third party can
verify that they were fixed first: a commit hash made before any analysis, or an external timestamp the user must
create. Otherwise the entry says "fixed before analysis, not externally timestamped", the word "pre-registered" is
not used, and `"Decision rules not externally timestamped: …"` goes into the risks — a "locked" plan nobody can check
is a claim, not a safeguard. Ids are those of `argument.json` as they stand, gaps included (`E0, E1, E3`): a retired
id is not reused and the list is not renumbered. The 7-key schema is a hard contract with `new_run.py` and the experiment stage: exactly
these keys, in this order, nothing added. The PICO and the journal list do not go in.

### Write it

```bash
# save the FinalizeIdea ARGUMENTS as gen_{k}/idea.json (the last idea_draft.json plus any Risk Factors entries the gates added), then:
$PY $SK/scripts/ideate_tools.py append-idea <topic>.json $RD/gen_{k}/idea.json
$PY $SK/scripts/ideate_tools.py consume $RD --gap GAP_00N --angle "<angle>" --idea <Name> [--also-uses GAP_00M]
# fusion-block topic: the question is the consumed unit (gap and angle are read off it)
$PY $SK/scripts/ideate_tools.py consume $RD --question Q_NNN --idea <Name> [--also-uses GAP_00M]
```

The Risk entries added at this point are taken from `reader_doubts` and the gate notes, never added to `idea.json`
alone. `idea_draft.json` is kept after finalize — it is what the last reader and the last check saw; `idea.json` is
the canonical copy, and `argument-check` without a flag prefers it.

When `coverage.angle` is `part`, record that in the ledger by passing
`--angle "<angle> [not covered: <angle_dropped, short>]"` to `consume`, so a later generation can see that the rest
of the angle is free instead of finding it marked as used.

`consume` runs only for an idea that was finalized and appended, as before. A `(gap, angle)` abandoned at B3.5 or after
a revision's trade-off rows (§5) is never consumed; list every abandoned pair, with the screen or trade-off that ended it, in the
final report to the user, so that many abandoned pairs are visible rather than silent. The same report lists, per
idea, what the labelled Risk entries say, every `tradeoffs` row (what was given up, the gate, what was lost), every
claim that is an estimate `by-construction:` (the test given up at B4) and `coverage.angle_dropped` (SKILL.md,
Finish).

The idea JSON takes no extra keys, so anything a reader must know about the *strength of the evidence* goes in the
text: after a `quick` run, or when the snowball or a source failed, say in `Related Work` what the literature base was
(how many papers, abstracts only, which classics were not retrieved) and repeat it as a `Risk Factors` entry.

`append-idea` validates the contract (keys and order, `Name` format, abstract length, list fields, duplicate names)
and appends atomically after **every** idea, so a crash never loses finished work. It refuses to overwrite an archive
that does not parse — tell the user instead. If it rejects the idea, fix the idea; do not hand-edit the archive.

Then write the prescriptive Body `gen_{k}/body/B_draft_{Name}.md` (template in
[knowledge-templates.md](knowledge-templates.md), `based_on` the descriptive Body; on the fusion block "the angle of
this generation" is `gen_k/question.json → angle`) and the journal recommendations.

For the next generation return to B2 with a new angle. `{prev_ideas_string}` from the original generation prompt
still applies: keep the already-finalized ideas in view so the new one differs in substance, not only in label.

---

## 7. Journal recommendations

`gen_{k}/step8_journal_recommendations.md` — kept because the writeup stage is planned to target journals. This is
the **only network use in stage B**, and it sits outside the reflection loop.

Start from `target_venues` in the session config (the same list the persona used, so the two cannot contradict each
other), adjust for this idea, and verify current facts with `WebSearch` rather than from memory — impact factors and
scopes change. Recommend 3–5 venues spanning one aspirational, two solid and one accessible:

`Venue | IF or tier (year) | Scope fit — specific | Review timeline | OA option and cost | Why this venue |
Shortlisted papers published there (citation keys)`

End with a comparison table and a one-paragraph submission strategy. The file also keeps the archived engine's
layout (`archived/scholar_research` render/step8.py, `it_legacy.py`), so a reader of the old files can read it:

```markdown
---
session_id: "YYYYMMDD"      (step0's)
topic: "…"
date: "YYYY-MM-DD"
step: 8
journals_recommended: N
---
# Journal recommendations — {Name}
> Topic: …   > Hypothesis: the primary claim in one sentence   > Date: YYYY-MM-DD
## Selection Criteria          one paragraph: what the venues were chosen for
## Recommended Journals        the venue table above, then per venue:
### {n}. {Venue}               "⭐ Top Recommendation" after the first-choice venue's name
| Field | Details |            rows **Impact Factor**, **Scope Fit**, **Review Timeline**, **Open Access**, **Why This Journal**
**Papers from our collection published here:** one `- key — …` line each, or "none"
## Comparison                  the comparison table
## Journal Comparison          | Rank | Journal | IF | Scope Fit | Review Time | OA Cost | Strategy |
## Submission strategy
## Dataset licences
```

The strategy's **first-named venue is the target**: `/ai-scientist-criteria` picks it automatically (no human checkpoint), so name exactly one first choice,
spelled as in the table, before any alternative, and put a special article type in the same sentence when it applies
("an eNeuro Registered Report", "a JNE Technical Note"). `WebSearch` may be a deferred tool that has to be
loaded first (via `ToolSearch`); if it is unavailable, write the table from the shortlist's venues alone and mark IF
and timelines `(TBD - unverified)`. Check that a venue still exists this cycle and that its deadline has not passed —
workshop series change theme or lapse. When a venue from `target_venues` turns out to be defunct or off-theme, remove
it from the session config too, so the next generation's persona is not aimed at it.

**Dataset licences.** Because this is the one step that may use the network, it also resolves what the loop could
not: for every dataset the idea marks `(licence unverified)`, look up its licence and whether the consent covers
secondary analysis, and record them under `## Dataset licences` in `step8_journal_recommendations.md` (dataset,
licence, source URL, date checked; `(TBD - unverified)` when the search fails). `idea.json` is not edited — it is
already in the archive, and its entry keeps saying `(licence unverified)`; this file is where the answer is found.

At `quick` depth two or three searches are enough; do not spend more on the venue table than the idea itself cost.
