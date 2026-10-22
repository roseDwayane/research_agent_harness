# Step 6 評估實驗設計（定案 2026-10-15）

評估對象：Step 6（State-of-the-Art review 綜述）的輸出 `step6_sota_review.md`。
輸入固定、只跑 Step 6，分數不受檢索與篩選影響。目前結果都是本地 judge 的可行性測試，正式結果要等換成 API judge。

## 評估範圍

MetaSyn 納入的論文 → Step 4 引用 key → `step5_full_text`（固定輸入）→ **Step 6：逐篇 digest → 綜合 review** → 評分

- MetaSyn 批次不跑 harness 的 Step 1–3 和 Step 5；`step5_full_text` 由 `metasyn_prepare.py` 直接從 MetaSyn corpus 寫入（摘要，加上有 PMC 時的全文段落）。
- ground truth 只寫到 `eval/`，Step 6 讀不到。

## 實驗總表

| 實驗 | 輸入 | 被評的輸出 | 參考值 | Judge | 指標 | 定位 |
|---|---|---|---|---|---|---|
| **MetaSyn 官方指標** | 原 review 納入的論文（`matched_corpus_ids` 扣掉原 review 本身）；Topic、PI/ECO | Step 6 review 全文；baseline 報告 | MetaSyn 的 `Effect_Direction`、`Key_Insights` | **GPT-5.5，temperature 0**（與 MetaSyn 論文相同）；可行性測試用 gemma4:31b | direction accuracy；`insights_consistency`（0–1）；prompt 逐字照抄官方 | **主指標** |
| **Insight coverage** | 同上 | Step 6 review 全文（逐條檢查，不先抽取） | Key_Insights 中 synthesis 類的條目 | 同上 | `coverage_all`（covered 1、partial 0.5、其餘 0），附 review 原句；`coverage_answerable` 一併報但會隨受評系統改變 | 補充（自訂） |
| **AutoSurvey 內容品質** | 同上 | review 文字（去掉程式產生的表格和 Papers 行）；naive baseline | 無，依 rubric 評分 | 多個 API judge 取平均（AutoSurvey 用 GPT-4、Claude-3-Haiku、Gemini-1.5-Pro）；可行性測試用 gemma4:31b | Structure（整篇＋逐 section）、Relevance；Coverage 只為可比性而報（1–5） | **主指標** |
| **Citation 品質** | 同上 | 帶引用的句子和 Key Results 表格列（引用移除後當 claim） | 被引論文：**摘要＋全文最相關的 3 段**（AutoSurvey 原版只用摘要） | NLI judge（與內容 judge 相同），AutoSurvey 的 NLI prompt 逐字照抄 | recall、precision（依每句引用數分 1 / 2 / 3+）；citation density；all-sentence recall | **主指標** |
| **Citation coverage** | 同上 | review 的 Theme 內文和 Key Results 表格 | Step 5 中 `access_level` 為全文的論文 | 無（確定性程式） | `coverage_rate`，門檻 0.8；結構檢查、數字核對另外報 | 確定性檢查 |

### 補充：Citation 的證據為什麼用「摘要＋全文 3 段」

citation 評估要判斷「被引的論文真的支持這句話嗎」，judge 只能根據我們給它的證據文字判斷。

**為什麼不能只看摘要（AutoSurvey 原版的做法）**：Step 6 是讀全文寫的，常引用只出現在內文的細節（次要結果、子群數字、方法限制）。只給摘要的話，judge 找不到依據就判「不支持」，會低估 Step 6。實測（metasyn_v2，Step 6）：

| 這句話引用的論文 | 只給摘要的 recall | 摘要＋全文 3 段的 recall |
|---|---|---|
| 都有全文 | 0.54 | **0.83** |
| 有些只有摘要 | 0.86 | 0.86 |

只有摘要的論文，Step 6 本來就只讀得到摘要，所以兩種做法結果一樣。

**為什麼不給整篇全文**

| | 摘要 | 整篇全文 | 摘要＋3 段 |
|---|---|---|---|
| 每篇論文長度 | 約 250 字 | 約 5,000 字（中位數 5,257，最長 8,455） | 約 250 ＋ 3 × 120 字 |

- 太貴：每份文本約 89 次 NLI 呼叫，一句話常引 2–3 篇，塞整篇全文的 token 數會是現在的 10 倍以上。
- judge 容易被干擾：在上萬字裡找支持一句話的證據，容易漏看或誤判；只給最相關的段落，判斷反而比較準。

**做法**（`fulltext_retrieval.py`）：全文切成約 120 字的小段，依關鍵字重疊和「這句話裡的數字有沒有出現在該段」挑出最相關的 3 段，接在摘要後面交給 judge。段數在 dev 6 篇上試過 3、4、5 段後決定為 3，之後凍結，held-out 20 篇沒有用來調整。

