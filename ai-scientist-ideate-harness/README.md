# ai-scientist-ideate-harness

The ideate stage of AI-Scientist (slides 3–5 of `aiscientist_architecture`): from a topic markdown to a list of 7-key
research ideas, run as a **harness of agents**. Each small step (Unit) is one agent. Each big step runs its Units
between two gates. A code conductor, not an LLM, decides what runs next.

```
topic.md ─▶ Stage A, once per topic                      Stage B, once per idea
            S1 define → S2 search → S3 screen →           P0 take a question → P1–P5 inside B5's three rounds
            S4 snowball → S5 export → F1 deconstruct →    → coherence gate → B6 finalize
            F2 align → F3 collide → F4 reconstruct
                                                            ─▶ <topic>.json + <topic>_research/ + ERRORS.md
```

## What is where

| Folder | What it is |
|---|---|
| `scripts/`, `references/`, `mcp/scholar_mcp`, `mcp/paper_pdf_mcp`, `SKILL.md` | The ideate skill. It implements every Unit: `ideate_tools.py`, `it_*.py`, the ledger, each Unit's checks, and the rules each Unit follows |
| `contracts/` | The architecture as data: 17 steps, 38 Units, 15 gates, 12 loops, 66 artifacts and retry policies (`architecture.json`, `units/`). `legacy_snapshot.json` is pinned by hash to `scripts/ideate_units.json` |
| `contracts/recipes/` | How each Unit is executed: `run` (a skill command), `write` (a worker: the Claude, OpenAI or Gemini API, an Ollama server or another provider), `fanout` (one worker per batch). All 38 are still `draft` |
| `ideate_v2/` | The referee: gate checks, loop bounds, retry ownership, error records, events and the three-level report (Unit → step → overall). Standard library only |
| `harness/` | The conductor: `PipelineAgent` → `StepAgent` / `GenerationAgent` → `UnitAgent` |
| `mcp/ideate_v2_mcp/` | Optional MCP server over `ideate_v2`, for a Claude session that inspects or conducts a run interactively (`references/orchestration.md`) |
| `evals/`, `tests/`, `scripts/tests/` | Behaviour cases and fixtures, the v2 and harness tests, and the skill's own suite |

**An agent** is one Unit contract plus one executor, run inside the same shell (`harness/shell.py`):

1. Upstream Units must be done.
2. The executor runs.
3. Every artifact the contract names must exist.
4. The Unit's own checks must pass.
5. A failure goes to the retry policy that owns it.

A custom executor goes through the same shell, so swapping a Unit cannot bypass its contract.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # Python >= 3.10; includes the Anthropic SDK
cp mcp/.env.example mcp/scholar_mcp/.env                    # then fill in the keys you have (gitignored)
export ANTHROPIC_API_KEY=...                                # the workers call the Claude API (or `ant auth login`)
```

Sources without a key are skipped and the run records a caveat; OpenAlex, arXiv, Crossref and PubMed need no key.
Full text (A6.d) looks for an open-access PDF in Unpaywall, OpenAlex, the PMC Cloud Service, the open publishers'
DOI patterns and arXiv. Unpaywall answers only with your own contact address in `PAPER_PDF_UNPAYWALL_EMAIL`; without
it the other sources still run, and a failed download says so. A6.c first takes PubMed Central's own XML of an
open-access paper (`pmc-text`: sections and tables' cells as published, and author manuscripts that have no PDF), then
converts the PDFs of the rest.

### poppler (standard and deep depth)

A6.c needs poppler's `pdftotext`, `pdftoppm` and `pdfinfo`: they render the figures of every PDF and convert the full
text when no `PDF2MD_API_KEY` is set. `--depth quick` reads no full text and needs none of them. Install one of:

```bash
sudo apt install poppler-utils              # Debian / Ubuntu / WSL
brew install poppler                        # macOS
conda install -c conda-forge poppler        # into the conda env that runs the harness
```

Check from the shell that will run `ideate-harness`: `pdftotext -v` must print a version. A conda install puts the
three programs in that env's `bin/`, so they are found only where the env is active (`conda activate <env>` first, or
its `bin/` on `PATH`); otherwise A6.c stops with `IDEATE.ENV.MISSING` ("pdftoppm / pdftotext / pdfinfo not found").
Install them, then run the same command again: the run resumes at A6.c.

## Try it

```bash
.venv/bin/ideate-harness check                     # contracts, docs, recipes, tests, evals, lint: everything should PASS
mkdir -p /tmp/try && cp evals/datasets/fusion_ready/eeg_topic.md /tmp/try/
.venv/bin/ideate-harness run /tmp/try/eeg_topic.md --dry-run --generations 2   # the whole pipeline on fixtures:
                                                                              # no network, no tokens
