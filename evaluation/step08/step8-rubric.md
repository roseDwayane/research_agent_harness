# Step 8 絕對 rubric：指標與實際輸入

這套 rubric 僅包含 Problem 5 項與 Method 5 項，共 10 項；評估 P2 每個 gap 對應的 Step 8 hypothesis spec，並不把「一個 spec 裡的多條 hypotheses」當成多個 idea。Gemma 使用獨立評審 client，每次只評一個 metric，以人工撰寫的 biomedical 或 cs_engineering 1–5 anchors 判斷，輸出 Review、Feedback 與整數 Rating。Python 計算平均；評分不回灌 Step 8 或 Step 9，也不觸發 revise。

## Problem：研究問題的品質

Problem Clarity 檢查問題是否清楚、精確且容易理解，主要讀 Step 8 的 research_questions 與 gap_summary_en/zh，確認讀者能辨識研究對象、問題與缺口。

Problem Relevance 檢查問題是否符合本次研究主題與 PICO，主要讀 Step 8 的 research_questions、gap_summary_en 與 executive_summary_en，並對照 Step 0 的 topic/PICO 和 Step 6 的 SOTA context。

Problem Originality 檢查是否提出未被深入探索的挑戰或觀點，主要讀 Step 8 的 gap_summary_en/zh、gap_selection_rationale_en 與 research_questions，並以 Step 7 的 locked gap、Step 3 的相關文獻摘要和 Step 6 的 SOTA 支持判斷。這只能評估相對於提供文獻的新意，不能證明整個領域都沒有人做過。

Problem Feasibility 檢查這個問題能否在合理資源與限制下研究，主要讀 Step 8 的 research_questions、risks、scope_in 與 gap_summary_en，並核對 locked gap 的可行性理由。這項關注問題本身是否可調查。

Problem Significance 檢查解決問題對科學或臨床的潛在影響，主要讀 Step 8 的 executive_summary_en/zh、gap_summary_en/zh 與 gap_selection_rationale_en/zh，並對照 Step 7 的 why_it_matters 與 Step 6 的領域背景。

## Method：研究方法的品質

Method Clarity 檢查方法描述是否讓別人理解如何執行，讀 Step 8 的 hypotheses、research_questions 與 conceptual_framework_en/zh，確認關鍵操作與研究流程有被說明。

Method Validity 檢查方法是否能回答所提出的研究問題，讀 Step 8 的 hypotheses、research_questions 與 conceptual_framework_en/zh，核對方法、RQ 和假說之間的對應。

Method Rigorousness 檢查方法是否系統完整、邏輯精確，讀 Step 8 的 hypotheses、conceptual_framework_en 與 traceability，尤其檢查 H0/H1、direction_magnitude_*、統計規劃以及證據來源是否一致。

Method Innovativeness 檢查方法是否引入有意義的新技術、組合或觀點，讀 Step 8 的 conceptual_framework_en/zh、hypotheses 與 gap_summary_en，再以 Step 3/6 的文獻脈絡判斷是否只是重新描述既有做法。

Method Generalizability 檢查方法能否推廣到其他研究對象、情境或資料，讀 Step 8 的 scope_in、scope_out、scope_rationale_en/zh、hypotheses 與 conceptual_framework_en。明確且合理的適用界線比無根據的普遍適用宣稱更有價值。

## 各 Step 的檔案如何進入評估

Step 0 的 step0_session_config.json 是必讀檔案，提供 topic、PICO 的 population/intervention/comparison/outcome/setting，以及 field_type。field_type 決定使用 biomedical 或 cs_engineering anchors；目前 other 會回退到 biomedical。

Step 1 的 step1_search_queries.md 不會由 rubric 讀取。這次 benchmark 使用 reference-only context 建立 Step 0，不需要重新做線上搜尋定向。

Step 2 的 step2_raw_papers.json 不會由 rubric 直接讀取。它是 P2 的 frozen references 輸入，經 Step 3 篩選後，才透過 shortlist 進入評審背景。

Step 3 的 step3_shortlist.json 提供 related papers 的 title、year 和 abstract。現行 runner 最多送 12 篇，每篇 abstract 截取最多 600 字元；這次每題起始只有 5 篇 refs，實際供應的是篩選後留在 shortlist 的文獻。

Step 4 的 citation key、APA 與 BibTeX 檔不會由 rubric 直接讀取。引用鍵及文獻對應已透過 Step 6 SOTA、Step 7 evidence 和 Step 8 traceability 間接進入評估。

Step 5 的全文與 access log 不會由 rubric 直接讀取。這次 P2 使用 abstract-only 模式，Step 6 的內容是摘要層級的證據，不能把分數解讀為評審已查核所有全文。

Step 6 優先讀 step6_sota.json，送出 executive_summary_en、trends_en、converging_en、diverging_en，以及 themes 的 title_en、consensus_en 和 methods_en，整段 context 截取最多 4,000 字元。只有 JSON 不存在時，才改讀 step6_sota_review.md，亦截取最多 4,000 字元。

Step 7 讀 step7_gaps.json，依 Step 8 檔案的 locked_gap ID 找出對應 gap，提供該 gap 的描述、supporting/counter evidence、why_it_matters 與評分理由。評審收到的是鎖定的 gap，而不是所有 gaps 的完整內容。

Step 8 的 step8_hypothesis.json 是必讀、被評分的 spec。每輪會依 metric 抽取相關欄位，加上相同的 Step 0/3/6/7 context，而不是每輪把所有 Step 8 欄位全部送出。

Step 9 不参与這次評分。step8_rubric_scores.json 與 step8_rubric_report.md 是旁路輸出，不能列為後續生成步驟的輸入。

## 檔案與平均分數

每個 P2 spec 分支都保存 step8_hypothesis.json、step0_session_config.json、step3_shortlist.json、step7_gaps.json、step6_sota.json 和 step6_sota_review.md。Rubric 評完後，在同一分支寫入 step8_rubric_scores.json 與 step8_rubric_report.md。

分數 JSON 每項包含 metric ID、類別、定義、主要欄位、review、feedback 和 rating，以及 Problem、Method 各自的平均與 overall 平均。Metadata 記錄 generator/judge 模型、prompt 版本、locked gap、field_type 和 feeds_pipeline=false。

實驗根目錄的 rubric_summary.json 彙整各 target 的所有 specs。因為每題 gap 數可能不同，會同時報告「所有 specs 等權」及「先算每題平均、再讓各題等權」兩種 overall，避免 gap 較多的題目不知不覺占比較大的權重。原始 10 項分數與理由仍保留，不能只用 overall 取代逐項檢查。

沒有具體、可查核的欄位證據時，不應給 4–5 分。缺少 context 代表判斷依據不足，不能簡單等同於研究品質差；本次實驗的 rubric 入口會檢查上述 context 檔案是否具備，缺失會明確記錄失敗，而不是默默省略。
