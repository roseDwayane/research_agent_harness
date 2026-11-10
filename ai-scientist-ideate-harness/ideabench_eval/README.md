# Offline IdeaBench P1/P2 evaluation

This runner uses the official IdeaBench release without OpenAlex or any online literature retrieval.

Protocol:

1. Freeze five references per target from `filtered_references.csv`.
2. Keep `target_papers.csv.abstract_summary` in a separate `gold/` path.
3. The adapter freezes those references at the acquisition boundary, records their hashes, and marks online
   search/full-text retrieval as intentionally bypassed.
4. P2 runs the current production conductor from Stage A fusion (`F1/A7.D`) through gaps/questions (`F2–F4`).
5. Every adopted question independently runs the current Stage B P0–P5/B5 recipes and must produce `idea.json`.
   B6 performs offline bookkeeping only; its journal web lookup is disabled.
6. `n_i` is the number of P5-valid P2 ideas.
7. P1 makes `n_i` independent direct-generation calls using the same five references.
8. Only after generation, an independent judge receives anonymous P1/P2/gold proposals and ranks novelty and feasibility.
9. Insight Score is the fraction of generated ideas ranked above the gold idea, averaged over balanced order rotations.

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

The old Step 2/3 evaluation lifecycle is preserved as explicit phases:

- `--phase prepare`: freeze inputs, write their contract and hashes, and create resumable pipeline artifacts.
- `--phase generate`: run P2 and matched P1, resuming completed artifacts.
- `--phase rank` (or `evaluate`): rank saved outputs without regenerating them.
- `--phase all`: perform all phases.

Changing frozen inputs or the experiment manifest requires a new output directory.
Each model call is logged with its tag, token counts, and wall time; every task has `progress.jsonl`.

