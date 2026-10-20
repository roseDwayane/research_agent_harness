# Step 08：假說評估與環境設定

## 檔案

- `runner.py`：對既有 Step 8 spec 執行獨立 rubric 評分。
- `metrics.py`：Problem／Method 各 5 項指標、欄位抽取與 1–5 分 anchors。
- `render.py`：產生評估報告。
- `ideabench/`：固定 benchmark 題目與 references、執行 P1／P2、匿名排名及用量紀錄。
- [Rubric 輸入與指標](step8-rubric.md)、[IdeaBench 協定](ideabench-evaluation.md)。

評估仍使用正式 `scholar_research/steps/s8_hypothesis.py` 產生假說。
這次整理沒有修改生成邏輯。Rubric 分數不回灌 Step 8／9，也不觸發修改。
評估專用 prompts 集中在本目錄的 `prompts/`，仍透過正式 prompt loader 讀取。
測試與一次性補跑腳本未搬入這個目錄。

## 環境設定做了什麼

以下是備份中已有的支援，不是這次搬移新增的模型功能：

1. `config.py` 新增獨立 `[judge]` 設定，與生成用 `[llm]` 分開。
   Judge 的 provider、base URL、context window、timeout 未設定時可繼承 generator；
   judge 的 model 必須明確設定，預設禁止與 generator 使用相同模型名稱。
2. 支援讀取 repo 根目錄的 `.env`，不覆寫已存在的 shell 環境變數。
   Generator 支援模型、連線、context、輸出長度、timeout、thinking 等環境設定；
   judge 支援獨立 `SCHOLAR_JUDGE_*` 設定。
3. `llm/client.py` 改用 Ollama streaming 接收回應，並保留結構化 JSON 驗證、cache、
   請求用量、時間與 attempt／重試紀錄。
4. `research.toml.example` 增加 `[judge]` 說明；`S8RubricRating` schema
   定義每項評分的 review、feedback、rating。
5. 部分實驗 runner 額外支援 IPv4 或連續失敗停止。這不是全域網路設定，
   一般 rubric CLI 也沒有自動套用所有實驗 runner 的選項。

本次整理只搬移評估程式與文件、修正 import 並將 `evaluation.step08*`
加入套件發現設定，未安裝新模型、啟動服務或修改遠端環境。

## 可重現的歷史設定

本機 `eval_runs/ideabench/experiment20_usage_v2/experiment_manifest.json` 記錄：

- Generator：Ollama `qwen3.8`，context 32768、max tokens 16384、temperature 0、
  thinking off、request timeout 300 秒。
- Judge：Ollama `gemma4:31b`，context 32768、max tokens 2048、temperature 0、
  thinking off、request timeout 600 秒。

這是保存的實驗設定，不代表目前遠端服務已驗證可用。歷史補跑腳本會從舊 manifest
還原設定；一般 CLI 則讀取 `research.toml`／環境變數，不會自動載入該 manifest。

## 準備與執行

以下指令在 repo 根目錄執行，使用既有 `.venv`：

```powershell
.\.venv\Scripts\python.exe -m pip install -e "."
```

以下為本機 `research.toml` 的設定範例。`127.0.0.1` 代表本機 Ollama；
使用遠端時，將 base URL 改成自己的服務位址。模型需已安裝且服務可用。

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

也可用 `.env` 的 `SCHOLAR_LLM_PROVIDER`、`SCHOLAR_LLM_MODEL`、
`SCHOLAR_LLM_BASE_URL`、`SCHOLAR_LLM_NUM_CTX`、`SCHOLAR_LLM_MAX_TOKENS`、
`SCHOLAR_LLM_TIMEOUT`、`SCHOLAR_LLM_THINK`；judge 對應為
`SCHOLAR_JUDGE_PROVIDER`、`SCHOLAR_JUDGE_MODEL`、`SCHOLAR_JUDGE_BASE_URL`、
`SCHOLAR_JUDGE_NUM_CTX`、`SCHOLAR_JUDGE_MAX_TOKENS`、`SCHOLAR_JUDGE_TIMEOUT`、
`SCHOLAR_JUDGE_THINK`。環境變數優先於 TOML；CLI 明確覆寫的選項最後生效。

### 評分單一既有 session

先檢查可用指標，這一步不呼叫模型：

```powershell
.\.venv\Scripts\python.exe -m scholar_research.cli eval step8-rubric --list-metrics
```

以下將 `YOUR_SESSION_FOLDER` 換成 research root 下的 session 資料夾名稱：

```powershell
.\.venv\Scripts\python.exe -m scholar_research.cli eval step8-rubric --session YOUR_SESSION_FOLDER
```

必要輸入為 `step0_session_config.json`、`step8_hypothesis.json`；
完整評估還需 Step 3 shortlist、Step 6 SOTA 與 Step 7 gaps 作為背景。
單一 session 入口對部分缺失背景會提供 unavailable 標記；IdeaBench rubric
入口則會檢查必要的 context 檔案，缺失會記錄失敗。
輸出放在同一 session 的 `step8_rubric_scores.json`、`step8_rubric_report.md`。

### IdeaBench：固定資料集與 P1／P2 比較

首次建立資料集會呼叫外部論文 API，並執行 target idea extraction。
預設用 OpenAlex 取得 targets／references；API 設定沿用正式 provider 設定。

```powershell
.\.venv\Scripts\python.exe -m scholar_research.cli eval ideabench-build --out eval_runs/ideabench/subset_v1 --m 20 --low-k 5 --source openalex
.\.venv\Scripts\python.exe -m scholar_research.cli eval ideabench-run --dataset eval_runs/ideabench/subset_v1 --out eval_runs/ideabench/experiment_v1 --rubric --max-tokens 16384 --num-ctx 32768
```

P1 直接由相同 references 生成想法；P2 執行既有 Steps 3／4／6／7／8，
每個有效 gap 產生一份 spec。兩者提供相同科學資訊，推論成本未強制相同。
獨立 judge 對匿名 ideas 與 gold 排名，另對 P2 spec 執行 10 項 rubric。
這兩種分數意義不同：相對排名用 Insight Score，rubric 用 1–5 分。

`--phase generate`、`--phase rank`、`--phase rubric` 可分階段執行；
續跑維持相同參數、資料與輸出目錄，僅評 rubric 時也保留 `--rubric`。
更改模型、prompt 或實驗設定使用新的輸出目錄。
主要輸出為 `summary.json`、`report.md`、`rubric_summary.json`、`costs.json`，
各題的 P1／P2 ideas、ranking 與 spec 評分保存在 `tasks/`。
