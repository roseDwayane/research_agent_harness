# Step-level evaluation

Step-level evaluation of the pipeline, one folder per step. Evaluators call the formal engine in
`scholar_research/`. Steps 2–3 use LitSearch; Step 6 evaluates the state-of-the-art review
(`step6_sota_review.md`); Steps 5 and 7 have deterministic contract checks so far.

```text
evaluation/
├── eval_common.py, run_batch.py, topics.toml   shared: batch layout, topic batches (Steps 1–N)
├── step02/            Step 2: LitSearch live retrieval and gold recall
├── step03/            Step 3: screening/ranking and official BM25 candidates
├── step05_fulltext/   Step 5 contract check
├── step06_sota/       Step 6: contract / numeric checks, AutoSurvey, MetaSyn (+ metasyn.toml)
├── step07_gaps/       Step 7 contract check
├── step08/            Step 8: independent rubric and IdeaBench P1/P2 evaluation
├── experiments/       local one-off scripts (Step 6 variants, Step 7 reruns) — gitignored, not shared
└── runs/{batch}/      sessions/ + eval/ (not in git)
```

## Step 02 / Step 03：獨立執行並自動評估

以下使用 **Git Bash**，在 repo 根目錄執行。兩階段各有獨立入口；
每題保存結果後自動重算評估，失敗與尚未完成題目保留在固定題目分母中。
正式搜尋與篩選仍呼叫 `scholar_research/steps/`。

```bash
./.venv/Scripts/python.exe -m pip install -e ".[litsearch]"
```

API 金鑰及模型連線讀取 repo 根目錄的 `.env`／`research.toml`。
搜尋支援 `S2_API_KEY`、`OPENALEX_API_KEY`；Ollama 使用
`SCHOLAR_LLM_PROVIDER=ollama`、`SCHOLAR_LLM_BASE_URL`、`SCHOLAR_LLM_MODEL`。
Step 2 Mode A 不使用生成模型；Mode B 和 Step 3 需要模型。

### Step 02：搜尋 → 自動評估

```bash
./.venv/Scripts/python.exe -m evaluation.step02.run --mode A --limit 1 --out eval_runs/verification/step02
```

Mode A 使用原始 query；`--mode B` 會先執行正式 Step 1 建立查詢。
預設題目集為 `evaluation/step02/subset_v1.json`；`--subset` 可指定另一份固定題目集。
`--mapping` 可讀取已保存的 gold map，省略 gold ID API lookup。
拿掉 `--limit 1` 可跑完整題目集，但需用新的 `--out`，避免變更已固定的實驗設定。

輸出在 `--out`：

- `subset_v1.json`、`gold_id_map.json`、`run_contract.json`：固定題目、對應與設定。
- `sessions/`：各題正式 Step 2 的候選與 trace。
- `results.jsonl`、`summary.json`：原執行紀錄與基本 set recall。
- `evaluation/results.jsonl`、`evaluation/summary.json`、`evaluation/report.md`、
  `evaluation/provenance.json`：自動完整 gold 評估；Step 2 重點看
  `completion.step2`、direct-search recall、final set recall、snowball gain 和 provider 狀態。
  共用的完整評估格式也會包含尚未執行的 Step 3 欄位，不能把它解讀為已測 Step 3。

### Step 03：讀 Step 2 固定候選 → 評分 → 自動評估

先完成上面的 Step 2，再執行：

```bash
./.venv/Scripts/python.exe -m evaluation.step03.run --source step02 --input eval_runs/verification/step02 --out eval_runs/verification/step03
```

從 Step 2 保存的題目、gold map 和結果建立輸入快照；不重新呼叫搜尋 API 或 gold lookup。
每份非失敗候選都執行正式 Step 3，**不依 gold 是否命中決定要不要評分**。
評分必須覆蓋所有候選且不得含缺失分數 fallback，才算成功。
Step 2 目錄維持原樣，Step 3 分開保存：

- `sessions/`：固定輸入快照與 Step 3 的完整分數、shortlist。
- `rank.jsonl`、`rank_summary.json`：排名結果。
- `evaluation/`：完整 gold 評估；查看 `completion.step3`、relevance／composite
  Recall@k、MRR、nDCG@10、shortlist recall、gold retention。

### 自動串接兩階段

