# Step 8 / IdeaBench

`python -m evaluation.step08.cli` is the organized Step 8 entry point. It delegates import/run to the existing
`ideabench_eval` package so saved experiments remain compatible, and adds a verified official-dataset downloader.

```powershell
eval-step08 download --out data\IdeaBench

eval-step08 import `
  --source data\IdeaBench `
  --out eval_runs\ideabench\health_50 `
  --domain "Health & Medicine" `
  --limit 50
```

The downloader resolves `kdm-daiict/Ideabench` to an immutable Hugging Face commit, downloads
`target_papers.csv`, `filtered_references.csv`, and `ideabench_clustering.json`, and records each file's SHA-256 in
`download_manifest.json`. A repeated command verifies and reuses the files. To reproduce an exact release explicitly,
pass `--revision <commit-sha>`.

For an offline Stage A comparison at production `standard` depth, pass `--depth standard` to `eval-step08 run`
and use a new output directory. The five IdeaBench references remain frozen and abstract-only: the adapter marks
search and full-text acquisition complete before Stage A, so this option does not fetch additional literature.
`standard` raises the paper-collision candidate cap from 0 to 150, but cannot create candidates when the five
references have no matching constructs, measures, or other qualifying evidence.
