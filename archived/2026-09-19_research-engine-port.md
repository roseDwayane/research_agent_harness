# SCHOLAR Research → 獨立可執行引擎（scholar-research）

**日期**: 2026-09-19
**狀態**: P0–P5 已實作（`scholar_research/`，19 tests 通過含 9 步離線 e2e + replay byte-identical）；P6 skill wrapper 未做。實作紀錄見 §10。
**目標**: 把 `/research` 9 步 pipeline 從 Claude Code skill 轉成獨立 Python 程式，直呼 LLM API 與學術 API，並讓**同樣輸入產生同樣輸出**。

---

## 1. 為什麼做（痛點）

使用者指定的首要痛點：**結果不可重現 —— 同一個 topic 跑兩次結果差很多**。

不可重現的根源有四層，全部都要處理，只修其中一層沒用：

| 層 | 不可重現來源 | 現況 |
|----|-------------|------|
| L1 輸入 | API 回傳隨時間變動（新論文、citation count 變）| 無快取，每次重打 |
| L2 取得 | WebFetch 內部小模型會把長論文**摘要掉**，每次摘法不同 | SKILL.md 自承是「最大品質風險」 |
| L3 推理 | LLM 無 seed、無 temperature 控制、無 structured output 強制 | 靠 prompt 說「請精確計算」 |
| L4 編排 | Skill 由對話驅動，步驟順序/是否跳步依當下對話而異 | `current_step` 是唯一狀態，靠 LLM 自律更新 |

**設計原則**：確定性的東西用 code 保證，不確定的東西用 code 框住（schema + 快取 + 記錄）。

---

## 2. 目標形態

獨立 Python package，**完全不依賴 Claude Code**：

```bash
pip install -e .
export ANTHROPIC_API_KEY=...
scholar-research new "EEG neurofeedback for MCI" --config research.toml
scholar-research run --session 20260919_eeg-nf-mci --until 3
scholar-research status --session 20260919_eeg-nf-mci
scholar-research replay --session 20260919_eeg-nf-mci --from 3   # 重現
```

輸出目錄格式**完全沿用現有** `10_Research/{session_id}_{topic_slug}/`，檔名不變（`step2_raw_papers.json`、`step3_shortlist.json` …）。這點很重要：下游 `/implement`、`/journal`、`research-to-knowledge` 都讀這些檔，格式一改就得連動改。**新引擎是換引擎，不是換油箱。**

---

## 3. 架構

```
40_SourceCode/scholar_research/
├── cli.py                  # typer CLI：new / run / status / replay / resume
├── config.py               # pydantic-settings：API keys、model、weights、threshold
├── session.py              # session 狀態機（取代 current_step 的自律更新）
├── schemas/                # pydantic models = 步驟間的硬合約
│   ├── session_config.py   # step0
│   ├── paper.py            # step2 raw / step3 shortlist
│   ├── screening.py        # 三軸分數 + composite
│   ├── sota.py  gaps.py  hypothesis.py
├── providers/              # 外部 API 層（全部可快取、可重試）
│   ├── base.py             # Provider 協定 + retry/backoff/rate-limit
│   ├── semantic_scholar.py  openalex.py  pubmed.py  arxiv.py
│   ├── fulltext/           # unpaywall.py  pmc.py  pdf_extract.py  grobid.py
│   └── cache.py            # ★ 內容定址快取（見 §4）
├── llm/
│   ├── client.py           # Anthropic Messages API，structured output
│   ├── prompts/            # ★ 從 SKILL.md 抽出來的 prompt，版本化
│   └── ledger.py           # ★ LLM 呼叫記錄（見 §4）
├── steps/                  # 9 步，每步 = 純函式 (inputs) -> outputs
│   ├── s1_init.py          # LLM: topic → PICO + queries
│   ├── s2_search.py        # 純 code：呼叫 4 個 API + 去重 + DOI 補回 + snowball
│   ├── s3_screen.py        # 混合：LLM 給三軸分數，code 算 composite/分類
│   ├── s4_export.py        # 純 code：APA / citation key / BibTeX
│   ├── s5_fulltext.py      # 純 code 取得 + LLM 做雙語筆記
│   ├── s6_sota.py  s7_gaps.py  s8_hypothesis.py  s9_write.py   # LLM 為主
└── checkpoints.py          # 4 個 checkpoint 的互動/非互動處理
```

### 每步的性質分類（決定怎麼保證重現）

| Step | 性質 | 重現手段 |
|------|------|---------|
| 1 init | LLM | prompt 版本化 + temp=0 + 快取 |
| 2 search | **純 code** | API 回應快取（snapshot）→ 100% 重現 |
| 3 screen | 混合 | LLM 只給 1–5 整數分數（structured output）；**composite 算術由 Python 做** |
| 4 export | **純 code** | 格式化規則寫死 → 100% 重現 |
| 5 fulltext | code 取得 + LLM 筆記 | PDF 原文快取（含 sha256）→ 取得層 100% 重現 |
| 6 sota | LLM | 快取 + ledger |
| 7 gaps | LLM | 快取 + ledger |
| 8 hypothesis | LLM | 快取 + ledger |
| 9 write | LLM + code 驗證 | 引用對照 BibTeX 由 code 硬驗（零幻覺引用） |

