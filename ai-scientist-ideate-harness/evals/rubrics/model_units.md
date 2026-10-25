# Rubrics for model-judged Units

Probabilistic quality evaluation, kept apart from the deterministic cases. Each rubric scores 0 / 1 / 2 per
criterion (0 = fails, 1 = partly, 2 = fully). A judge (a different model or a person, blind to which version
produced the output) scores each output; a case passes when the mean of every criterion reaches its threshold.

**Thresholds are TBD (OQ-11).** Establish them by scoring the current implementation on the labelled sets below
(baseline), then set each threshold at the baseline minus one standard deviation, and require any change to keep
the paired difference non-negative (Wilcoxon signed-rank, alpha 0.05, >= 20 items).

| Rubric | Unit | Labelled set needed | Criteria |
|---|---|---|---|
| R-A1e | A1.e | 10 protocols, 5 with a planted defect (forced PICO, missing anchor axis, criterion with two readings) | C1 the planted defect is found · C2 every finding quotes the protocol line · C3 the verdict agrees with the findings · C4 no invented defect |
| R-A2c | A2.c | 20 queries with signals, labelled ok / replan / accept-weak by two reviewers | C1 verdict matches the label · C2 the reason cites the signals (on-anchor share, top titles) · C3 replans name a concrete revision |
| R-A3 | A3 | 100 candidate papers labelled include / exclude with the criterion | C1 inclusion agrees with the label (report Cohen's kappa) · C2 every score follows a verbatim quote that exists in the abstract · C3 exclusions name the criterion · C4 no venue or citation reasoning (blinding held) |
| R-A7D | A7.D | 10 papers with reference decon records | C1 claims keep strength (hedges stay hedged) · C2 scope is not widened · C3 quotes are verbatim · C4 limitations and not-done items are found · C5 nothing comes from another paper |
| R-A7X2 | A7.X2 | 30 candidate pairs labelled agree / conflict / boundary / extends / incommensurable | C1 result matches the label · C2 the differing axes are right · C3 no straight conflict on a hedged claim |
| R-B35 | B3.5 | 10 gaps, 3 with a planted 'already settled' answer in the agree collisions | C1 the settled screen fires on the planted cases · C2 the condition comes from the gap's collisions · C3 every ladder rung cites evidence · C4 section 9 names a real target |
| R-P1 | P1 | 10 questions with their primary collisions | C1 the form matches the derivation table or the deviation is justified · C2 rivals come from the handed-over accounts · C3 the direction uses the handed-over magnitudes |
| R-P4 | P4 | 10 attack plans with their sources | C1 each target sentence exists verbatim · C2 wording not stronger than the source · C3 lands_on and if_miss name existing leaves · C4 concessions are honest |
| R-P5 | P5 | 10 packagings with their argument and tree | C1 no decision absent from P1-P4 · C2 title promises only tested parts · C3 abstract <= 250 words without results · C4 blind restatement matches the primary claim |

Running a rubric case needs a judge integration (not built): `run_evals.py` reports these cases as `not_executed`
with the reason, never as passed. Planned interface: `IDEATE_EVAL_JUDGE=<command>` receiving the rubric id, the
output and the reference on stdin and returning `{criterion: score}` JSON.
