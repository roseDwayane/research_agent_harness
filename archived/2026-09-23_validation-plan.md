# scholar_research 驗證方法整理

> 來源：`material/` 全部資料：LitSearch (arXiv 2407.18940)、IdeaBench (arXiv 2411.02429)、OpenScholar / ScholarQABench 筆記、`Cite_implementation_flow`、ResearchAgent 摘要（rubric + prompt 圖）、IdeaBench gist，以及 2026-09-17 ~ 09-22 的 LINE 討論。
> 對照程式：`scholar_research/` 目前版本（P0–P5 完成）。
> 目的：週四對齊前，把「每一步怎麼驗、用什麼指標、跟誰比、要先改哪裡」整理成一份。

---

## 0. 總覽：資料 → 步驟 → 指標

| 層 | 驗證對象 | 依據 | 核心指標 | 需要 GPU/LLM? | 負責（LINE 共識） |
|---|---|---|---|---|---|
| L0 | 引擎本身（可重現性） | 既有 port plan | pytest、replay sha256、manifest diff | 否 | Cary |
| L1 | **Step 2 檢索**（+ Step 3 排序） | LitSearch | Recall@5 / @20、MRR、nDCG@10、損失漏斗 | Mode A 否 / Mode B 需 LLM | Joanna |
| L2 | **Step 6 SOTA：確定性檢查** | Cite flow + LINE | citation integrity、結構、≥80% coverage、數字 attestation ≥0.90 | 否 | 志芸 |
| L3 | **Step 6 SOTA：Cite-p / Cite-r / F1** | ScholarQABench + Cite flow | Cite-p、Cite-r、Cite-F1 | LLM judge | 志芸 / 待定 |
| L4 | **Step 6 SOTA：內容品質** | ScholarQABench (Prometheus v2) | organization / coverage / relevance（1–5） | GPU（5090） | 志芸 |
| L5 | **Step 8 假說** | ResearchAgent + IdeaBench | 15 項 Likert rubric；Insight Score（novelty / feasibility） | LLM judge | 待 Cary 決定 |
| L6 | 評審器本身 | ScholarQABench 一致性做法 | judge vs 人類的 κ / Pearson | 人工標註 | 全員 |

原則（沿用 Joanna 的建議）：**確定性檢查、Cite、Prometheus 內容品質各自回報，不混成一個平均分。** 確定性檢查是硬閘（hard gate），沒過就不必再跑模型。

---

## 1. 驗證前要先知道的程式現況（會直接影響指標）

讀 `scholar_research/` 後發現下面幾點。不處理的話，部分指標會變成恆真或量不到：

