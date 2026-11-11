# LitSearch evaluation for current pipeline Steps 2 and 3

This ports the old `evaluation/step02` and `evaluation/step03` experiment boundary to the current conductor:

- Step 2 is `STEP-S2`: `A2.s -> A2.m -> A2.c`. Evaluate its final retrieval set in
  `step2_raw_papers.json` without treating it as a ranked top-k result.
- Step 3 is `STEP-S3`: `A3.b -> A3.g -> A3`. It consumes one frozen BM25 candidate pool and produces
  `screening_scores.json` plus `step3_shortlist.json`. The evaluator ranks by relevance and composite score.
- Gold corpus IDs remain only in `tasks.jsonl`; they are never written to a pipeline research directory or prompt.

The combined `step0203 run` executes every question through `STEP-S1`–`STEP-S4`. `STEP-S4` is A5 snowball; the
production conductor rescreens A5 additions in A3 before its `GATE-a5-check`. The combined evaluator reads the
final `step3_screening_all.json`, `step3_shortlist.json`, and snowball file only after that gate passes. It does not
skip Step 3 when the initial Step 2 search misses a gold paper. The separate `step02` and `step03` commands above
remain available for isolated checkpoints.
The evaluation runner sends `think=false` to Ollama for its structured outputs; otherwise reasoning can exhaust
`num_predict` before Qwen emits any JSON. The selected value is part of the resume key.
For a completed STEP-S4 run that predates the completion marker, the runner checks the latest production summary,
the passed `GATE-a5-check`, the unchanged query, and all final outputs. If they are valid it restores the marker
and skips model calls. The restored marker records that the original model settings were not in the summary.

`tasks.jsonl` uses one object per question. Step 2 requires `qid`, `query`, and `corpusids`. Step 3 preparation
also requires `bm25_top100` and the official corpus file uses `corpusid`, `title`, and `abstract`.

Download and prepare these inputs from the official `princeton-nlp/LitSearch` dataset:

```powershell
python -m pip install -e ".[litsearch]"

# Step 2 + Step 3: official queries and gold IDs (no corpus download)
python -m evaluation.step0203.cli download --out eval_runs/litsearch/step0203_data

# Step 3 frozen BM25 pool: also downloads corpus_clean and computes top 100
python -m evaluation.step03.cli download --out eval_runs/litsearch/step03_data
```

Both commands pin the project's previously used official revision by default. `--revision <sha>` selects another
revision and `--limit N` limits the number of query tasks (Step 3 still indexes the complete corpus). Each output has
`tasks.jsonl`, `queries.jsonl`, and `data_manifest.json`; Step 3 also has `corpus_title_abstract.jsonl`.
The Step 3 BM25 computation follows the official title/abstract format, NLTK tokenization, English stopword removal,
Porter stemming, BM25Okapi parameters, and NumPy ranking. Hugging Face may transfer the full-text Parquet corpus
before the script extracts just title and abstract. A repeat download verifies the saved files against SHA-256 hashes.
To create a reproducible sample shaped like the paper's Table 7, add `--sample table7-80 --seed 20261110` to either
download command. This selects 40 specific inline-citation and 40 specific author-written questions, alternating the
two groups in `tasks.jsonl` so an even `--limit N` remains balanced. It is a **new random sample**, not the paper's
unpublished exact 80 questions; the manifest records its seed, split counts, and actual number of gold papers.
Add `--limit N` to `step02 run`, `step03 prepare/run/evaluate`, or `step0203 run/evaluate` to execute and score only
the first N tasks of a frozen task file. Use the same limit for separate prepare/run/evaluate commands.

For live Step 2 provider results, an external-ID-to-corpus-ID `--mapping` is still needed for reliable gold matching;
the official query/corpus download cannot infer that mapping. Build it before the combined run. `map-ids --limit N`
can resolve just the first N tasks for a smoke run, and later runs extend the same mapping file.

```powershell
python -m evaluation.step0203.cli map-ids `
  --tasks eval_runs/litsearch/step0203_data/tasks.jsonl `
  --out eval_runs/litsearch/step0203_data/gold_id_map.json
```

This looks up gold `CorpusId`s through the Semantic Scholar paper batch API (up to 500 per request), saves each
completed batch, and retries unresolved IDs on a later invocation. It uses `SEMANTIC_SCHOLAR_API_KEY` when present
and backs off after HTTP 429 responses. The output reports mapping coverage; do not treat unmapped gold as a
confirmed miss. The mapping is evaluation-side data and is never put into a production research directory.

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
The combined results write each question's final screening audit into `results.jsonl.screening_audit`. These
values are read directly from the production `step3_shortlist.json` after its legacy-format augmentation:
`screening_config.threshold`, `borderline_threshold`, the three weights, and the requested `summary` fields.