**關鍵洞察**：Step 2、4 完全不需要 LLM；Step 3 的算術（`composite = rel×0.5 + qual×0.3 + rec×0.2`）現在是靠 prompt 拜託 LLM「不要憑感覺內插」——搬到 Python 就永遠正確。這是最高 CP 值的一刀。

---

## 4. 重現性機制（本案核心）

### 4.1 內容定址快取（解 L1）

所有外部請求以 `sha256(method + url + sorted_params + body)` 為 key，回應原樣存檔：

```
10_Research/{session}/.cache/
├── http/{hash}.json        # {request, response, status, fetched_at}
├── pdf/{sha256}.pdf        # 原始 PDF
└── llm/{hash}.json         # {prompt_version, model, params, messages, response}
```

- 預設 `--cache read-write`：有快取就用，沒有就打 API 並存。
- `replay` 指令 = `--cache read-only`：**任何 cache miss 直接報錯**，保證是重跑而非重新生成。
- `--refresh` 才會真的重打外部 API。

這一條就把「兩次跑結果不同」從不可控變成可稽核：不同一定是因為 cache miss，而 miss 會明說是哪一筆。

### 4.2 LLM 決定論（解 L3）

- `temperature=0`、`top_p` 固定、model ID 釘死在 session config（不寫 `latest`）。
- 所有判斷型輸出走 **structured output（tool use / JSON schema）**，由 pydantic 驗證，失敗就重試而非讓 LLM 自由發揮。
- Prompt 存成檔案並帶 `prompt_version`；prompt 一改，快取 key 就變，不會拿舊結果冒充。
- ⚠️ **誠實說明**：即使 temp=0，LLM API 仍**不保證** bit-level 一致（浮點/批次/後端版本）。所以真正的重現靠的是**快取回放**，temp=0 只是降低漂移。這點必須在文件寫清楚，不要對使用者過度承諾。

### 4.3 全文品質（解 L2）

淘汰 WebFetch 路徑，改成明確的 fallback 鏈，每層都記錄實際走到哪：

```
arXiv LaTeX source → arXiv HTML → PMC XML → Unpaywall OA PDF
  → pymupdf 文字抽取 →（掃描件）GROBID / OCR
```

每篇記 `sha256`、`extraction_method`、`char_count`、`section_count`。用字數/章節數做健全性檢查（例如抽出來只有 3000 字的 survey 直接標紅），取代現在「LLM 自己判斷有沒有被摘要」。

### 4.4 Run manifest（解 L4）

每次執行寫 `run_manifest.json`：engine version、git SHA、model ID、prompt versions、各步驟 input/output 檔的 sha256、cache hit/miss 統計、wall time、token 用量與成本。

**兩次跑的差異 = 兩份 manifest 的 diff。** 這是「不可重現」這個抱怨從感覺變成可定位問題的關鍵。

---

## 5. Checkpoint 怎麼辦（脫離對話後）

現有 4 個 checkpoint 依賴人在對話裡回話。脫離 Claude Code 後三種模式：

| 模式 | 行為 | 用途 |
|------|------|------|
| `--interactive`（預設）| 停下來、印出表格、等 stdin | 取代現在的對話體驗 |
| `--checkpoint-file decisions.toml` | 預先寫好決策（含 `lock_gap = "GAP_001"`）| 可重現、可版控、可 replay |
| `--auto` | 套用預設規則（不撈 borderline、選 priority 最高的 gap）| CI / 無人值守 |

決策一律寫回 `checkpoints.json`，所以 `replay` 能原封不動重放人的選擇——**人的判斷也要進快取**，否則重現性在 checkpoint 處斷掉。

---

## 6. 實作階段（建議順序，按痛點排）

| 階段 | 內容 | 產出 | 為何這個順序 |
|------|------|------|------------|
| **P0** | 骨架：schemas + session + cache + manifest + CLI | 空跑 pipeline 能建 session、寫 manifest | 快取與 manifest 是後面每一步的地基 |
| **P1** | Step 2 search（純 code，4 個 provider + 去重 + snowball）| `step2_raw_papers.json` bit-identical 可重現 | 最吃 token 又完全不需 LLM，先拿下 |
| **P2** | Step 3 screen + Step 4 export | composite 算術由 code 保證 | 解掉「分數漂移」這個最常被抱怨的點 |
| **P3** | Step 5 fulltext（PDF/GROBID 鏈）| 逐字全文 + 品質指標 | 解掉 L2，也讓 6–9 的輸入變穩 |
| **P4** | Step 1, 6–9（LLM 步驟 + structured output）| 完整 9 步 | 有前面地基後這些只是套模板 |
| **P5** | Checkpoint 三模式 + `replay` + 差異報告 | 可 CI、可稽核 | |
| **P6** | 薄 skill wrapper（選配）| `/research` 改成呼叫 CLI | 保留原本的對話入口 |

**P1 + P2 就能顯著改善重現性**，不必等全部做完。建議以 P2 結束作為第一個可驗收里程碑。

