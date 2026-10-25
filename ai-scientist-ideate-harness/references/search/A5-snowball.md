# A5 snowball — fill the gaps along the citation graph

**Augmentation** is the fourth phase of the literature search ([README.md](README.md)). Keyword search misses what the
field calls by other names, what predates the search window, and what appeared after the queries were written. The
snowball follows the citation graph out from papers **already screened as relevant** and sends everything it finds
back through A3. It runs before A4: keys are minted once, on the final shortlist.

| Unit | Decides | Writes (through the tool only) |
|---|---|---|
| [A5 snowball](#a5) | nothing by judgement — routes, seeds and thresholds are rules; A3 decides inclusion | `step2b_snowball_papers.json`, A5's entries in `_state/paper_ids.jsonl` |

---

<a id="a5"></a>
## A5 — snowball

### Purpose
Propose the papers the keyword search could not reach — the classics many included papers cite, the recent work that
cites the best ones, and their embedding neighbours — for A3 to screen like any other candidate.

### Inputs
`step3_shortlist.json` (roles, composite; A3 passes), `step3_bibliometrics.json` (reference lists, OpenAlex ids),
`step2_raw_papers.json`, step0 `protocol.timeframe` and `anchor_terms`, `_state/paper_ids.jsonl`.

### Method

**1. Four routes, one round.**

| Route | From | Kept when | Cap |
|---|---|---|---|
| **backward** | the reference lists A3.b holds for **every included paper** (no network for the counting) | cited by ≥ max(3, 2 % of the included papers) | 40 |
| **co-citation** | the reference lists of the papers that cite **two or more seeds** (the forward route's citers) | cited by ≥ max(3, 2 % of those papers) | 20 |
| **forward** | OpenAlex `cites:` per seed, within the protocol's timeframe, ≤ 200 citers per seed, newest first | the paper cites **≥ 2 seeds** | 40 |
| **similar** | Semantic Scholar recommendations (embedding neighbours) | the top results the collection does not hold | 30 |

Each route is ranked by its own count and cut at its own cap; a work that qualifies for backward and co-citation is
added once, under backward, with both routes named. Each route records what its cap cut off (`truncated`).

**2. Seeds, by rule.** Forward: the included papers holding the A3 roles `foundational` or `core-method`, top 10 by
composite. Similar: `core-method` or `emerging`, top 10 with a DOI. Backward needs no seeds — every included paper
votes.

**3. Why these thresholds.** A fixed count would admit hundreds of works in a large collection and nothing in a small
one; 2 % of the population counted, with a floor of 3, scales with it, and the cap keeps the most-cited. A citer of one
seed may simply have used one method; a citer of two seeds works on the field's problem — which is why only those
papers' reference lists count for co-citation: counting every citer of any seed fills the pool with the statistics and
toolboxes everyone cites. Co-citation has its own pool and cap so that it can never crowd out backward.

**4. Not screening by fame.** Backward's top hits are the field's toolboxes, cited by nearly everyone. Being cited earns
no relevance: snowball additions need relevance ≥ 3 in A3 (code `FLOOR` below that), as dense-only papers do. The
snowball proposes; A3 decides.

**5. Each addition** carries `found_via: "snowball"`, `snowball_direction` (one or more routes), the round, and the
evidence of its route: `cocited_by_included` and `cited_by` (backward), `cocited_with_seeds` (co-citation),
`cites_seeds` (forward). Its `sem_sim` is computed with A2.m's model and `sem_pct` is its percentile **among the search
collection**, so A3's bulk-rule guard (`sem_pct` < 25) means the same for a snowball paper as for a searched one. New
ids come from the A2 registry with `minted_by: "A5"`; a work the collection already holds (OpenAlex id, DOI or
normalised title) is never added again.

**6. Then A3 again, on the additions only:** `bibliometrics` → `screen-gate` → `screen-plan` (only the unscored) →
subagents → `screen-merge` → `screen-build`.

**7. A second round** runs only when round 1 grew the included set by ≥ 10 % — the snowball then opened a region the
search did not reach. Its seeds are the round-1 additions A3 kept. Otherwise the citation graph around the collection
is saturated.

**8. Redo.** A round starts from the included papers the search found (from round 2 on, also those earlier rounds
brought in); the ledger hashes that set as A5's seed basis. When it changes — a person includes or excludes one of
them — A5 is stale and `snowball` redoes the round: its own earlier additions are not counted as known, so a work found
again keeps its id, and later rounds are dropped. A3 then withdraws the entries of the works the redo no longer holds
(kept under `withdrawn`, restored if a later redo finds them again) and scores only the new ones. While A5 is current,
a second `snowball` for the same round is refused.

### Outputs
`step2b_snowball_papers.json` (schema `ideate-snowball/2`): `rounds` (per round: the status of every route, the
backward and co-citation thresholds, what each cap cut off, the basis, the counts per route), `thresholds`, `caps`,
`caveats`, `papers`.

### Done when
`a5-check` passes (N01–N08): the file was written by this snowball; no addition duplicates the search collection and
every id was minted for A5 once; every addition names its routes and meets their thresholds, and each round's two
thresholds follow the rule; truncation is recorded and no route exceeds its cap; the forward seeds follow the rule; a
second round only after ≥ 10 % growth; every route has a status, a skipped one a reason.

### When something fails
- No included paper has an OpenAlex reference list: backward falls back to Semantic Scholar references of the forward
  seeds, kept when shared by max(2, a quarter of the seeds that answered); those additions carry
  `via: "semantic_scholar"` (caveat `backward-fallback`).
- Fewer than half of the included papers have a reference list: caveat `refs-sparse`.
- Semantic Scholar recommendations unavailable (rate limit, no key): similar is `skipped` with the reason (caveat
  `similar-skipped`). Every S2 request waits its turn on a clock shared by all server processes (1.1 s apart) and a 429
  is waited out — 10, 30, 60 s with a key (or the answer's `Retry-After`), 3, 6, 9 s without; still a 429, the
  snowball waits 120 s and asks once more (`status.similar.retried`) before the route gives up (s20: without the
  pacing, 3 of 20 snowballs lost the route even with a key; s20v2, with it, 4 of 40 rounds — §15 G4).
- Neither backward nor forward ran: caveat `snowball-failed`, must-disclose (N08 WARN) — continue, and state in the
  idea's `Related Work` that foundational and recent citing work was not recovered.
- A pooled work without an OpenAlex record is left out and counted (caveat `snowball-no-metadata`).
- Without the SPECTER2 model, `sem_sim` is not computed and A3's bulk rules spare the additions.

A round is written once, at its end; recorded network answers replay with `IDEATE_REPLAY=1`.

### Commands
```bash
SK=.claude/skills/ai-scientist-ideate; PY=<interpreter with mcp>; RD=<topic>_research
$PY $SK/scripts/mcp_bridge.py snowball $RD               # round 1 (refuses before A3 passes)
$PY $SK/scripts/ideate_tools.py a5-check $RD
# A3 on the additions
$PY $SK/scripts/mcp_bridge.py bibliometrics $RD
$PY $SK/scripts/ideate_tools.py screen-gate $RD
$PY $SK/scripts/ideate_tools.py screen-plan $RD          # only the unscored -> subagents as in A3
$PY $SK/scripts/ideate_tools.py screen-merge $RD
$PY $SK/scripts/ideate_tools.py screen-build $RD $RD/screening_scores.json
$PY $SK/scripts/mcp_bridge.py snowball $RD --round 2     # only after >= 10 % growth of the included set
```

Run it at every depth, including `quick`: it costs seconds of network and is the cheapest protection against a
novelty claim that ignores the field's classics or last year's work.
