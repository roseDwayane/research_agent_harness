# IdeaBench-style P1/P2 evaluation

The dataset is frozen before generation. Every target task supplies the same low-resource references to both protocols. Target titles, abstracts and gold ideas are never included in generator prompts. A shared topic and PICO are inferred from reference titles and abstracts only.

P2 first runs the existing Step 3 screening, Step 6 synthesis and Step 7 gap identification. Step 2 receives the frozen references instead of performing online search. Step 4 exports citation keys and bibliography; when author metadata is absent, a benchmark adapter writes a marked title/year registry and Anonymous BibTeX rather than inventing authors. Step 5 provides abstract-only context, so P2 cannot obtain extra scientific information unavailable to P1.

Every actual, distinct Step 7 gap gets one Step 8 hypothesis spec. There is no repeated-gap allocation and no score-based selection. Each gap must cite at least two distinct supplied papers. A failed task is recorded rather than filled with invented evidence. Existing Step 8 generation code is unchanged.

The actual number of P2 gaps defines n for that task. P1 receives only that count, the shared research context and the same reference abstracts, and generates exactly n ideas in one prompt. It never sees P2 gaps or specs. P2 specs are compressed into idea paragraphs by the generator using the target-extraction template. The generation prompt is adapted from IdeaBench's procedure, not a verbatim Figure 1 reproduction.

An independent judge checks basic coherence, then ranks each system's n ideas together with the one gold idea. Authorship and gold identity are hidden in the prompt. Novelty and feasibility are assessed separately by default; significance and clarity are also available. A seeded shuffle followed by all n+1 cyclic rotations gives every idea every display position once. Python maps the anonymous ranking back to the gold rank and computes (rank - 1) / n, then averages across rotations.

P1 and P2 are summarized only on the same complete target pairs. Results are grouped by actual n, including P2 minus P1 within each group. The overall mean is descriptive: variable n differs from original IdeaBench's fixed-n protocol. Missing generation, incoherent output, invalid rankings and other failures are visible; they are not silently assigned zero. This evaluates output quality under equal information, not equal inference cost.

With --rubric, every saved P2 spec is independently scored on the selected 10 ResearchAgent-derived Problem/Method metrics, one metric per call. Required inputs are step8_hypothesis.json and step0_session_config.json. Each benchmark branch also contains step7_gaps.json, step3_shortlist.json, step6_sota.json and step6_sota_review.md. Rubric files are side outputs and never enter generation or revision. Rubric scoring remains available even if relative ranking fails.

Each spec receives step8_rubric_scores.json and step8_rubric_report.md. The experiment also writes rubric_summary.json with per-spec results and both spec-weighted and target-weighted overall means. Scores reflect assessment of a proposal, not empirical confirmation of scientific validity or feasibility. The single judge has not yet been calibrated to expert human ratings.

Run the complete experiment from the repository with the project Python:

```powershell
.\.venv\Scripts\python.exe -m scholar_research eval ideabench-run `
  --dataset eval_runs/ideabench/subset_v1 `
  --out eval_runs/ideabench/experiment_v1 `
  --rubric --max-tokens 8192 --num-ctx 32768
```

Use --limit 1 with a separate output folder for a smoke test. --phase generate runs generation alone; --phase rank evaluates saved ideas; --phase rubric runs absolute evaluation alone. Use the same --rubric and configuration options when resuming. The manifest freezes the dataset hash, model settings, prompts, protocol and seed; changed contracts require a new output folder. Repeating a command resumes saved outputs and LLM cache entries.

The experiment writes experiment_manifest.json, tasks/{target_id}/context.json, P1_ideas.json, P2_ideas.json, P2/pipeline/Steps 0–7, P2/spec_XX/Step 8 specs and their contexts, coherence records, per-metric ranking records, P1_scores.json and P2_scores.json. summary.json contains paired results and n-stratified deltas; report.md describes interpretation and limitations. errors.json and task error files record failures. costs.json aggregates observed calls, cache hits, validation attempts, token counts and elapsed call time; incomplete failed-call accounting makes it unsuitable as an exact billing estimate.

This implementation uses OpenAlex-sourced references and their type mappings, skips full-text background-citation filtering, and uses the supplied cutoff registry as metadata rather than independent proof of zero contamination. Gold extraction and ranking currently use the same Gemma model, which is disclosed as a possible source of style bias. These differences must accompany any reported benchmark result.

Method source: https://arxiv.org/abs/2411.02429.
