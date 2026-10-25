# AI-Scientist-v2 Ideation Stage — Reference

Source files (repo root `/Users/kyc/PythonProject/AI-Scientist-v2`):

- `ai_scientist/perform_ideation_temp_free.py` — the ideation loop, prompts, parsing.
- `ai_scientist/tools/semantic_scholar.py` — `SemanticScholarSearchTool` (the `SearchSemanticScholar` action).
- `ai_scientist/tools/base_tool.py` — `BaseTool(name, description, parameters)` with abstract `use_tool(**kwargs)`.
- `ai_scientist/ideas/i_cant_believe_its_not_better.md` — example topic/workshop description.
- `ai_scientist/ideas/i_cant_believe_its_not_better.json` — example idea archive produced from it.
- `ai_scientist/treesearch/bfts_utils.py` — `idea_to_markdown` (idea.json -> idea.md).
- `launch_scientist_bfts.py` — consumer of the idea JSON (selects one idea, writes `idea.json` + `idea.md`).

## Table of contents

1. Topic / workshop markdown input format
2. Verbatim prompts
   2.1 Tool definitions and how they are rendered
   2.2 `system_prompt` (fully rendered)
   2.3 `idea_generation_prompt`
   2.4 `idea_reflection_prompt`
   2.5 FinalizeIdea IDEA JSON schema and field descriptions
   2.6 ACTION / ARGUMENTS response format and parsing rules
3. Control flow of `generate_temp_free_idea`
4. Idea archive JSON: naming, reloading, saving
5. Semantic Scholar tool: API details, formatting, rate limits, backoff
6. `idea_to_markdown` conversion (idea.json -> idea.md)
7. Example idea archive (first two ideas, summarized)
8. CLI defaults

---

## 1. Topic / workshop markdown input format

The ideation script takes a single markdown file (`--workshop-file`) whose entire text is read and injected verbatim as `{workshop_description}` into the first user prompt. There is no parsing of the file; any markdown works, but the shipped example uses this structure:

```markdown
# Title: <workshop / topic title>

## Keywords
<comma-separated keywords>

## TL;DR
<one or two sentences>

## Abstract
<one paragraph, conference-style call-for-papers abstract>
```

Example file `ai_scientist/ideas/i_cant_believe_its_not_better.md` (summarized):

- **Title:** "I Can't Believe It's Not Better: Challenges in Applied Deep Learning"
- **Keywords:** negative results, deep learning, failure modes
- **TL;DR:** Why don't deep learning approaches always deliver as expected in the real world? Dive deep into the pitfalls and challenges of applied deep learning.
- **Abstract:** One paragraph describing the ICBINB workshop: promoting slow science and a community for surprising/negative results; DL performs well on benchmarks but faces challenges when deployed in dynamic real-world conditions; the workshop seeks contributions on challenges, unexpected outcomes and common principles behind failure modes across healthcare, scientific discovery, robotics, education, fairness, social sciences; failure modes include suboptimal performance, safety/reliability concerns, ethical/societal challenges; goal is to find common patterns across disciplines and treat negative results as learning opportunities to drive more robust, reliable, applicable AI.

The README instructs users to "Create a new Markdown file describing your desired subject field or topic, following the structure of the example".

---

## 2. Verbatim prompts

### 2.1 Tool definitions and how they are rendered

The `tools` list contains two entries, in this order:

1. `SemanticScholarSearchTool()` instance (a `BaseTool`) with
   - `name = "SearchSemanticScholar"`
   - `description = "Search for relevant literature using Semantic Scholar. Provide a search query to find relevant papers."`
   - `parameters = [{"name": "query", "type": "str", "description": "The search query to find relevant papers."}]`
   - `max_results = 10`
2. A plain dict `{"name": "FinalizeIdea", "description": <see below>}` (not a `BaseTool`; handled specially).

`tools_dict = {tool.name: tool for tool in tools if isinstance(tool, BaseTool)}` — so only `SearchSemanticScholar` is in `tools_dict`; `FinalizeIdea` is matched by string comparison in the loop.

`tool_descriptions` is built as `"\n\n".join(f"- **{name}**: {description}")` for each tool, and `tool_names_str` is `", ".join('"' + name + '"')`, i.e. exactly:

```
"SearchSemanticScholar", "FinalizeIdea"
```

The `FinalizeIdea` description string, verbatim:

