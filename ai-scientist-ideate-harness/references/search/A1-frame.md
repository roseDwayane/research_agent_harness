# A1 frame — define the search

**Definition** is the first phase of the literature search ([README.md](README.md)). It fixes, before any result
exists, what counts as the topic and how the databases will be asked, and has an independent reader check both. The
topic file is the only input; nothing here reads ideas, gaps or knowledge cards.

| Unit | Decides | Writes (through the tool only) |
|---|---|---|
| [A1.p protocol](#a1p) | what counts as this topic | step0 `protocol` |
| [A1.q strategy](#a1q) | how to ask the databases | step0 `queries`, `anchor_terms`, `sources`, `known_items`, `scope_probe`, `strategy_basis` |
| [A1.e evaluation](#a1e) | whether the protocol is fit to search with | `step1_protocol_evaluation.{json,md}` |
| [A1.v context](#a1v) | venues, expert domain, local environment (for Stage B) | step0 `target_venues`, `expert_domain`, `local_environment` |

Order: **A1.p → A1.q (+ probe) → A1.e**; A1.v any time before Stage B. After every write the tool renders
`step1_protocol.md`, a view of step0 — read it, never edit it. A write that finds an ERROR prints it and writes
nothing; fix the draft and run the same command again.

A protocol written down before the search is what the search is later judged against (Kitchenham & Charters 2007
§5.4: "a pre-defined protocol is necessary to reduce the possibility of researcher bias").

---

<a id="a1p"></a>
## A1.p — protocol

### Purpose
Write down what counts as this topic — review type, question framework, search axes, outcomes, timeframe and
eligibility criteria — before a single title has been seen.

### Inputs
The topic file. Your draft `$RD/_state/A1/protocol.json`.

### Method

**1. Review type (fixed).** Stage A is a **scoping review for gap identification**: `review_type: scoping`,
`reporting_standard: PRISMA-ScR`, `purpose: gap-identification` (the tool writes these). Munn et al. (2018) give six
reasons to scope rather than review systematically; ideation has three: identify the types of available evidence,
examine how research on the topic is conducted, identify knowledge gaps. It never pools effects into one verdict.
PRISMA is a reporting-transparency tool here — the flow diagram and the search record — not a claim that nothing was
missed.

**2. Question framework — chosen by what the topic asks, not by its field.**

| The topic asks… | Framework | Slots (use these names) | Anchor slot |
|---|---|---|---|
| the effect of a method the researcher **applies** | **PICO** | population · intervention · comparison · outcome | intervention |
| the same, when the deployment context changes what works | **PICOC** | PICO + context | intervention |
| whether an **exposure / condition** is associated with an outcome | **PECO** / **PEO** | population · exposure · comparator · outcome | exposure |
| an **inventory**: what methods / datasets / evaluations exist, and where | **PCC** | population · concept · context | concept |
| a phenomenon and how it is experienced (qualitative) | **PICo** / **SPIDER** | population · phenomenon · context / sample · phenomenon · design · evaluation · research_type | phenomenon |
| how an intervention triggers a mechanism in a context (design proposition) | **CIMO** | context · intervention · mechanism · outcome | intervention |
| nothing above fits | **custom** | your slots (≥ 2), `anchor_slot`, `outcome_slot`, and why no standard frame fits | yours |

The boundary cases: *"Does ICA vs ASR vs wavelet cleaning change classification accuracy?"* — the researcher applies
the method → **PICO**, not PECO. *"Is long-term noise exposure associated with EEG markers?"* → a real exposure →
**PECO**. *"Which artifact-removal methods are used, on which tasks?"* → inventory → **PCC**. A mapping question in a CS
field is still PCC; the domain never decides the frame.

**Never force-fill a slot.** A PCC topic has no intervention or comparison; inventing them anchors every later step to
slots the question does not have. Record an `alternative` (framework + why not) only when two frames are genuinely in
contention.

**3. Every slot: value, operational role, reason.**

| `operational_role` | Meaning |
|---|---|
| `search-and-eligibility` | enters the queries (as a search axis) and gates inclusion |
| `eligibility-only` | applied at screening, not searched — a criterion must apply it |
| `extraction-only` | recorded per paper later (methods matrix), neither searched nor gating |

The `reason` answers three questions: **nameability** — will authors write this in the title or abstract?
**Discriminating power** — does it cut the topic away from its neighbours? **Not over-narrowing** — would AND-ing it
drop relevant papers that do not state it? The **anchor slot is always searched**; the **comparison arm almost never**
is — keep it eligibility-only and reach its literature with the `contrast` variant; population and outcome only when
they are specific and nameable.

**4. Search axes — every way a concept is written.** A search axis is one searched slot written as an **OR-cluster**:
2–4 search axes per topic, each with every way the concept is written — the technical and the common term,
abbreviations, sub-paradigms, British and American spellings, a truncated stem (`electroencephalograph*`), a MeSH
heading for biomedical axes. A concept written three ways needs all three. Aim for 3–8 terms (quick: ≥ 2); write each
term as 1–4 plain words — no `AND` / `OR` / brackets / quotes: the tool renders the Boolean form.

Auxiliary axes, drawn on by the query variants:

| `kind` | Holds | Needed |
|---|---|---|
| `anchor` | the field's named tools, methods and benchmarks any expert would expect cited (EEG cleaning: Autoreject, PREP pipeline, FASTER, ICLabel). A generic "benchmark" term does not retrieve them | every depth |
| `contrast` | the comparator or the adjacent field whose methods transfer (often the comparison slot's terms) | standard, deep |
| `counter` | negative-result vocabulary: `"does not improve"`, `fail*`, `"negative result"`, `limitation` | deep |
| `rigor` | `benchmark`, `"subject-independent"`, `leakage`, `reproducib*` — only when the topic has a validity question | optional |

When the outcome slot is searched, give each outcome its own search axis (`"outcome": "O1"`): otherwise the literature
on one outcome arrives only by accident.

**5. Outcomes, timeframe, setting, criteria, completion.**

- **Outcomes** (`O1`, `O2`, …): one entry per distinct outcome of the outcome slot (compression ratio *and* bit-error
  robustness are two). Required whenever the frame has an outcome slot.
- **Timeframe**: the search's hard `start-end` year filter, with a `timeframe_reason`. The last 5 years for
  fast-moving ML topics; 10+ years when the field rests on older standards or methods that are still the baseline. The
  snowball's backward route is not limited by year: that is how foundational papers get in.
- **Setting**: the compute budget experiments must fit (CPU / Apple MPS, minutes to hours).
- **Criteria**, written now: inclusion (`IN1`…) and exclusion (`EX1`…) rules, each with `refs` naming the slots and
  outcomes it applies. Every outcome is referred to by an inclusion criterion (relevance is screened against every
  outcome, not only the first idea in mind); every `eligibility-only` slot is applied by some criterion. A3 scores
  papers against these and may amend them only with a recorded reason.
- **Completion criterion**: when the search counts as done. The tool's default (every variant × source run, snowball
  run, relevance check passed or the weakness recorded, every resolved known item found or reported missing) is the
  right one unless the topic needs more.
- **Languages** (optional, default `["en"]`): the languages screening keeps (A3.g).

**6. The draft.**

```json
{"topic": "English title", "topic_file": "ai_scientist/ideas/my_topic.md", "depth": "standard",
 "protocol": {
  "framework": {"name": "PICO", "rationale": "the researcher applies a cleaning method and compares it ...",
                "slots": [{"slot": "population", "value": "scalp EEG recordings", "operational_role": "search-and-eligibility",
                           "reason": "nameable; separates EEG from MEG / fMRI"},
                          {"slot": "comparison", "value": "expert annotation", "operational_role": "eligibility-only",
                           "reason": "rarely named in titles; screening + contrast variant"}]},
  "axes": [{"id": "C1", "kind": "search", "slot": "population", "name": "EEG", "terms": ["EEG", "electroencephalograph*", "scalp recording"]},
           {"id": "C3", "kind": "anchor", "name": "named pipelines", "terms": ["Autoreject", "PREP pipeline", "FASTER", "ICLabel"]}],
  "outcomes": [{"id": "O1", "text": "agreement with expert labels"}],
  "timeframe": "2013-2026", "timeframe_reason": "...", "setting": "CPU / Apple MPS, minutes-to-hours per experiment",
  "criteria": {"inclusion": [{"id": "IN1", "text": "...", "refs": ["population", "intervention"]}],
               "exclusion": [{"id": "EX1", "text": "...", "refs": ["population"]}]},
  "a1p_note": "optional"}}
```

A complete example is `scripts/tests/fixtures/search/a1/good/protocol.json`.

### Outputs
step0 `protocol` (with `topic_sha256`, `written_at`, `history`), and the view `step1_protocol.md`.

### Done when
`frame check --unit A1.p` passes: framework and slots, axes and terms, outcomes, timeframe, criteria and their `refs`,
completion criterion (P01–P11; X01 = a step0 key no Unit owns). The topic file's hash is kept: a later edit of the
topic file is reported STALE (P10, a warning).

### When something fails
No topic file: stop. A frame that does not fit the question is caught by A1.e. Re-writing the protocol later (a better
frame, a new synonym) is allowed with `--note <reason>`, which goes into the deviation log; it makes the strategy and
the evaluation stale, and after the search every screening score.

### Commands
```bash
SK=.claude/skills/ai-scientist-ideate; PY=<interpreter with mcp>; RD=<topic>_research
mkdir -p $RD/_state/A1
$PY $SK/scripts/ideate_tools.py frame set-protocol $RD $RD/_state/A1/protocol.json [--note "<reason>"]
```

---

<a id="a1q"></a>
## A1.q — search strategy

### Purpose
Turn the axes into a small set of query variants, each rendered in the forms the databases parse; name the anchor
terms, the sources and the known items; and probe the scope before the search.

### Inputs
step0 `protocol` (A1.p passes). Your draft `$RD/_state/A1/strategy.json`.

### Method

**1. Query variants — controlled prunings of one axis tree.** A query is a choice of axes (and, per axis, all its terms
or a subset), not an independent keyword string. The variants are prunings of the same tree, so they compose and can be
re-run:

| `strategy` | Axes it uses | Why | quick | standard | deep |
|---|---|---|:-:|:-:|:-:|
| `primary` | every search axis, all terms | maximum precision | ✔ | ✔ | ✔ |
| `synonym-swap` | every search axis, another term subset | phrasings the ranking engines see one at a time | ✔ | ✔ | ✔ |
| `anchor-methods` | an anchor axis + the search axes other than the anchor slot's | the named tools a generic query misses | ✔ | ✔ | ✔ |
| `loosen` | every search axis but one (usually the most often unstated) | method and dataset papers that do not state that concept | | ✔ | ✔ |
| `contrast` | a contrast axis in place of the anchor slot's axes | the comparator / adjacent-field literature | | ✔ | ✔ |
| `counter-evidence` | a counter axis + all (or all but one) search axes | failures and null results a novelty claim must not ignore | | | ✔ |
| `recent` | every search axis, `"year": "last-12-months"` | preprints of the last year | | | ✔ |
| `rigor` | every search axis + a rigor axis | only when the topic has a validity question | opt. | opt. | opt. |

Add variants when they ask something new — another anchor subset, a second synonym-swap. A variant that repeats
another's axes and terms is refused. Every term of every search axis is asked by some active variant, or listed in
`dropped_terms` with a reason.

**2. Two rendered forms.** You write the axes and the flat words; the tool renders the rest:

- **`boolean_query`** — `(EEG OR electroencephalograph* OR "scalp recording") AND ("artifact rejection" OR …)`,
  rendered from the axes; editing it by hand is refused. A2.s sends it, in each engine's dialect, to the engines that
  parse Boolean.
- **`flat_query`** (= `query`) — 3–5 plain content words, each from the query's own axis terms, for the engines that
  rank flat text (Semantic Scholar). Prefer distinctive nouns ("motor imagery" over "classification"). An
  anchor-methods flat query names **one** anchor — the AND-ing backends answer two named tools with nothing; the
  Boolean form carries them all.

**3. Anchor terms, sources, known items.**

- **`anchor_terms`**: 2–5 short lower-case substrings, at least one of which any on-topic paper contains in its title
  or abstract. Papers that match none are flagged `NO-ANCHOR` and sorted last — a triage aid, not a filter. Choose
  stems that mark *your corner* of the field (`onboard`, `lossless`, `rice`), not one every hit contains.
- **`sources`**, from the topic — the union of the rows a topic straddles:

  | Topic signal | `sources` |
  |---|---|
  | biomedical / neuro / clinical | `semantic_scholar, openalex, pubmed, scopus` |
  | pure ML / CV / signal processing | `semantic_scholar, openalex, arxiv, ieee` |
  | engineering / hardware / communications | `semantic_scholar, openalex, ieee, scopus, wos` |
  | unclear | `semantic_scholar, openalex, arxiv` (the three keyless ones) |

  A source whose key is missing is skipped and reported. Keyless Semantic Scholar is rate-limited most days: keep it
  (dense retrieval and the snowball's similar route use it) but do not count on it.
- **`known_items`**: papers any expert expects this search to find — the anchor tools' own papers, the papers the
  topic file names, the field's standard benchmark paper. At least two from standard depth, each with a `why`. They are
  the only recall test with a known answer: the probe checks that each exists in a database (an item no database has
  is usually invented — fix or drop it); A2.c checks that the search retrieved them; A2.s seeds dense retrieval with
  them.

**4. Scope probe (standard, deep).** Up to three trial queries (primary, loosen, anchor-methods; `--queries` to
choose) at 10 hits each, OpenAlex's total count per query (the order-of-magnitude yield), and a lookup of every known
item. It changes nothing that bias control protects — no screening, no synthesis, and **its hits never enter the
collection** (they stay in `_state/probes/A1q/`). It catches a query that returns nothing or tens of thousands, and an
invented known item. The probe records which strategy it answered: re-running `set-strategy` with unchanged queries
keeps it; a changed query drops it and `frame check` asks for a new probe.

Then print the pre-run estimate, one line per fact, and continue without waiting:

```
depth=standard | variants=5 × sources=4 | OpenAlex total for the primary ~2,140 | search ~3-7 min
fulltext: up to 20 PDFs (expect ~1/3 lost to paywalls), pdf2md ~1-2 min/paper → ~20-40 min
Pass M: 1 row per abstract-only paper + 1-4 per full text; ~5 subagents ≈ 5 min, ~0.5M tokens
generations=3 → research cycle runs 3×
```

**5. The draft.**

```json
{"queries": [{"id": "Q1", "strategy": "primary", "axes": {"C1": "all", "C2": "all"},
              "flat_query": "EEG automated artifact rejection", "rationale": "both search axes, every synonym"},
             {"id": "Q3", "strategy": "loosen", "axes": {"C2": "all"}, "flat_query": "automated artifact rejection",
              "rationale": "recovers method papers validated on MEG and EEG together"}],
 "dropped_terms": [], "anchor_terms": ["eeg", "electroenceph", "artifact", "artefact"],
 "sources": ["semantic_scholar", "openalex", "pubmed", "scopus"],
 "known_items": [{"title": "Autoreject: Automated artifact rejection for MEG and EEG data", "why": "the anchor pipeline"}]}
```

**6. After the search: revise, never re-set.** `set-strategy` refuses once `step2_raw_papers.json` exists (the
strategy already in step0, sent again, is accepted and writes nothing: it re-records A1.q). A2.c changes
a query with `frame query-revise` — `{"retire": "Q4", "add": {…new query, new id…}, "reason": "…", "round": 1}` — which
retires the old query (its papers stay in the collection), adds the replacement and logs both in `queries_history` and
the deviation log; a missing synonym goes in with `frame add-terms` (add only), an ambiguous term goes out with
`frame retire-terms` (kept in the protocol as written, marked retired, no longer rendered), and anchor terms of a
reading the protocol has since given up go out with `frame anchors-revise` — `{"anchor_terms": [...], "reason": "…"}`
(Q14 still applies; logged in `queries_history` with the old and the new terms; §15 G2). All four are declared
revisions of A1, not a new protocol: they make neither A1.q nor the evaluation stale — only the searches they change
(anchors: the merge, which recomputes `anchor_match`).

### Outputs
step0 `queries` (with `boolean_query`, `flat_query`), `dropped_terms`, `anchor_terms`, `sources`, `known_items`,
`strategy_basis` (the protocol it was built on), `scope_probe`; probe answers in `_state/probes/A1q/`.

### Done when
`frame check --unit A1.q` passes: variants per depth, term coverage, flat-query length and vocabulary, one anchor per
anchor-methods flat query, anchor terms, sources, known items, a probe for the current strategy, built on the current
protocol (Q01–Q03, Q11–Q21).

### When something fails
The scholar server down during the probe: `scope_probe.skipped` records why, the search still runs, and the missing
yield estimate is reported at Finish. A known item no database has: fix or drop it. A1.p with errors: `set-strategy`
refuses.

### Commands
```bash
$PY $SK/scripts/ideate_tools.py frame set-strategy $RD $RD/_state/A1/strategy.json
$PY $SK/scripts/mcp_bridge.py probe $RD [--queries Q1,Q4]
$PY $SK/scripts/ideate_tools.py frame query-revise $RD revision.json        # after the search, from A2.c
$PY $SK/scripts/ideate_tools.py frame add-terms $RD terms.json              # after the search, from A2.c:
#   {"axis": "C2", "terms": ["..."], "reason": "...", "evidence": "...", "round": 1}
$PY $SK/scripts/ideate_tools.py frame retire-terms $RD retire.json          # the same shape; an ambiguous term
$PY $SK/scripts/ideate_tools.py frame anchors-revise $RD anchors.json       # after the search, from A2.c; then merge
```

---

<a id="a1e"></a>
## A1.e — protocol evaluation

### Purpose
Have a reader who did not write the protocol judge whether it is fit to search with. The main session wrote it, so the
same blind spot that wrote it would pass it; Kitchenham (§5.5) asks for an independent expert — here a subagent that
reads only the topic file and `step1_protocol.md`.

### Inputs
The topic file and the view `step1_protocol.md` (A1.p and A1.q pass).

### Method
1. `frame eval-brief $RD` renders the view and writes `_state/A1e/brief_r{n}.md` (it prints the path): the two files,
   the five checks, the JSON to return.
2. Spawn one subagent (same model tier as the main session) with only: *"Read `<brief path>` and do exactly what it
   says. Return only the JSON object."* No summary of the topic or of your reasoning: the reader must not inherit your
   framing.
3. Save its reply verbatim to `$RD/_state/A1e/round_{n}.json` and store it with `frame set-evaluation`.

The checks: **E1** the search follows from the question (every concept an axis, synonyms expanded, the anchor
searched, no scope creep, sources fit); **E2** the criteria follow from the slots and outcomes and are applicable;
**E3** the frame fits the question's semantics, no invented slot; **E4** recall risks (missing spellings, a timeframe
that cuts off the baselines, an unnamed anchor, implausible known items); **E5** completeness; **E6** readings — a
criterion that rests on one reading of a word in the topic with another plausible reading ("elderly": aged 65 or
over, or frail at any age) gets a note naming the `criterion`, the `word` and the `alt_reading` (E06 when
one is missing). The **exclusion** criteria the final round names under E6 are **soft** in A3: a paper violating only
them under the protocol's reading while meeting them under the other one, and included without them, is kept at the
borderline instead of excluded; an inclusion criterion named under E6 stays a note (inclusion criteria define the
topic). Any other criterion whose text holds the same word is **linked** and read the same way in A3 — without that, a
soft EX1 changes nothing when IN1 turns on the same word (`it_frame.soft_criteria` → `linked`; A3 reads them through
the view `soft_criteria`, whose hash leaves `linked` out: it follows from the criteria A3 already reads).
A round stored before E6 (no `checks` field) is judged on E1–E5 and makes nothing soft.

Verdicts: `approved` · `approved-with-notes` · `revision-required`. Each failed check is `improvable` (edit one
component) or `blocking` (the question is misframed), with `fix_target` A1.p or A1.q.

**One forced revision, then go.** A `revision-required` round 1 means: fix every failed finding in A1.p / A1.q, then
round 2 (a fresh brief listing the round-1 findings). If round 2 still asks for revision, the tool finalizes the
evaluation as `accepted-with-doubts` and the unresolved findings become caveats of the search — no loop, no human
checkpoint; the doubt is recorded instead.

### Outputs
`step1_protocol_evaluation.json` (rounds, each with the protocol and strategy hashes it judged; `final.status`) and its
view `step1_protocol_evaluation.md`.

### Done when
`frame check --unit A1.e` passes (E01–E05): a final status that is not `pending-revision`, on the current protocol and
strategy — a protocol edited after its last round is stale and evaluated again.

### When something fails
Malformed JSON from the subagent: fix the format once, then ask again. Round 2 still asks for revision:
`accepted-with-doubts`, findings reported at Finish. A1.p / A1.q with errors: the brief is refused.

### Commands
```bash
$PY $SK/scripts/ideate_tools.py frame eval-brief $RD
$PY $SK/scripts/ideate_tools.py frame set-evaluation $RD $RD/_state/A1e/round_1.json
$PY $SK/scripts/ideate_tools.py frame check $RD                     # every A1 check; exit 1 on an ERROR
```

---

<a id="a1v"></a>
## A1.v — context for Stage B

### Purpose
Record where the work could be published, whose expertise it draws on, and what this machine has — the inputs the
persona and the journal recommendations need. It is not a search decision; Stage A writes it because it runs first.

### Inputs
The topic file; the local file system and interpreter.

### Method
Write `$RD/_state/A1/context.json` with:

- **`target_venues`**: 2–4 plausible venues from the topic's nature (workshop call, main-conference topic,
  journal-style problem). This one list feeds both the persona's "targeted at …" line and the journal
  recommendations, so they cannot contradict each other.
- **`expert_domain`**: e.g. "EEG signal processing and BCI decoding" (the persona's specialisation).
- **`local_environment`** — look before planning; ideas are only useful if their experiments can run *here*:
  `artefacts` (local code and data paths the topic file names — open them; a topic that points at its C source is a
  different topic once you have read it), `cached_data` (`~/mne_data`, `~/.cache/torch`, `~/.cache/huggingface`,
  `~/scikit_learn_data`), `packages_present` / `packages_missing` (a quick `$PY -c "import x"` for the two or three
  libraries the experiments would lean on). Empty lists are fine — they say you looked.

### Outputs
step0 `target_venues`, `expert_domain`, `local_environment`.

### Done when
`frame check --unit A1.v` passes (V01). A1.v is not required by the search gate.

### When something fails
This is prose for the persona. Stage B's gates read `local_environment.probe` (written by `env-probe --write` at each
generation), never this text, because Stage A may be weeks old; `set-context` never touches `probe`.

### Commands
```bash
$PY $SK/scripts/ideate_tools.py frame set-context $RD $RD/_state/A1/context.json
```

---

## Sources of these rules

| Rule | Source |
|---|---|
| protocol before results; protocol evaluation | Kitchenham, B. & Charters, S. (2007). *Guidelines for performing Systematic Literature Reviews in Software Engineering*, §5.4–5.5 |
| scoping vs systematic review | Munn, Z. et al. (2018). *BMC Medical Research Methodology* 18:143 |
| PRISMA-ScR | Tricco, A.C. et al. (2018). *Annals of Internal Medicine* 169(7):467–473 |
| PRISMA-S (reporting the search) | Rethlefsen, M.L. et al. (2021). *Systematic Reviews* 10:39 |
| frameworks (PICO, PECO, PCC, SPIDER, PICo, CIMO) | Richardson 1995; Peters et al. 2020 (JBI); Cooke, Smith & Booth 2012; Denyer, Tranfield & van Aken 2008 |
| axis construction, searchability test, recall variants, Boolean + flat rendering | `rsrch-P1-specify-rq/references/query_construction.md` and `rsrch-P2-develop-protocol/references/framework_decision.md` (forecasting_the_brain), for a run without human checkpoints |
