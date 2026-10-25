# The literature search (A1–A5)

The first block of Stage A. From one topic file it builds the evidence base every later step stands on: a screened,
named collection of papers whose every inclusion and exclusion can be traced to a rule or a quoted judgement. The
block ends when the shortlist, its citation keys and its bibliography pass their checks; full text (A6) and the
knowledge base (A7) start from there.

## The logic: define → search → screen → augment (→ screen) → export

```
 define A1 ──frame check──► search A2 ──a2-check──► screen A3 ──a3-check──► augment A5 ──a5-check──► export A4 ──a4-check──► A6
    ▲                          │                       ▲    │                    │
    └──── re-plan a query ─────┘                       │    └─ amend a criterion ─┘ (recorded beside the protocol)
          query-revise · add/retire-terms (≤ 2 rounds) └──── additions screened again (relevance ≥ 3)
```

| Phase | Question it answers | Units | Rules |
|---|---|---|---|
| **Define** | What counts as this topic, and how will the databases be asked? | A1.p protocol · A1.q strategy · A1.e evaluation · A1.v context | [A1-frame.md](A1-frame.md) |
| **Search** | What did every database answer, and did each query ask well? | A2.s retrieval · A2.m merge · A2.c relevance check | [A2-search.md](A2-search.md) |
| **Screen** | Does each paper belong? | A3.b bibliometrics · A3.g gate · A3 scoring and build | [A3-screen.md](A3-screen.md) |
| **Augment** | What did keyword search miss along the citation graph? | A5 snowball, then A3 again on the additions | [A5-snowball.md](A5-snowball.md) |
| **Export** | What is each paper called, and what does its entry say? | A4.k keys · A4.b bibliography | [A4-export.md](A4-export.md) |

Three rules hold the phases together:

- **Each phase starts only when the previous one passes its check.** The tools refuse otherwise, and a check whose
  input changed reports STALE. A topic whose step0 has no protocol is refused by every command: the search starts at A1.