1. **Step 2 的輸出順序不是相關度順序。** `s2_search.py` 最後依「query 編號 → 正規化標題」排序（`_qrank`），所以 `step2_raw_papers.json` 的順序不能直接拿來算 Recall@k 或 MRR。有意義的排序只存在於 Step 3（`composite`，或只用 `relevance`）。
2. **Step 2 會套年份過濾。** 依 Step 1 的 `timeframe`（例如 `2019-2026`）過濾 `y0..y1`，snowball 也一樣。LitSearch 的 gold paper 可能更早（例如 BERT 2019），所以 benchmark 時要把 timeframe 放寬，否則是在量過濾器而不是檢索能力。
3. **Step 6 `_repair()` 會把每篇論文強制分進恰好一個主題**（LLM 漏掉的全部丟進第一個主題）。因此用 `paper_map` 或 `**Papers / 論文:**` 那行算 coverage 永遠是 100%。Coverage 必須用「主題正文 + Key Results 表格中實際被引用」來算，並另外記錄 repair 補了幾篇（建議在 `step6_sota.json` 或 summary 加 `n_repaired`）。
4. **Step 6 沒有檢查正文裡的 citation key。** `_repair()` 只清 `paper_map` 和 `edges`，`consensus_en / debates_en / methods_en / key_results_en` 裡的幽靈鍵不會被擋（只有 Step 9 會 strip `\cite{}`）。所以 L2 的 integrity 硬閘是真的有用、不是形式。建議之後把這個檢查也放進引擎。
5. **Step 6 prompt 要求行內引用寫成 `(AuthorYear)`，但 Step 4 的 key 是 `YamadaEtAl2025` 這種 PascalCase。** 模型實際可能寫 `(Yamada et al., 2025)`、`(YamadaEtAl2025)` 或 `(Yamada 2025)`，所以 checker 要先做正規化，對回 `step4_citation_keys.json`。
6. **Step 7 的 evidence 過濾有漏洞。** `g.supporting_evidence = [valid...] or g.supporting_evidence`：若所有 supporting evidence 都是幽靈鍵，會原封不動保留。L2 的 integrity 檢查也應涵蓋 `step7_gaps.json`。
7. **Step 6 在 `context_strategy="summary"` 下看的是 digest，不是全文。** Cite-p 的證據必須用 `step5_full_text/{key}.md`（照 Cite flow 規定）。另外可以做歸因：如果 claim 在 digest 裡有、在全文裡沒有，錯在 `s6_note`；digest 裡也沒有，錯在 `s6_sota`。
8. **Step 8 每個 locked gap 只產出一份 spec。** IdeaBench 的 Insight Score 需要同一題有 n 個想法。Step 7 預設 `max_gaps = 3`，所以「逐一 lock 3 個 gap → 3 份 spec」剛好等於 IdeaBench 的 n = 3。

---

## 2. L0：引擎本身（已有，補一項）

已有：
- `python -m pytest tests -q`：composite 的 Decimal 計算、citation key 規則、phantom strip、快取模式等。
- `test_e2e_replay.py`：離線跑完 9 步後，用 read-only cache replay，所有輸出的 sha256 不變。
- `scholar-research diff`：解釋兩次 run 的差異。

補充（不在 material 內，但針對你最在意的「同題目不同結果」）：
- **Run-to-run 變異量**：同一 topic 用 `--refresh` 跑 N = 3–5 次，量 shortlist 的 Jaccard、主題數與主題標題的穩定度、locked gap 是否一致。這個值是後面所有指標的雜訊底線：如果兩個版本的 Cite-F1 差距小於 run-to-run 變異，就不能說哪個版本比較好。
- **Golden session**：挑 1–2 個固定 session（例如 LINE 裡提到的 49 篇全文那個），cache 凍結後大家都對同一份輸出做評估，才能比較不同 evaluator 的結果，也能比較不同引擎版本。

---

## 3. L1：Step 2 檢索（+ Step 3 排序）— LitSearch

### 3.1 Benchmark 內容
- 597 題人工檢查過的文獻搜尋問題，每題附 gold paper（平均 1.0–1.2 篇）：
  - Inline-citation 351 題（broad 120 / specific 231）：由 GPT-4 改寫論文中的 inline citation 段落，再用 word overlap 過濾加人工篩選。
  - Author-written 246 題（broad 35 / specific 211）：ACL 2023 / ICLR 2024 作者為自己的論文出題。
- Specificity：broad ≈ 符合的論文 ≤ 20 篇；specific ≈ ≤ 5 篇。Quality 分 1 / 2，Qual = 2 較難。
- Corpus：S2ORC 中的 ACL Anthology 加 ICLR，共 64,183 篇；gold 以 S2ORC corpus ID 標註。
- 資料與程式碼：`github.com/princeton-nlp/LitSearch`

### 3.2 指標（照論文的報告方式）
| 子集 | 主要指標 |
|---|---|
| specific | Recall@5、Recall@20 |
| broad | Recall@20 |
| 跨 benchmark 比較 | nDCG@10（Table 8） |
| 額外 | MRR（Joanna 提議；**論文沒有報 MRR，所以沒有官方 baseline**） |

分層回報：inline vs author × broad vs specific，再加上 Qual = 1 / 2。