```bash
./.venv/Scripts/python.exe -m evaluation.step02.run --mode A --limit 1 --out eval_runs/verification/step02 --then-step3 --step3-out eval_runs/verification/step03
```

順序是 Step 2 → Step 2 評估 → Step 3 → Step 3 評估。
成功結束回傳 0；有題目執行失敗回傳非 0。部分 provider 失敗等診斷仍需閱讀報告，
回傳 0 不代表 recall 或研究品質達標。
相同設定可續跑；改題目、候選、模型或 prompt 時使用新的輸出目錄。
Step 3 會核對輸入與完成輸出 hash。`--out` 不可與 `--input` 相同或互相嵌套。

### Step 03：官方 BM25 固定候選 → 自動評估

這條流程跳過 Step 2 API 搜尋。首次需要下載官方資料、建立 BM25 baseline，
並從已有的 80 題 run 取得凍結的 topic／PICO。將 `--old-source` 換成自己的 run：

```bash
./.venv/Scripts/python.exe -m evaluation.step03.official_bm25 download
./.venv/Scripts/python.exe -m evaluation.step03.official_bm25 baseline
./.venv/Scripts/python.exe -m evaluation.step03.official_bm25 prepare --subset evaluation/step02/subset_v1.json --old-source eval_runs/litsearch/modeB_step3_retry6_v2
./.venv/Scripts/python.exe -m evaluation.step03.run --source bm25 --out eval_runs/litsearch/official_bm25_step3_80
```

最後一條指令同時執行 Step 3 與 evaluation，不需再手動執行 `evaluate`。
已有 prepared 候選時，直接執行最後一條；加 `--limit 1` 可先驗證第一題，
此時報表分母只包含該一題。移除 limit 可續跑完整 prepared 題目集。
BM25 scorer 沿用原實驗固定的 Ollama `qwen3.8` 設定。
輸出為 `comparison_summary.json`、`comparison_per_question.jsonl` 和各題 sessions。

完整 597 題入口也會自動評估；完成 download／baseline 後可直接使用，
不需要 80 題的 prepare，但會對每題重新執行 Step 1：

```bash
./.venv/Scripts/python.exe -m evaluation.step03.full597 --date 2026-10-13
```

上述日期沿用原實驗，續跑不得改變。新實驗可另指定日期與新的 `--out`；
此入口使用 Windows 檔案鎖。全部 597 題完成前，結果僅視為部分結果。

### 檢查程式與階段交接

```bash
./.venv/Scripts/python.exe -m pytest tests/test_eval_stage_commands.py tests/test_eval_litsearch.py tests/test_litsearch_full_gold.py tests/test_official_bm25.py tests/test_litsearch_full597.py -q
```

測試使用假的 provider／model，不驗證遠端連線；上面的實際執行指令才會呼叫服務。
舊的 `scholar_research.cli eval litsearch --mode A/B/A3/B3` 保留相容性；
A3／B3 的歷史 gold-hit gating 與新獨立入口不同，新實驗使用本節的 `step02.run`／`step03.run`。

詳細協定：[完整 gold 指標](step02/litsearch-full-gold-evaluation.md)、
[官方 BM25](step03/litsearch-official-bm25-step3.md)、
[597 題實驗](step03/litsearch-full597-run.md)。

## Step 08：假說生成、IdeaBench 比較與獨立 rubric

程式位於 `evaluation/step08/`：`runner.py`／`metrics.py`／`render.py` 執行 rubric；
`ideabench/` 建立固定資料集、執行 P1／P2 比較；`prompts/` 保存 6 份評估指令。
正式假說生成仍呼叫 `scholar_research/steps/s8_hypothesis.py`。

### 環境設定

在 repo 根目錄的本機 `research.toml` 分開設定 generator 與 judge。
以下使用本機 Ollama 位址；遠端服務請換成自己的 base URL：

```toml
[llm]
provider = "ollama"
model = "qwen3.8"
base_url = "http://127.0.0.1:11434"
num_ctx = 32768
max_tokens = 16384
temperature = 0.0
think = false
request_timeout = 300

[judge]
provider = "ollama"
model = "gemma4:31b"
num_ctx = 32768
max_tokens = 2048
temperature = 0.0
think = false
request_timeout = 600
```

Judge 未指定 base URL 時繼承 generator；必須明確指定 judge model，預設禁止
與 generator 相同名稱。這組模型／參數也是已保存的歷史實驗設定；不代表遠端服務目前已驗證可用。