```

The dry run replaces the skill's commands and the model workers with fixtures. ideate_v2 still evaluates the contract
half of every gate for real. Inject faults to see how they are handled:

```bash
--inject A2.s=external_service                     # retried by the orchestrator (RP-UNIT), then done
--inject A2.s=external_service,external_service    # exhausted: downstream stops, one root cause
--inject A3=check:C05                              # a check failure: not retried, the run stops
--inject B5=revise:P2                              # round-2 revision: P2..P5 produced again
--inject GATE-coherence=fail,fail                  # decision gate: the question is abandoned, the next one taken
```

A real run (this costs tokens; start small):

```bash
.venv/bin/ideate-harness run path/to/topic.md --smoke-cap 4 --generations 1
```

`--smoke-cap N` limits every database and snowball route to N papers. The tokens and cost of every Unit are in the
run's summary. Resume a run with the same command; Units that are already done are skipped.

Other options:

- `--from F1 --to F4` runs part of Stage A.
- `--depth quick` runs without full text and with weak evidence.
- `--replay` returns recorded network answers instead of calling the services.

## The model Units: the Claude API

By default (`worker = "claude"`) every write and fan-out step is one call of the Anthropic Messages API, through the
official SDK (`harness/providers/claude.py`). It works as on an Ollama server (below): the conductor puts the files
and the read-only lookups into the prompt, the model answers with one JSON object, and the conductor writes the files
the step may write. A step that needs the worker to run a skill command itself is refused at once, and only B6 (each
generation's last Unit: `consume`, and a journal lookup on the web) does: no built-in provider runs it, so each
generation stops at B6. An agent of your own (`AgentProvider`, `harness/providers/agent.py`) could run it.

```toml
[harness]
worker = "claude"                   # the default
model = "claude-opus-5-5"           # the default

[harness.provider_options.claude]   # all optional
effort = "medium"                   # low | medium | high | xhigh | max (the default is Claude Opus 5.5's own);
                                    # "" sends none, for a model without effort
max_tokens = 64000                  # the answer, thinking included
context_window = 1000000            # tokens: a file over half of it is cut, a longer prompt is not sent
fallbacks = true                    # a request a safety classifier declines is answered by the model Anthropic
                                    # names for that category (server-side fallback, beta)
max_retries = 2                     # the SDK's own retries of a rate limit, an overload or a dropped connection
# base_url = "https://gateway.example.org"   # a gateway in front of the API (or ANTHROPIC_BASE_URL)
# price_per_mtok = [4.0, 20.0]      # USD per million input/output tokens, for a model the price table lacks
```

- Credentials are the SDK's: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` or an `ant auth login` profile.
- The answer is a structured output, decoded under the step's JSON schema. A schema with an open map (an object
  without fixed keys) cannot be one: that answer is asked for in the prompt and read from the text. A request the API
  refuses (400) for its schema or the fallback beta is sent once more without them.
- The Unit's rules and the conversation are cached: a fan-out's batches share the rules, and a revision reads the
  files of its first message back from the cache.
- Thinking is the model's own (adaptive); `effort` sets how much. `temperature` and `think` are Ollama's settings
  and are not sent.
- Each call's tokens and cost (list prices, cache reads and writes included) go into the run's summary.

## On the OpenAI or the Gemini API