### 3.3 對照 baseline（論文數字）
| 系統 | Avg broad R@20 | Avg specific R@5 |
|---|---|---|
| BM25 | 39.9 | 50.0 |
| GritLM-7B | 70.8 | 74.8 |
| GPT-4o rerank (w/ GritLM) | 75.3 | 79.2 |

商用引擎（80 題 specific 子集，R@5，inline / author）：Google Search 23.1 / 62.5、Google Scholar 20.5 / 17.5、Elicit 23.1 / 17.5。論文自己也說這組比較不是 apples-to-apples，因為 corpus 不同。**我們的 Step 2 打的是線上 API，最適合對照的就是這組。**

另外，論文 Table 5 顯示用全文做 embedding 沒有穩定提升。我們只用 title + abstract，不算吃虧。

### 3.4 怎麼接到 scholar_research（兩種模式）

Joanna 指出的落差：LitSearch 是「找某一篇特定論文」，我們的 pipeline 是「topic → PICO → 5 個 query → 綜述」。所以要拆成兩種模式來量：

- **Mode A（只測檢索，不經 LLM）**：直接寫 `step0_session_config.json`，其中 Q1 = LitSearch 問題原文（其餘 query 留空或也用原文），timeframe 放寬到涵蓋 gold 年份，然後只跑 Step 2。這樣量的是 providers、dedup、snowball 本身的能力。
- **Mode B（端到端）**：把問題當 topic 餵給 `scholar-research new`，讓 Step 1 自己產 PICO 和 5 個 query，再跑 Step 2–3。
- **A 和 B 的差距 = Step 1 query 生成造成的損失**，這是最能指導改善方向的數字。

**排序來源**（見 §1-1）：
- Step 2：只能算 **set recall**（gold 有沒有在集合裡），同時回報集合大小 |S|。
- Step 3：用 `composite` 排序算 R@5 / R@20 / MRR；另外算一個只用 `relevance` 排序的版本，因為 composite 含 quality 和 recency，不純是相關度。整數分數會大量同分，要固定 tie-break 規則，或回報隨機 tie-break 下的期望值。

**ID 對映**：gold 是 S2ORC corpusId，我們的紀錄有 `semantic_scholar_id`、`doi`、`arxiv_id`。先用 S2 API（`CorpusId:xxx`）把約 650 篇 gold 轉成 paperId / DOI / arXiv，建一次對照表並 cache；對不到的再用 title fuzzy match（沿用 `word_overlap` ≥ 0.85）。

**Corpus 對齊（選做）**：把 Step 2 的結果後過濾成只留 LitSearch corpus 內的論文，再算 recall。這樣比較接近論文 Table 3 的設定。

### 3.5 損失漏斗（最有診斷價值）
對每一篇 gold paper，記錄它在哪一關消失：

```
provider 沒搜到 → 被年份過濾 → dedup 誤合併 → snowball overlap 過濾
→ Step 3 被排除（看 exclusion_reason）→ 排名 > k
```

### 3.6 實務
- 先跑分層抽樣子集（例如 80 題 specific，比照 Table 7；或每格 20 題），全量等確認流程再跑。arXiv 需要約 3 s 的間隔，全量會很慢。HTTP cache 在，重跑不用錢。
- ML/NLP 題目可以關掉 PubMed（`search.sources`）。
- 預期：S2 / OpenAlex 的搜尋本質上是關鍵字檢索，Mode A 的結果大概會接近 BM25 或 Google Scholar，而不是 GritLM。如果真的如此，可參考 LitSearch 的 LLM rerank（Table 13 的 RankGPT prompt）或 dense reranker 作為 Step 2 / 3 的改進方向。

### 3.7 補強：主題層級的 recall（用 IdeaBench 資料）
LitSearch 只驗「找特定一篇」。要驗「綜述該找的有沒有找到」，可以借用 IdeaBench 的結構：把 target paper 的主題當成 topic 輸入，用它的（過濾後的）references 當 gold set，量 Step 2 set recall 和 Step 3 shortlist recall。這比較貼近 `/research` 的實際用途。