也可使用本機 `.env` 的 `SCHOLAR_LLM_PROVIDER`、`SCHOLAR_LLM_MODEL`、
`SCHOLAR_LLM_BASE_URL`、`SCHOLAR_LLM_NUM_CTX`、`SCHOLAR_LLM_MAX_TOKENS`、
`SCHOLAR_LLM_TIMEOUT`、`SCHOLAR_LLM_THINK`，以及對應的 `SCHOLAR_JUDGE_*`。
環境變數覆寫 TOML，`.env` 不覆寫已存在的 shell 環境變數。
使用 Anthropic 時則設定對應 provider 與 `ANTHROPIC_API_KEY`。
`.env`、本機 `research.toml`、虛擬環境與評估輸出均不納入 Git；
可分享的設定範本為 `research.toml.example`。

### 評分已生成的 Step 8 session

以下為 Git Bash 指令。先列出指標，不會呼叫模型：

```bash
./.venv/Scripts/python.exe -m scholar_research.cli eval step8-rubric --list-metrics
```

將下面兩個 placeholder 換成實際 session 上層目錄與資料夾名稱：

```bash
./.venv/Scripts/python.exe -m scholar_research.cli eval step8-rubric --root "SESSION_PARENT" --session "SESSION_FOLDER"
```

此入口只評估既有假說，不重新執行 Step 8。必要輸入為 `step0_session_config.json`
和 `step8_hypothesis.json`；Step 3 shortlist、Step 6 SOTA、Step 7 gaps 提供評審背景。
單一 session 缺少部分背景時會標記 unavailable；完整評估應提供這些檔案。
每項指標獨立呼叫 judge，評 Problem／Method 各 5 項、每項 1–5 分，Python 計算平均。
輸出同一 session 的 `step8_rubric_scores.json`、`step8_rubric_report.md`，
分數不回灌 Steps 8／9，也不觸發 revise。

### IdeaBench：生成完成後自動排名與評估

若尚無固定資料集，先建立。這會查詢外部論文 API 並抽取 gold idea；
預設使用 OpenAlex，API 設定沿用正式 providers。

```bash
./.venv/Scripts/python.exe -m scholar_research.cli eval ideabench-build --out eval_runs/ideabench/subset_v1 --m 20 --low-k 5 --source openalex
```

已有 `subset_v1` 時直接執行以下指令，先用一題確認真實模型可以完成流程：

```bash
./.venv/Scripts/python.exe -m scholar_research.cli eval ideabench-run --dataset eval_runs/ideabench/subset_v1 --out eval_runs/verification/step08 --limit 1 --rubric --max-tokens 16384 --num-ctx 32768
```

P1 從固定 references 直接生成 ideas；P2 使用相同 references 執行正式
Steps 3／4／6／7／8，每個有效 gap 產生一份 spec。Step 2 不做線上搜尋，
Step 5 採摘要背景。獨立 judge 進行匿名 coherence／ranking，另評 P2 rubric。
這裡的 P1／P2 是兩種實驗流程，不是 Step 1／2。

去掉 `--limit 1` 並換新的輸出目錄可跑完整資料集。
續跑同一實驗時維持相同參數、資料、模型與 prompts；改設定需換新 `--out`。
也可用 `--phase generate`、`--phase rank`、`--phase rubric` 分階段執行，
只重跑 rubric 時仍需保留 `--rubric` 及原實驗的設定。

輸出位於 `--out`：

- `experiment_manifest.json`：固定資料、模型、prompts 與實驗設定。
- `summary.json`、`report.md`：P1／P2 成對排名結果；Insight Score 為相對排名指標。
- `rubric_summary.json`：P2 的 1–5 分絕對評分，與 Insight Score 分開解讀。
- `costs.json`：記錄到的模型用量與時間。
- `tasks/`：各題 ideas、pipeline 輸出、spec、排名和 rubric 原始結果。
- `errors.json` 與各題錯誤檔：查看失敗／未完成項目，不以檔案存在就判定成功。