`worker = "gpt"` (the OpenAI Responses API, `harness/providers/gpt.py`) and `worker = "gemini"` (the Gemini API's
generateContent, `harness/providers/gemini.py`) run the model Units the same way as the Claude API, each through its
official SDK:

```bash
.venv/bin/pip install -e ".[gpt]"       # openai;       export OPENAI_API_KEY=...
.venv/bin/pip install -e ".[gemini]"    # google-genai; export GEMINI_API_KEY=... (Vertex AI: the SDK's
                                        # GOOGLE_GENAI_USE_VERTEXAI, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION)
```

```toml
[harness]
worker = "gpt"                      # or "gemini"
model = "gpt-6-astra"               # the default; gemini's: "gemini-4-argon"

[harness.provider_options.gpt]      # all optional
effort = "high"                     # reasoning effort: none | low | medium | high | xhigh | max (default: the model's)
max_tokens = 64000                  # the answer, reasoning included
store = false                       # true lets OpenAI keep the responses

[harness.provider_options.gemini]   # all optional
effort = "high"                     # thinking level: minimal | low | medium | high (default: the model's)
max_tokens = 65536                  # the answer, thinking included
```

Both also take `context_window`, `max_retries`, `base_url` and `price_per_mtok`, as the Claude provider does.

| | GPT | Gemini |
|---|---|---|
| The answer's schema | A strict structured output: every object closed, every field required. A schema strict mode cannot take (an open map, an optional field) gets JSON mode | `response_json_schema` as it is, open maps too |
| Cache | OpenAI's automatic prompt caching; reads and writes are in the cost | Gemini's implicit caching; reads are in the cost |
| Not sent | `temperature` | `temperature`, `thinking_budget` |

As on the Claude API, B6 cannot run, a request refused (400) for its schema is sent once more
without it, and the cost is at list prices - for Gemini at the price in force on the day, as its announced changes
(December 1, 2026 and January 1, 2027) take effect.

## On an Ollama server

The model Units can run on an Ollama server over its HTTP API instead of the Claude API. Nothing else changes: the
same recipes, shell, gates and reports. Put this in a `harness.toml`:

```toml
[harness]
worker = "ollama"
ollama_url = "https://ollama.example.org"   # or http://127.0.0.1:11434
model = "qwen3.8"
num_ctx = 65536         # use the context the server loads the model with (`ollama ps`), or Ollama reloads the model;
                        # one the GPU cannot hold puts part of it on the CPU (`ollama ps`: PROCESSOR): on one server
                        # 131072 read prompts 15-30x and wrote 7x slower than 65536
think = false           # optional: a thinking model's reasoning off (faster); leave it out for the model's default
num_predict = 32768     # optional: the longest answer, reasoning tokens included (default 16384)
feedback_rounds = 2     # optional: revisions a refused submission gets (default: the contract's one)
# batch_chars = 40000   # optional: characters of papers / candidates per fan-out call (default: what num_ctx holds)
# ollama_parallel = 1   # optional: fan-out calls at once (one server answers one at a time; a queued request is silent)
# ollama_busy_retries = 4    # optional: a call the server or its proxy dropped (busy server, 524) is tried again
# ollama_busy_wait_s = 120   # after 2, 4, 8, 15 minutes, and only once a one-token probe finds the server free;
                             # a stream cut before `done` counts as dropped, never as an answer
# ollama_keep_alive = "30m"  # optional: keep the model loaded between Units (a reload before the first byte can
                             # trip a proxy's timeout after the network steps)
```

```bash
export OLLAMA_API_KEY=...        # only if the server sits behind an auth proxy; sent as "Authorization: Bearer ..."
.venv/bin/ideate-harness run path/to/topic.md --config harness.toml --to F4
```

The local model gets no tools, so the conductor does what an agent's tools would (`harness/providers/chat.py`, with
Ollama's own HTTP handling in `harness/providers/ollama.py`):

- It puts into the prompt the files the step may read, and the output of the read-only lookups the recipe allows
  and checks the recipe allows (`list-papers`, `list-methods`, `env-probe`, `plan-status`, and B5's
  `argument-check`, `tree-check`, `attack-check`, `pack-check`).
