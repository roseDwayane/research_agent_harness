# Evaluation layout

```text
evaluation/
  step02/    current STEP-S2 retrieval-set evaluation
  step03/    current STEP-S3 three-axis scoring and ranking
  step0203/  production STEP-S1 -> STEP-S4; score after A5 and any A3 rescreen
  step08/    IdeaBench P1/P2 offline experiment entry point
  litsearch/ shared adapters, production-conductor runner, and ranking metrics
```

Step 3 requires the model to return integer `relevance`, `quality`, and `recency_impact` scores from 1 to 5.
Python calculates `0.50*relevance + 0.30*quality + 0.20*recency_impact` with decimal `ROUND_HALF_UP` to two
places. The primary relevance order is `(-relevance, -composite, paper.id)`; the comparison order is
`(-composite, paper.id)`. Normalized records, including `included`, `borderline`, and `excluded`, are written to
`step3_screening_all.json.papers`.

The combined evaluator runs every question through STEP-S4, including A5 snowball and any A3 rescreen. It scores
the final `step3_screening_all.json` after `GATE-a5-check` passes. Gold IDs never gate execution. Failed or
incomplete final checkpoints contribute zero to headline metrics, with every requested question in the denominator.