**效度檢查**：引用換成隨機文獻後 recall 降到 0.05，claim 的數字或方向改掉後從 0.89 降到 0.08，表示 judge 確實在看證據內容。

## 比較對象

| 系統 | 怎麼產生 | 和 Step 6 的關係 | 用在 |
|---|---|---|---|
| Step 6 | harness 的 Step 6；可行性測試用 qwen3.8（Ollama），正式測試換成更強的 LLM | 受評系統 | 全部 |
| Naive RAG | `naive_baseline.py`：同一批論文的標題和摘要，一個 prompt 寫完整篇，長度對齊 Step 6 | 同一批論文、同一個模型；差在 Step 6 讀全文並先逐篇寫 digest 再綜合，naive 只看摘要、一次寫完（AutoSurvey 的 naive baseline 設計） | AutoSurvey、citation |
| GPT-Researcher | MetaSyn 公開的報告（gpt-5.4，`ma_retriever`）；agent 自己搜尋、抓取論文 | 只拿到研究問題和 PI/ECO，論文要自己從 MetaSyn 論文庫檢索；Step 6 則直接拿到原 review 作者最後納入的那批研究，不需檢索。因此 Step 6 只評「讀和綜合」，baseline 是「檢索＋讀和綜合」，比較時要註明這個前提 | MetaSyn |
| RAG | MetaSyn 公開的報告（gpt-5.4，`ma_retriever`）；用 MA-Retriever 檢索後一次生成 | 同上 | MetaSyn |

## 資料

- MetaSyn 測試集 86 篇 review，目前跑 26 篇（`runs/metasyn_v2`）。
- 6 篇 dev（255、356、225、243、324、70）用來調 judge prompt 和全文檢索，調完凍結；20 篇 held-out。
- 每篇平均 15.5 篇輸入論文（5–32 篇）、7.3 條 Key Insights，其中 synthesis 類 5.3 條。

## 效度檢查（取代人工標註）

**破壞測試：judge 會不會扣分**
- AutoSurvey 整篇：主題順序對調、重複、句子打亂、刪掉一半主題、只留摘要、混入別的主題。
- AutoSurvey 逐 section：拿掉小標、段落重複、句子打亂。
- MetaSyn：刪掉一半主題、只留摘要、換成別的主題的 review。
- Citation：引用換成隨機文獻（swap）、claim 的數字或方向改掉（perturb）。

**Judge 一致性與收斂效度**
- 引用 MetaSyn 的人工驗證（arXiv 2606.17041 附錄 F）：direction 與人工一致 91.2%、ρ = 0.82；insights 為正相關。前提：相同 prompt、GPT-5.5、temperature 0。
- 多 judge 一致性：Cohen's κ、Fleiss' κ（`metasyn_judge_agreement.py`）。
- 收斂效度：insight coverage 和官方 `insights_consistency` 的 Spearman ρ。
- 不另做人工標註。

## 可行性結果（gemma4:31b，metasyn_v2，26 篇）

不是正式結果。括號內為系統間配對 95% CI。

| 指標 | Step 6 | Naive | GPT-Researcher | RAG | 說明 |
|---|---|---|---|---|---|
| Direction accuracy | 14/26 | – | 17/26 | 17/26 | Step 6 在結論為 Positive 的題目上常保守寫成 Mixed |
| insights_consistency | 0.35 | – | 0.45 | 0.39 | 只有 6 檔分數，多數集中在 0.4 |
| coverage_all（補充） | 0.45 | – | 0.50 | 0.49 | 和 insights_consistency 的 ρ = 0.51 [0.30, 0.66] |
| Citation recall（全文） | 0.85 | 0.92 | – | – | 差 −0.06 [−0.09, −0.04] |
| Citation precision（全文） | 0.68 | 0.85 | – | – | 差 −0.17 [−0.22, −0.12]；引用 3 篇以上的句子差最多 |
| Citation density | 0.54 | 0.46 | – | – | Step 6 引用得比較多 |
| Structure、Relevance | 5 | 5 | – | – | 原始 review 全部滿分，gemma4 分不出系統差異；破壞測試有扣分 |

- Citation 效度檢查通過：swap 後 recall 降到 0.05；perturb 後從 0.89 降到 0.08。
- 逐 section Structure：段落重複時 35/35 個 section 扣分，句子打亂時 34/35。

## 待討論

### 1. 要不要刪掉 Consensus / Debates，讓 Step 6 的輸出更接近 MetaSyn 的形式

**背景**：Step 6 每個主題都有 Consensus 和 Debates 小節。MetaSyn 的 direction 指標要求報告給出明確結論（Positive / Negative / Mixed）。Debates 會讓 Step 6 在結論其實是 Positive 的題目上保守地寫成 Mixed（15 題 Positive 中有 7 題被寫成 Mixed）。

