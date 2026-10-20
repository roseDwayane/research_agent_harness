# LitSearch full-gold evaluation v2

The evaluation keeps every frozen question and every original gold paper. Unmapped gold is an unconfirmed hit counted as zero in headline metrics, not removed from the denominator. Mapping coverage and mapped-only recall remain separate diagnostics. This evaluation never sends gold information to Step 3 prompts.

For question q, G is the original gold set, M is the mapped subset, D is the direct-search set after year filtering, dedup and DOI enrichment before snowball, S is the final Step 2 set, and H is the actual Step 3 shortlist.

- Mapping coverage: numerator |M|, denominator |G|.
- Direct-search recall: numerator |G intersect D|, denominator |G|.
- Final Set Recall: numerator |G intersect S|, denominator |G|.
- Mapped-only recall: numerator |G intersect S|, denominator |M|; undefined if no mapped gold.
- Snowball gain: numerator |G intersect S| minus |G intersect D|, denominator |G|. Report the additional gold count separately.
- Shortlist recall: numerator |G intersect H|, denominator |G|.
- Gold retention: numerator |G intersect H|, denominator |G intersect S|. Undefined on Step 2 misses.
- Candidate retention: numerator |H|, denominator |S|. Undefined for an empty S.
- R@k: numerator gold hits in top k, denominator |G|, using all screened papers including excluded.
- MRR: reciprocal rank of the first gold hit, or zero. It has no gold-count denominator.
- nDCG@10: numerator binary discounted gain in top 10; denominator the ideal discounted gain for min(10, |G|) gold papers, including unmapped/missing gold.
- Step completion: completed questions divided by every frozen question. Step 3 completion requires the full Step 2 ID set to be scored and a shortlist output.
- Provider success/failure: successful/failed search queries divided by attempted search queries for that provider. These exclude DOI recovery and reference calls. Missing execution records are explicitly marked.

Headline aggregation is a macro arithmetic mean over all questions, including failures/skips as zero. Also report micro summed gold hits / summed gold counts; these differ when questions have multiple gold papers. Conditional diagnostics use only defined questions and always expose that question denominator. Per-question ratios and summary ratios retain numerator, denominator and value in JSON.

Gold category counts include included, borderline, excluded, not_scored and not_retrieved. Do not call failed or unexecuted Step 3 gold excluded. Loss reasons are gold counts, not mutually exclusive question counts. A provider miss means no confirmed raw hit in recorded data, and must be interpreted alongside provider failures/trace availability.

New Step 2 runs persist exact pre-snowball records and individual query success/failure in step2_gold_trace.json. Historical outputs may reconstruct D from found_via != snowball using final enriched metadata. Historical provider results can be inferred from completed query plans and source_failures, and are labelled inferred. Missing historical traces cannot prove a fine-grained loss cause; use not_in_step2_set instead of inventing one.

Offline re-evaluation entry point (no API or LLM calls):

```powershell
.\.venv\Scripts\python.exe -m evaluation.step02.rescore --source eval_runs/litsearch/modeA_s2 --subset eval_runs/litsearch/modeA/subset_v1.json --mapping eval_runs/litsearch/modeA_s2/gold_id_map.json --out eval_runs/litsearch/full_gold_v2/modeA
.\.venv\Scripts\python.exe -m evaluation.step02.rescore --source eval_runs/litsearch/modeB --subset eval_runs/litsearch/modeA/subset_v1.json --mapping eval_runs/litsearch/modeB/gold_id_map.json --out eval_runs/litsearch/full_gold_v2/modeB
```

Outputs: results.jsonl (all question details), summary.json (macro/micro, completion, categories, losses and provider counts), report.md (definitions and results), provenance.json (source file SHA256). Original experiment outputs are preserved. This is an evaluation rerun, not a fresh live retrieval or a retry of failed Step 3 generations.
