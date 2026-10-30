# A3 screen — decide what belongs

**Screening** is the third phase of the literature search ([README.md](README.md)): one decision per candidate paper —
does it belong, and if not, under which criterion is it excluded. It runs twice: on the search collection, and again
on A5's additions (incrementally — only unscored papers are batched).

| Unit | Decides | Writes (through the tool only) |
|---|---|---|
| [A3.b bibliometrics](#a3b) | nothing — it measures citations, venues and the collection's own citation links | `step3_bibliometrics.json` |
| [A3.g gate](#a3g) | which records are not research papers in the protocol's languages | `step3_gate.json` |
| [A3 scoring and build](#a3) | whether each paper belongs, its tier and its reading roles | `screening_scores.json`, `step3_shortlist.json`, `step3_screening_results.md` |

Whether a paper is in scope and how much attention it deserves are different questions. Relevance and quality are
**judged** from what the paper says; impact is **measured** from citations and venues; impact never decides inclusion
on its own.

`screen-build` refuses before `a2-check` passes and writes nothing while any A3 check fails; `snowball` (A5) and
`export` (A4) refuse before A3 passes.

---

<a id="a3b"></a>
## A3.b — bibliometrics

### Purpose
Measure, for every candidate, the facts the gate and the impact axis need — type, retraction, language, citations,
venue — and the citations among the candidates themselves; and find the abstract a record came without, so that it
is not judged on its title alone.

### Inputs
`step2_raw_papers.json` and, once A5 has run, `step2b_snowball_papers.json`.

### Method
From OpenAlex in batches of 40 (by DOI, else by OpenAlex id) and from Scopus through the scholar server's
`scholar_venues`:

- **type**, **retraction**, **language** — for the gate;
- **citations**: the count, the **field- and year-normalised percentile** (OpenAlex), the **velocity** (mean of the
  last two complete years), the yearly counts;
- **venue**: name and type, **SNIP** (Scopus; corrects for the field's citation habits, which suits a topic that crosses
  fields), SJR, and OpenAlex's two-year mean citedness (computed like an impact factor) as the fallback for journals
  without SNIP. The Clarivate Journal Impact Factor is a paid product and is not used;
- **the collection's own citation links**: how many candidates cite this paper (`in_degree`) and how many it cites
  (`out_degree`) — being cited by other on-topic papers says more about standing in *this* field than a global count;
- the paper's **reference list** (OpenAlex ids), the **full author list** and the **publication date** — A5 counts the
  references, A4.k mints keys from the full author list, the report reads its citation graph from here;
- **the abstract a record lacks** (§15 G3: in s20v2, 19 % of the scored records had none and a scorer filled the gap
  from memory) — OpenAlex's own (`abstract_inverted_index`, in the same batches), else Semantic Scholar's by DOI or S2 id
  (`scholar_abstracts`, one batch request per 100, on the shared S2 clock). Only text that `has_abstract` accepts is
  kept (OpenAlex's index is often an author list), as `abstract_fill {text, source}`; a fill from an earlier A3.b run is
  kept without asking again. Scoring, its checks and the shortlist read the filled text (`abstract_filled_by`); the step2
  files are never changed.

**Impact** (1–5) = `1 + 4 × value`, where value = 0.7 × the normalised citation percentile + 0.3 × the in-collection
citation percentile. A paper **younger than two years** has had no time to be cited: half of its value comes from its
venue's percentile; at two years a quarter; from the third year none. A paper without a venue metric (a preprint, a
conference paper) gets the neutral venue value — never a penalty.

### Outputs
`step3_bibliometrics.json` (schema `ideate-bibliometrics/1`): one record per candidate, the computed `impact`, the
`abstract_fill` where one was found, the counts `abstract_fill {lacking, openalex, semantic_scholar, still_missing}`, the
basis (hashes of the candidate files), caveats (`abstract-fill` with the counts).

### Done when
`a3-check --unit A3.b` passes (B01–B03): every candidate has a record, built on the current candidate files.

### When something fails
A paper with no OpenAlex record is scored impact 3.0 (caveat `no-metadata`). Without `SCOPUS_API_KEY` there is no SNIP:
journals fall back to OpenAlex's two-year mean citedness, everything else is neutral. A failed batch leaves its papers
without metadata. Semantic Scholar's abstracts unavailable (rate limit, preflight says down): those records are judged
on the title (caveat `abstract-fill-partial`).

### Commands
```bash
SK=.claude/skills/ai-scientist-ideate; PY=<interpreter with mcp>; RD=<topic>_research
$PY $SK/scripts/mcp_bridge.py bibliometrics $RD
```

---

<a id="a3g"></a>
## A3.g — gate

### Purpose
Exclude, before any token is spent, the records that are not research papers in the protocol's languages.

### Inputs
`step3_bibliometrics.json`; `protocol.languages` (default `["en"]`).

### Method
Codes from the bibliometrics alone:

- **X-RET** retracted;
- **X-TYPE** not a research report (editorial, erratum, retraction notice, paratext, letter, peer review, grant,
  supplementary material, guide, reference entry);
- **X-LANG** a language the protocol does not keep — **unless the abstract itself is in English**: OpenAlex's language
  describes the full text, and a Dutch or Chinese journal article with an English abstract already says what was done;
  its record keeps `abstract_english: true` for the full-text step.

Articles, preprints, reviews, chapters, books, theses, reports and datasets pass — recall first. Missing metadata
passes.

### Outputs
`step3_gate.json`: one entry per excluded paper with its code and detail.

### Done when
`a3-check --unit A3.g` passes (G01–G03): the gate equals its recomputation on the current bibliometrics.

### When something fails
No bibliometrics: stop (run A3.b).

### Commands
```bash
$PY $SK/scripts/ideate_tools.py screen-gate $RD
```

---

<a id="a3"></a>
## A3 — scoring and build

### Purpose
Decide for every paper past the gate whether it belongs — from what its title and abstract say, quoted first and
judged second — and build the shortlist: composite, inclusion, tiers, exclusion reasons and reading roles.

### Inputs
The candidates past the gate; the protocol's slots, outcomes and criteria; `step3_bibliometrics.json` (build only —
never shown to the scorers); the SPECTER2 vectors (novelty).

### Method

**1. Batches.** `screen-plan` writes a brief and batches of up to 60 unscored papers. A batch holds only
`id, title, abstract, year, flags` — **no journal, no citation counts, no similarity**: the scorer judges what the
paper says, not where it appeared or how famous it is. The brief carries the protocol's slots, outcomes and criteria
with their ids. Spawn one subagent per batch, same model tier as the main session, with only the brief's and the
batch's paths: *"Read `<brief.md>` and `<batch_k.in.json>`; write `<batch_k.out.json>`."* `screen-merge` stores the
answers with their batch and model; papers left unanswered go into new batches the next time `screen-plan` runs.

**2. Evidence first.** For each paper, before any number, the scorer copies verbatim from the title or abstract (two
words or more, or the literal `not stated`): `problem`, `method`, `data`, `code`. The tool checks every quote against
the text, ignoring case, punctuation and spacing. The scorer judges the text of the batch only — never what it knows
about the work from elsewhere. A relevance of 3 or more needs a quoted problem and method (a paper without an abstract:
the problem, from the title, and a rationale starting `no abstract:`, C18; a title that may be on topic but does not
settle it: relevance 3, `"needs_text": true` — the shortlist marks it for A6 to read in full first). **No abstract**
(flag NO-ABSTRACT, after A3.b's fill) also covers an abstract field that
holds something else: the citation (authors and venue), a bare author list, repository boilerplate ("International
audience", "status: Published"), a table of contents — text with almost no lower-case words; text mostly in another
script is left to the scorer (`has_abstract`). An abstract that plainly belongs to **another paper** is flagged by the
scorer, `"record_problem": "abstract-mismatch"`: the paper is then judged on its title alone (quotes from the title, the
no-abstract rule), and an exclusion of it is recorded as `X-REC` — A6's full text can rescue it. Then the two judged
axes (1–5), with the anchors of the brief:

- **relevance to the protocol** — against every slot and outcome, not only the idea in mind;
- **methodological quality** — what the abstract reveals; reviews by systematic rigour; preprints not penalised.

A paper that violates an exclusion criterion is answered with `"violates": ["EX1"]`, one that meets no inclusion
criterion with the inclusion criteria it fails (`"violates": ["IN1"]`, not a low relevance score), and a rationale —
no scores. A **soft** criterion is one A1.e's E6 says rests on one reading of a word in the topic (only exclusion
criteria can be soft); a criterion whose text holds the same word is **linked** and read the same way (q032: IN1 and
EX1 both turn on "low-resource language"). For each soft or linked criterion a paper fails under the protocol's reading,
the scorer judges the other reading too (§15 G1):

- it **meets** the criterion under the other reading → `"soft_violates": {"EX1": "<how>"}`, scored as if the criterion
  were absent, kept if it would be included without it;
- it **fails both** readings → an ordinary `"violates": ["EX1"]`; when every criterion in `violates` is soft or linked,
  with `"both_readings": {"EX1": "<why>"}`.

Either form needs its reason (C16): an English-only paper is not "soft" under an EX1 whose two readings both exclude
English. Entries from batches before this brief (no `brief: 2`) keep the old rule (a list, no reasons); `screen-plan
--rescore soft` reads them again. Duplicates: `duplicate_of`, with `carry` for the identifiers of a
dropped open-access copy (copied onto the kept record in the shortlist, never into the A2 files). Every rationale is
that paper's own: a rationale shared word for word by two papers of relevance 3 or more is refused — a rule that
scores a family of papers is not a judgement.

**3. Bulk rules** clear obvious noise in one stroke (`{"title_regex": ..., "rel": 1, ...}` in the scores file), but they
may only give relevance ≤ 2 and only touch papers that contain no anchor term **and** sit in the bottom quarter by
semantic similarity (`sem_pct` < 25) — a close paper written in other words is never cleared unread.

**4. Criteria amendments.** The criteria are A1.p's. A family of papers nobody foresaw may need one changed:
`screen-amend $RD amendment.json` (`{"change": "...", "reason": "...", "refs": ["EX2"]}`) records it beside the
criteria; the protocol itself is not edited. Papers already scored under the old wording may need another look.

**5. The build** (`screen-build`):

- composite = relevance × 0.50 + quality × 0.30 + **impact (A3.b)** × 0.20, the arithmetic written out per paper;
- included when composite ≥ 3.00 — snowball and dense-only papers also need relevance ≥ 3: no query matched them, and
  a high composite from quality and impact alone admits widely cited toolboxes;
- tiers: ≥ 4.50 core · 4.00 strong · 3.50 contextual · 3.00 borderline (included);
- a paper with `soft_violates` that would be included without the soft criteria (composite ≥ 3.00 on its own
  relevance) is included at tier 4, its composite computed on relevance ≤ 2 (it ranks low,
  and the arithmetic says why); the results file lists the soft criteria, their linked criteria and how many papers
  they kept; more than 25 % of the shortlist kept this way is a WARN (C20) — look at a few;
- **exclusion reasons as codes** — `X-RET`, `X-TYPE`, `X-LANG`, the criterion (`EX1`…), `SCORE` (composite below
  3.00), `FLOOR` (a snowball / dense paper below relevance 3), `DUP`, `X-REC` (judged on the title because the abstract
  was another paper's; the detail keeps the underlying code) — counted per code in the results: the PRISMA screening
  box;
- **novelty**: 1 − the highest similarity to any paper ranked above it (SPECTER2 vectors) — used only for the roles,
  never for inclusion: a near-copy of a better paper is exactly the prior work a novelty claim must face;
- **reading roles**, by rule:

  | Role | Rule | Used by |
  |---|---|---|
  | foundational | relevance ≥ 4 and (in-collection citations in the top 20 %, or normalised citations ≥ 0.9 and three years or older) | A5 forward seeds |
  | core-method | relevance ≥ 4 and (quality ≥ 4, or code available and quality ≥ 3) | A5 forward and similar seeds |
  | emerging | relevance ≥ 4, two years old or younger, and (velocity in the top 30 % or novelty in the top 20 %) | A5 similar seeds |
  | survey | an OpenAlex review, or citing ≥ 5 candidates and in the top 10 % for that | the report's Hubs |
  | supporting | none of the above | — |

  A paper can hold several roles. The roles change no inclusion.

### Outputs
`screening_scores.json` (schema `ideate-scores/2`; `superseded` keeps the entries a rescue replaced, `withdrawn` those
of works an A5 redo dropped), `step3_shortlist.json` (schema `ideate-shortlist/2`: summary +
included papers with `screening`, `impact`, `novelty`, `roles`), `step3_screening_results.md` (criteria and
amendments, tiers with the arithmetic, exclusions by code). `citation_key` on the shortlist belongs to A4.k.

### Done when
`a3-check --unit A3` passes (C01–C18, O01–O02; C19–C20 warn): every candidate past the gate has exactly one entry,
merged through `screen-merge` from the batch that held it; scores in range with verbatim evidence and a paper's own
rationale; exclusions name protocol criteria, soft and linked criteria are judged under both readings with a reason
(C16); a `record_problem` is a known kind (C17); a NO-ABSTRACT paper at relevance 3+ says `no abstract:` (C18); an entry
scored before A3.b found its abstract is a WARN (C19: `screen-plan --rescore filled`); bulk rules never admit; amendments,
rescues and rescores carry a reason; a person's
include / exclude is applied and backed by an override; only a work the snowball dropped is withdrawn; the shortlist
equals its recomputation on the current collection.

### When something fails
A subagent that does not answer, or answers part of its batch: `screen-merge` lists what is missing and `screen-plan`
batches it again. An answer that fails on its own (a quote not in the text or under two words, a score out of range, a
criterion the protocol does not have) is refused at `screen-merge` — kept under `refused` with its batch and reason —
and the paper is batched again, so one bad entry never holds up the rest. Evidence that is not in the text is refused. Without SPECTER2 vectors, novelty and the emerging
role's novelty test are skipped. Any failing check at build: nothing is written. Fewer than 10 included papers: every
gap and idea from this base is preliminary.

### Commands
```bash
$PY $SK/scripts/ideate_tools.py screen-plan $RD [--size 60] [--rescore soft] [--rescore filled]
#   one subagent per batch: "Read <brief.md> and <batch_k.in.json>; write <batch_k.out.json>"
#   --rescore: also batch entries to read again (an old-rule soft entry; one scored before its abstract was found);
#   the answer supersedes the earlier entry (kept under `superseded`), a refused answer leaves it in place
$PY $SK/scripts/ideate_tools.py screen-merge $RD
$PY $SK/scripts/ideate_tools.py screen-amend $RD amendment.json          # only when a criterion must change
$PY $SK/scripts/ideate_tools.py screen-rescue $RD <id> --reason "..."    # a second reading, asked for later
$PY $SK/scripts/ideate_tools.py screen-build $RD $RD/screening_scores.json
$PY $SK/scripts/ideate_tools.py a3-check $RD                             # every A3 check; exit 1 on an ERROR
```

---

<a id="rescue"></a>
## Rescuing a paper later

### Purpose
Give an excluded paper a second, blind reading when a later step has a reason to think it belongs — typically Stage B,
whose angle hinges on an outcome the paper bears on (`list-papers --file excluded --grep "<words>"`).

### Method
1. `screen-rescue $RD <id> --reason "<why it may belong>" --by gen_k` writes a one-paper batch. The scorer sees the
   paper as in any batch — no journal, no citations, not the earlier reading — plus the reason it is asked again.
   Mechanical exclusions (X-RET, X-TYPE, X-LANG) and duplicates are refused: a retraction, a record type, a language or
   a duplicate is a fact, not a judgement.
2. One subagent answers it with the usual brief: *"Read `<brief.md>` and `<batch_k.in.json>`; write
   `<batch_k.out.json>`."*
3. `screen-merge` puts the new answer in place and keeps the earlier entry under `superseded`; `screen-build` then
   decides inclusion by the usual rules, and `step3_screening_results.md` lists the paper under "Read again on
   request" with the outcome.
4. Included: `export` mints its key (no other key changes), `mcp_bridge.py bibliography` rebuilds the `.bib`,
   `fulltext-status` gives it an `access_level`. In the knowledge base, add it to the relevant Plane's
   `member_papers` in `knowledge_cards.json` and give it a methods-matrix row (an abstract row in a new file under
   `knowledge/methods_batches/`, or full-text rows if you fetch it); then `build-methods`, `build-cards` and
   `concept-index`.
5. Still excluded: it is not cited. Name it in `Related Work` or `Risk Factors` as excluded at screening, with its id
   and exclusion code.

### Done when
`a3-check --unit A3` passes, including C12: every rescue names its reason, every superseded entry is kept and has a
current rescue pointing at it — entries change only through `screen-rescue` and `screen-merge`.

### Commands
```bash
$PY $SK/scripts/ideate_tools.py screen-rescue $RD paper_123 --reason "bears on O2, which this idea hinges on" --by gen_3
#   one subagent: "Read <brief.md> and <batch_k.in.json>; write <batch_k.out.json>"
$PY $SK/scripts/ideate_tools.py screen-merge $RD
$PY $SK/scripts/ideate_tools.py screen-build $RD $RD/screening_scores.json
$PY $SK/scripts/ideate_tools.py export $RD
$PY $SK/scripts/mcp_bridge.py bibliography $RD
$PY $SK/scripts/ideate_tools.py fulltext-status $RD
```
