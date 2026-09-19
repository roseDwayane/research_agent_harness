# scholar-research

Standalone, reproducible Python engine for the SCHOLAR `/research` pipeline (9 steps, 4 human checkpoints). It replaces the Claude Code skill chain with code that calls the LLM and the academic APIs directly, while writing **exactly the same files** under `10_Research/{session_id}_{topic_slug}/` so `/implement`, `/journal` and `research-to-knowledge` keep working unchanged.

Design rule (from [the port plan](2026-09-19_research-engine-port.md)): **deterministic things are guaranteed by code, non-deterministic things are fenced by code** (schema + cache + ledger).

```
pip install -e ".[pdf]"
export ANTHROPIC_API_KEY=...            # LLM steps
export OPENALEX_MAILTO=you@example.org  # polite pool (optional)
export UNPAYWALL_EMAIL=you@example.org  # OA PDFs in Step 5 (optional)

scholar-research new "EEG neurofeedback for MCI"          # Step 1 → Checkpoint 1
scholar-research run --session 20260919_eeg --until 3     # Steps 2–3 → Checkpoint 2
scholar-research checkpoint 2 --include paper_012          # rescue a borderline paper
scholar-research run --session 20260919_eeg               # Steps 4–7 → Checkpoint 3
scholar-research checkpoint 3 --lock GAP_001 --drop GAP_002
scholar-research run --session 20260919_eeg               # Step 8 → Checkpoint 4
scholar-research checkpoint 4 --approve
scholar-research run --session 20260919_eeg               # Step 9
scholar-research status --session 20260919_eeg
scholar-research replay --session 20260919_eeg --from 3   # cache-only re-run, verifies sha256
scholar-research diff --session 20260919_eeg              # why did two runs differ?
```

Unattended: `run --auto` (default rules: no borderline rescue, lock the top gap, approve) or `run --decisions decisions.toml` (see `decisions.example.toml`). In an interactive terminal the checkpoints prompt on stdin; without a TTY the run pauses and tells you which `checkpoint` command to issue.

## Local models (Ollama)

The LLM steps can run against a local Ollama server instead of the Anthropic API — no key needed. Set in `research.toml`:

```toml
[llm]
model = "qwen3.8"
provider = "ollama"
```

or `SCHOLAR_LLM_PROVIDER=ollama SCHOLAR_LLM_MODEL=qwen3.8` (`SCHOLAR_LLM_BASE_URL` if the server is not on `127.0.0.1:11434`). The forced tool call is replaced by Ollama's `format` = JSON schema (grammar-constrained decoding), so outputs go through the same pydantic validation, cache and ledger. On Windows set `PYTHONUTF8=1` so the bilingual console output prints under a non-UTF-8 code page.

## What each step is made of

| Step | Skill | Nature | How reproducibility is guaranteed |
|---|---|---|---|
| 1 | research-init | LLM | versioned prompt, temperature 0, structured output, cached |
| 2 | research-search | **pure code** | every API response cached; stable IDs (query order + normalized title, never citation counts) |
| 3 | research-screen | hybrid | LLM emits integers 1–5 only; composite `rel×0.5+qual×0.3+rec×0.2` is Decimal arithmetic in Python, classification strict |
| 4 | research-export | **pure code** | APA 7 / citation keys / BibTeX rules implemented once, cross-validated before writing |
| 5 | research-fulltext | code fetch + optional LLM notes | arXiv HTML → arXiv PDF → PMC XML → Unpaywall PDF → OA publisher; PDFs stored by sha256; quality = char/section counts (no "summarized" state exists) |
| 6 | research-sota | LLM | per-paper digests (cached) → synthesis; canvas layout by code; phantom keys/edges dropped by code |
| 7 | research-gaps | LLM | integer scores → composite `sev×0.4+nov×0.3+fea×0.3` and ranking by code |
| 8 | research-hypothesis | LLM | needs the locked gap from `checkpoints.json` |
| 9 | research-write | LLM + code validation | every `\cite{}` checked against `step4_references.bib`; phantoms stripped and flagged; pruned `.bib` is a strict subset |

## Reproducibility machinery

* `.cache/http/{sha256}.json`, `.cache/pdf/{sha256}.pdf`, `.cache/llm/{sha256}.json` — content-addressed. Key = method + URL + sorted params + body (API keys excluded), or prompt name + **prompt version** + model + params + messages + schema.
* Cache modes: `read-write` (default), `read-only` (= `replay`: any miss is an error, never a silent regeneration), `refresh` (`--refresh`), `off`.
* `.state.json` pins one timestamp per step on first execution, so replays write byte-identical files. `--refresh` re-pins.
* `checkpoints.json` records every human decision (mode, time, choice); replay re-applies it.
* `run_manifest.json` (+ `.runs/{run_id}.json`): engine version, git SHA, model, prompt versions, sha256 of every input/output file, cache hit/miss, token usage. `scholar-research diff` explains a difference between two runs.
* `.cache/llm/ledger.jsonl`: one line per LLM call.

Honest caveat: `temperature=0` reduces drift but the Anthropic API does not promise bit-level determinism. True reproduction is **cache replay**; a fresh run against the API may differ, and the manifest diff will say exactly where.

## Layout

```
scholar_research/
├── cli.py            new / run / step / status / checkpoint / replay / diff / prompts
├── config.py         research.toml + env (see research.toml.example)
├── session.py        session folder, state machine (file existence, not LLM self-report), timestamps
├── cache.py          content-addressed cache + modes
├── manifest.py       run manifest + diff
├── checkpoints.py    interactive / file / auto modes
├── pipeline.py       runner (inputs check → step → hashes → manifest)
├── schemas/          pydantic contracts: session config, papers, LLM outputs, checkpoints
├── providers/        semantic_scholar, openalex, pubmed, arxiv, fulltext/{sources,extract}
├── llm/              client (tool-use structured output, retries on schema failure), ledger, prompts/*.md (versioned)
├── steps/            s1_init … s9_write — each is run(ctx) -> StepOutput
└── render/           markdown renderers matching the skills' templates
tests/                unit tests + offline 9-step end-to-end + replay byte-identity
```

Extra machine-readable files the engine adds next to the skill outputs (harmless to downstream readers): `step3_screening_all.json`, `step4_citation_keys.json`, `step5_full_text/_access_log.json`, `step6_paper_digests.json`, `step6_sota.json`, `step7_gaps.json`, `step8_hypothesis.json`, `step9_manuscript/_validation.json`.

## Tests

```
python -m pytest tests -q
```

`tests/test_e2e_replay.py` runs all nine steps offline (fake LLM + fake HTTP), checks the file contracts, then replays with the cache in read-only mode and asserts every output file's sha256 is unchanged with zero external calls.

## Known limits

* arXiv LaTeX-source extraction and GROBID/OCR for scanned PDFs are not implemented (PyMuPDF text extraction is used; `pdftotext` is the fallback).
* `fulltext.translate` (bilingual `_zh.md` notes) is off by default because it is token-heavy.
* Journal impact factors in Step 8 come from the model's knowledge, not a live lookup; they are labelled with `~` when uncertain.
* arXiv throttles aggressively (HTTP 406/429); the engine spaces requests ~3 s apart and retries with backoff.