```
Finalize your idea by providing the idea details.

The IDEA JSON should include the following fields:
- "Name": A short descriptor of the idea. Lowercase, no spaces, underscores allowed.
- "Title": A catchy and informative title for the proposal.
- "Short Hypothesis": A concise statement of the main hypothesis or research question. Clarify the need for this specific direction, ensure this is the best setting to investigate this idea, and there are not obvious other simpler ways to answer the question.
- "Related Work": A brief discussion of the most relevant related work and how the proposal clearly distinguishes from it, and is not a trivial extension.
- "Abstract": An abstract that summarizes the proposal in conference format (approximately 250 words).
- "Experiments": A list of experiments that would be conducted to validate the proposal. Ensure these are simple and feasible. Be specific in exactly how you would test the hypothesis, and detail precise algorithmic changes. Include the evaluation metrics you would use.
- "Risk Factors and Limitations": A list of potential risks and limitations of the proposal.
```

### 2.2 `system_prompt` (fully rendered)

The code defines `system_prompt` as an f-string with `{tool_descriptions}` and `{tool_names_str}` substituted and `{{ }}` unescaped to `{ }`. The exact text sent as the system message is:

````
You are an experienced AI researcher who aims to propose high-impact research ideas resembling exciting grant proposals. Feel free to propose any novel ideas or experiments; make sure they are novel. Be very creative and think out of the box. Each proposal should stem from a simple and elegant question, observation, or hypothesis about the topic. For example, they could involve very interesting and simple interventions or investigations that explore new possibilities or challenge existing assumptions. Clearly clarify how the proposal distinguishes from the existing literature.

Ensure that the proposal does not require resources beyond what an academic lab could afford. These proposals should lead to papers that are publishable at top ML conferences.

You have access to the following tools:

- **SearchSemanticScholar**: Search for relevant literature using Semantic Scholar. Provide a search query to find relevant papers.

- **FinalizeIdea**: Finalize your idea by providing the idea details.

The IDEA JSON should include the following fields:
- "Name": A short descriptor of the idea. Lowercase, no spaces, underscores allowed.
- "Title": A catchy and informative title for the proposal.
- "Short Hypothesis": A concise statement of the main hypothesis or research question. Clarify the need for this specific direction, ensure this is the best setting to investigate this idea, and there are not obvious other simpler ways to answer the question.
- "Related Work": A brief discussion of the most relevant related work and how the proposal clearly distinguishes from it, and is not a trivial extension.
- "Abstract": An abstract that summarizes the proposal in conference format (approximately 250 words).
- "Experiments": A list of experiments that would be conducted to validate the proposal. Ensure these are simple and feasible. Be specific in exactly how you would test the hypothesis, and detail precise algorithmic changes. Include the evaluation metrics you would use.
- "Risk Factors and Limitations": A list of potential risks and limitations of the proposal.

Respond in the following format:

ACTION:
<The action to take, exactly one of "SearchSemanticScholar", "FinalizeIdea">

ARGUMENTS:
<If ACTION is "SearchSemanticScholar", provide the search query as {"query": "your search query"}. If ACTION is "FinalizeIdea", provide the idea details as {"idea": { ... }} with the IDEA JSON specified below.>

If you choose to finalize your idea, provide the IDEA JSON in the arguments:

IDEA JSON:
```json
{
  "idea": {
    "Name": "...",
    "Title": "...",
    "Short Hypothesis": "...",
    "Related Work": "...",
    "Abstract": "...",
    "Experiments": "...",
    "Risk Factors and Limitations": "..."
  }
}
```

Ensure the JSON is properly formatted for automatic parsing.

Note: You should perform at least one literature search before finalizing your idea to ensure it is well-informed by existing research.
````

Raw (unrendered) source for reference — the only differences are the two placeholders and the doubled braces:

```
... You have access to the following tools:

{tool_descriptions}

Respond in the following format:

ACTION:
<The action to take, exactly one of {tool_names_str}>

ARGUMENTS:
<If ACTION is "SearchSemanticScholar", provide the search query as {{"query": "your search query"}}. If ACTION is "FinalizeIdea", provide the idea details as {{"idea": {{ ... }}}} with the IDEA JSON specified below.>
...
```

Placeholders:
- `{tool_descriptions}` — the `"\n\n"`-joined `- **name**: description` bullets shown above.
- `{tool_names_str}` — `"SearchSemanticScholar", "FinalizeIdea"`.

The same `system_prompt` is used as the system message for **every** LLM call in the ideation loop (initial generation and every reflection round).

### 2.3 `idea_generation_prompt`

Verbatim (Python `str.format` template):