---

## 7. 驗收標準

1. 同一 session 連跑兩次 `replay`，所有輸出檔 sha256 完全相同。
2. Step 2、4 在 `--refresh` 下（重打 API）除 `fetched_at` 外輸出不變。
3. Step 3 的 composite 分數與三軸分數在數學上永遠自洽（property test：隨機 1–5 分數 × 1000 組）。
4. Step 5 全文抽取成功率與逐字率（char_count / 預期頁數）有報表，且無 `summarized` 狀態。
5. 一個既有 session 用新引擎重跑，產出的檔案能被現行 `/implement`、`/journal` 正常讀取（回歸測試）。

---

## 8. 風險與取捨

| 風險 | 對策 |
|------|------|
| LLM API 本身不保證 bit 一致 | 重現靠 cache replay，文件不誇大 temp=0 的效果（§4.2）|
| 9 步全部重寫工程量大 | 分階段；P1–P2 已有獨立價值，隨時可停 |
| Skill 與 code 雙軌並存易發散 | P6 讓 skill 變成 CLI 的薄殼，**邏輯只有一份** |
| 學術 API 有 rate limit / 需 key | provider 層統一 backoff；S2 API key 選配，無 key 降速不失敗 |
| GROBID 需跑 service | 設為選配依賴，預設用 pymupdf，缺 GROBID 只影響掃描件 |
| 輸出格式漂移打壞下游 | schema 凍結 + §7.5 回歸測試 |

---

## 9. 尚待決定

- Package 放 `40_SourceCode/scholar_research/` 還是獨立 repo？（依 `2026-05-20_polyrepo-v1.md` 的 polyrepo 方向，可能該獨立）
- 是否保留 skill 入口（P6），或完全以 CLI 為唯一介面？
- Step 6/9 的長上下文策略：全文塞進去 vs. 先做 per-paper 結構化摘要再合成（後者較省且較穩，但多一層失真）。

---

## 10. 實作紀錄（2026-09-19）

實際落地位置：本 repo 根目錄 `scholar_research/`（§9 第一題：採獨立 repo）。CLI 為 `scholar-research`，用法見 `README.md`。

| 階段 | 狀態 | 備註 |
|------|------|------|
| P0 骨架 | ✅ | `config` / `session`（file-existence 狀態機 + 每步 pinned timestamp）/ `cache`（4 modes）/ `manifest` + `diff` / CLI |
| P1 Step 2 | ✅ | 4 providers 純 code；穩定 ID（query 序 + normalized title）；DOI 補回；snowball 用 PICO 詞彙重疊過濾；引用網路用 OpenAlex `referenced_works` + S2 references；cluster = 連通分量 |
| P2 Step 3/4 | ✅ | LLM 只給 1–5 整數；composite 由 `Decimal` 算並 half-up 取 2 位；125 組窮舉 + 1000 組隨機測試通過。Step 4 純 code + 交叉驗證（& 檢查、a/b 消歧、單一字母序排序） |
| P3 Step 5 | ✅（部分） | fallback 鏈 arXiv HTML → arXiv PDF → PMC XML → Unpaywall PDF → OA publisher；PDF 以 sha256 快取；`char_count` / `section_count` 品質指標。**未做**：arXiv LaTeX source、GROBID/OCR。雙語筆記 `_zh.md` 改為選配（`fulltext.translate`） |
| P4 Step 1, 6–9 | ✅ | 全部 structured output（tool use + pydantic，schema 失敗回饋重試）。Step 6 採 per-paper digest → synthesis（§9 第三題選「先摘要再合成」，可用 `llm.context_strategy="full"` 切換）；canvas 佈局由 code 算。Step 9 引用由 code 對 `.bib` 硬驗、幻覺 key 拔除並留 TODO |
| P5 Checkpoint + replay | ✅ | `--auto` / `--decisions d.toml` / 互動（無 TTY 則暫停並提示 `checkpoint N` 指令）；決策寫入 `checkpoints.json`；`replay` = cache read-only + sha256 比對 |
| P6 skill wrapper | ⏸ | 未做（§9 第二題未決） |

驗收標準對照（§7）：
1. replay 兩次 sha256 相同 — ✅ 由 `tests/test_e2e_replay.py` 自動驗證（9 步、0 次外部呼叫）。
2. `--refresh` 下 Step 2/4 輸出不變 — ⚠️ 設計上 ID 與排序不依賴 citation count，但 API 結果集本身會隨時間變，只能做到「差異可由 manifest diff 定位」。
3. composite 自洽 — ✅ 屬性測試。
4. 全文報表且無 `summarized` — ✅ `_access_log.md` 有 extraction quality 表。
5. 既有 session 回歸 — ⏸ 尚未用真實 session 對 `/implement`、`/journal` 跑回歸（需 API key 跑一次真 session）。

已知：真實 API 煙霧測試中 OpenAlex / PubMed / S2 references 正常；S2 search 無 key 時容易 429（已有 backoff）；arXiv 對 percent-encoded query 回 406，已改為手組 URL 並把 406 視為可重試。
