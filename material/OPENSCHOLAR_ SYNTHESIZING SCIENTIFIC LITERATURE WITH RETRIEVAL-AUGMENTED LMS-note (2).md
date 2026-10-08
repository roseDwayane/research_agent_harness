### OPENSCHOLAR

* 這是一個專為科學文獻合成（Scientific Literature Synthesis）任務所設計的檢索增強型大型語言模型（Retrieval-Augmented LM）

- 核心組件：由專門的科學文獻資料庫 (OSDS)、高效的檢索器 (Retriever) 與重排序器 (Reranker) 以及大型語言模型 (LM) 組成。
- 自我反饋推理 (Self-feedback Inference)：模型在生成初步回答後，會進行自我評估並產出自然語言形式的反饋，隨後根據這些反饋執行更深入的檢索與內容修正，從而提升輸出品質。
  開
- 高效模型：訓練了輕量級的 OPENSCHOLAR-8B 模型:

  * Inference: 檢索與重排序 (Retrieve & Rerank) -> 初始生成與反饋 (Initial Response & Feedback) ->迭代修正 (Iterative Refinement) ->引用驗證 (Citation Verification)
  * Training: 合成數據生成 (Data Generation) -> 數據過濾 (Data Filtering) -> 數據混合與訓練 (Data Mixing & Training)
  * SCHOLARQABENCH 要求模型必須具備從龐大的開放取用論文資料庫中，自主進行檢索並跨多篇文獻進行整合推理的能力。

### SCHOLARQABENCH

* 這是一個專為科學文獻合成（Scientific Literature Synthesis）任務所設計的檢索增強型大型語言模型（Retrieval-Augmented LM）涵蓋電腦科學、物理學、神經科學與生物醫學的大規模多領域科學 QA 

- 包含 2,967 個查詢與 208 篇由博士級專家撰寫的長篇參考解答
- 任務多樣性 (Diversity of tasks)：

  涵蓋了從閉合分類 (Closed-form classification)、多選題到長篇生成 (Long-form generation) 等多種格式
- 評估維度 (Evaluation)：

  * Corr (Correctness)：評估模型回答的正確性。

  -
    Cite (Citation Accuracy)：評估模型引用文獻的準確度與必要性
  - LLM 與 Expert：針對 SCHOLARQA-MULTI，使用了專用的模型評估（如 Prometheus）以及真人專家評估，確保評測結果的全面性與可信度
- 評分標準的建立與一致性 :

  「評分準則」(rubrics) 來確保評估的品質：
  * 參考範例：為了讓專家能制定更好的評分標準，他們先展示了四種不同的 LLM 服務（Claude 3.5 Sonnet, GPT-4o, Perplexity Pro 等）產出的回應給標註者參考
  * 關鍵要素 (Key Ingredients)：每個問題平均被拆解為 4.4 個關鍵要素，並且每個要素都有 4.4 個引用來源作為佐證，確保評分有據可依。
  * 一致性檢驗：
    * 為了驗證專家標註的一致性，團隊採取了抽樣測試（10 個問題）。
    * 計算了兩位不同標註者各自產出的評分之間的 Pearson correlation coefficient (皮爾森相關係數)。包含通用評分標準 (general criterion) 的一致性為 79.3，若不包含則降至 59.5。這顯示「通用標準」對於降低主觀性差異非常重要。
  * **SCHOLARQA-BIO & NEURO**：
    * 針對生物醫學與神經科學領域，招募了 6 位擁有博士學位的研究科學家。
    * 標註者根據自己的專業領域選取論文，並設計出符合該領域專家思維的複雜科學問題。
    * 涵蓋主題：生物影像 (bioimaging)、遺傳學 (genetics)、微生物學 (microbiology)、神經調節 (neuromodulation) 等。
  * **SCHOLARQA-MULTI**：
    * 涵蓋更多元領域（電腦科學、生物醫學、物理學）。
    * 標註者同樣為博士生或具備博士後研究經驗的專家。
    * 嚴格限制：明確規定標註過程中禁止使用任何 LLM 工具

### EXPERIMENTS AND RESULTS

* 正確性 (Correctness, Corr): 

  *
    針對簡單的二分類任務（如 SciFact, PubMedQA），直接使用準確率 (Accuracy)。
  * 針對長篇 QA 任務（如 QASA），使用 ROUGE-L 指標計算字串重疊率。
  * 針對 SCHOLARQA-CS，開發了基於「專家評分表 (Rubrics)」的評估流水線，其中包含一般標準（佔 40%）與關鍵資訊點 (Key Ingredients) 的覆蓋度（佔 60%），並由 GPT-4o-turbo 進行評分。

- 引用準確性 (Citation Accuracy, Cite)

  * Cite-r (Recall)：檢查所有需要引用的陳述是否都有對應的文獻支持。
  * Cite-p (Precision)：驗證被引用的文獻是否真正支持該論點，且該引用是否有存在的必要性（即移除後是否影響陳述品質）。
  * Cite-F1：結合 Recall 與 Precision 的綜合指標

* 內容品質與組織 (Content Quality and Organization):

  研究團隊採用 Prometheus v2 作為「LLM-as-a-judge」，依據設定好的 rubric 進行五分制評分，確保評估標準與人類專家的專業觀點趨於一致。

