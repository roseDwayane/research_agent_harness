# A2 search — run the queries

**Search** is the second phase of the literature search ([README.md](README.md)). It sends A1's queries to every
chosen database in the form each one parses, turns every answer into one candidate collection, and judges whether the
databases were asked well.

| Unit | Decides | Writes (through the tool only) |
|---|---|---|
| [A2.s retrieval](#a2s) | nothing — it records what each database answered | `step2_queries/<id>@<hash>.json` |
| [A2.m merge](#a2m) | which records are the same paper | `step2_raw_papers.json`, `step2_search_summary.md`, `_state/paper_ids.jsonl` |
| [A2.c relevance check](#a2c) | whether each query asked well | `step2_relevance_check.{json,md}` |

`mcp_bridge.py search` refuses to start before A1.p, A1.q and A1.e pass; `screen-build` refuses before `a2-check`
passes. Every network answer is recorded under `$RD/_state/net/`; `IDEATE_REPLAY=1` replays a run from those
recordings without touching the network (and fails on a request it has no recording for).

---

<a id="a2s"></a>
## A2.s — retrieval

### Purpose
Ask every chosen database every active query, in the form that database parses, and keep a complete record of what was
sent and what came back.

### Inputs
step0 `queries`, `sources`, `protocol` (axes, timeframe), `known_items` resolved by the scope probe.

### Method

**1. One instance per query.** The query, rendered for each source, sent once per form, every attempt written down. An
instance is named `<query id>@<hash>`; the hash covers what was sent (the rendering, the year window, the limit, each
source's result order), so a
query whose rendering changes is a new instance and the old file stays as the record of what was asked.

**2. Each source gets the form it parses.**

| Source | Form | Note |
|---|---|---|
| PubMed, Scopus, IEEE Xplore, Web of Science | Boolean (`boolean_query`) | the server wraps Scopus in `TITLE-ABS-KEY()`, WoS in `TS=()` |
| OpenAlex | Boolean without truncation | its title-and-abstract field is stemmed and refuses `*`; stemming covers the variants |
| arXiv | arXiv syntax rendered from the axes: `(all:EEG OR all:"scalp recording") AND (…)` | passed through by the server untouched |
| Semantic Scholar | flat (`flat_query`) | its search parses no Boolean |

Each source returns up to **50** records per query (Scopus pages through 25 at a time) and reports its **total** hit
count; both go into the instance, because 25 taken from 25 and 25 taken from 4,300 are different searches. Every source
is asked for its results **by relevance** (`SOURCE_ORDER`; PubMed Best Match, Scopus `relevancy`, IEEE's default), so
a capped query takes the most relevant records of its total, not the most cited ones — the cited classics the search
misses come back through A5's backward route.

**3. Routing.** A `recent` variant goes to arXiv, OpenAlex and Semantic Scholar, the sources that carry last year's
preprints; every other variant goes to every chosen source. A query's own `sources` (A1.q) overrides this.

**4. Retries.** A flat query a source answers with 0 is retried once with its first four content words. A source
rate-limited on two queries running is benched for the rest of the run; benched and rate-limited pairs get one delayed
retry at the end. A source that still fails is recorded as failed and never waited on again.

**5. The dense instance D1 (standard, deep).** Keyword search misses papers written in other words. D1 asks Semantic
Scholar's recommendation service for up to 50 embedding neighbours of the **known items the scope probe resolved** —
the only papers known to be relevant before any screening, which is why D1 runs with the search. It is recorded like a
query (`found_by: D1`). A paper only D1 found was never matched against the protocol's wording, so at screening it
needs relevance ≥ 3, like a snowball addition.

### Outputs
`step2_queries/<id>@<hash>.json`: per source the string sent, filters, the result order, attempts, records returned,
the reported total, errors.

### Done when
`a2-check --unit A2.s` passes (S01–S05): every active query and D1 has a complete instance for its current rendering.

### When something fails
- A source rate-limited or down: benched, retried once, then recorded as failed (caveat `source-failed`; a source no
  query got an answer from is `source-dead`, must-disclose).
- A key missing or inactive: that source is skipped and reported.
- D1 without a Semantic Scholar key (`SEMANTIC_SCHOLAR_API_KEY` in `mcp/scholar_mcp/.env`): usually rate-limited;
  recorded as skipped (caveat `dense-skipped`) and the search goes on.
- Every query failed on every source: stop.
- The scholar server unusable: `python3 .claude/skills/ai-scientist/scripts/s2_search.py "<flat query>" --limit 10
  --no-sort` per query, each answer written as an instance of the same shape (`kind: query`, one attempt per source
  with `sent_query`, `at`, `filters`, `returned`), then `mcp_bridge.py merge`; record that the search was degraded.

A complete instance for the current hash is not run again (`--force` runs it again); an interrupted one is.

### Commands
```bash
SK=.claude/skills/ai-scientist-ideate; PY=<interpreter with mcp>; RD=<topic>_research
$PY $SK/scripts/mcp_bridge.py search $RD                 # A2.s for every active query (+ D1), then A2.m
$PY $SK/scripts/mcp_bridge.py search $RD --only Q7       # a revised query only (A2.c)
```

---

<a id="a2m"></a>
## A2.m — merge

### Purpose
Turn all instances into one collection in which every paper appears once, keeps a stable id, and records every query
that found it.

### Inputs
Every instance of every query in step0 — **active and retired** (a revised query's papers stay), the latest and the
ones it superseded (a query asked again under another rendering or result order: what only the old instance found
stays) — and the latest of D1;
`_state/paper_ids.jsonl`; `anchor_terms`; the protocol (for `sem_sim`).

### Method

**1. Merge deterministically**, in this order:
1. a shared **DOI** (including `alt_dois`);
2. a shared **arXiv id** (also read from DataCite DOIs `10.48550/arXiv.*`) — a preprint and its journal version are
   one paper, and the journal record's metadata is kept;
3. a **fuzzy title** match: word-set Jaccard ≥ 0.85, the same first-author surname (or none), years at most one apart;
4. an identical normalised title.

A merged paper keeps **every** query that found it (`found_by`, in order; a superseded instance is named
`<id>@<hash>`; `found_via` = the first current query, or `dense` for a D1-only paper) and the number of records it
absorbed (`merged_from`). A2.c judges a query on its latest instance only; caveats describe the latest instances.

**2. Ids** come from the append-only registry `_state/paper_ids.jsonl`: a known paper keeps its id (matched by DOI,
then arXiv id, then normalised title), a new one gets the next number, and the registry records which Unit minted
each id (A2.m here, A5 for snowball additions). An id is never reused.

**3. Enrichment.** An arXiv record without a DOI gets the published version's DOI from Semantic Scholar when a key is
set (and the preflight does not find S2 down), and otherwise its own DataCite DOI `10.48550/arxiv.<id>` (`doi_source:
arxiv`, caveat `doi-recovery-skipped`): keyless, one rate-limited lookup per record stalls a merge for many minutes.
One OpenAlex request per 40 DOIs fills a missing abstract, the OpenAlex id and the open-access link (`oa_url`, used
later for full text).

**4. Computed fields:** `anchor_match`, `has_abstract`, `code_hint` (a repository link or "code is available" in the
abstract), `retired_only`, `superseded_only`.

**5. Semantic similarity.** `sem_sim` is the cosine between the paper (title and abstract) and a description of the
protocol built from its slots, outcomes and search terms, computed with the fixed local model `allenai/specter2_base`
(revision recorded in the summary) on the CPU, so the same text always gives the same vector; vectors are cached under
`_state/embeddings/`, so a re-merge embeds only new papers. The raw cosine of this model sits in a narrow band, so every
rule reads **`sem_pct`**, the paper's percentile in the collection: "semantically close" is the top quarter.

**6. The summary** (`step2_search_summary.md`) carries PRISMA's **identification** counts — records retrieved per
database and the sum of the totals each reported — the merges by rule, the caveats, and each query's per-source result
with the exact string sent.

### Outputs
`step2_raw_papers.json` (schema `ideate-raw/2`: `search_summary` + `papers`), `step2_search_summary.md`, A2.m's
entries in `_state/paper_ids.jsonl`.

### Done when
`a2-check --unit A2.m` passes (M00–M07): written by this merge, built on the current instances, every id from the
registry, merges and computed fields as recomputed; a paper outside the protocol's timeframe — a source that ignored
the year filter — is a warning (M07).

### When something fails
A failed OpenAlex batch is counted; those abstracts stay missing. Without the SPECTER2 model in the Hugging Face cache
the summary says "sem_sim not enabled" (the tool never downloads it). No instance to merge: stop.

### Commands
```bash
$PY $SK/scripts/mcp_bridge.py merge $RD                  # the merge alone (search runs it already)
```

---

<a id="a2c"></a>
## A2.c — relevance check

### Purpose
Judge whether each query **asked well** — not whether the collection is big: 29 papers of which 3 are relevant is a
failed search — and repair the queries that did not, within a fixed number of rounds.

### Inputs
`step2_raw_papers.json`, the instances, step0 `queries`, `known_items`, `protocol` (axes, outcomes).

### Method

**1. Signals.** `search-check` computes and prints, per query: papers, papers no other query found, the share
containing an anchor term, each source's returned / total, and why the query **may not be judged ok** if it cannot.
Below that: known items found / missing, papers per outcome, D1's share, the largest overlaps between queries, the
share of new papers the latest re-plan round brought, and the **vocabulary feedback** — papers in the top quarter by
`sem_sim` that contain no anchor term, and the words they share that no axis has. An empty list is a result ("no
missing synonym detected"). Its mirror image is the **ambiguous-term signal** (`term_pull`): for every term of a search
or contrast axis, the papers that axis matched through that term alone, and how many of them sit in the bottom quarter
by `sem_sim`. A term is flagged when at least **5** papers are its own catch and at least **half** of them are that far
— a quarter of any collection is, so half is a term pulling in what the protocol does not mean ("automated cleaning" →
solar panels). It also says which queries bring the far papers and which the near ones: a term can be loose only in a
`loosen` variant (the axis asked without the population) and precise wherever it is ANDed with it.

**2. Verdicts.** Judge every active query `ok`, `replan` or `accept-weak`, with a reason for the last two. Read titles,
not abstracts — this is about the query, not an early screening. A query **cannot be ok** when it found no paper, when
fewer than half of its papers contain an anchor term, when an anchor it names appears in no paper, or when its last
run used an older rendering. Every known item missing from the collection needs an action (`replan Q3`, `add-terms`
or `accept-weak`) and a reason — a missing known item is the one recall failure with a known answer. Every flagged
term needs an answer, `keep` or `retire`, with a reason. Keep it when the near papers it alone brings are ones the
protocol wants and the far ones come from one loose query — A3 drops them (no anchor, low `sem_pct`), retiring would
lose the near ones; retire it when it is loose everywhere.

```json
{"verdicts": [{"query": "Q1", "verdict": "ok", "reason": "…"}],
 "known_items": [{"ref": "…", "action": "…", "reason": "…"}],
 "vocabulary": [{"axis": "C2", "term": "…", "action": "added|rejected", "reason": "…"}],
 "term_pull": [{"axis": "C2", "term": "…", "action": "keep|retire", "reason": "…"}],
 "summary": "…", "model": "…"}
```

**3. Re-planning**, at most **two rounds** after the first (three in all):
- replace the query — `frame query-revise` ([A1-frame.md](A1-frame.md#a1q)): the old one is retired, its papers stay;
- a synonym the axes lack — `frame add-terms`: an add-only revision of the protocol. `"all"` in an existing query keeps
  meaning A1.p's own terms, so nothing else goes stale; the added term must be asked by a revised query;
- an ambiguous term — `frame retire-terms`: the term stays in the protocol as written, marked retired, and no query
  renders it any more; the queries that asked it are stale and run again (`--only` the ids it prints). It refuses when
  a query would be left with no term on that axis, when a query's flat form names the term or a word only that term
  supplied, and on an anchor axis (an anchor is a named method — revise its query instead);
- run the replacement — `mcp_bridge.py search $RD --only <new id>` (it merges again) — then `search-check` and the
  next round.

A round may not keep a `replan` the previous round asked for, may not `replan` in the last round, and may not `replan`
once the latest re-plan round brought **fewer than 5 %** new papers — the search is saturated; accept the weakness
instead.

**4. A protocol revised after the search** (A1.p `set-protocol --note …`, e.g. after A1.e found a misreading) asks a
new question: it starts a new **epoch** (§15 G2). Each round records the protocol it judged (`protocol_sha`,
`epoch_round`); the round limit, the previous round's pending re-plans and saturation count only the rounds of the
current epoch, and the queries that came in before it are its base (round 0). The earlier rounds stay in the file and in
the `.md` view, under a line that marks the new epoch. A round without `protocol_sha` (stored before this rule) belongs
to the epoch it came after. Anchor terms of the rejected reading go out with `frame anchors-revise`, then
`mcp_bridge.py merge $RD` (offline) recomputes `anchor_match` before the epoch's first `search-check`.

### Outputs
`step2_relevance_check.json` (rounds of verdicts, each on the collection it judged) and its view `.md`;
`_state/A2c/signals_r{n}.json`.

### Done when
`a2-check --unit A2.c` passes (R00–R11): the last round judged the current collection, every active query has a
permitted verdict, every missing known item an action, every ambiguous term an answer, and no re-plan or retirement is
pending.

### When something fails
`accept-weak` verdicts and unresolved known items become **must-disclose caveats**: the idea's `Related Work` or
`Risk Factors` has to state them. A round judged on a collection that has since changed is stale and judged again.
Without `sem_sim` there is no vocabulary feedback and no ambiguous-term signal.

### Commands
```bash
$PY $SK/scripts/ideate_tools.py search-check $RD [--json]
$PY $SK/scripts/ideate_tools.py relevance-set $RD $RD/_state/A2c/verdicts_r0.json
$PY $SK/scripts/ideate_tools.py a2-check $RD             # every A2 check; exit 1 on an ERROR
```
