# The planning block — one idea from one question (B4–B6)

The fusion block hands over a list of research questions (`questions/index.json`, references/fusion/README.md). The
planning block turns **one** of them into one 7-key idea, once per generation, in five steps whose order is fixed:

| step | answers | writes | rules |
|---|---|---|---|
| **P1 Gap2Hypo** | what does this gap predict, why this direction, who would explain it otherwise? | step8 RQ / Hypotheses / Rival explanations; `argument.json → claims[]`, `derivation`, `rivals[].id` | [P1-gap2hypo.md](P1-gap2hypo.md) |
| **P2 design** | which data, which measure, which number decides, which control aims at which rival, what can the sample detect? | the rest of step8; the design fields of `argument.json` | [P2-design.md](P2-design.md) |
| **P3 decision tree** | what does each outcome of each experiment mean, which rival dies, what paper is each leaf, where do we stop early? | `gen_k/decision_tree.json` (+ `decision_tree.md`); `claims[].outcomes` is its projection | [P3-decision-tree.md](P3-decision-tree.md) |
| **P4 attack-type Related Work** | whose sentence do we test, on what record, with which experiment, where does the blow land, what do we say if it misses? | `gen_k/attack_plan.json` → `Related Work` | [P4-attack.md](P4-attack.md) |
| **P5 packaging** | title, short hypothesis, abstract — only what P1–P4 decided, in the logical order | `idea_draft.json` (Title, Short Hypothesis, Abstract), `gen_k/packaging.json` | [P5-package.md](P5-package.md) |

Each step reads only the steps before it and the fusion block's hand-over (`gen_k/question.json`: the question, its gap,
its collisions and — from the question's section 9 — `targets`, `rival_accounts`, `magnitudes`). A revision enters at the
earliest step it changes; everything after that step is produced again, never patched. The reflection loop (B5: rounds,
blind reader, gates) wraps the five steps; B6 appends the idea, consumes the question, writes the prescriptive Body and
the journal recommendations.

What does not change: the 7-key idea contract; `argument.json` (schema `ai-scientist-argument/1`, fields only added) and
its checks C1–C24, defined in [../question-craft.md](../question-craft.md) §4–§5; the round cap `num_reflections + 2`; no
network inside the loop.

Status (2026-10-18): built (PLAN [docs/decisions/PLAN_ideate_planning.md](../../../../../docs/decisions/PLAN_ideate_planning.md)
§11). The rounds that wrap the five steps are research-cycle.md §5, "On the fusion block". A generation without
`decision_tree.json` is the older flow and is checked as before; the planning checks (C25–C28 inside `argument-check`,
`tree-check`, `attack-check`, `pack-check`) run only on a generation that has `gen_k/question.json` or the planning files.

| step | commands | checks |
|---|---|---|
| P1 | `hypo-prefill`, `hypo-check` | C25 derivation · C26 rival accounts · C27 the field's numbers |
| P2 | `power`, `argument-render` | C1–C24 (question-craft §5.2) |
| P3 | `tree-prefill`, `tree-render --project`, `tree-check` | T01–T14 (T09 the decision gate) |
| P4 | `attack-prefill`, `attack-render`, `attack-check [--idea]` | R01–R13 |
| P5 | `pack-prefill`, `pack-render`, `pack-check [--idea]` | K01–K10 |
| all | `plan-status`; `argument-check` | C28: the tree, attack plan and packaging rest on the current argument |
