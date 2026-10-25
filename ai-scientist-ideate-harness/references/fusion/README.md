# The fusion block — deconstruct → align → collide → reconstruct

**Fusion** turns the papers the search block delivered into a ranked, screened list of research questions. It runs
**once per topic** (decision record: docs/decisions/PLAN_ideate_fusion.md). The planning block (B4 hypothesis and
argument, B5 reflection, B6 finalize) runs once per idea and takes one question from that list.

| Step | Answers | Current steps it covers | Rules |
|---|---|---|---|
| **Deconstruct** | What does each paper, *on its own*, claim, rely on and leave undone? Is it eligible? | A6 full text; A7.D one record per paper | [F1-deconstruct.md](F1-deconstruct.md) |
| **Align** | Which statements are about the same thing? Where do *we* stand on the same coordinates? | A7.A vocabulary, coordinates, concept Points; B1 lens | [F2-align.md](F2-align.md) |
| **Collide** | How do units on the same coordinates relate? Where does the field meet our conditions? What is empty? | A7.X paper × paper collisions; B3.c lens collisions; B3 the gap list | [F3-collide.md](F3-collide.md) |
| **Reconstruct** | Put the collisions back together: what does the field look like, and what should be asked? | A7.R Lines, Points, Planes, Body; B2 synthesis; B3.5 questions | [F4-reconstruct.md](F4-reconstruct.md) |

Each step reads only what the steps before it wrote. A correction going backwards is a declared revision, never a
silent edit: a collision judged `incommensurable` sends a vocabulary revision to the alignment step; a source check in
B3 that opens a full text revises that paper's record (`decon-merge --revise "<why>"`).

Point / Line / Plane / Body cards, `concept_index.json`, the methods matrix and the step6 / step7 / step7b templates keep
their schemas (fields are only added). What changes is which step each card and line grows from.

**Which flow a topic is on.** `knowledge/decon/` exists → this block. A knowledge base built before it (hand-written
`knowledge/_notes/`, no `knowledge/decon/`) is frozen and read as before ([../knowledge-passes.md](../knowledge-passes.md));
the tools refuse to overwrite its notes. To move an old topic onto this block, copy its research folder and run the
block on the copy.

**Order for a topic on this block** (framed with a protocol): A6 → [F1](F1-deconstruct.md) → [F2](F2-align.md) →
[F3](F3-collide.md) → [F4](F4-reconstruct.md). The block hands over `questions/index.json`; the planning block (B4–B6)
takes one ready question per idea. Until the planning block reads that index directly (PLAN phase 5), a generation copies
its question into `gen_k/step7b_problem.md` and goes on from B4 as research-cycle.md describes.

**On the ledger.** A6 full text, before this block, is two Units of its own ledger block (`fulltext`: A6.d fetch, A6.c
convert; [../scholar-pipeline.md](../scholar-pipeline.md) §2); A7.D requires A6.c. The fifteen Units (A7.D, A7.A1–A3, B1, A7.X1, A7.X2, B3.c, B3, A7.R1–R3, B2, B3.5, F.9) are recorded in
`<RD>/_state/ledger.jsonl` like the search's. The commands that write a Unit's files are its boundary: `decon-merge` (A7.D),
`align-set` (A7.A1), `align-coords --auto|--apply` (A7.A2), `lens-set` (B1), `collide-candidates` (A7.X1), `collide-merge`
(A7.X2 for paper batches, B3.c for the lens batch; `collide-plan` closes a Unit with nothing left to judge), `collide-retire`
(A7.X2), `gaps-set` (B3), `questions-index` (F.9, which also renders `fusion_map.md`). The Units the model writes by hand are
opened with `ideate_tools.py unit-begin <RD> <unit>` and closed with `unit-done` (A7.A3, A7.R1, A7.R2, A7.R3, B2, B3.5):
done when the Unit's checks pass, pending otherwise. Shared files are owned by part: `alignment.json` (vocab: A7.A1, coords:
A7.A2), `knowledge_cards.json` (concept Points: A7.A3, findings Points: A7.R1, Planes: A7.R2), `collisions.jsonl` (paper
judgements: A7.X2, lens judgements: B3.c); a write into another Unit's part fails the done. The rendered files (notes, Point
and Plane pages, `_MANIFEST.md`, `concept_index.json`, the methods matrix, `fusion_map.md`) are views no Unit owns.
`ideate_tools.py next <RD>` speaks for the fusion block once it has begun (`--block search|fusion` to choose), `status`
adds a fusion section to `STATUS.md` and writes `fusion_caveats.json` (abstract-heavy, lens-stale, candidates-cut,
incommensurable-open, record-revisions-queued, questions-short), `trace <RD> <key|X0001|GAP_001|Q_001>` follows one paper,
collision, gap or question. A topic fused before the ledger is put on it with `ideate_tools.py adopt <RD>`: each Unit whose
checks pass is recorded done, in order, up to the first that does not.