**Working together.** Each `stepNN_<name>/` folder has one owner (Steps 5–7: Chih-Yun Lin). Code that only one
step uses stays in that step's folder; something moves to the top level only when two steps really need it and
both owners agree. Results go under `runs/{batch}/eval/{session}/stepNN/` so steps never overwrite each other (Step 6's existing
LLM-judge outputs — `autosurvey/`, `metasyn/` directly under `eval/{session}/` — predate this and stay where
they are; batches made before 2026-10-18 also keep `contract_results.json` etc. there).
Branch from `eval/main` as `eval/<step>-<topic>` and open PRs back into it.

Steps 2–3 use the module commands above. Steps 5–7 run from the repo root as `python evaluation/<step folder>/<script>.py`; each adds `evaluation/` to
`sys.path` itself where it needs `eval_common` / `run_batch`.

Two families of measures:

| | measure | how | reference answer |
|---|---|---|---|
| **AutoSurvey** ([NeurIPS 2024](https://github.com/AutoSurveys/AutoSurvey)) | Structure, Relevance (1–5) | LLM judge, AutoSurvey rubric verbatim; Structure whole-survey **and** per section | none |
| | Citation recall / precision | AutoSurvey NLI prompt verbatim, `Judge.citation_quality` algorithm; evidence = cited paper's abstract + 3 retrieved full-text windows (AutoSurvey: abstract only) | the cited paper itself |
| **Citation coverage** | share of full-text papers cited in the themes | deterministic (`check_step6_contract.py`) | none |
| **MetaSyn** ([THUIR/MetaSyn](https://github.com/THUIR/MetaSyn)) | direction accuracy, insights_consistency (official, primary); item-level insight coverage (ours, supplementary) | LLM judge against the source review | MetaSyn Key_Insights / Effect_Direction |

**Judges.** Everything so far is a feasibility run with one local judge (`gemma4:31b` on Ollama).
Formal experiments will use AutoSurvey's API judges (AutoSurvey: mean of GPT-4, Claude, Gemini) as far as
possible. The judge clients are currently Ollama-only (`OllamaChat`); an API client is still to be added.

## Inputs: two kinds of batch

**Topic batches** (`run_batch.py`) — Steps 1–6 run end to end per topic, each topic in a fresh session
(own folder, own HTTP/LLM cache), one `Config` per batch recorded in `batch.json`, auto checkpoints
(CP1 approve, CP2 no borderline rescue), no manual edits, failures kept in `runs.jsonl`.
`topics.toml` (5 topics, batch `smoke1`) is a smoke test: it shows the flow runs, not how good the reviews are.

**MetaSyn fixed-input batches** (`metasyn_prepare.py`) — only Step 6 runs, on the papers the source
review included, so retrieval and screening play no part in the score:

| session file | built from |
|---|---|
| `step0_session_config.json` | MetaSyn Topic + PI/ECO (Intervention, or Exposure when there is none) |
| `step3_shortlist.json` | MetaSyn `matched_corpus_ids` minus `source_review_corpus_ids`, all included |
| `step4_*` | real Step 4 (deterministic, no network) |
| `step5_full_text/{key}.md` | MetaSyn corpus: abstract + PMC sections when available |
| `step6_*` | real Step 6, pipeline model from `metasyn.toml` |

Ground truth goes to `eval/{review}/ground_truth.json` only, never into the session Step 6 reads.
Papers that cannot enter Step 6 (title only, or no authors after a PubMed lookup) are listed in
`eval/{review}/input_report.json`.

## Run

```powershell
$env:PYTHONUTF8 = "1"

# topic batch: Steps 1–6 only (produces sessions, evaluates nothing)
python evaluation/run_batch.py --topics evaluation/topics.toml --batch-id smoke1 [--resume]

# Step 6 deterministic checks (manifest, contract, citation coverage, numeric claims) → eval/{id}/step06/
python evaluation/step06_sota/run_checks.py --batch evaluation/runs/<batch>
python evaluation/step06_sota/aggregate.py  --batch evaluation/runs/<batch>   # protocol checks + averages

# MetaSyn batch: one review at a time, then register the batch
python evaluation/step06_sota/metasyn_prepare.py --data-dir <dir with test.parquet and corpus/> --review-id 255 --batch-id metasyn_v2
python evaluation/step06_sota/metasyn_prepare.py --batch-id metasyn_v2 --register-only

# AutoSurvey (either kind of batch); naive baseline first if it is to be compared
python evaluation/step06_sota/naive_baseline.py   --batch evaluation/runs/<batch>
python evaluation/step06_sota/autosurvey_eval.py  --batch evaluation/runs/<batch> [--judges <m1> <m2> <m3>] \
    [--citation-sources fulltext abstract] [--citation-controls] [--max-claims 20]
python evaluation/step06_sota/autosurvey_controls.py --batch evaluation/runs/<batch> [--level section] [--only <ids>]

# MetaSyn scoring (+ damaged forms, + MetaSyn's own baseline reports judged by the same judge)
python evaluation/step06_sota/metasyn_eval.py --batch evaluation/runs/<batch> [--judge <m>] --controls \
    --baselines gptresearcher__gpt-5.4__ma_retriever rag__gpt-5.4__ma_retriever

# Step 5 / Step 7 deterministic contract checks (exit 1 on any failure) → eval/{id}/step{05,07}/contract.json
python evaluation/step05_fulltext/check_step5_contract.py --batch evaluation/runs/<batch>
python evaluation/step07_gaps/check_step7_contract.py   --batch evaluation/runs/<batch>

```

`OPENALEX_MAILTO` / `S2_API_KEY` / `UNPAYWALL_EMAIL` are read from the environment as usual.

## AutoSurvey: Structure, Relevance, Citation

| | AutoSurvey | here |
|---|---|---|
| criteria, judging prompt, NLI prompt | — | copied verbatim (`autosurvey_prompts.py`, MIT) |
| judged text | whole survey | Step 6 review without Methodology Legend / Paper–Theme Mapping / Papers lines (`autosurvey_common.step6_survey`); English-only since harness `e4f37a6` (smoke1 predates it and is bilingual) |
| judges | GPT-4, Claude-3-Haiku, Gemini-1.5-Pro, mean | `--judges`, mean of valid scores (local Ollama for now) |
| score parsing | first integer in the reply | bare 1–5 only, else `no_result` (not counted) |
| Structure per section | — | `Structure_section` (Step 6 only): same prompt on each section (Executive Summary, Themes, Cross-Theme Analysis), mean over sections |
| citation recall / precision | NLI-by-LLM on abstracts | same algorithm and prompt; evidence = abstract + 3 best-matching full-text windows (`fulltext_retrieval.py`, below); `--citation-sources abstract` gives AutoSurvey's original; bib keys instead of `[n]` |
| extra | — | recall / precision by citations per claim (1 / 2 / 3+), `citation_density`, `all_sentence_recall` (uncited sentences count as unsupported), invalid keys; `--citation-controls`: swap / perturb validity controls |
| baseline | naive RAG | `naive_baseline.py`: pipeline model, one prompt, same papers, length matched to Step 6 |

Output: `eval/autosurvey_summary.md` (means, paired step6 − naive with bootstrap 95% CI, held-out scope on MetaSyn
batches), per topic `eval/{topic}/autosurvey/{step6,naive}.json`.

**Citation evidence: full text.** AutoSurvey judges a citation against the cited abstract. Step 6 reads full text,
so abstracts underestimate it: on metasyn_v2 (step6) claims citing only full-text papers get recall 0.54 from
abstracts and 0.83 with full text; claims citing abstract-only papers are unaffected (0.86 / 0.86). The retrieval
(~120-word windows, BM25 + claim-number match, top 3, abstract always included) was tuned on the 6 dev reviews only
and frozen on 2026-10-14; it was ported unchanged from the feasibility scripts, and the ported code reproduces their
364 metric values exactly from the same LLM cache. Controls (abstract source, 26 reviews): swapped citations →
recall 0.04; numbers / direction words changed in the claim → 0.80 → 0.07. Recall and precision are also reported
by citations per claim, because precision is harder to earn with many keys and the systems cite differently.
A "partial support" metric was tried on the dev reviews and not adopted (not validated; not to be reported).

**Structure is reported whole-survey and per section.** Whole-survey Structure only catches gross damage;
per section it tracks damage. Discrimination controls (`autosurvey_controls.py`, gemma4:31b, English-only
metasyn_v2, the 6 dev reviews; original / damaged pairs, "lower in" = original scored higher):

| damage (whole survey, 6 reviews) | Coverage | Structure | Relevance |
|---|---|---|---|
| original | 4.83 | 5 | 5 |
| themes reversed | 4.83 | **5** (0/6 lower) | 5 |
| last Theme followed by Theme 1 again | 4.83 | 3 (6/6) | 5 |
| Theme 1 sentences shuffled | 4.83 | **5** (0/6) | 5 |
| all sentences shuffled | 4.5 | 1 (6/6) | 4.5 |
| half the themes removed | **3.83** (6/6) | 4.67 | 5 |
| Executive Summary only | **3.67** (4/6) | 5 | 4.5 |
| Theme 2 from another topic | 2 | 2.5 | **2** (6/6) |

| form (per section, 35 sections) | Structure |
|---|---|
| original | 5 |
| no subheadings | 4.91 (lower in 3/35) |
| paragraphs repeated | 2.86 (lower in 35/35) |
| sentences shuffled | 1.83 (lower in 34/35) |

So with this judge: Structure reacts to repetition and shuffling (per section clearly; whole survey only to gross
damage), Relevance only to off-topic content, Coverage to removed content but by about one point. The earlier smoke1
run (bilingual Step 6, 3 reviews / 19 sections) showed the same pattern, except that there Coverage barely moved.

**Results, metasyn_v2** (26 reviews, `eval/autosurvey_summary.md`): with gemma4:31b every original scores at the
ceiling — Structure 5 and Relevance 5 for all 26 Step 6 and all 26 naive surveys, Structure 5 for all 145 Step 6
sections, Coverage 5 except 3 surveys at 4. The judge separates damaged from intact text (above) but not one
intact review from another, so these criteria cannot rank systems with this judge; they are reported, not
compared. Citation (full-text source, step6 − naive, paired 95% CI, 26 reviews): recall 0.85 vs 0.92
(−0.06 [−0.09, −0.04]), precision 0.68 vs 0.85 (−0.17 [−0.22, −0.12]), citation density 0.54 vs 0.46
(+0.08 [+0.00, +0.17]), all-sentence recall 0.46 vs 0.42 (n.s.). The precision gap is largest for claims citing
3+ keys (held-out: 0.34 vs 0.47). Full-text controls: swap recall 0.05 / 0.07, perturb 0.89 → 0.08 / 0.94 → 0.04
(step6 / naive, held-out).

## Coverage

Two different questions, kept apart:

| | citation coverage | insight coverage |
|---|---|---|
| question | are the full-text papers actually used? | does the review state the source review's findings? |
| method | deterministic, `check_step6_contract.py` → `coverage_rate` | LLM judge, `metasyn_eval.py` (MetaSyn batches only) |
| definition | denominator: Step 5 `access_level` in `full-text-pdf` / `full-text-html`; numerator: those cited in any Theme's prose or Key Results table (Papers line excluded, each key once) | mean score over answerable synthesis Key Insights (below) |
| pass | ≥ 0.8 | — |

The denominator includes `full-text-html` because the harness fetches arXiv HTML before PDFs.

## MetaSyn

**Primary metrics: MetaSyn's own** (decided 2026-10-15, to follow the paper): conclusion **direction accuracy**
and **`insights_consistency`**, prompts copied verbatim from `src/metasyn/llm_client.py`. The paper validates both
against humans (arXiv 2606.17041, App. F: 30 instances, 8 annotators; direction 91.2% evaluator–human agreement,
ρ = 0.82; insights "positive but less strong", supports system-level comparison) with **GPT-5.5, temperature 0**
as evaluator (App. G.3). Using the same prompts, judge and temperature lets us cite that validation instead of
annotating ourselves; the limitation is that they validated on systematic-review reports, not thematic reviews.
MetaSyn's retrieval / screening / criteria metrics do not apply (fixed input, Step 6 only), and its PRISMA
structure quality does not fit Step 6 (structure: AutoSurvey Structure instead).

**Supplementary: item-level insight coverage (ours, not MetaSyn's).** The official score is one holistic 0–1 band
(most reports land on 0.4), counts pooled meta-analysis numbers Step 6 cannot produce, goes through a verbatim
extraction step first, and gives nothing per item to inspect. Ours, per review (`metasyn_eval.py`):

1. **classify** each Key Insight → `synthesis` / `pooled_estimate` / `meta_analysis_specific` / `external` / `generic`,
   with a number-free restatement for synthesis items. Written once to `insight_classes.json` and reused, so it
   can be corrected by hand. Only `synthesis` items are scored (pooled meta-analysis numbers cannot come from Step 6).
2. **digest**: is the claim's evidence in Step 6's per-paper digests? supported / partial → *answerable*.
   Caveat: the digests are Step 6's own first stage, so this filter depends on the system under test (it hides
   what the digests missed, and changes with the pipeline model); `coverage_all` (no answerable filter) does not.
3. **coverage**: does the full review text state the claim? covered 1 / partial 0.5 / not_covered 0 / contradicted 0,
   with an exact quote that is checked. `coverage_all` = mean over synthesis claims; `coverage_answerable` = mean
   over answerable ones.
4. **official**: the two primary metrics above.

**Judge validation without human labels** (`metasyn_judge_agreement.py`): run `metasyn_eval.py` once per judge
(e.g. GPT-5.5, Claude, Gemini), then

```powershell
python evaluation/step06_sota/metasyn_judge_agreement.py --batch evaluation/runs/<batch> --judges <m1> <m2> <m3>
```

reports agreement between judges (coverage, digest and direction verdicts: exact agreement, Cohen's κ per pair,
Fleiss' κ; `insights_consistency`: Spearman ρ per pair) and convergent validity (Spearman ρ of insight coverage vs
`insights_consistency` over (review, system), bootstrap CI over reviews). Control forms are excluded (easy cases).
With gemma4:31b alone (metasyn_v2, 26 reviews × 3 systems): ρ = 0.51 [0.30, 0.66] for `coverage_all`,
0.38 [0.12, 0.60] for `coverage_answerable` — `coverage_all` tracks the official score better.
Together with the controls and the quote check, this is the evidence for the supplementary measure; no human
annotation is planned.

`--controls` also scores half the themes removed, Executive Summary only, and another topic's review
(off-topic must score 0). `--baselines` judges MetaSyn's published reports for the same reviews.

**Split.** 26 test reviews so far: 6 dev (255, 356, 225, 243, 324, 70) used to tune the judge prompts
(topic anchoring, the `generic` class, the uncertainty rule for `contradicted`, last-JSON parsing), then frozen;
20 held-out. The dataset has 86 test reviews.

**Results so far** (`runs/metasyn_v2`, pipeline qwen3.8, judge gemma4:31b — feasibility, not the paper's judge; 26 reviews):

| system | direction accuracy | insights_consistency | coverage_all | coverage_answerable |
|---|---|---|---|---|
| Step 6 | 14/26 | 0.35 | 0.45 | 0.54 (held-out 0.57) |
| GPT-Researcher (gpt-5.4) | 17/26 | 0.45 | 0.50 | 0.57 (0.56) |
| RAG (gpt-5.4) | 17/26 | 0.39 | 0.49 | 0.61 (0.63) |

Paired 95% CIs between systems include 0 (insight coverage). Controls: off-topic 0 in 26/26; Executive Summary only
drops modestly; half the themes removed does not drop (Key Insights are conclusion-level). The insight classes
are still as gemma4 produced them (`frozen: false`).

## Step 6 variants (Consensus / Debates)

Fixed-input A/B on the same 26 MetaSyn sessions: only the Step 6 synthesis is re-run (per-paper digests are
cache hits, byte-identical), each variant from its own git branch checked out as a worktree, so
`eval/step6-smoke` is never changed.

| variant | branch (worktree) | batch | insight cov. | direction | words |
|---|---|---|---|---|---|
| original | `eval/step6-smoke` | `metasyn_v2` | 0.536 | 14/26 | 1718 |
| no Debates | `exp/step6-no-debates` (`../harness_exp_nod`) | `metasyn_v2_nod` | 0.565 | 16/26 | 1464 |
| no Consensus / Debates | `exp/step6-no-consensus-debates` (`../harness_exp_nocd`) | `metasyn_v2_nocd` | 0.543 | 17/26 | 1356 |
| **C**: no C/D + explicit Diverging Findings | `exp/step6-diverging` (`../harness_exp_div`) | `metasyn_v2_div` | 0.554 | 17/26 | — |

Removing Debates is what stops Step 6 hedging Positive questions to Mixed (7 → 4 of 15); Consensus makes no
measurable difference. Removing Debates also removes most conflict content Step 7 draws on; variant C moves it
into Cross-Theme Diverging Findings and recovers it (Step 7 gaps built on conflicting findings, 10 reviews:
original 9, no C/D 5, C 9 by keyword; by reading, ~3–5 / 2 / 6). Single runs; undecided.
Reports: `runs/metasyn_v2_*/eval/ab_*.md`, `runs/metasyn_v2_div/eval/step7_ABC.md`.

Step 7 for these comparisons runs with `exp/step7-counter-evidence` (`../harness_exp_s7ce`), which makes
`counter_evidence` required (reported upstream; without it the field is always omitted).

Adopting a variant changes the Step 6 format: `check_step6_contract.py` requires Consensus / Debates per theme
and will fail it.

## Discrimination controls (recommended)

A rubric that works with one judge may not with another (gemma4 gives whole-survey Structure 5 to a reordered
review). Whenever the judge or a prompt changes, rerun

```powershell
python evaluation/step06_sota/autosurvey_controls.py --batch evaluation/runs/smoke1 --judge <m> [--level section]
python evaluation/step06_sota/metasyn_eval.py --batch evaluation/runs/<metasyn batch> --judge <m> --controls
```

and for MetaSyn re-check the frozen prompts on the 6 dev reviews and redo `insight_classes.json`.

## Files

| File | Role |
|---|---|
| `eval_common.py` | shared paths and helpers (batch layout, runs.jsonl, run_script) |
| `run_batch.py`, `topics.toml` | topic batch: runs Steps 1–N per topic and records the run; topics + pipeline model settings |
| **`step05_fulltext/`** | |
| `check_step5_contract.py` | Step 5 contract: files ↔ shortlist, frontmatter, access-level rules, truncation / duplicates, access log |
| **`step06_sota/`** | |
| `metasyn_prepare.py`, `metasyn.toml` | MetaSyn fixed-input sessions; pipeline settings for them |
| `metasyn_eval.py`, `metasyn_prompts.py` | MetaSyn scoring (classify / digest / coverage / official) |
| `metasyn_judge_agreement.py` | agreement between judges + convergent validity of insight coverage (no human labels) |
| `autosurvey_eval.py`, `autosurvey_prompts.py`, `autosurvey_common.py` | AutoSurvey Structure (whole + per section) / Relevance / Coverage + citation NLI |
| `fulltext_retrieval.py` | full-text evidence windows for the citation NLI (frozen v2) |
| `autosurvey_controls.py` | AutoSurvey discrimination controls (whole survey; `--level section`) |
| `naive_baseline.py` | one-prompt survey from the same papers |
| `run_checks.py` | runs make_manifest → check_step6_contract → check_numeric_claims for a batch → `eval/{id}/step06/` |
| `make_manifest.py` | Step 6 manifest from `step5_full_text/*.md` frontmatter and the `.bib` |
| `check_step6_contract.py`, `check_numeric_claims.py`, `step6_common.py` | deterministic checks (copied unchanged from the top-level `evaluation/`) |
| `aggregate.py` | batch protocol checks (same config / prompts, auto checkpoints, Step 6 untouched) + deterministic averages → `eval/summary.{json,md}` |
| **`step07_gaps/`** | |
| `check_step7_contract.py` | Step 7 contract: raw LLM output vs tool schema (omitted fields), ranking / composite, evidence keys, md ↔ json |

## History

Step 6 was first judged with ScholarQABench's Prometheus rubrics (organization / coverage). This was dropped:
`prometheus-bgb-8x7b-v2.0` copied the rubric text instead of scoring above ~9–10k prompt tokens and did not
react to damaged inputs, and without ScholarQABench's expert reference answers the setup did not match theirs.
Its scripts were first retired and then deleted on 2026-10-15: `run_prometheus.py`, `prometheus_eval.py`,
`prepare_prometheus_input.py`, `prometheus_sections.py`, `judge_controls.py`, `judge_validity.py`,
`step6_rubrics.json`. Before deletion, the section damage (`no_subheadings` / `repeated` / `shuffled`, same seed)
and the section split that `autosurvey_controls.py --level section` needed were moved into that file.
`aggregate.py` was kept for its protocol checks and deterministic averages; its Prometheus columns were removed.
The Prometheus run outputs stay in `runs/smoke1` as a record (`eval/prometheus_status.json`, `eval/summary.*`,
`eval/{topic}/prometheus*`, `eval/{topic}/controls/gemma4-31b/`, `logs/*.prometheus.log`). The Prometheus models
on the shared Ollama server were not removed.
