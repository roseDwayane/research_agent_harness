# LitSearch evaluation for current pipeline Steps 2 and 3

This ports the old `evaluation/step02` and `evaluation/step03` experiment boundary to the current conductor:

- Step 2 is `STEP-S2`: `A2.s -> A2.m -> A2.c`. Evaluate its final retrieval set in
  `step2_raw_papers.json` without treating it as a ranked top-k result.
- Step 3 is `STEP-S3`: `A3.b -> A3.g -> A3`. It consumes one frozen BM25 candidate pool and produces
  `screening_scores.json` plus `step3_shortlist.json`. The evaluator ranks by relevance and composite score.
- Gold corpus IDs remain only in `tasks.jsonl`; they are never written to a pipeline research directory or prompt.

`tasks.jsonl` uses one object per question. Step 2 requires `qid`, `query`, and `corpusids`. Step 3 preparation
also requires `bm25_top100` and the official corpus file uses `corpusid`, `title`, and `abstract`.

```powershell
# Run current Step 2 (S1 is run first to establish its required protocol)
python -m evaluation.litsearch.cli run-step2 `
  --tasks eval_runs/litsearch/tasks.jsonl `
  --sessions eval_runs/litsearch/current_step2/sessions `
  --model qwen3.8 --url http://127.0.0.1:11434

python -m evaluation.litsearch.cli evaluate-step2 `
  --tasks eval_runs/litsearch/tasks.jsonl `
  --sessions eval_runs/litsearch/current_step2/sessions `
  --mapping eval_runs/litsearch/gold_id_map.json `
  --out eval_runs/litsearch/current_step2/evaluation

# Freeze official BM25 top-100 at the S2/S3 boundary, then run current Step 3
python -m evaluation.litsearch.cli prepare-step3 `
  --tasks eval_runs/litsearch/tasks.jsonl `
  --corpus eval_runs/litsearch/official_bm25/corpus_title_abstract.jsonl `
  --sessions eval_runs/litsearch/current_step3/sessions

python -m evaluation.litsearch.cli run-step3 `
  --tasks eval_runs/litsearch/tasks.jsonl `
  --sessions eval_runs/litsearch/current_step3/sessions `
  --model qwen3.8 --url http://127.0.0.1:11434

python -m evaluation.litsearch.cli evaluate-step3 `
  --tasks eval_runs/litsearch/tasks.jsonl `
  --sessions eval_runs/litsearch/current_step3/sessions `
  --out eval_runs/litsearch/current_step3/evaluation
```

Preparation records SHA-256 hashes for Step 0, the frozen Step 2 candidates, and the ledger. Step 3 refuses to
run or evaluate if those inputs change. Runs resume completed units through the production ledger, while progress
and per-question failures are kept separately so an infrastructure failure is not counted as a retrieval miss.
