# LitSearch 官方 corpus BM25 與 Step 3 top-100 實驗

## 範圍

1. 下載官方 `query`（597 題）與 `corpus_clean`（64,183 篇），鎖定 Hugging Face revision；另存官方 BM25 原始碼的 commit 與 SHA256。
2. 使用官方 title＋abstract 格式、NLTK 斷詞、英文停用詞移除、Porter stemming、rank-bm25 BM25Okapi（k1=1.5、b=0.75、epsilon=0.25）與官方 NumPy 排序規則，計算完整題集 BM25 baseline。
3. 對目前凍結的 80 題，每題固定其 BM25 top-100，轉成新的 `step2_raw_papers.json`。不使用 API 搜尋、snowball，也不補入未找回的 gold。
4. 所有 80 題都執行原 Step 3，不依 gold 是否命中決定要不要呼叫模型。比較 BM25、relevance、composite，保留每題结果、tokens、時間與失敗紀錄。

這是官方協定的適配執行入口
Step 3 使用專案既有 qwen3.8。MRR 與標準 binary nDCG@10 是 harness 補充指標，官方核心比較為分組 Recall@k。

官方 title＋abstract 建索引使用字串作 dictionary key，因此完全相同文字會覆蓋成最後一個 corpus ID；本入口保留此行為，另報告 raw／indexed 論文數。不要把這個 baseline 與每題 API 候選內的簡易 BM25 混為一談。

## 指令（在 repo 根目錄依序執行）

套件備妥後依序執行以下指令，前一階段成功後再執行下一階段；後續重跑沿用已凍結資料與完成題目的 cache。獨立執行與自動評估入口見 [evaluation README](../README.md)。

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[litsearch]"
.\.venv\Scripts\python.exe -m evaluation.step03.official_bm25 download
.\.venv\Scripts\python.exe -m evaluation.step03.official_bm25 baseline
.\.venv\Scripts\python.exe -m evaluation.step03.official_bm25 prepare
.\.venv\Scripts\python.exe -m evaluation.step03.official_bm25 score
.\.venv\Scripts\python.exe -m evaluation.step03.official_bm25 evaluate
```

download、baseline 使用 `eval_runs/litsearch/official_bm25`。prepare、score、evaluate 使用獨立的 `eval_runs/litsearch/official_bm25_step3_80`。來源 API 實驗不會被覆寫。

資料套件可能下載含全文的 corpus_clean parquet，再抽出 title／abstract 保存，因此第一次下載的大小可能高於最後的索引資料大小。

## 產出與檢查

- `data_manifest.json`：revision、upstream commit、來源與資料 hash、數量。
- `index_contract.json`：前處理版本、公式參數、原始與索引篇數；`encoded_corpus.jsonl` 可重用前處理。
- `bm25_full597.jsonl`：每題前 200 名與 BM25 分數；接 Step 3 僅使用前 100。
- `bm25_summary.json`：完整題集與 inline／author、broad／specific 分組結果。
- `tasks.jsonl`：目前 80 題与官方题目的对应、固定 top-100；gold 僅留在評估側檔案。
- `sessions/{qid}/step2_raw_papers.json`：100 篇固定候選，內部 paper ID 直接使用 corpus ID，避免外部 ID mapping。
- `input_contract.json`、`input_hashes.json`：固定輸入與對應 hash；重跑不得悄悄改資料。
- `run_contract.json`：Step 3 prompt hash、model 與 screening 設定。
- `completed.json`：候選完整性、無 fallback score、輸出 hash 與時間；有此標記才視為成功。
- `.cache/llm/ledger.jsonl`、`ledger_attempts.jsonl`：請求 cache、時間、已知 tokens、重試；失敗且 tokens 不明者另記，不當成零用量。
- `progress.json`：完成題數、失敗與目前題目；連續三題失敗會停止。
- `comparison_summary.json`、`comparison_per_question.jsonl`：overall／hit-only、三條排名、完整 gold 分母、用量統計。

## 限制

官方 clean corpus 在本實驗只提供 title／abstract，因此 authors、year、venue、citation count 均不另透過 API 補全；Step 3 的品質與 recency 分數會受到缺漏資訊影響，不能視為与有完整 metadata 的 API 實驗完全相同。

Step 0 topic／PICO 沿用原 80 題凍結設定，不重新生成；generator 不讀 gold IDs 或 gold paper metadata。`comparison_summary.json.completed` 未等於 80 時，不得將部分結果標為完成實驗。

Ollama 評分使用 IPv4 連線（只作用於此評分 client，不改電腦網路設定），並在 run_contract 記錄此設定；不啟用 thinking。

門檻仍為 composite ≥3.5，排序為 relevance 降序／composite 次序與 composite 降序兩條。gold 缺席不改變候選集合；評估仍保留完整原始 gold 分母。

## 官方來源

- https://github.com/princeton-nlp/LitSearch
- https://aclanthology.org/2024.emnlp-main.840/