```
{workshop_description}

Here are the proposals that you have already generated:

'''
{prev_ideas_string}
'''

Begin by generating an interestingly new high-level research proposal that differs from what you have previously proposed.
```

Placeholders:
- `{workshop_description}` — the full text of the `--workshop-file` markdown, read with `f.read()`, unmodified.
- `{prev_ideas_string}` — `"\n\n".join(idea_str_archive)`, where each element of `idea_str_archive` is `json.dumps(idea)` (a single-line compact JSON string of one previously finalized idea). Includes ideas reloaded from the JSON archive file *and* ideas finalized earlier in the current run. Empty string on the very first idea with no archive (the `'''` fences remain, containing nothing).

Note there is a trailing newline in the template (the closing `"""` is on its own line).

### 2.4 `idea_reflection_prompt`

Verbatim:

```
Round {current_round}/{num_reflections}.

In your thoughts, first carefully consider the quality, novelty, and feasibility of the proposal you just created.
Include any other factors that you think are important in evaluating the proposal.
Ensure the proposal is clear and concise, and the JSON is in the correct format.
Do not make things overly complicated.
In the next attempt, try to refine and improve your proposal.
Stick to the spirit of the original idea unless there are glaring issues.

If you have new information from tools, such as literature search results, incorporate them into your reflection and refine your proposal accordingly.

Results from your last action (if any):

{last_tool_results}
```

Placeholders:
- `{current_round}` — `reflection_round + 1` (so the first reflection message says `Round 2/5` with defaults; round 1 is the generation prompt).
- `{num_reflections}` — total rounds (`num_reflections` argument, default 5).
- `{last_tool_results}` — `last_tool_results or "No new results."`. `last_tool_results` is the string returned by the most recent tool call (`SearchSemanticScholar` formatted papers, or `"No papers found."`, or `"Error using tool SearchSemanticScholar: <exception>"`). It is **not** reset between rounds, so if the model emits an invalid action in a later round, the previous search results are shown again. It starts as `""` for each new idea, hence `"No new results."` if the first response had no valid tool call.

Trailing newline present in the template.

### 2.5 FinalizeIdea IDEA JSON schema and field descriptions

The `ARGUMENTS` for `FinalizeIdea` must be a JSON object with a single top-level key `"idea"` whose value has these seven keys (order as specified in the prompt):

| Field | Description (verbatim from the tool description) | Observed type in archive |
|---|---|---|
| `Name` | A short descriptor of the idea. Lowercase, no spaces, underscores allowed. | string (e.g. `compositional_regularization_nn`) |
| `Title` | A catchy and informative title for the proposal. | string |
| `Short Hypothesis` | A concise statement of the main hypothesis or research question. Clarify the need for this specific direction, ensure this is the best setting to investigate this idea, and there are not obvious other simpler ways to answer the question. | string |
| `Related Work` | A brief discussion of the most relevant related work and how the proposal clearly distinguishes from it, and is not a trivial extension. | string |
| `Abstract` | An abstract that summarizes the proposal in conference format (approximately 250 words). | string |
| `Experiments` | A list of experiments that would be conducted to validate the proposal. Ensure these are simple and feasible. Be specific in exactly how you would test the hypothesis, and detail precise algorithmic changes. Include the evaluation metrics you would use. | list of strings (prompt skeleton shows `"..."` but shipped examples use JSON arrays) |
| `Risk Factors and Limitations` | A list of potential risks and limitations of the proposal. | list of strings |

Skeleton exactly as shown to the model:

```json
{
  "idea": {
    "Name": "...",
    "Title": "...",
    "Short Hypothesis": "...",
    "Related Work": "...",
    "Abstract": "...",
    "Experiments": "...",
    "Risk Factors and Limitations": "..."
  }
}
```

Only `arguments_json.get("idea")` is validated (must be truthy); no per-field validation occurs. The `idea` dict is stored as-is. Later, `launch_scientist_bfts.py` uses `idea['Name']` for the experiment directory name (`experiments/{date}_{Name}_attempt_{attempt_id}`) and may add a `"Code"` key.

### 2.6 ACTION / ARGUMENTS response format and parsing rules

Expected model output:

```
ACTION:
<exactly one of "SearchSemanticScholar", "FinalizeIdea">

ARGUMENTS:
<JSON object; may be wrapped in a ```json fenced block>
```

Parsing in `generate_temp_free_idea`:

- `action_pattern = r"ACTION:\s*(.*?)\s*ARGUMENTS:"` with `re.DOTALL | re.IGNORECASE`; group 1 stripped -> `action`.
- `arguments_pattern = r"ARGUMENTS:\s*(.*?)(?:$|\nTHOUGHT:|\n$)"` with `re.DOTALL | re.IGNORECASE`; group 1 stripped -> `arguments_text`. (Because of the non-greedy match with `$` alternatives under DOTALL, the group effectively runs to end-of-string or to a `\nTHOUGHT:` line.)
- If both matches are not found -> `ValueError("Failed to parse the LLM response.")` -> caught, traceback printed, **the reflection loop for this idea breaks** (idea is abandoned, no retry; outer loop moves to the next generation index).
- If `arguments_text.startswith("```json")`, the inner content of the first ```` ```json ... ``` ```` fence is extracted.
- If `action in tools_dict` (i.e. `SearchSemanticScholar`):
  - `json.loads(arguments_text)`; failure -> `ValueError("Invalid arguments JSON for SearchSemanticScholar.")` -> loop breaks.
  - `tool.use_tool(**arguments_json)` -> `last_tool_results = result`; any exception -> `last_tool_results = f"Error using tool {action}: {str(e)}"` (loop continues).
- Elif `action == "FinalizeIdea"`:
  - `json.loads(arguments_text)`; `idea = arguments_json.get("idea")`; missing -> `ValueError("Missing 'idea' in arguments.")` -> loop breaks.
  - `idea_str_archive.append(json.dumps(idea))`; `idea_finalized = True`; `break`.
- Else: prints "Invalid action. Please specify one of the available tools." and the available actions; the loop simply proceeds to the next reflection round (the model is *not* told explicitly it was invalid, other than via `last_tool_results` being unchanged).

Tool arguments for `SearchSemanticScholar`: `{"query": "your search query"}` -> `use_tool(query=...)`.

---

## 3. Control flow of `generate_temp_free_idea`

Signature:

```python
def generate_temp_free_idea(
    idea_fname: str,
    client: Any,
    model: str,
    workshop_description: str,
    max_num_generations: int = 20,
    num_reflections: int = 5,
    reload_ideas: bool = True,
) -> List[Dict]
```

Steps:

1. **Reload archive.** If `reload_ideas` and `idea_fname` exists: load the JSON list and append `json.dumps(idea)` for each entry to `idea_str_archive`; print `Loaded N ideas from ...`. Otherwise print `No ideas found in ... Starting from scratch.`
2. **Outer loop** `for gen_idx in range(max_num_generations)` — each iteration attempts to produce exactly one new idea. Prints `Generating proposal {gen_idx+1}/{max_num_generations}`.
   - `prev_ideas_string = "\n\n".join(idea_str_archive)` (recomputed each generation, so ideas finalized earlier in the run are included).
   - `last_tool_results = ""`, `idea_finalized = False`, `msg_history = []` (fresh conversation per idea).
   - **Inner loop** `for reflection_round in range(num_reflections)`:
     - Round 0: `prompt_text = idea_generation_prompt.format(workshop_description=..., prev_ideas_string=...)`.
     - Rounds >= 1: `prompt_text = idea_reflection_prompt.format(current_round=reflection_round+1, num_reflections=num_reflections, last_tool_results=last_tool_results or "No new results.")`.
     - Call `get_response_from_llm(prompt=prompt_text, client=client, model=model, system_message=system_prompt, msg_history=msg_history)`; the returned `msg_history` (user + assistant turns accumulated) is carried across rounds so the model sees its previous ACTION/ARGUMENTS and the reflection prompts. No temperature is passed (the LLM helper's default is used).
     - Parse ACTION/ARGUMENTS as in §2.6. Search results are only delivered to the model via `{last_tool_results}` in the **next** round's reflection prompt.
     - On `FinalizeIdea` -> archive and `break`. On parse failure -> `break` (idea lost).
   - If the inner loop exhausts all `num_reflections` rounds without a `FinalizeIdea`, nothing is archived for this generation.
   - Whole generation is wrapped in `try/except` that prints the traceback and `continue`s.
3. **Save.** After the outer loop, `ideas = [json.loads(s) for s in idea_str_archive]` and the entire list (reloaded + new) is written to `idea_fname` with `json.dump(ideas, f, indent=4)`. Prints `Stored N ideas in ...` and returns `ideas`.

Effective budget: at most `num_reflections` LLM calls per idea (default 5), i.e. up to 4 search-then-reflect cycles before the last round must finalize; if the model finalizes on round 1 without searching, that is accepted (the "at least one literature search" is prompt guidance only, not enforced).

**When `SearchSemanticScholar` is called:** whenever the model chooses `ACTION: SearchSemanticScholar` in any round. The system prompt asks for at least one search before finalizing. Typical trajectory: Round 1 -> search; Round 2 (reflection with results) -> possibly another search or refine; ... -> `FinalizeIdea`.

---

## 4. Idea archive JSON: naming, reloading, saving

- **Naming:** in `__main__`, `idea_fname = args.workshop_file.replace(".md", ".json")` — the archive lives next to the topic markdown with the same basename (`ideas/i_cant_believe_its_not_better.md` -> `ideas/i_cant_believe_its_not_better.json`).
- **Format:** a JSON array of idea objects (each with the seven fields above), `indent=4`.
- **Reloading:** on start, if the file exists and `reload_ideas=True` (default; the CLI never turns it off), all existing ideas are loaded and become the "already generated" context, so re-running the script appends new, different ideas rather than overwriting.
- **Saving:** the full list is rewritten at the end of the run (not incrementally); a crash mid-run loses ideas finalized in that run.
- **Downstream:** `launch_scientist_bfts.py --load_ideas <file>.json --idea_idx N` picks `ideas[N]`; if `--load_code` is set it looks for a sibling `<file>.py` (same basename, `.py` extension) and passes its path to `idea_to_markdown`.

---

## 5. Semantic Scholar tool: API details, formatting, rate limits, backoff

Class `SemanticScholarSearchTool(BaseTool)` in `ai_scientist/tools/semantic_scholar.py`.

**Constructor**
- `name="SearchSemanticScholar"`, description as above, `max_results=10`.
- `self.S2_API_KEY = os.getenv("S2_API_KEY")`; if unset emits `warnings.warn("No Semantic Scholar API key found. Requests will be subject to stricter rate limits. Set the S2_API_KEY environment variable for higher limits.")`.

**`use_tool(query: str) -> Optional[str]`**
- `papers = self.search_for_papers(query)`; returns `self.format_papers(papers)` if any, else the string `"No papers found."`.

**`search_for_papers(query) -> Optional[List[Dict]]`**
- Decorated with `@backoff.on_exception(backoff.expo, (requests.exceptions.HTTPError, requests.exceptions.ConnectionError), on_backoff=on_backoff)` — exponential backoff with **no max_tries / max_time**, so HTTP 429 (rate limit) or 5xx responses are retried indefinitely with exponentially growing waits (plus backoff's default jitter). `on_backoff` prints `Backing off {wait:0.1f} seconds after {tries} tries calling function search_for_papers at HH:MM:SS`.
- Empty query -> `None`.
- Request: `GET https://api.semanticscholar.org/graph/v1/paper/search`
  - headers: `{"X-API-KEY": S2_API_KEY}` only if the key is set; otherwise `{}` (unauthenticated requests share the public rate limit, commonly ~1 request/sec shared pool, so 429s and backoff are expected).
  - params: `{"query": query, "limit": self.max_results (10), "fields": "title,authors,venue,year,abstract,citationCount"}`.