- The model answers with one JSON object, `{"files": [{"path", "content"}], "note"}`, decoded under a JSON schema.
  A step whose recipe names a `schema` for its file is answered as `{"answer": <that object>, "note"}` instead: the
  file's own structure is the grammar (A1.p protocol, A1.q fill, A1.v context, A1.e evaluation, A2.c verdicts, A3
  scores per batch, A7.D records per batch, A7.A1 words, A7.A2 coordinates, A7.A3 Points, A7.X2 / B3.c judgements,
  B1 lens, A7.R2 Planes with every paper's Plane in `assign`). Free text in these schemas has a `maxLength`, so a
  model caught repeating itself inside one string stops there instead of writing until `num_predict`.
- The answer is streamed, so a proxy in front of the server never sees an idle request (Cloudflare closes one after
  100 s), and fan-outs run one call at a time against one server.
- Code settles what follows from the inputs before a model is asked: A1.q's queries and their axes
  (`frame strategy-brief`), A1.v's installed packages (`set-context` imports them), A2.c's allowed verdicts
  (`search-check`), A7.D's ids and record structure and a near-verbatim quote's exact words (`decon-merge`), A3's
  evidence quotes (`screen-merge`), A7.A1's concepts from the answers (a word whose roles share no kind asked once per
  role), A7.A3's Point structure (`align-points --merge-answers`), B3's open moves, severity bound, an empty cell's
  papers and feasibility cap (the digest's `gap:` lines), A7.R2's Plane members (`assign`), B2's methodology legend
  and paper–theme mapping (`sota-tables`), and in A7.R3 / B2 the sections that must say (TBD) because the corpus has
  nothing for them to cite. Plan commands take `--max-chars $BUDGET`, so no batch is cut to fit a prompt; a full
  text longer than `$BUDGET` reaches A7.D as an excerpt made by code (`decon-plan`: the reference list and back matter
  left out, each section's beginning kept), as the archived engine cut its digests' text. Its quotes are still checked
  against the whole paper.
- A revision prompt shows a file again only where a tool changed it after the model wrote it (the model's own answer
  is already in the conversation); a file an earlier run left is shown on a first call as context to rewrite from.
- The conductor writes only the files the step may write, and checks that each JSON file parses.
- A refused submission goes back to the same conversation.

Limits to know:

- **Ollama cuts an over-long prompt silently.** The worker estimates each prompt before sending it and refuses one
  that does not fit `num_ctx`. It also refuses an answer whose prompt filled the whole context.
- **A step whose task asks the worker to run a skill command itself is refused at once**, with the command named.
  Today this is B6 (`consume`). A2.c's re-plan runs its commands as steps of its own (`frame replan-brief` -> new
  words -> `frame replan-apply`), and so does B3.5 (`questions-plan` -> one question per gap -> `questions-handovers`
  -> section 9 -> `questions-attach`); A7.R2, A7.R3 and B2 read a digest of the ids they may cite (`recon-digest`).
- **At the scale of a standard-depth topic** (hundreds of papers) the big worklists are fanned out in batches:
  A7.A1's words (`align-terms --batches`, the vocabulary built by code from the answers), A7.A2's unsettled axes
  (`align-coords --batches`), A7.A3's candidates (`align-points --batches`). The reconstruct Units read digests
  (`recon-digest`), which at that scale run to 60-200k characters: a context of 64k tokens or more is needed there.
- B6's journal lookup uses web search, which an Ollama worker does not have.
- Strict checks (verbatim quotes, schemas) fail more often with smaller models: compare models on the same topic.
- **A proxy with a time-to-first-byte limit** (Cloudflare: 100 s, error 524) in front of the server is the most common
  cause of failed calls: a request that waits behind another is closed, and the server may still compute the dropped
  answer. Reach the server directly (its LAN address, `http://127.0.0.1:11434`, or an SSH tunnel) when you can; the
  worker streams, runs one call at a time, keeps the model loaded and re-sends a dropped call only once the server is
  free (a re-send to a server still writing the dropped answer would queue a second one): a one-token probe repeats
  the call's prompt, so the server's prompt cache holds it and the re-send starts writing at once. A prompt of more
  than 20k characters gets that probe before it is sent at all (`prewarm`): if the proxy drops the probe, the server
  still finishes reading the prompt, and the call then starts writing at once - instead of a dropped call whose whole
  answer the server writes for nobody before the re-send.

## Another model provider

The Claude, OpenAI and Gemini APIs and an Ollama server are four providers behind one interface
(`harness/providers/`). The executor gives every provider the same request (`WorkerRequest`: task, system prompt,
folder, `FileScope`, the step's commands and tools, the session to resume) and gets the same result back
(`WorkerResult`). It never asks which provider runs.

| Kind | Base class | Built in | The conductor's part |
|---|---|---|---|
| A chat model without tools | `ChatProvider` (`chat.py`) | `ClaudeProvider` (`claude.py`, worker `claude`), `GPTProvider` (`gpt.py`, worker `gpt`), `GeminiProvider` (`gemini.py`, worker `gemini`), `OllamaProvider` (`ollama.py`, worker `ollama`) | The files and the read-only lookups in the prompt, one JSON answer under a schema, the conductor writes the files the scope allows |
| An agent with tools | `AgentProvider` (`agent.py`) | None (`claude -p` was one); the only kind that could run B6 | The shims on its PATH and the allowed commands; the agent opens and writes its files itself |

To add one, subclass the base class that fits and set its `name`:

- A chat API (OpenAI-compatible, vLLM) implements only `chat()`: one call that takes the conversation and the
  answer's JSON schema, and returns the answer's text with its tokens and cost. The prompt, the conversation per
  session, the correction turn and the write scope come from `ChatProvider`; `claude.py`, `gpt.py`, `gemini.py` and
  `ollama.py` are four.
- An agent (another coding-agent CLI, an API with tool use) implements `run()`.

A provider can also override how long to wait before a dropped call is sent again (`retry_delay`; the default is the
contract's RP-TRANSPORT), the fan-out width (`parallel`), the batch size (`batch_budget`), its context window
(`window`), its model when none is set (`default_model`) and the checks on a config it cannot run with
(`check_config`). Name it in `harness.toml` with no change to the harness:

```toml
[harness]
worker = "my_pkg.providers:OpenAIProvider"   # or a name registered with harness.providers.register()
model = "my-model"

[harness.provider_options.openai]            # its own settings, under its `name`; read as self.options()
base_url = "https://llm.example.org/v1"
```

## What a run leaves

| Where | What |
|---|---|
| `<topic>.json` | The ideas (the downstream contract: exactly 7 keys each) |
| `<topic>_research/` | The evidence base and every Unit's files (the layout is in `SKILL.md`) |
| `<topic>_research/ERRORS.md` | The report: status per step, root causes, and the caveats each idea must disclose |
| `<topic>_research/_state/errors/<run_id>/` | Events and error records per Unit; step and overall reports |
| `<topic>_research/_state/harness/<run_id>/` | `summary.json` (status, tokens and cost per Unit), worker prompts and answers, command logs |

To inspect a research folder:

- `ideate-harness status <RD>` shows every Unit's state.
- `ideate-harness report <RD>` rebuilds the report.
- `ideate-harness trace <RD> <error_id|unit>` follows an error to its root cause and lists what it affects.

## Swapping a Unit

```bash
.venv/bin/ideate-harness run topic.md --agent A3=my_package.screen:MyScreen
```

`MyScreen` needs one method:

```python
execute(ctx, unit, recipe, phase, gen, attempt) -> harness.executors.ExecResult
```

It must leave the same artifacts as the Unit it replaces; the shell checks them.

## Status

- The conductor, the contracts and the dry run are complete and tested: `ideate-harness check` passes 14/14.
- The recipes are drafts: none has run on a real topic yet.
- Known open questions are listed in `ARCHITECTURE.md` §10. For example, Stage B is not on the ledger yet (OQ-06), and
  loops without a declared bound get the bounds in `harness/config.py` (OQ-07).
