# Offline IdeaBench P1/P2 evaluation

This runner uses the official IdeaBench release without OpenAlex or any online literature retrieval.

Protocol:

1. Freeze five references per target from `filtered_references.csv`.
2. Keep `target_papers.csv.abstract_summary` in a separate `gold/` path.
3. P2 first runs offline Stage A to produce distinct gaps/questions.
4. Every adopted question independently runs Stage B P1–P5 and must produce a valid seven-key `idea.json`.
5. `n_i` is the number of P5-valid P2 ideas.
6. P1 makes `n_i` independent direct-generation calls using the same five references.
7. Only after generation, an independent judge receives anonymous P1/P2/gold proposals and ranks novelty and feasibility.
8. Insight Score is the fraction of generated ideas ranked above the gold idea, averaged over balanced order rotations.

The target title, abstract, and gold summary are never supplied to the generator.

## Commands

```powershell
ideabench-offline import `
  --source C:\data\IdeaBench `
  --out evals\datasets\ideabench_health `
  --domain "Health & Medicine" `
  --limit 50

ideabench-offline run `
  --dataset evals\datasets\ideabench_health `
  --out results\ideabench_health_50 `
  --limit 50 `
  --max-questions 3 `
  --generator-url http://generator-server:11434 `
  --generator-model qwen3.8 `
  --judge-url http://judge-server:11434 `
  --judge-model judge-model `
  --generator-num-ctx 32768 `
  --judge-num-ctx 32768
```

Generation and ranking can be separated with `--phase generate` and `--phase rank`. Existing artifacts are resumed.
Each model call is logged with its tag, token counts, and wall time; every task has `progress.jsonl`.