- Prints `Response Status Code: <code>` and `Response Content: <first 500 chars>`.
- `rsp.raise_for_status()` (raises `HTTPError` -> triggers backoff).
- `results = rsp.json()`; if `results.get("total", 0) == 0` -> `None`.
- `papers = results.get("data", [])`, sorted by `citationCount` descending (missing -> 0).

**`format_papers(papers) -> str`** — the string returned to the ideation loop as `last_tool_results`. Each paper `i` (0-based, printed 1-based) is rendered as:

```
{i+1}: {title}. {author names joined by ", "}. {venue}, {year}.
Number of citations: {citationCount}
Abstract: {abstract}
```

with fallbacks `"Unknown Title"`, `"Unknown"` (author name), `"Unknown Venue"`, `"Unknown Year"`, `"N/A"`, `"No abstract available."`. Entries are joined with `"\n\n"`. Note: when the S2 API returns `null` for a field (e.g. `abstract: null`), `dict.get` returns `None` and the text `None` is rendered (the fallback only applies to missing keys).

**Module-level `search_for_papers(query, result_limit=10)`** (used elsewhere, e.g. citation gathering in writeup): same endpoint; fields `title,authors,venue,year,abstract,citationStyles,citationCount`; backoff only on `HTTPError`; `time.sleep(1.0)` after each successful request; returns raw `results["data"]` unsorted.

---