---

## 4. L2：Step 6 確定性檢查（不需要 GPU，志芸可先做）

輸入：`step6_sota_review.md`（或更好用的 `step6_sota.json`）、`step4_citation_keys.json` / `step4_references.bib`（合法鍵集合 K）、`step5_full_text/{key}.md`（frontmatter 有 `access_level`）。

### 4.1 Citation integrity（硬閘）
- 從正文與 Key Results 表抽出所有 key，正規化後（`(Yamada et al., 2025)` → `YamadaEtAl2025`）必須 ⊆ K。
- 只要出現任何不在 K 的 key（例如 `FakeEtAl2024`）→ `integrity_fail = true`，Cite 三個分數直接記 0，不必跑模型。
- 同樣檢查 `step7_gaps.json` 的 evidence（見 §1-6）；Step 9 可以直接讀 `_validation.json` 的 `phantom_removed`。
- 建議加一項 EN/ZH 一致性：同一段落的中英文版本，key 集合應相同。

### 4.2 結構（organization 的確定性部分）
- 每個主題的 Consensus / Debates / Dominant Methods / Key Results 四個維度都不能是空的。
- Consensus 至少引 2 篇；Debates 雙方都有引用，至少 2 個不同的 key。
- 若 Key Results 是表格，表頭為 `| Study | N | Method | Primary Outcome | Result |`。
- 主題數在 prompt 規定的範圍內（< 10 篇：2–3 個；> 30 篇：最多 8 個；其餘 4–6 個）。每個主題至少 2 篇。

### 4.3 ≥ 80% 全文覆蓋（Joanna 9/20 的定義）
```
分母 = Step 5 access_level == full-text-pdf 的論文（摘要／濃縮版不算）
分子 = 分母中「至少出現在一個主題」的論文（跨主題只算一次）
「出現」= 主題正文或 Key Results 表格裡的引用，兩者同等
過關：分子 / 分母 ≥ 0.80
```
- ⚠ 依 §1-3，**不能**用 `paper_map` 或 `Papers:` 那行判定，要用實際引用。另外回報 `paper_map` 版本和 `n_repaired` 當對照。
- ⚠ 引擎的 `access_level` 還有 `full-text-html`（arXiv HTML，實際上是全文）和 `partial-text-html`。要不要算進分母，**週四要定**。建議把 `full-text-html` 算進去。
- 延伸（LINE 提到）：對立證據有沒有進 Debates。見 §5.3 的 must-cite 清單。

### 4.4 數字 attestation（沿用舊的 90% gate）
- 對每筆含數字（數值、百分比、p 值、r）的 citable claim：這個數字的字面值，或四捨五入後等價的值，必須出現在「該句所引 key」對應的 `step5_full_text/{key}.md`。
- **搜尋範圍只限該句引用的 key，禁止全庫掃描。**
- 只有摘要的 key 不能拿來支撐細節數字。
- `numeric_attestation = 對得回的筆數 / 含數字的 citable 筆數`，≥ 0.90 過關。
- LINE 裡的抽樣例子：6.33、80% 造假、r = +0.29、≥ 90% discriminator。

---

## 5. L3：Step 6 Cite-p / Cite-r / F1（ScholarQABench 做法）

### 5.1 切成評分單位
一個單位 = `{claim_text, keys[], source}`
- 正文：按句號或分號切；括號引用掛在同一句。
- Key Results 表：一列一筆，Result 是主張，Study 是引用。
- 不進 Cite：Papers 名單、Paper–Theme Mapping、主題標題、方法學圖例、限制章節。
- 建議先只評英文（中文是翻譯，另用 §4.1 的 EN/ZH 一致性管）。