**已做的實驗**（同一批 26 篇固定輸入，只重跑 Step 6 的綜合；qwen3.8 + gemma4 可行性測試，各跑一次）：

| 版本 | direction | insights_consistency | coverage_all | 字數 |
|---|---|---|---|---|
| 原版 | 14/26 | 0.354 | 0.446 | 1,718 |
| 拿掉 Debates | 16/26 | 0.377 | 0.460 | 1,464 |
| 拿掉 Consensus 和 Debates | 17/26 | 0.400 | 0.438 | 1,356 |
| 拿掉兩者，改在 Cross-Theme 的 Diverging Findings 寫明每個衝突（方案 C） | 17/26 | 0.400 | 0.451 | – |

- direction 的提升主要來自拿掉 Debates（Positive 被寫成 Mixed：7 → 4 題）；拿掉 Consensus 沒有可測量的差異。
- 和原版比，direction 的 95% CI 下限剛好是 0；`insights_consistency` 的差異 CI 包含 0。

**代價**
- Debates 是 Step 7（找研究缺口）引用「研究結果衝突」的主要來源。10 篇的人工閱讀：以衝突為依據的缺口，原版約 3–5 個、拿掉兩者 2 個、方案 C 6 個。方案 C 把衝突內容移到 Diverging Findings，補回了這部分。
- 確定性檢查 `check_step6_contract.py` 要求每個主題有 Consensus / Debates，改版後會判失敗，檢查規則要跟著改。

**要討論的**
- 改輸出格式來配合 MetaSyn 的 direction 指標，是 Step 6 本來就該做的事，還是在配合指標？Step 6 的用途（給 Step 7 找缺口）需要保留衝突資訊。
- 目前都是單次、可行性等級的結果。建議換成正式的 LLM 和 judge、重跑之後再決定。
- 如果要改，方案 C 同時保住了 direction 的提升和 Step 7 需要的衝突內容。

### 2. 為什麼需要 insight coverage（補充指標）

官方 `insights_consistency` 用在 Step 6 上有四個限制：

1. **太粗**：只有 0、0.2、…、1.0 六檔，多數報告落在 0.4（Step 6 有 17/26 篇是 0.4），比較兩個 Step 6 版本或兩個模型時很難看出差異。
2. **包含 Step 6 不可能產生的題目**：189 條 Key Insights 裡有 52 條（28%）不是綜合結論，包括 meta-analysis 的合併數字 6 條、meta-analysis 特有的分析 17 條、外部資訊 6 條、空泛敘述 23 條。Step 6 不做 meta-analysis，這些題目對它來說是無法得分的。
3. **多一道抽取步驟**：先從報告逐字摘出重點句，再和 Key Insights 比對。報告其實有寫、但第一步沒摘到的話，分數會被低估，而且看不出是哪一步出問題。
4. **沒有逐條結果可檢查**：只給一個總分，無法看出是哪幾條沒寫到。

insight coverage 針對這四點：逐條判定（較細）、只計 synthesis 類、直接在 review 全文裡找（不先抽取），每條都附 review 原句可以檢查。

**定位與限制**
- 是我們自訂的指標，只當補充分析；主指標仍是官方的兩個。
- 和官方指標方向一致：`coverage_all` 和 `insights_consistency` 的 Spearman ρ = 0.51 [0.30, 0.66]。
- 報 `coverage_all`（所有 synthesis 條目）。`coverage_answerable` 只計 Step 6 自己的 digest 有證據的條目，分母會隨受評系統和模型改變，只當參考。

## 接下來要做的

**已決定**
1. **換 judge**：MetaSyn 用 GPT-5.5；AutoSurvey 用多個 API judge。評估程式要先加 API client（目前只支援 Ollama）。
2. **換 harness 模型**：`naive_baseline.py` 也要能接 API 模型；Step 6 的 digest 會改變，`coverage_answerable` 的分母也會跟著變。
3. **跑 judge 一致性和收斂效度**：程式已完成，換 judge 後直接跑。

**建議**
- 跑完剩下的 60 篇 review（目前系統間的 CI 多半包含 0）。
- 同一設定至少重跑 2 次，先量出重跑雜訊。
- 報告時列出字數：GPT-Researcher 平均 2,673 字、Step 6 1,718 字、RAG 1,129 字。

## 預算（正式實驗，86 題）

以 2026-10-13 的估算為基礎（GPT、Claude、Gemini 三家各跑一次 Step 6 和 naive，共 6 個系統；judge 照論文設定），再依今天定案的設計更新。token 數由 26 題的實測值推算（qwen / gemma tokenizer，再乘 1.2）。

### Token 估算

