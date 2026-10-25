# Architecture reference

A working summary for implementers. The authority is [ARCHITECTURE.md](../ARCHITECTURE.md) and the
contracts in [`contracts/`](../contracts/); query them with the `ideate_v2` MCP server
(`ideate_list_units`, `ideate_get_contract`, resource `ideate://architecture`) rather than copying facts from here.

## Shape

```
STAGE-A (once per topic)
  BLK-search  S1 Define  -> S2 Search -> S3 Screen -> S4 Augment -> S5 Export          gates: frame, a2, a3, a5, a4
  BLK-fusion  F1 Deconstruct -> F2 Align -> F3 Collide -> F4 Reconstruct              gates: decon, align, collide, recon
STAGE-B (once per idea, gen_k)
  BLK-planning P0 take -> P1 Gap2Hypo -> P2 Design -> P3 Tree -> P4 Attack -> P5 Pack -> B5 Reflect -> B6 Finalize
                                                                 gates: hypo, argument, tree, attack, pack, coherence
```

38 Units, 31 substeps, 15 gates, 12 loops, 66 artifacts. Identifiers: Units keep their slide ids (`A2.s`, `B3.5`,
`P3`); substeps are `<unit>/<label>` (`A5/cocite`, `P3/T09`, `B6/append`); everything else has a typed prefix
(`STEP-`, `GATE-`, `LOOP-`, `ART-`, `RP-`, `INFRA-`, `EXT-`, `STORE-`, `MCP-`, `D-`, `OQ-`) — decision D-03.

## Terms

| Term | Meaning |
|---|---|
| Unit | One decision with its own files (or parts of a shared file), its checks, and a ledger entry |
| Gate | A handover check; a failing gate refuses the next step. v2 gate = contract check AND the legacy `*-check` (D-10) |
| Loop | A declared back-edge with a bound (iterations and/or a measured condition); evaluated by `ideate_check_loop` |
| Artifact | A data contract: path (+ part), schema, owner(s), readers; views (`kind: view`) are derived and owned by no Unit |
| Ledger | `<RD>/_state/ledger.jsonl`: begin / done / pending / fail per Unit instance with input and output hashes |
| Stale | An output or input changed since done, or an upstream is not done |
| Caveat | A weakness a Unit could not repair; must-disclose caveats reach the idea's Risk Factors |
| Run (v2) | One orchestration session: `run_id`, `trace_id`, events and error records under `<RD>/_state/errors/<run_id>/` |
| Maturity L0–L4 | Legacy `units check` levels over twelve conditions: L1 boundary (1–4), L2 decidable (5, 6, 10), L3 resilient (7–9), L4 complete (11, 12) |

## Dependencies that are easy to miss

* **A1.v → B1, B6** — context written in S1 is read in F2 and B6; v2 declares B1 requires A1.v (D-12).
* **A7.A3 → A7.R2, B2 → P2, A7.R3 → B6** — ordered only by the block gates (align-check, recon-check).
* **A5 ↔ S3** — snowball additions are screened again (LOOP-04); A5 is not made stale by that re-screen.
* **B3 → A7.D, A7.X2 → A7.A1, B3.5 → A6.d** — declared revisions and targeted re-runs (LOOP-06, LOOP-05, LOOP-07).
* **B5 → P1 | P2 | P3** — one revision per round; steps after the entry point are re-produced (LOOP-09).

## Where things run

| Layer | Component | Writes |
|---|---|---|
| Judgement | the agent and its subagents, following SKILL.md | drafts in scratch, through the Unit's tool |
| Unit mechanics | legacy `ideate_tools.py`, `mcp_bridge.py` | the Unit's owned artifacts, the ledger |
| Network | legacy `scholar_mcp`, `paper_pdf_mcp`, Crossref, pdf2md | recordings under `_state/net/` |
| Orchestration support | `ideate_v2` MCP server (this module) | `_state/errors/**`, `ERRORS.md` only (D-07) |

## Depths

`quick` (3 query variants, no full texts, no scope probe, no blind readers), `standard` (5 variants, 20 full texts,
dense D1), `deep` (7 variants, every Tier 1 full text). The depth changes Unit `when` clauses and degraded paths, not
the architecture (legacy D8).