### 5.2 Citable 判定
- 進 Cite：數字、百分比、p 值、相關係數；「X 做了／發現／報告」；對立結果；因果陳述。
- 不進 Cite：標題、圖例、目錄、「本綜述的限制…」、純過渡句。
- 可以用規則或小分類器；citable = 0 的句子既不算漏引，也不算精準。

### 5.3 逐筆打分
- **r_i（程式就能算）**：keys 非空且全在 K → 1；keys 為空 → 0。
- **加強版 recall（must-cite 清單）**：每個主題預先列出必引的 hub 和對立證據，例如 Theme 1 的 Debates 應該同時出現 Yamada 和 Ravideshik，或 ChenEtAl2024 的負面結果。沒出現的話，那一筆或該主題 r = 0。
  - 候選可以自動產生：Step 2 citation network 的 `is_hub`、Step 7 的 `counter_evidence`；最終由人工確認（golden session 做一次就好）。
- **p_i（LLM-as-judge，要讀全文）**：prompt 裡只放該句 keys 對應的 md。每個 key 問兩題 yes/no：
  1. **Support**：全文是否真的主張或報告了這句？（例：「80% 造假」其實不是 Gaddipati 的結果 → no）
  2. **Necessary**：拿掉這個 key，這句是否就無法核對或明顯變弱？（例：同主題順手塞的第五個作者 → no）
  - 每個 key 都 yes/yes → p_i = 1，否則 p_i = 0。細緻版可取 key 的平均（3 個過 2 個 → 2/3）。
  - Abstract-only 的 key 撐細節數字 → 該 key 記 p = 0。
  - 數字 attestation 失敗 → 通常 p_i = 0。

### 5.4 聚合
```
N   = citable 筆數
N+  = 有引用（r_i = 1）的 citable 筆數

Cite-r  = (1/N)  · Σ r_i
Cite-p  = (1/N+) · Σ p_i        # 沒引用的句子不進 precision 分母，避免重複懲罰
Cite-F1 = 2·p·r / (p + r)       # 任一方為 0 → 0
integrity_fail → 三者皆 0
```
輸出格式（Cite flow 範例）：
```json
{"n_claims":120,"n_citable":95,"integrity_fail":false,"cite_p":0.84,"cite_r":0.79,"cite_f1":0.81,"numeric_attestation":0.92,"errors":[]}
```

### 5.5 Judge prompt 骨架（建議）
```
You verify one citation in a literature review.
Claim: {claim_text}
Cited paper ({key}, access_level={level}): {full_text_md}
Q1 Support: Does this paper itself state or report the claim (numbers must match)? yes/no + quote
Q2 Necessary: If this citation were removed, would the claim become unverifiable or clearly weaker? yes/no
Output JSON: {"support": "...", "support_quote": "...", "necessary": "..."}
```
- 要求附上 quote，才能人工抽查。
- Judge 呼叫同樣走 `llm/client` 的 cache 和 ledger，prompt 放進 `llm/prompts/` 並加版號。這樣評分本身也能 replay。
- **Judge 不要和 generator 用同一個模型家族**，避免自我偏好。

### 5.6 延伸到 Step 9
`01_intro.tex` 和 `02_relatedwork.tex` 用 `\cite{key}`，抽取更容易。同一套 Cite-p / r 可直接套用；integrity 則已由 `_validation.json` 保證。

---

## 6. L4：Step 6 內容品質（Prometheus v2，需要 GPU）

- ScholarQABench 用 Prometheus v2 當 LLM-as-judge，依 rubric 打 1–5 分（`prometheus_eval.py`）。預計在 Cary 的 5090 上跑。
- 輸入 = PICO + 全文清單 + `step6_sota_review.md`（建議只給英文部分，控制 context 長度）。
- 三個維度要分開回報，**不要和 Cite 混在一起平均。**

草擬的 rubric anchors（給志芸當起點）：