| 項目 | 10-13 估算（輸入 / 輸出） | 更新後（輸入 / 輸出） | 呼叫哪一家 | 變更原因 |
|---|---|---|---|---|
| A + B. 產生綜述（Step 6 + naive）× 3 家 | 2,640 萬 / 900 萬 | 2,640 萬 / 900 萬 | 三家各自 | – |
| C. MetaSyn 官方指標：6 系統 × 86 題 | 930 萬 / 70 萬 | 930 萬 / 70 萬 | OpenAI（GPT-5.5） | – |
| C'. 官方指標的第 2、3 個 judge（抽 20%） | – | 370 萬 / 28 萬 | Anthropic、Google | 新增：judge 一致性 |
| E1. AutoSurvey 內容評分：8 份文本 × 3 項 × 3 judge | 2,060 萬 / 10 萬 | 2,060 萬 / 10 萬 | 三家各自 | – |
| E1'. 逐 section Structure（Step 6 × 3 家 × 3 judge） | – | 420 萬 / 1 萬 | 三家各自 | 新增 |
| E2. 引用 NLI：Step 6 和 naive × 3 家 | 3,500 萬 / 40 萬 | 7,100 萬 / 40 萬 | OpenAI | 證據改成摘要＋全文 3 段，每份文本約 2 倍 |
| E2'. 引用效度檢查（swap / perturb，只做 1 個系統） | – | 830 萬 / 5 萬 | OpenAI | 新增 |
| D. 逐條涵蓋率：主 judge | 3,160 萬 / 90 萬 | 3,160 萬 / 90 萬 | Anthropic | 改為補充指標，用量不變 |
| D'. 逐條涵蓋率：第 2 個 judge（抽 20%） | 600 萬 / 20 萬 | 600 萬 / 20 萬 | Google | – |
| D''. 逐條涵蓋率：第 3 個 judge（抽 20%） | – | 600 萬 / 20 萬 | OpenAI | 新增：Fleiss' κ 需要 3 個 judge |
| **合計** | **約 1.29 億 / 1,130 萬** | **約 1.87 億 / 1,180 萬** | | |
| **加 25% 緩衝** | **約 1.6 億 / 1,400 萬** | **約 2.3 億 / 1,480 萬** | | |

### 分廠商申請量（已含 25% 緩衝）

| 廠商 | 10-13 估算（輸入 / 輸出） | 更新後（輸入 / 輸出） | 用途 |
|---|---|---|---|
| **OpenAI** | 7,500 萬 / 510 萬 | 約 1.4 億 / 540 萬 | GPT 產生綜述、MetaSyn 官方 judge、AutoSurvey judge、引用 NLI 和效度檢查、逐條涵蓋率第 3 judge |
| **Anthropic** | 5,900 萬 / 490 萬 | 約 6,300 萬 / 510 萬 | Claude 產生綜述、AutoSurvey judge、逐條涵蓋率主 judge、官方指標第 2 judge |
| **Google** | 2,700 萬 / 400 萬 | 約 3,100 萬 / 420 萬 | Gemini 產生綜述、AutoSurvey judge、逐條涵蓋率第 2 judge、官方指標第 3 judge |

金額：10-13 時估算 Anthropic 部分約 $150（產生和 judge 都用 Sonnet 5.5；產生改用 Opus 5.5 約 $200），更新後 Anthropic 的用量增加約 7%。OpenAI 和 Google 要依各家官網價格乘上表中的 token 數。

### 說明

- 增加最多的是引用 NLI（+3,600 萬）：改用全文證據後，每次呼叫除了摘要還要帶 3 段全文，每份文本的輸入約從 5.5 萬變成 11.5 萬 token（實測）。為什麼這樣做，見上方「補充：Citation 的證據為什麼用『摘要＋全文 3 段』」。
- AutoSurvey 原版的「只用摘要」NLI 沒有算進來；如果要一起報告以便和論文對照，OpenAI 要再加約 3,500 萬輸入。
- **可以省錢的地方**：評分全部改用 Batch API（Anthropic 5 折，其他家也有批次折扣）；逐條涵蓋率調整 prompt 順序以利用快取（D 的輸入成本可降 70–80%）。兩項加起來，總費用大約能降到估算值的一半以下。
- **不確定性**：各家 tokenizer 和 thinking 用量不同，可能差 ±30%。建議經費下來後，每家先試跑 3 題校正。
- 只算跑一次。如果同一設定要重跑 2 次量雜訊，A + B 要再乘 2（總額約增加 15%）。

---
程式：`research_agent_harness/evaluation/`（`metasyn_eval.py`、`autosurvey_eval.py`、`fulltext_retrieval.py`、`metasyn_judge_agreement.py`）。完整設計與歷史紀錄見該資料夾的 README。
Step 6 變體實驗（拿掉 Consensus / Debates）和 Step 7 counter_evidence 修正另有紀錄，未定案。