- **Loops are bounded and declared.** A2.c may revise A1's queries and add synonyms, at most two rounds; A3 may amend a
  criterion with a reason, beside the protocol; A5's additions go back through A3 with a stricter relevance floor; a
  second snowball round needs ≥ 10 % growth of the included set; a later step may ask for one excluded paper to be
  read again (`screen-rescue`, [A3-screen.md](A3-screen.md#rescue)), never for its score to be edited.
- **Judgement and mechanics are separated.** Models judge — the protocol evaluation (A1.e), the query verdicts (A2.c),
  the paper scores (A3) — always through a tool that checks what they wrote. Everything else is computed and
  recomputed.

## A full run

`ideate_tools.py next <RD>` always says which Unit comes next and with which commands; the list below is the same
order written out.

```bash
SK=.claude/skills/ai-scientist-ideate; PY=<interpreter with mcp>; RD=<topic>_research
$PY $SK/scripts/mcp_bridge.py preflight $RD                               # keys, services, SPECTER2 (before a run)
# define
$PY $SK/scripts/ideate_tools.py frame set-protocol $RD $RD/_state/A1/protocol.json
$PY $SK/scripts/ideate_tools.py frame set-strategy $RD $RD/_state/A1/strategy.json
$PY $SK/scripts/mcp_bridge.py probe $RD                                   # standard, deep
$PY $SK/scripts/ideate_tools.py frame set-context $RD $RD/_state/A1/context.json
$PY $SK/scripts/ideate_tools.py frame eval-brief $RD                      # -> one subagent -> round_1.json
$PY $SK/scripts/ideate_tools.py frame set-evaluation $RD $RD/_state/A1e/round_1.json
# search
$PY $SK/scripts/mcp_bridge.py search $RD
$PY $SK/scripts/ideate_tools.py search-check $RD                          # -> verdicts
$PY $SK/scripts/ideate_tools.py relevance-set $RD $RD/_state/A2c/verdicts_r0.json
# screen
$PY $SK/scripts/mcp_bridge.py bibliometrics $RD
$PY $SK/scripts/ideate_tools.py screen-gate $RD
$PY $SK/scripts/ideate_tools.py screen-plan $RD                           # -> one subagent per batch
$PY $SK/scripts/ideate_tools.py screen-merge $RD
$PY $SK/scripts/ideate_tools.py screen-build $RD $RD/screening_scores.json
# augment, then screen the additions
$PY $SK/scripts/mcp_bridge.py snowball $RD
#   bibliometrics -> screen-gate -> screen-plan -> subagents -> screen-merge -> screen-build
# export
$PY $SK/scripts/ideate_tools.py export $RD
$PY $SK/scripts/mcp_bridge.py bibliography $RD
$PY $SK/scripts/ideate_tools.py a4-check $RD
$PY $SK/scripts/ideate_tools.py status $RD                                # every Unit's state -> STATUS.md
```

`PY` is the interpreter that has the `mcp` package (`bash .claude/skills/ai-scientist/scripts/check_env.sh`); shell
variables do not survive between separate tool calls, so set them at the top of every command block.

## Depth

| | A1.q variants | scope probe | dense D1 | snowball |
|---|---|---|---|---|
| `quick` | primary, synonym-swap, anchor-methods | — | — | ✔ |
| `standard` | + loosen, contrast | ✔ | ✔ | ✔ |
| `deep` | + counter-evidence, recent | ✔ | ✔ | ✔ |

## Files

| File | Written by | Holds |
|---|---|---|
| `step0_session_config.json` | A1.p · A1.q · A1.v (each its own keys) | protocol, queries, sources, anchor terms, known items, scope probe, context |
| `step1_protocol.md` | view (rendered) | the protocol as a PRISMA-ScR-style document, with its deviation log |
| `step1_protocol_evaluation.{json,md}` | A1.e | the independent reader's verdict, by round |
| `step2_queries/<id>@<hash>.json` | A2.s | one recorded instance per query and per dense instance |
| `step2_raw_papers.json`, `step2_search_summary.md` | A2.m | the merged collection; PRISMA identification counts |
| `step2_relevance_check.{json,md}` | A2.c | the verdict per query, by round |
| `step3_bibliometrics.json` | A3.b | citations, venues, reference lists, computed impact |
| `step3_gate.json` | A3.g | mechanical exclusions |
| `screening_scores.json` | A3 (via `screen-merge`, `screen-amend`) | evidence, scores, exclusions, criteria amendments |
| `step3_shortlist.json`, `step3_screening_results.md` | A3 (`screen-build`); `citation_key` by A4.k | included papers, tiers, roles; the PRISMA screening box |
| `step2b_snowball_papers.json` | A5 | additions by route, per round |
| `step4_citation_keys.jsonl`, `.md` | A4.k | one key per paper, append-only |
| `step4_references.bib`, `step4_bib_metadata.json` | A4.b | the bibliography and where each entry came from |
| `_state/paper_ids.jsonl` | A2.m, A5 | the append-only id registry |
| `_state/net/` | the transport | every network answer, for replay |
| `_state/embeddings/` | A2.m, A5 | cached SPECTER2 vectors |
| `_state/ledger.jsonl`, `_state/ledger_snap/` | every command (it_ledger) | each Unit's begin / done / fail, with input and output hashes |
| `_state/preflight.json` | `mcp_bridge.py preflight` | which keys are set and which services answer, for 12 hours |
| `_human/search_overrides.json` | a person | interventions ([below](#intervening)) |
| `STATUS.md`, `search_caveats.json` | views (rebuilt after every done) | every Unit's state, the funnel, the caveats — the block's exit contract |

## Shared mechanisms

- **Stable ids.** `paper_NNN` comes from one append-only registry, matched by DOI, then arXiv id, then normalised
  title; each entry records which Unit minted it. An id is never reused.
- **Record and replay.** Every network answer (scholar server, OpenAlex, Crossref) is recorded under `_state/net/`, in
  order; with `IDEATE_REPLAY=1` a run replays from the recordings without touching the network and fails on a request
  it has no recording for. Requests are recorded without credentials.
- **Keys.** All optional, in `mcp/scholar_mcp/.env` (names in `mcp/.env.example`; never printed): Scopus, IEEE and
  WoS keys open those sources; a Semantic Scholar key makes dense retrieval and the similar route dependable; an
  OpenAlex key gives this machine its own daily budget instead of the one every keyless client on the network shares.
- **Semantic similarity.** The fixed local model `allenai/specter2_base`, on the CPU, embeds each paper and a
  description of the protocol; rules read the percentile `sem_pct`, never the raw cosine.
- **The ledger.** Every Unit's command records `begin` and, once the Unit's own checks pass, `done` with the hashes
  of its inputs and outputs (`_state/ledger.jsonl`). A Unit is current while its outputs still hash as recorded and its
  inputs as they did at `begin`; otherwise it is stale, and so is everything downstream of it — `next` names the
  command to run again (nothing re-runs by itself: A3's scores cost tokens). A `begin` without a `done` is a run that
  was interrupted. Between the two, a change to any file outside the Unit's card (`io`: owned files, scratch, declared
  revisions) refuses the `done`. A declared revision (A2.c revising A1.q's queries) does not make the owner stale, and
  A5's own additions do not make A5 stale when A3 screens them. An input the card declares but the `done` did not
  record counts as changed; a view over the Unit's own output (A5's seed basis) is hashed at `done`, not at `begin`.
  A deterministic Unit run again on unchanged inputs keeps its file as it was, so nothing downstream goes stale.
- **Staleness by hash, inside each Unit.** Every output also records the hashes of what it was built on; a Unit's own
  check reports STALE when that basis changed.
- **Views.** `STATUS.md` (every Unit's state with its counts, the PRISMA funnel, the caveats, a person's overrides)
  and `search_caveats.json` are rebuilt after every `done` and never edited.
- **Caveats.** A weakness the search could not repair — a failed source, a skipped route, an accepted weak query, a
  missing known item — is written as a caveat in the step's own file; one marked `must_disclose` has to be stated in the
  idea's `Related Work` or `Risk Factors`.

<a id="intervening"></a>
## Intervening

The flow does not stop to ask. A person who wants a decision changed writes an entry, with a reason, into
`<RD>/_human/search_overrides.json`; the Unit that owns the decision applies it the next time it runs, the ledger
records it, and the downstream Units go stale:

| Entry | Applied by | Effect |
|---|---|---|
| `{"kind": "include", "id": "paper_123", "reason": "…", "by": "…"}` | A3 `screen-build` | included, marked `decided_by: human`, counted apart; a retraction cannot be included |
| `{"kind": "exclude", "id": …, "reason": …}` | A3 `screen-build` | excluded with code `HUMAN` |
| `{"kind": "reread", "id": …, "reason": …}` | A3 `screen-plan` | a blind second reading (`screen-rescue`), once |
| `{"kind": "seed", "id": …, "action": "add" \| "remove", "reason": …}` | A5 | the forward seeds change; the round records it |
| `{"kind": "known_item", "title": …, "doi": …, "reason": …}` | A2.c | must be found, or answered for, like A1.q's known items |

An include or exclude of a paper the search found changes what A5 started from: A5 goes stale, and `snowball` redoes
its round (A5's *Redo*), after which A3 screens only the works the redo found new.

The protocol and the queries change through their own tools (`frame set-protocol --note`, `frame query-revise`,
`frame add-terms`, `frame retire-terms`). The search-block Units are not re-entry points for `fork`: they are
topic-level, so a change re-runs what follows rather than branching.

## Tracing a decision

`ideate_tools.py trace <RD> <paper_id | citation_key | query_id | protocol>` lists every Unit's decision about that
item with its evidence and file — found by which queries and sources, merged how, measured how, scored with which
quoted evidence by which batch and model, read again or decided by a person, used as a seed, keyed and entered — and
ends with where a comment on it goes and what is downstream of that decision.

## Reading the collection

Never paste whole JSON files or many full abstracts into the context; read papers in slices:

```bash
$PY $SK/scripts/ideate_tools.py list-papers $RD --slice 0:200 --abstract-chars 0      # titles only, one line each
$PY $SK/scripts/ideate_tools.py list-papers $RD --slice 0:30 --abstract-chars 400     # a triage pass
$PY $SK/scripts/ideate_tools.py list-papers $RD --ids paper_012,paper_040             # full abstracts, a few at a time
$PY $SK/scripts/ideate_tools.py list-papers $RD --file shortlist                      # key, composite, tier
$PY $SK/scripts/ideate_tools.py list-papers $RD --file excluded --grep "dry electrode"
```

Thirty papers with abstracts cut to about 400 characters fit one tool result; ask for full abstracts only where a
decision is close.

## What the block hands on

To full text (A6) and the knowledge base (A7), once `a4-check` passes:

- `step3_shortlist.json`: the included papers — inclusion is decided at title and abstract level — with their scores,
  tiers, reading roles and citation keys;
- `step4_references.bib` and the key log: the names every later file and citation uses;
- `search_caveats.json`: the caveats of every step; the must-disclose ones travel into the idea.

Each Unit's card — inputs, outputs, checks with one counter-example each, failure paths, maturity — is in
[../units.md](../units.md).