| 分數 | organization | coverage | relevance |
|---|---|---|---|
| 5 | 每個主題的四個維度齊全且各司其職；主題之間界線清楚；跨主題分析真的連回各主題 | ≥ 80% 全文被實際引用；每個主題的 hub 與對立證據都進了 Debates | 全文緊扣 PICO；沒有離題的主軸 |
| 4 | 四個維度齊全，偶爾重疊（Consensus 和 Key Results 重複） | ≥ 80%；對立證據大致有，漏 1 組 | 偶有旁支，但有標明是背景 |
| 3 | 有維度流於形式（Debates 只寫「仍需更多研究」） | 60–80%，或對立證據明顯缺漏 | 有一個主題偏離 PICO |
| 2 | 主題像論文清單（按論文而非按觀點組織） | 40–60% | 離題內容寫成主軸之一（LINE 例：把自駕實驗室、SWE-agent 寫成主軸） |
| 1 | 沒有可辨識的主題結構 | < 40% | 大部分內容與 PICO 無關 |

- ScholarQABench 的經驗：rubric 若包含一條「通用標準（general criterion）」，兩位標註者的 Pearson 相關為 79.3；不包含則掉到 59.5。**所以每個維度都要附通用標準加上具體 anchor**，不能只寫一句定義。
- 選做（正確性 Corr）：ScholarQA-CS 的做法是 40% 通用標準 + 60% key ingredients 覆蓋度，需要專家為每個 topic 寫 key ingredients（原資料平均每題 4.4 個要素，每個要素 4.4 篇引用）。可以在 golden session 上由你（EEG / 神經領域）寫一份。ScholarQA-Neuro / Bio 的題目也能拿來當 topic 輸入，但它們是否附 rubric 要回原資料確認。

---

## 7. L5：Step 8 假說（ResearchAgent + IdeaBench；待 Cary 決定）

兩種互補的評法：**絕對 rubric**（每份 spec 各自打 1–5 分）與**相對排名**（Insight Score）。LLM 打絕對分容易集中在 4–5，所以建議兩者都做，以相對排名為主。

### 7.1 絕對 rubric：ResearchAgent 的 15 項（Problem / Method / Experiment 各 5 項）

| 類型 | 項目 | 定義（摘自原表） | 對應 `step8_hypothesis.json` 欄位 |
|---|---|---|---|
| Problem | Clarity | 問題定義清楚、精確、易懂 | `research_questions`, `gap_summary` |
| | Relevance | 與當前領域相關、適用 | `research_questions` vs PICO / SOTA |
| | Originality | 未被深入探索的新挑戰或觀點 | `gap_summary`, locked gap |
| | Feasibility | 現有資源與限制下能否調查或解決 | `research_questions`, `risks` |
| | Significance | 對領域的潛在影響 | `executive_summary`, gap 的 `why_it_matters` |
| Method | Clarity | 描述足以讓他人理解與復現 | `hypotheses`, `conceptual_framework` |
| | Validity | 能切中並解決所提問題 | `hypotheses` ↔ `research_questions` |
| | Rigorousness | 系統、結構完整、精確 | `h0/h1`, `direction_magnitude` |
| | Innovativeness | 引入突破常規的新技術或觀點 | `conceptual_framework` |
| | Generalizability | 可推廣到其他情境或資料 | `scope_in`, `scope_out` |
| Experiment | Clarity | 設定、流程、預期結果清楚 | `scope_in`（Design / Timeframe）, `statistical_approach` |
| | Validity | 設計真的能檢驗假說 | `statistical_approach` ↔ `hypotheses` |
| | Robustness | 結果不依賴少數特例 | `risks`, `scope_in` |
| | Feasibility | 資源、時間、技術上可行 | `risks`, `scope_in` |
| | Reproducibility | 資訊足以讓他人重做 | `statistical_approach`, `traceability` |

