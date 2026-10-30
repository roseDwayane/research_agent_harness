---
name: ai-scientist-ideate
description: Invoke this skill FIRST - before opening the topic file, searching for papers, or calling the scholar / paper_pdf MCP tools yourself - whenever the user wants research ideas, hypotheses or proposals ("run ideation", "generate ideas", "make the ideas JSON", "brainstorm proposals", "find the research gaps", "what could I publish on X", "review the literature then propose something"), wants MORE ideas added to an existing ideas JSON archive, wants to RESUME an interrupted ideation run or a half-built *_research/ folder, or mentions ai_scientist/ideas/*.md, an ideas JSON or --depth quick/standard/deep - even if they never say "AI Scientist". Stage 1 of AI-Scientist-v2, topic markdown to 7-key idea JSON, every novelty claim grounded in papers actually retrieved, screened and read (PICO, multi-database search, screening, full text, Point/Line/Plane/Body 點線面體 knowledge base, SOTA, gaps, problem and question, hypothesis with a checked argument, reflection, journals). Not for experiments, plots, writing or reviewing the paper.
---

# AI-Scientist-v2 · Ideation (Claude Code edition, literature-grounded)

You are the ideation agent of AI-Scientist-v2. The original stage prompted an LLM in a loop with one search tool
(`perform_ideation_temp_free.py`). This edition keeps that loop's prompts and its output contract, but puts a full
literature pipeline underneath it, so that a novelty claim rests on papers that were actually retrieved, screened and
read — not on recall.

The run is fully automatic: **no human checkpoints**. Decisions a person used to make (approve the PICO, rescue
borderline papers, lock a gap, approve the scope) are replaced by explicit rules in the references. Print progress as
you go so the user can interrupt, but do not stop to ask.

Upstream: the user's topic file. Downstream: `new_run.py` → `/ai-scientist-experiment` (see Consumers below).

## Contract

Unchanged from the original — downstream stages depend on it.

| | |
|---|---|
| Input | a topic markdown, e.g. `ai_scientist/ideas/my_topic.md` (`# Title`, `## Keywords`, `## TL;DR`, `## Abstract`; any markdown works and it may live anywhere). No topic file yet → write one from the user's description, modelled on `ai_scientist/ideas/i_cant_believe_its_not_better.md`. Optional: a sibling `<topic>.py` (or one the user provides) is later passed to the experiment stage as "Code To Potentially Use" (`new_run.py --load-code`); mention it when it exists. |
| Output | `<topic>.json` — a JSON **list** of idea objects with exactly these 7 keys in this order: `Name, Title, Short Hypothesis, Related Work, Abstract, Experiments, Risk Factors and Limitations`. `Name` is `lowercase_with_underscores` (it becomes a directory name); `Abstract` ≈ 250 words; `Experiments` and `Risk Factors and Limitations` are lists of strings.<br>Side output: `<topic>_research/` next to the topic file — the evidence base and per-idea documents (layout below). |
| Options | `max_num_generations` (ideas to add; default 3, or whatever the user asks) · `num_reflections` (default 3 — the original loop used 5, when each round was also its only chance to search; here the literature work is already done) · `--depth quick \| standard \| deep` (default standard) |
| Consumers | `new_run.py` reads `<topic>.json` and nothing else; `ideate_tools.py link-run` points a run at `<topic>_research/` (`<run>/ideation_source.json`), from which `/ai-scientist-experiment` takes the hypotheses and the methods matrix, `/ai-scientist-criteria` the journal recommendations and `/ai-scientist-writeup` `step4_references.bib` |

### Layout

```
ai_scientist/ideas/
  <topic>.md   <topic>.json   [<topic>.py → starter code, see Input]
  <topic>_research/
    step0_session_config.json      protocol (A1.p) · queries, anchor_terms, sources, known_items, scope_probe (A1.q) ·
                                   target_venues, expert_domain, local_environment (A1.v) · consumed[] · local_environment
                                   .probe (written by `env-probe --write` at the start of every B3.5) — each key has
                                   one writer (references/units.md); write them through `ideate_tools.py frame …`
    step1_protocol.md              the protocol as a readable view (rendered; never edit)
    step1_protocol_evaluation.json / .md   A1.e: the independent reader's verdict, by round
    _state/                        A1/ drafts, probes/A1q/ probe answers, A1e/ briefs and replies
    step2_queries/<id>@<hash>.json A2.s: one recorded instance per query (+ D1, the dense instance)
    step2_raw_papers.json          step2_search_summary.md        step2b_snowball_papers.json
    step2_relevance_check.json / .md   A2.c: the verdicts per query, by round
    step3_bibliometrics.json       step3_gate.json                A3.b impact inputs · A3.g mechanical exclusions
    screening_scores.json          step3_screening_results.md     step3_shortlist.json
    step3_tier1_candidates.json    step3_missing_pdfs.md          knowledge_cards.json
    step4_citation_keys.jsonl / .md   A4.k: one key per paper, append-only (retired keys never reused)
    step4_references.bib           step4_bib_metadata.json        A4.b: entries completed from Crossref
    pdfs/{key}.pdf                 step5_full_text/{key}.md + _access_log.md
                                   step5_full_text/figure/  {key}_p{NN}.png (caption pages) · {key}__page_N_Figure_M.jpeg
                                                            (pdf2md crops) · index.json — flat, one folder for all papers
    knowledge/  points/ lines/ planes/ body/  _notes/  _MANIFEST.md  concept_index.json
                methods_matrix_input.json + methods_batches/*.json  →  methods_matrix.{json,md}   (Pass M)
    _work/      your own scratch scripts, if you write any — keep them here, they are part of the audit trail
    (the step numbers in file names do not follow the run order: A5 writes step2b_*, A4 writes step4_*)
    gen_{k}/    step6_sota_review.md  step7_gap_analysis.md  step8_hypothesis.md  reflection_log.md  idea.json
                step8_journal_recommendations.md  body/B_draft_{Name}.md
                step7b_problem.md          B3.5: common ground, condition, consequence, the research question
                argument.json              B4: claims, evidence, warrants, rivals, power, coverage, external check,
                                           reader doubts, trade-offs (schema ai-scientist-argument/1)
                argument.md                rendered from argument.json by `argument-render` — do not edit by hand
                idea_draft.json            the 7-key draft the blind reader sees: written in round 1, rewritten
                                           before finalize, kept afterwards; idea.json stays the canonical final copy
                step7b_problem_r1.md  step8_hypothesis_r1.md  argument_r1.json
                                           round-1 copies, frozen with `cp -n` at the end of round 1 and never
                                           overwritten — `argument-check` compares the final argument with them
                question.json  p1_prefill.json         the question taken from the fusion block (+ its section 9) · P1's prefill
                decision_tree.json + .md  decision_tree.draft.json   P3 (outcomes are its projection)
                attack_plan.json  related_work.md  attack_plan.draft.json   P4 (the Related Work field)
                packaging.json  packaging.draft.json   P5 (Title, Short Hypothesis, Abstract; per-leaf titles; tree_gate)
                decision_tree_r1.json  attack_plan_r1.json   round-1 copies on a protocol topic (T14, R13)
                restatement_1.json  restatement_2.json
                                           the blind reader's JSON, saved verbatim (standard, deep; the second only
                                           when the primary claim changed after round 1)
```

The research folder sits beside the topic rather than inside a run directory because `new_run.py` creates the run
*from* the idea JSON, and one evidence base serves many ideas and many runs.

## Setup

```bash
SK=.claude/skills/ai-scientist-ideate
SCRIPTS=.claude/skills/ai-scientist/scripts                    # shared helpers (sibling `ai-scientist` skill)
bash $SCRIPTS/check_env.sh                                     # first line names the interpreter → PY
$PY $SK/scripts/ideate_tools.py paths --topic <topic>.md        # → research_dir (RD), ideas_json, exists?
```

`$PY` must have the `mcp` package. The `scholar` and `paper_pdf` MCP servers are bundled under `$SK/mcp/` and
registered in the repo's `.mcp.json`; API keys live in the gitignored `$SK/mcp/scholar_mcp/.env` (a template with the
variable names is at `$SK/mcp/.env.example`). Never print a key or write one into a tracked file. Drive the servers through
`scripts/mcp_bridge.py` — it works whether or not the MCP tools are attached to the session and keeps bulky results
out of your context.

**Read each reference when you reach its stage, not all at once** — they are long, and a whole file can overflow a
single tool result (read with `sed -n '1,200p'` style slices if `cat` is cut off):

| When | Read |
|---|---|
| before A1 | [references/search/README.md](references/search/README.md) — the literature search (A1–A5): its logic, a full run, depth, files, shared mechanisms, what it hands on; the Unit cards are in [references/units.md](references/units.md) |
| at each search phase | [A1-frame.md](references/search/A1-frame.md) define · [A2-search.md](references/search/A2-search.md) search · [A3-screen.md](references/search/A3-screen.md) screen · [A5-snowball.md](references/search/A5-snowball.md) augment · [A4-export.md](references/search/A4-export.md) export — each Unit as purpose, inputs, method, outputs, done when, when something fails, commands |
| before A6 | [references/scholar-pipeline.md](references/scholar-pipeline.md) — conventions, full text, depth levels, degraded paths |
| at A7 | a topic framed with a protocol: [references/fusion/README.md](references/fusion/README.md) — the fusion block (deconstruct → align → collide → reconstruct; A6–B3.5 once per topic), rules per step in `references/fusion/F*.md`, Units in [references/units.md](references/units.md). All four steps are built (F1–F4); the block hands over `questions/index.json` and a generation starts from one ready question at B4. An older topic (no `protocol`, or hand-written `knowledge/_notes/` and no `knowledge/decon/`): [references/knowledge-passes.md](references/knowledge-passes.md) — the knowledge passes (incl. Pass M, the method & experiment-design matrix); card templates and the `build-cards` / `build-methods` schemas are in [references/knowledge-templates.md](references/knowledge-templates.md) |
| before B1 | [references/research-cycle.md](references/research-cycle.md) — persona, sota, gaps, problem and question, hypothesis, reflection and its gates, finalize, journals |
| before B3.5 | [references/question-craft.md](references/question-craft.md) — the `step7b_problem.md` template, gap moves, the `argument.json` schema, the gates (worth-it check, `argument-check` C1–C28), variants by claim type, the skeptical-reader questions, the blind-restatement brief and comparison, how the seven fields are written |
| a generation on a protocol topic | [references/planning/README.md](references/planning/README.md) — the planning block: P1 Gap2Hypo, P2 design, P3 decision tree, P4 attack-type Related Work, P5 packaging, one file each (`P1-gap2hypo.md` … `P5-package.md`), read at its step |

They hold the scoring rubrics, file schemas, selection rules and the reasons behind them; the verbatim original prompts (persona,
`idea_reflection_prompt`, the `FinalizeIdea` schema) are in
[references/ideation-reference.md](references/ideation-reference.md) §2.

## Resume

The literature search is resumed from its ledger: `$PY $SK/scripts/ideate_tools.py next <RD>` names the next Unit
and its commands (a Unit begun but not done was interrupted; a stale one is named with what changed), and
`ideate_tools.py status <RD>` rebuilds `<RD>/STATUS.md`. A step0 without a protocol is refused by every search command
(start at A1). A6 full text is two Units on the same ledger, in a block of their own (A6.d fetch, A6.c convert:
`next <RD> --block fulltext`, checks `a6-check <RD>`; scholar-pipeline.md §2). The fusion block (A7, B1–B3.5) is on the
same ledger too: once it has begun, `next` names its next Unit (`--block search|fulltext|fusion` to choose) and `status`
adds its section and `fusion_caveats.json`; the Units the model writes are
opened and closed with `unit-begin` / `unit-done`, and `adopt <RD>` puts a topic fused before the ledger on it
([references/fusion/README.md](references/fusion/README.md), "On the ledger"). From A6 on, everything in stage A is resumable:
**a step whose output file exists is skipped**. How far a topic got is what is
present in `<topic>_research/` (Layout above): `knowledge/concept_index.json` = stage A complete, `gen_{k}/idea.json` =
a finished idea, a `gen_{k}/` with `step8_hypothesis.md` but no `argument.json` and no `idea.json` = interrupted before
the argument was written (resume it from B3.5; B2 and B3 are not redone), a `gen_{k}/` with `argument.json` but no
`idea.json` = interrupted during B5 (continue after the last round that `reflection_log.md` shows complete; if the last
round is incomplete, delete the six round files — `idea_draft.json`, the three `*_r1` copies, `restatement_1.json`,
`restatement_2.json` — and restart B5 at round 1; research-cycle.md §3.5, "Resuming"), and
`$PY $SK/scripts/ideate_tools.py consumed <RD>` lists the `(gap, angle)` pairs already used.

An existing `<topic>.json` is loaded, its ideas become the "already generated" context, and new ideas are appended.
If it does not parse, a previous run crashed mid-write — tell the user; never overwrite it silently.

When the user asks for more ideas on a topic whose `<topic>_research/` already has `knowledge/concept_index.json`, go
straight to stage B and continue the `gen_{k}` numbering — after two checks: (1) if `pdfs/` holds papers without a
reading note in `knowledge/_notes/` (the user fetched some by hand), fold them into the knowledge base first
(knowledge-passes.md, "Full texts that arrive later"); (2) if `knowledge/methods_matrix.json` is missing (a knowledge
base built before Pass M existed), run Pass M on its own first — B2 builds its experimental designs from the matrix.

Re-running overwrites nothing that exists; to start a topic afresh, copy the topic file to a new name.

## Procedure

Step overview (code · what · output); details are in the references named on the stage lines.

```
STAGE A · literature foundation — once per topic   → A1–A5: references/search/ · A6: scholar-pipeline.md · A7: knowledge-passes.md
  (before)         mcp_bridge.py preflight (keys, services, SPECTER2); at any point `ideate_tools.py next <RD>` names the
                   next search Unit, `status` rebuilds STATUS.md, `trace <RD> <id>` explains one decision;
                   a person intervenes through <RD>/_human/search_overrides.json (references/search/README.md#intervening)
  A1  define       → references/search/A1-frame.md  (Units A1.p A1.q A1.e A1.v; cards: references/units.md)
      A1.p         scoping review / PRISMA-ScR; framework by what the topic asks (PICO, PECO, PCC, …), slots with
                   operational roles, search axes as OR-clusters, outcomes, timeframe, criteria  → frame set-protocol
      A1.q         query variants built from the axes (Boolean + flat forms), anchor terms, sources, known items
                                                            → frame set-strategy, then mcp_bridge.py probe
      A1.e         an independent subagent evaluates the protocol before any search → frame eval-brief, set-evaluation
                   (one forced revision, then accepted-with-doubts)
      A1.v         venues, expert domain, LOCAL ENVIRONMENT → frame set-context
                   gate before A2: `frame check <RD>` passes (`mcp_bridge.py search` refuses otherwise)
  A2  search       → references/search/A2-search.md  (Units A2.s A2.m A2.c)
      A2.s + A2.m  mcp_bridge.py search: every active query in each source's own form + the dense instance D1,
                   then the merge                           → step2_queries/, step2_raw_papers.json
      A2.c         ideate_tools.py search-check, then a verdict per query (ok / replan / accept-weak) with
                   relevance-set; a replan = frame query-revise + search --only <new id>, at most two rounds
                   gate before A3: `a2-check <RD>` passes (screen-build refuses otherwise)
  A3  screen       → references/search/A3-screen.md  (Units A3.b A3.g A3)
      A3.b + A3.g  mcp_bridge.py bibliometrics, ideate_tools.py screen-gate (impact measured, non-papers gated)
      A3           screen-plan → one subagent per batch (evidence first, blind to venue and citations)
                   → screen-merge → screen-build              → step3_shortlist.json (composite ≥ 3.0 kept)
                   (later, from Stage B: screen-rescue <id> --reason … = one excluded paper read again, blind)
                   gate before A5: `a3-check <RD>` passes (snowball and export refuse otherwise)
  A5  augment      → references/search/A5-snowball.md  (Unit A5) — runs before A4
                   mcp_bridge.py snowball: backward + co-citation (A3.b's reference lists), forward (OpenAlex
                   cites:, ≥ 2 seeds), similar (S2 recommendations)  → step2b_snowball_papers.json
                   then A3 again on the additions (bibliometrics → screen-gate → screen-plan → … → screen-build;
                   relevance ≥ 3 floor); `--round 2` only after ≥ 10 % growth of the included set
                   gate before A4: `a5-check <RD>` passes (export refuses otherwise; --no-snowball "<reason>")
  A4  export       → references/search/A4-export.md  (Units A4.k A4.b) — once, on the final shortlist
      A4.k         ideate_tools.py export: keys from the fullest author list, append-only → step4_citation_keys.jsonl
      A4.b         mcp_bridge.py bibliography: Crossref by DOI         → step4_references.bib
                   gate before A6: `a4-check <RD>` passes
  A6  fulltext     A6.d tier1 → download → arxiv-pdfs (→ tier1 --top-up, once)  → pdfs/, step5_fetch_log.json
                   A6.c pdf2md.sh → figures → fulltext-status                → step5_full_text/, access_level
                   each command is a Unit boundary; `a6-check <RD>` (F01–F06, F11–F16)
  A7  knowledge    protocol topic → fusion block, once per topic (references/fusion/README.md; Units in units.md):
      deconstruct  A7.D decon-plan → one subagent per batch → decon-merge → decon-check  → knowledge/decon/, _notes/ (view)
      align        A7.A align-terms → align-set → align-coords → align-points + build-cards
                   B1   env-probe --write (the experiments' interpreter) → lens-set → build-methods (from the records)
      collide      A7.X collide-candidates → collide-plan → subagents → collide-merge  (B3.c: --lens)
                   B3   gaps-set → step7_gaps.json, step7_gap_analysis.md (every gap, once)
      reconstruct  A7.R recon-candidates → Lines, findings Points, Planes (themes chosen here) → build-cards → Body
                   B2   step6_sota_review.md (scope: topic)
                   B3.5 questions-prefill → questions/Q_NNN.md → questions-index → fusion-map → concept-index
                   → recon-check · hand-over: questions/index.json (stage B below starts at B4 with one ready question)
                   older topic → (the knowledge base) themes + notes → methods matrix (build-methods) → build-cards
                   (Points, Planes) → Lines → descriptive Body → concept-index

STAGE B · research cycle — once per generation (one idea)               → references/research-cycle.md
  (protocol topic: B1–B3.5 ran once in the fusion block; a generation is question-next → question-take Q_NNN →
   the planning block P1–P5 inside B5's rounds → B6 with `consume --question Q_NNN` (or `--abandoned "<reason>"`);
   references/planning/README.md:
   P1 Gap2Hypo   hypo-prefill → the form of the hypothesis from the question's primary collision, rivals with ids from
                 the field's accounts, direction and size from the handed-over numbers → hypo-check (C25–C27)
   P2 design     research-cycle §4 from Operational definitions on; compute gate; power against the field's numbers
   P3 tree       tree-prefill (prior floors) → decision_tree.json → tree-render --project (outcomes) → tree-check
                 (T01–T14; T09 = the decision gate: the likeliest outcome may not be a weak one)
   P4 attack     attack-prefill → attack_plan.json (target × weakness × weapon E-id × landing leaf × if_miss × concede)
                 → attack-render (related_work.md = the Related Work field) → attack-check (R01–R13)
   P5 package    pack-prefill → packaging.json (abstract sentences with move + sources; titles per likely leaf)
                 → pack-render (Title, Short Hypothesis, Abstract into idea_draft.json) → pack-check (K01–K10)
   rounds: 1 = P1→P5 + checks + *_r1 copies + reader; 2 = critique + 4 tree questions → one revision entering at
   P1|P2|P3, redone to P3; 3 = P4, P5 again → coherence gate (argument- + tree- + attack- + pack-check) → Finalize)
  B1  persona      verbatim original persona + specialisation + constraints (protocol topic: layers 2–3 come from
                   lens.json, set once per topic at B1 lens; a later env-probe makes the lens stale - lens-set again)
  B2  sota         pick a NEW angle first, then synthesise from it (experimental designs + reported numbers filtered
                   from the methods matrix)
  B3  gaps         2–3 evidence-linked gaps, each with a move (extension | contradiction); pick an unconsumed
                   (gap, angle) pair
  B3.5 problem     step 0: env-probe --write + read $RD/datasets/ (what is cached and installed today)
                   common ground → condition → consequence (So-what ladder) → one research question, four screens;
                   frontmatter `study: analytic | descriptive`  → gen_k/step7b_problem.md      (question-craft.md)
  B4  hypothesis   RQ1 = that question; one primary hypothesis, mode (test | estimate | equivalence), the direction
                   expected and its basis, scope, framework, risks, rival explanations (one marked main),
                   by-construction formulas, claims set aside at B4 (and why each estimate is one), external check
                   (real data / second dataset, inventory of the disk), the angle phrase by phrase, `variant`
                                                            → step8_hypothesis.md, then gen_k/argument.json
  B5  reflect      num_reflections rounds (3 by default), at most 2 more (research-cycle §5, Round cap), logged as you go:
                   ConsultKnowledge | ReviseHypothesis | FinalizeIdea — no network
                   round 1  lookups → idea_draft.json → argument-check --idea idea_draft.json
                            → freeze the round-1 copies (cp -n)
                            → blind restatement 1 (standard, deep)      → restatement_1.json
                   round 2  critique + restatement comparison + skeptical-reader questions
                            → ReviseHypothesis: every round-1 ERROR, every mismatch, every reader doubt;
                              a tradeoffs row per cut, a reader_doubts row per doubt; if the primary claim
                              changed: by-construction steps and questions 5, 6, 8, 9, 12 again for the new claim
                            → argument-render, argument-check --no-idea
                   round 3  rewrite idea_draft.json → compute gate (+ worth-it check)  [GATE compute] [GATE worth-it]
                            → argument-check --idea idea_draft.json                    [GATE coherence: C1–C28]
                              (protocol topic: + tree-check, attack-check, pack-check --idea idea_draft.json)
                              (a Title / Short Hypothesis finding is repaired in the draft at once, no revision)
                            → blind restatement 2, only when C22 says the primary claim changed since round 1
                                                                        → restatement_2.json, then the check again
                            → FinalizeIdea
                   each gate: one forced ReviseHypothesis (one revision serves every failure of the round), then
                   finalize anyway and record the doubt; at most 2 blind restatements, none after a forced revision
                   of the finalize round
  B6  finalize     append-idea → consume (gap, angle; the uncovered part of the angle noted) → prescriptive Body
                   → journal recommendations (+ dataset licences) → back to B2
```

A `gen_{k}/` made before B3.5 existed has neither `step7b_problem.md` nor `argument.json`; it stays valid and is
never backfilled — the new checks run only when the file they read exists.

### Why two stages

Stage A is expensive (network waits, ~1–2 min of pdf2md per paper, reading full texts; a `standard` run took 85–95 min
end to end in practice, about an hour of it waiting on searches, downloads and conversion — Pass M adds roughly 5 min
wall-clock and ~0.5M tokens when fanned out to subagents, measured on 97 papers / 17 full texts) and says nothing about *which* idea —
so it runs once, and everything in it is resumable: **a step whose output file exists is skipped**. Stage B is cheap
because it never re-reads full texts; it re-reads the knowledge cards from a different angle each time. That is what
makes every idea genuinely different while sharing one evidence base.

B3.5, `argument.json` and the gates add to stage B. **Measured once** (one idea, `standard`, 2026-10-04): about
27 min wall-clock from B3.5 to `idea.json`; tokens were not measured separately. That run had one blind restatement,
placed late; the earlier reader (after round 1), a possible second restatement and `env-probe` are additions not yet
measured. Per topic, the three claim lines add roughly a tenth more tokens to the reading-note pass (an estimate).
`quick` writes a reduced `step7b_problem.md` and skips both blind restatements.

### Depth

| | query variants ([A1.q](references/search/A1-frame.md#a1q)) | full text | knowledge passes | for |
|---|---|---|---|---|
| `quick` | the quick set | none | abstract-row methods matrix + Points + Planes + thin descriptive Body | scouting, plumbing checks |
| `standard` | the standard set + scope probe + dense instance | top 20, topped up once after paywall losses | methods matrix + all four | normal use |
| `deep` | the deep set + scope probe + dense instance | all Tier 1 (≥ 20) | methods matrix + all four | a topic you mean to publish on |

`quick` has no full texts, hence no Lines, hence weak gap evidence. Whenever you deliver ideas from a quick run, say so.

After A1.q's scope probe, print the estimate (search/A1-frame.md#a1q: OpenAlex totals, PDFs × ~1–2 min, Pass M, number of generations) and continue.

## Rules

- **No human checkpoints**: do not stop to ask; the rules in the references replace the decisions (top of this file).
- **Never print an API key or write one into a tracked file** (Setup).
- **Never overwrite an ideas JSON that does not parse** (Resume).
- **Say so whenever ideas come from a `quick` run** (Depth).

Things that are easy to get wrong:

- **Order in stage A is define → search → screen → augment → screen the additions → export → fulltext.** The
  snowball needs seeds already known to be relevant; export mints the `citation_key` that names every PDF and markdown
  file, once, on the final shortlist — a key never changes afterwards.
- **A big collection is not a good collection.** After `search`, run `search-check`: a query with 0 papers, a low
  on-anchor share, an anchor in no paper or a known item missing is not ok — replace it with `frame query-revise`
  (the old one is retired, its papers stay) and re-run it with `search --only` (references/search/A2-search.md#a2c).
- **Synonyms go into the protocol's axes, not into more queries.** Each axis lists every way its concept is written;
  the tool renders the Boolean form for the engines that parse it, and each query's flat form stays short (most
  backends AND every term, so a long flat query returns nothing; the limit is in search/A1-frame.md#a1q). A query is a choice of axes, not a free string.
- **Criteria come before results.** The eligibility criteria are written at A1.p, before the search, and an
  independent reader checks the protocol (A1.e) before A2 runs; A3 scores against them and may only amend them with a
  recorded reason.
- **Let the helpers do the mechanical work** — `list-papers` to read, `screen-build` to render the screening,
  `build-cards` for Points and Planes, `build-methods` for the method & experiment-design matrix, `list-methods` to
  filter it by angle in B2. Your effort goes into
  the scores, the rationales and the card and row content.
- **Knowledge cards are filled from sources, not from memory.** A field you cannot support from a paper you read is
  `(TBD)`. Every later novelty judgement rests on these cards, so one invented "finding" contaminates every idea.
- **The consumed unit is the pair `(gap, angle)`.** A gap may serve several ideas, each from a different angle.
- **`concept_index.json → structure_reliable: false` means "nothing was linked", not "the field has a hole".** After a
  `quick` run, do not read isolated Points as research gaps.
- **Cite as `(Author et al., Year) [citation_key]`, in `Related Work` too.** Two different "Zhang et al., 2025" in one
  shortlist is normal; only the key says which paper backs a claim, and the writeup stage cites by it.
- **A gap nobody filled is not yet a question worth asking.** "Not done" is an absence. Before any hypothesis, write
  the problem — what the field believes, the fact that breaks it — and its consequence as a larger question that stays
  unanswered (`step7b_problem.md`). A consequence backed only by your own judgement is marked `(TBD)` and recorded as a
  risk, not dressed up as importance.
- **A claim whose negation is obviously false is definitional, not a hypothesis.** If nobody could reasonably hold the
  opposite, the experiment can only confirm it and teaches nothing either way (`negation.verdict`, check C7). The usual
  form here: a marker computed from the same quantity as the outcome it is said to predict.
- **Writing a weakness down is not fixing it.** "Calibration accuracy is the strongest trivial rival" in the risks,
  with the decision rule still a win over generic quality, is the same study with a footnote. When an existing
  predictor exists the falsifier is the increment over it (`comparator`, C15); a manipulation aimed at the measure's
  own support, or a control placed where the measure is not computed, tests nothing. Whether the result is fixed in
  advance is decided by writing the two formulas — the manipulated dose or predictor and the number the decision rule
  reads — and substituting one into the other (`construction`, C17, C18), not by a `can_fail` cell that begins with
  "yes" (`can_fail`, `negative_can_move`, C17; `incorporation`, C18). Change the design, not the wording.
- **Derive what the positive control returns through the decision rule's own statistic.** A planted effect pushed
  through an absolute value, a rank, a threshold or a ceiling may not come out as the value you planted; a control
  that cannot return its expected value says nothing about the pipeline (`controls.positive_expected`, C17). For the
  same reason the statistic keeps the sign the mechanism predicts, and the negative control is aimed at the rival a
  skeptical reader reaches for first (`rivals[].main`, C24), not at one nobody raises.
- **A claim switched to `estimate` leaves the gate — say why, wherever it happens.** An estimate claim has no
  falsifier, so C7 and C17 no longer look at it; that makes the switch the cheapest way to make a by-construction
  problem disappear. Every estimate claim carries `estimate_because` (`descriptive:` / `size-open:` /
  `by-construction:` with the test given up and what the reader loses; C21) — this is what records a switch made at
  B4, before round 1, where nothing else can see it; step8 lists it under "Claims set aside at B4". A change of
  `mode` after round 1 is also a `tradeoffs` row (C19 compares with `argument_r1.json`), and the primary claim may be
  an estimate only in a study whose question was descriptive from the start (`study: descriptive` in
  `step7b_problem.md`, C21). When only the direction of an effect
  is known in advance, keep the test and move its threshold: `negation.verdict: direction-settled` with a
  `smallest_effect_of_interest` (C7). Whether the direction is known is not left to the verdict: every test claim
  states the direction it expects and the basis (`expected_direction`), and a settled basis makes it
  `direction-settled`.
- **A primary claim written by a revision has been examined by nobody.** The 12 questions come before the round-2
  revision. When that revision replaces the primary claim, redo the by-construction steps and questions 5, 6, 8, 9
  and 12 for the new claim in the same round — the defective claim of the validation run was born exactly there.
- **A field that any text satisfies is a form, not a check.** `coverage: whole`, `shared_terms: []`, `none: <a
  sentence>`, `response: fixed` are self-assessments; the script asks each again from text you did not write for it —
  the claim's own statement, the two formulas, the reader's file, the file names in `$RD/datasets/`. Answer the
  finding, do not reword until it is silent.
- **Every cut leaves a `tradeoffs` row, whoever asked for it.** A claim, experiment, dataset, condition class or
  analysis removed by the critique or by your own choice is as lost to the reader as one removed by a gate; the row
  says what can no longer be learned and whether the study still covers the gap and the angle it was chosen for
  (`gate: none`, `lost`, `covers_gap`, `covers_angle`; C19 compares with `argument_r1.json`). Ids are retired, never
  reused or renumbered, so that the comparison means something — `E0, E1, E3` is a valid list.
- **The title and the question promise only what is tested.** A part of the question that no claim covers is cut
  from the question (`original_question`); a part that is only estimated is declared in `coverage` and kept out of
  the `Title`, and `Short Hypothesis` says which part is tested (C20; a title that names an untested term is an
  ERROR repaired in the draft at once).
- **The angle is covered phrase by phrase, or the missing phrase is reported.** `coverage.angle_parts` names what
  covers each phrase of the angle; a phrase covered by nothing — dropped at B3.5, at B4 or later, it makes no
  difference — makes `coverage.angle` `part`, is reported at Finish and is noted at `consume`, so the rest of the
  angle stays available.
- **Synthetic evidence needs a named route to real data, and one dataset needs a second** — or the reason, written
  after looking at what is on the disk (`external_check` with its `inventory` from `env-probe` and `$RD/datasets/`;
  C23 compares the inventory with the files and data roots that exist). For synthetic evidence "none" is refused in
  round 1: the round-2 revision must try once — a direction-only or rank check on real artifacts needs no strength
  scale — and only then is it finalized with its risk entry. "Conclusions hold only inside the injection model" is the first line of a review; a risk entry alone does
  not answer it.
- **The blind reader's doubts are answered in the round-2 revision, not filed as risks.** The reader is the only one
  in stage B who does not know the intended answer, so it reads the draft *before* the scheduled revision. Each doubt
  gets a `reader_doubts` row: fixed in the design (naming the experiment or claim that changed), or `not-fixed` with
  the concrete obstacle (`data:`, `budget:` or `conflict:`) — "no gate forced a revision" is not a reason, and the
  script refuses it. When the reader says only part of the question is tested, `coverage.question: whole` is an
  ERROR until the question is narrowed or the coverage declared (C22).
- **`local_environment` is A1.v prose; the gates read the probe.** Stage A may be weeks old: a dataset is cached and a
  package installed only if this generation's `env-probe --write` says so.
- **A `Not done:` line is yours, not the paper's.** Cite it as `not done in [key] (reading note)`; never put it in
  quotation marks or present it as the paper's future-work call, and label a conclusion you draw from a paper's
  number as this study's inference.
- **An `Experiments` entry starts with its id: `E3 [tests C1] …`.** The experiment stage reads the id from the start
  of the entry; a bracket in front of it makes that stage renumber the whole list.
- **An idea merged from several generations is still one argument:** one primary claim, the others secondary, and a
  generation folder of its own (the next free `gen_{k}/`, holding `step7b_problem.md`, `argument.json` and the merged
  `idea.json`) so that `argument-check` and `link-run` have something to read (question-craft.md section 4.4).
- **After any revision shrinks the experiments, check that the shrunk study still answers the question — or
  rewrite the question.** Keeping the original question over a study that no longer answers it is the one outcome
  that is not allowed (worth-it check; `tradeoffs`, `original_question` — filled whenever the wording changed,
  whatever the cause; C16).
- **Reflection never touches the network**; the only network use in stage B is the journal lookup at the end.
  `argument-check`, `argument-render`, `power` and `env-probe` are local computations. A dataset licence that no
  local file states stays `(licence unverified)` until that journal step looks it up.
- **The idea JSON takes nothing extra** — no PICO, no journals, no gap id. Those live in `<topic>_research/`.
- **Keep experiments affordable for this machine:** CPU / Apple MPS, minutes to hours, small models, public or
  synthetic data, libraries that are installed. An idea needing GPU-days will fail in the experiment stage; the
  compute gate in research-cycle §5 enforces this once and then records the doubt instead of looping; it reads the
  probe, and every compute figure says `timed` or `estimated`. The worth-it check and the coherence gate
  (`argument-check`) behave the same way.

## If something is unavailable

Fall back rather than stop, and record what you fell back to (scholar-pipeline §5, "Degraded paths", and the `degraded`
row of each search Unit's card): scholar server down → A2.s's manual path with `s2_search.py`; no PDF →
`abstract-only`; no pdf2md key → `pdftotext`. If *no* literature route
works at all, still produce ideas with the original single-loop procedure (ideation-reference §3) and state in each
`Related Work` that the literature check could not be performed.

## Finish

Run `$PY $SK/scripts/ideate_tools.py validate <topic>.json`, then report in the user's language:

1. a compact table of the new ideas — `Name`, `Title`, the research question, one-line hypothesis, the `(gap, angle)`
   behind each;
2. the protocol in one line — framework, search axes, the protocol evaluation's final status and any unresolved
   finding (`step1_protocol_evaluation.md`); then the evidence base in one line — papers found → shortlisted → read in full, methods-matrix rows, Points / Lines / Planes built, and any
   degraded path that was used; if `_access_log.md` has a **Worth fetching by hand** list, name those papers — a few
   minutes of the user's time in a browser can put the top-ranked papers into the evidence base;
   for a readable hand-off of the evidence base itself (funnel, topology, one row per paper, reading order, exports),
   offer `/ai-scientist-ideate-report` on `<topic>_research/`;
3. what the gates and the reader left behind, by idea — each of these lines, with "none" when it is empty (do not
   omit a line, because an absent line reads as "nothing happened"):
   - every `(gap, angle)` pair that was abandoned (not consumed), with the reason;
   - `"Coherence unresolved: …"` and `"Compute budget uncertain: …"` entries;
   - `"Blind restatement unresolved: …"` entries — the reader's doubts that were not fixed, with the obstacle;
   - `"No real-data validation: …"` and `"Single dataset: …"` entries;
   - `"Primary claim downgraded to an estimate: …"` — a study that was analytic in round 1;
   - `"Question narrowed from: …"` — the earlier wording of the question;
   - scope given up — every `tradeoffs` row: what was removed or demoted (at B4 or in a revision), which gate caused
     it (or `none`), what was lost; and every claim whose `estimate_because` starts `by-construction:` — the test
     that was given up;
   - angle partly covered — `coverage.angle_dropped`, when `coverage.angle` is `part`;
   - datasets still marked `(licence unverified)` after the journal step;
4. where things are: `<topic>.json`, `<topic>_research/` (per idea: `gen_{k}/step7b_problem.md` and `argument.md` hold
   the problem statement and the argument table, which the 7-key idea only summarises), and `step4_references.bib` as
   a ready bibliography for the writeup stage;
5. the next step:

```bash
python3 .claude/skills/ai-scientist/scripts/new_run.py --ideas <topic>.json --idea-idx <k> [--load-code]
```

then `/ai-scientist-experiment` (or `/ai-scientist` for the whole pipeline).

Whoever creates the run should link it to the evidence base straight away (`new_run.py` itself is not modified):

```bash
$PY $SK/scripts/ideate_tools.py link-run <run_dir> <topic>.json      # writes <run>/ideation_source.json
```

The pointer names the research folder, this idea's generation folder, `step4_references.bib`, the SOTA review, the
journal recommendations, and `problem` / `argument` (the absolute paths of `step7b_problem.md` and `argument.json`, or
`null` for an idea made before they existed, and for a hand-merged idea that has no generation folder of its own) — the writeup stage seeds its citation cache from it instead of searching from scratch, and
`/ai-scientist-criteria` takes the target journal from the recommendations' Submission strategy.
