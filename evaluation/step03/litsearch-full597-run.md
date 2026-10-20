# LitSearch 全部 597 題：統一初始化與固定 top-100 Step 3

本實驗使用已完成的官方 BM25 全 corpus 結果。597 題均重新執行既有 Step 1，從官方原始 query 建立 topic、PICO、field_type 與五條查詢式；不沿用原 80 題的初始化結果。

初始化呼叫只提供原始 query 與固定評估日期，不提供 gold IDs、gold paper 或候選論文。五條查詢式保存供追查，但不實際呼叫 API：Step 2 一律注入原始官方 query 的 BM25 top-100，Step 3 對全部候選評分，不依 gold 命中與否跳過題目。

## 執行與續跑

在 repo 根目錄執行：

```powershell
.\.venv\Scripts\python.exe -m evaluation.step03.full597 --date 2026-10-13
```

輸出目錄：`eval_runs/litsearch/official_bm25_step3_597`。原本 `official_bm25_step3_80` 保留。所有題目採同一固定評估日期，避免長時間執行跨日改變評分輸入。

同一指令可以續跑：完成題目按 hash 驗證後跳過，未完成題目可重用有效請求 cache。OS-held runner.lock 防止重複啟動兩個 worker。模型或 prompt 變動時，必須使用新的 `--out` 目錄。

## 設定

- Generator／scorer：qwen3.8，temperature 0、thinking off、num_ctx 8192、max_tokens 3072。
- Ollama 使用 IPv4 client，不修改電腦網路設定。
- Step 1：原 `s1_init` prompt；Step 3：原 `s3_criteria` 與 `s3_score` prompts。
- Step 3 每批 12 篇；composite 權重 relevance 0.50、quality 0.30、recency_impact 0.20。
- included 門檻 3.5；borderline 門檻 3.0。100 篇候選不觸發小集合降低門檻。
- 官方 corpus 僅取 title／abstract，沒有透過 API 補 authors、year、venue、citation count；Step 3 的原摘要字元限制維持 2500。
- 單一 worker；連續三次 transport 失敗即停止，保留 cache 與紀錄。

## 進度與結果檔

- `progress.json`：目前題目、階段、初始化完成數、Step 3 完成數、错误與本次執行時間；每批更新。
- `run_contract.json`：模型、參數、評估日期、prompt hash、資料與 BM25 結果 hash。
- `tasks.jsonl`：597 題的原始 query、gold IDs（評估側）與固定候選。
- `sessions/official_0001` 至 `official_0597`：每題獨立 session。
- `step0_session_config.json`、`step1_search_queries.md`：query-only 初始化。
- `step2_raw_papers.json`：固定 top-100。
- `prepared.json`：初始化耗時與固定輸入 hash。
- `step3_screening_all.json`、`step3_shortlist.json`、`step3_screening_results.md`：完整分數與入選結果。
- `completed.json`：成功完整評分 100 篇、無 fallback 分數、耗時與輸出 hash；沒有此標記不得視為成功。
- `.cache/llm/ledger.jsonl`、`ledger_attempts.jsonl`：cache／請求與已知 tokens、重試、時間；未知失敗用量另列。
- `comparison_per_question.jsonl`：逐題 BM25、relevance、composite 指標。
- `comparison_summary.json`、`report.md`：每題結束更新，包含 overall、hit-only、四種題型分組及 Step 1／Step 3 分開的用量。

## 如何解讀

模型指標在全部 597 題完成前均是暫時結果。未完成題目留在 overall 計零，report 不將其呈現成正式完整結果。

正式比較須分 inline／author-written 與 broad／specific：specific 主報 R@5／R@20，broad 主報 R@20。MRR、標準 binary nDCG@10 為 harness 補充指標。

此實驗評估我們整套 query 初始化＋Step 3 在官方固定候選上的排序能力；沒有執行原 Step 2 API 搜尋，也沒有重現官方 GPT-4o reranker。金標匹配由 corpus ID 與 Python 算術完成，不另呼叫 judge。

依前 80 題 Step 3 平均約 93 秒，597 題的 Step 3 約需 15.4 小時；初始化、網路與重試另加。這是估計，不是保證完成時間。