Prompt 設計（照 ResearchAgent 的 prompt 圖）：
1. **一次只評一個 metric**（`{metric}` 變數化），讓每輪回饋聚焦在單一維度。
2. 提供 context：research problem 與 rationale，加上 target paper 和 related papers 的標題、摘要。對應到我們是 locked gap、SOTA 摘要和 shortlist 摘要。
3. 強制輸出 `Review:` / `Feedback:` / `Rating (1-5):`。
4. `{criteria}` 放**人工撰寫的 1–5 分 anchor**（ResearchAgent 用的是人類標註的 Likert 標準），並寫明「避免一律給 4–5 分，除非完全有根據」。
5. 評審模型要和 generator 以及 pipeline 內部任何 reviewer 分開，避免 Goodhart。ResearchAgent 的 generate → review → revise 迴圈是另一件事，可以當作 Step 8 的改進方向，但評估用的 judge 要獨立。

### 7.2 相對排名：IdeaBench Insight Score
**資料集建構**（照 IdeaBench，換成你的領域）：
- 選 target paper：**發表時間晚於 generator 模型的訓練截止日**（IdeaBench 用 2024 年論文對上 2024-01-01 前截止的模型）。本機的 qwen 和雲端的 Claude 截止日不同，要分開挑。
- 用 S2 API 取 references，照三條規則過濾：被引數 < 5 排除；非原創研究（review、editorial、letter、book）排除；不在 background 段落被引用的排除（這條需要全文，可選）。
- 用 Figure 5 prompt，把 target abstract 萃取成一段「Hypothesis: …／Given that …」形式的想法，拿掉細節數字。

**兩種協定**：
- **P1（IdeaBench 原版 baseline）**：把 reference abstracts 丟給單一 prompt（Figure 1），直接生成 n 個想法。
- **P2（pipeline）**：把 references 注入成 `step2_raw_papers.json`（跳過線上搜尋），跑 Steps 3–7，逐一 lock Step 7 的 3 個 gap，得到 3 份 Step 8 spec，再用與 target 相同的萃取 prompt 各自壓縮成一段。
- **P2 − P1 = Steps 3–7 的加值。** 這是 scholar_research 最需要回答的問題：多花這麼多步驟，想法有沒有比較好。
- 再分 low resource（5 篇過濾後的 references）和 high resource（全部 references）兩種情境。

**排名與計分**：
- 把 target idea 和 n 個生成的想法放在一起，judge 在不知道哪個是原作的情況下，依 quality indicator 排名（Figure 2 prompt）。
- ⚠ IdeaBench 的模板固定把 target 放在 Hypothesis 1，有位置偏誤的疑慮。**建議隨機打亂順序，並對多個排列取平均。**
- Quality indicator 可以自訂定義，例如 novelty = 「開發新方法學」或「把既有技術用到新問題」。至少做 novelty 和 feasibility，可以再加 ResearchAgent 的 significance、clarity。

```
I(system, q) = (1/m) · Σ_i (r_target_i|q − 1) / n        ∈ [0, 1]
r_target ∈ {1..n+1}；> 0.5 表示多數生成想法排在原作之前
```
- 所有比較對象的 **n 要固定**，因為 n 不同會改變 target 的名次，也改變分數的粒度。
- 參考值：多數模型 novelty > 0.6（GPT-4o high resource 為 0.766）；feasibility 全部 < 0.5。可以預期我們也會看到「新穎但不可行」的落差。

**相似度輔助指標**（量「能不能重新發現真正的下一篇論文」）：
- BERTScore F1 對 target abstract（IdeaBench 算出的實際上限約 0.718）。
- LLM idea-overlap 1–10 分（Figure 3 prompt），取 n 個想法中最相似的那個。

**注意**：IdeaBench 發現 Llama 3.1 8B 會生成大量不連貫的文字，而 LLM judge 會被這類文字騙（反而給高 novelty）。**用本機 qwen 時要加一道連貫性前置檢查，並做人工抽查。**