## 6. `idea_to_markdown` conversion (idea.json -> idea.md)

`ai_scientist/treesearch/bfts_utils.py`:

```python
def idea_to_markdown(data: dict, output_path: str, load_code: str) -> None
```

For each `(key, value)` in the idea dict, **in dict order**:

- Header: `## {key.replace("_", " ").title()}` followed by a blank line. E.g. `Name` -> `## Name`, `Short Hypothesis` -> `## Short Hypothesis`, `Risk Factors and Limitations` -> `## Risk Factors And Limitations` (note `.title()` capitalizes "And").
- If value is a `list`/`tuple`: one `- {item}` line per item, then a blank line.
- If value is a `dict`: for each sub-key, `### {sub_key}` then `{sub_value}` and a blank line.
- Otherwise: `{value}` then a blank line.

Then, if `load_code` is truthy: asserts the path exists (message: `Code path at {load_code} must exist if using the 'load_code' flag. This is an optional code prompt that you may choose to include; if not, please do not set 'load_code'.`) and appends:

````
## Code To Potentially Use

Use the following code as context for your experiments:

```python
<contents of the code file>
```

````

Resulting layout for a standard idea:

````
## Name

compositional_regularization_nn

## Title

Enhancing Compositional Generalization ...

## Short Hypothesis

...

## Related Work

...

## Abstract

...

## Experiments

- Implement ...
- Train ...

## Risk Factors And Limitations

- ...

## Code To Potentially Use          (only when --load_code)

Use the following code as context for your experiments:

```python
...
```
````

In `launch_scientist_bfts.py`: `idea_dir = experiments/{YYYY-mm-dd_HH-MM-SS}_{idea['Name']}_attempt_{attempt_id}`; `idea_to_markdown(ideas[idx], idea_dir/idea.md, code_path)` where `code_path = load_ideas.rsplit(".",1)[0] + ".py"` if `--load_code` and the file exists, else `None`. Separately, if code and/or `hf_dataset_reference.py` (with `--add_dataset_ref`) were loaded, their concatenation is added to the idea dict as `"Code"` and the dict is dumped to `idea_dir/idea.json` (`indent=4`), which is what `bfts_config.yaml`'s `desc_file` points at.

---

## 7. Example idea archive (first two ideas, summarized)

`ai_scientist/ideas/i_cant_believe_its_not_better.json` contains 3 ideas. First two:

1. **`compositional_regularization_nn`** — "Enhancing Compositional Generalization in Neural Networks via Compositional Regularization". Hypothesis: adding a compositional regularization term to the loss encourages compositional representations and better generalization to novel combinations. Related work cites Ito et al. NeurIPS 2022 and notes lack of explicit regularization approaches. Abstract ~250 words; Experiments is a 6-item list (implement term in seq2seq+attention; SCAN/COGS; IWSLT MT and GeoQuery parsing; embedding visualization + compositionality metrics; ablations on regularization strength; comparison to meta-learning/specialized architectures). Risks is a 5-item list (dataset variance, hurting primary task, compute overhead, defining compositional structures, scalability).
2. **`interpretability_failure_modes`** — "When Interpretability Fails: Investigating the Limitations of Explanation Methods in Deep Learning". Hypothesis: explanation methods are not always reliable; identifying failure conditions informs better use/development. Related work cites Adebayo et al. 2018 (Sanity Checks) and Kindermans et al. 2017. Experiments is a 7-item list (diverse pretrained models; Grad-CAM/IG/LIME/SHAP; controlled failure-inducing settings; fidelity evaluation; new metrics; user studies; guidelines). Risks is a 5-item list (no ground truth, generalizability, subjectivity, user-study design, compute).

Both confirm: `Experiments` and `Risk Factors and Limitations` are JSON arrays of strings; the other five fields are strings.

---

## 8. CLI defaults (`python ai_scientist/perform_ideation_temp_free.py`)

| Flag | Default | Meaning |
|---|---|---|
| `--model` | `gpt-4o-2024-05-13` | LLM (must be in `AVAILABLE_LLMS`); `create_client(model)` returns `(client, client_model)` |
| `--max-num-generations` | `1` | Number of new ideas to attempt this run (function default is 20) |
| `--workshop-file` | `ideas/i_cant_believe_its_not_better.md` | Topic markdown |
| `--num-reflections` | `5` | Rounds per idea (generation + up to 4 reflections) |

Output: `<workshop-file with .md -> .json>`; prints `{workshop_file} generated {N} ideas.` where N is the total archive size including reloaded ideas.