### 7.3 附帶：校準 Step 7 的自評分數
Step 7 由 LLM 對每個 gap 打 severity / novelty / feasibility（1–5），再由程式算 composite 並決定排名。`--auto` 模式會直接 lock 第一名。

可以拿 Step 7 自評的 novelty 和 feasibility，跟 §7.2 外部 judge 的排名算 Spearman 相關。如果不相關，代表 `--auto` 選 gap 的依據不可靠，這也是 Checkpoint 3 需要人工把關的量化理由。

---

## 8. L6：評審器本身的可信度

每一個 LLM-as-judge 指標，都要有一小份人工標註集：

| 指標 | 人工標註量 | 回報 |
|---|---|---|
| Cite Support / Necessary | 約 50 筆 claim–key 配對 | Cohen's κ（judge vs 人） |
| Prometheus 三維度 | 約 10 份 SOTA（或 golden session 的不同版本） | Pearson / Spearman |
| Step 8 rubric / 排名 | 約 10 題 | 與人工排名的 Kendall τ |

做法參考 ScholarQABench：先抽 10 題，由兩位標註者各自打分，計算彼此的相關，再決定 rubric 夠不夠明確（有通用標準時 79.3，沒有時 59.5）。

---

## 9. 建議實作方式（放在這個 repo）

- 新增 `scholar_research/eval/`（或獨立的 `scholar_eval/`）與 CLI 子命令，例如：
  - `scholar-research eval litsearch --mode A --subset specific --k 5,20`
  - `scholar-research eval sota --session …`（L2 確定性檢查 + L3 Cite）
  - `scholar-research eval hypothesis --session …`（L5）
- 評估結果寫到 session 資料夾**之外**（例如 `eval_runs/{session}/{eval_run_id}.json`），不要動到 session 檔案，避免 replay 和 manifest 的 hash 改變。
- Judge 呼叫沿用現有的 cache、ledger 和版本化 prompt，評分本身也能 replay。
- 引擎的小修改（讓評估能量到東西）：
  1. Step 6 記錄 `n_repaired`，並檢查正文中的 citation key（§1-3、§1-4）。
  2. Step 7 修正 `or g.supporting_evidence`（§1-6）。
  3. 支援注入 query 或 raw papers 的 fixture（LitSearch Mode A、IdeaBench P2）。session 狀態是看檔案是否存在，所以理論上直接寫檔就能跳過 Step 1 或 Step 2，但要確認 manifest 和 state 檔會接受。

---

## 10. 優先順序

| 階段 | 內容 | 資源 |
|---|---|---|
| **P0** | L2 確定性 checker（integrity、結構、coverage、數字 attestation）；引擎修正 §9-1、§9-2 | 無 |
| **P0** | LitSearch Mode A，80 題子集 + 損失漏斗 | API 時間 |
| **P1** | L3 Cite-p / r / F1 + 50 筆人工標註；LitSearch Mode B 與全量 | LLM judge |
| **P2** | L4 Prometheus 三維度 | 5090 |
| **P3** | L5 Step 8：先做 ResearchAgent rubric，再做 IdeaBench 資料集與 Insight Score（P1 vs P2 協定） | LLM + 建資料集 |
| 持續 | L0 run-to-run 變異量、golden session 凍結 | 無 |

---

## 11. 週四要決定的事

1. Coverage 分母要不要納入 `full-text-html`（Joanna 的定義只算 `full-text-pdf`）？
2. Cite 只評英文，還是中英都評？
3. Judge 模型選誰（不和 generator 同一家族；Claude / GPT-4o / 本機 Prometheus）？人工標註由誰負責？
4. LitSearch：先 Mode A 還是 A、B 並行？子集怎麼抽？要不要做 corpus 對齊？
5. Step 8：只做絕對 rubric，還是也建 IdeaBench 式資料集（領域、target paper 年份、m 取多少）？
6. Golden session 用哪一個？must-cite 清單由誰整理？
7. Eval 程式放在哪裡（`scholar_research/eval/` 或獨立套件）？
