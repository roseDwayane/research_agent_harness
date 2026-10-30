# Stage A — literature foundation (runs once per topic)

Everything here builds `<topic>_research/`, the shared evidence base that every generated idea draws on. It is the
expensive part of ideation, so it runs once and every step is resumable. Intermediate artifacts are written in English
only; nobody downstream reads a second language.

Stage A has two blocks. The **literature search** (A1–A5: define → search → screen → augment → export) has its own
references in [search/](search/README.md); this file covers what comes after it and the conventions both share.

## Contents

| § | Step | What it produces |
|---|---|---|
| 1 | Conventions | — |
| — | **A1–A5** literature search → [search/README.md](search/README.md) | `step0`–`step4` files: protocol, collection, shortlist, citation keys, bibliography |
| 2 | **A6** fulltext | `pdfs/`, `step5_full_text/` |
| 3 | **A7** knowledge base → [knowledge-passes.md](knowledge-passes.md) | `knowledge/` |
| 4 | Depth levels | — |
| 5 | Degraded paths | — |

---

## 1. Conventions

```bash
SK=.claude/skills/ai-scientist-ideate            # this skill
PY=/path/to/python                               # from: bash .claude/skills/ai-scientist/scripts/check_env.sh
RD=<topic>_research                              # from: $PY $SK/scripts/ideate_tools.py paths --topic <topic>.md
```

Shell variables do not survive between separate Bash tool calls, so set `SK`, `PY` and `RD` at the top of every
command block rather than once.

`$PY` must be the interpreter that has the `mcp` package (the same one `check_env.sh` reports; `mcp_bridge.py` exits
with code 4 if it is missing). Export `IDEATE_PYTHON=$PY` before calling `pdf2md.sh`.

The two MCP servers (`scholar`, `paper_pdf`) are registered in the repo's `.mcp.json`. Drive them through
`scripts/mcp_bridge.py` rather than calling the MCP tools directly, even when the tools are attached to the session:
the bridge runs a whole multi-call sequence in one command and writes the result to disk, so a 100-paper JSON never
passes through your context. Use `mcp_bridge.py call …` for one-off tool calls.

The order of Stage A is **define → search → screen → augment → screen the additions → export → fulltext → knowledge
base**. Full text comes after export because the `citation_key` names every PDF and markdown file.

Never paste whole JSON files or 20 full abstracts into your context — a single tool result overflows. Read papers with
`ideate_tools.py list-papers` ([search/README.md](search/README.md#reading-the-collection)).

---

## 2. A6 — fulltext

A6 is two Units on the ledger, in a block of their own (`fulltext`, between the search and the fusion block):
`ideate_tools.py next $RD --block fulltext` names the next one, `status` adds a full-text section to `STATUS.md`, and
`ideate_tools.py a6-check $RD` runs their checks. Every command below is a Unit boundary: it ends `done` when the Unit's
checks pass and `pending` (with the first failing check) when they do not yet - after `tier1` alone, A6.d waits for
`download`. A topic whose full texts were fetched before these Units existed has no full-text events, and its fusion
Units do not go stale for want of them.

<a id="a6d"></a>**A6.d fetch** — `tier1`, `download`, `arxiv-pdfs` (and one `tier1 --top-up`). The candidates follow
the depth rule (`tier1` takes the depth from step0); every attempt is recorded with its route and reason in
`step5_fetch_log.json`. Done when: every candidate has a complete PDF or was tried on every route that applies to it
(F01) · every PDF is complete (F02) · the candidates follow the depth rule on the current shortlist (F03) · at most one
top-up pass (F04; `tier1` refuses a second) · no credential in the files it writes or the paper_pdf log (F05). Fewer
PDFs in hand than the depth asked for is a warning (F06, caveat `fulltext-short`).

<a id="a6c"></a>**A6.c convert** — `pdf2md.sh` (not a Python command: run it first, in the background), `figures`,
`fulltext-status` (the command that closes the Unit). Done when: every shortlisted paper carries the access level its
files give (F11) · every full text is UTF-8 with LF and no NUL byte (F12) · every PDF went through `figures` as it is
now (F13) · every PDF and full text is named after a citation key (F14). Warnings: full texts from pdftotext (F15,
caveat `fulltext-plain`), PDFs nothing could convert (F16, caveat `pdf-unconverted`).

At `--depth quick` run only the first line (`tier1 --depth quick`, which writes an empty candidate list) and the last
line, so every paper gets an `access_level`.

```bash
$PY $SK/scripts/ideate_tools.py tier1 $RD --depth standard      # → step3_tier1_candidates.json
$PY $SK/scripts/mcp_bridge.py download $RD                      # paper_pdf: Unpaywall → PMC → arXiv → IEEE
$PY $SK/scripts/ideate_tools.py arxiv-pdfs $RD                  # direct arXiv fetch for what paper_pdf cannot resolve
$PY $SK/scripts/ideate_tools.py tier1 $RD --depth standard --top-up   # paywalls ate the budget? add next-ranked papers,
                                                                      #   then run download + arxiv-pdfs once more
$PY $SK/scripts/ideate_tools.py tier1 $RD --targets               # after B3.5 wrote section 9: the questions' attack
                                                                      #   targets known from an abstract only (at most 5),
                                                                      #   then download + arxiv-pdfs + pdf2md, decon-plan
                                                                      #   (their records go stale: D02 / D11), A7.D again,
                                                                      #   collisions re-judged, questions-handover again
IDEATE_PYTHON=$PY bash $SK/scripts/pdf2md.sh $RD                # pdfs/*.pdf → step5_full_text/*.md  (~1-2 min each when healthy)
$PY $SK/scripts/ideate_tools.py figures $RD                        # caption pages → step5_full_text/figure/*.png (local, ~2 s/paper)
$PY $SK/scripts/ideate_tools.py fulltext-status $RD             # → _access_log.md, access_level per paper
```

- `tier1` selects the papers to read in full — standard: the 20 best by composite; deep: every Tier 1 paper, and never
  fewer than the standard 20. It writes the exact JSON shape `paper_pdf` parses; feeding it `step3_shortlist.json`
  directly yields zero rows.
- `paper_pdf` resolves **by DOI only**, so arXiv-only preprints all land in its `no_doi` bucket — that is what
  `arxiv-pdfs` is for. It verifies each file is a complete PDF (`%PDF-` header and `%%EOF` trailer) and refetches
  truncated ones; a cut-off PDF would otherwise reach pdf2md as garbage.
- Expect to lose a third or more of the targets to paywalls — that is what `--top-up` is for. One top-up pass is
  enough; do not chase a full 20.
- `pdf2md.sh` reads its API key from the gitignored `mcp/scholar_mcp/.env`, so the key never appears in a command. The
  service converts one paper at a time, and one stuck job blocks everything behind it, so the script gives each paper
  15 minutes, declares the service wedged after two consecutive failures, and converts whatever is left with
  `pdftotext`. A healthy conversion takes 20 s – 2 min; the failure mode is a stall, not slowness. The script always
  terminates by itself, so start it as a background command and carry on — you are notified when it exits. Do not
  poll it with `sleep` loops and never kill it. Every stage skips files that already exist, so an interrupted
  run resumes where it stopped.
- **While it converts** (run it in the background for more than ~5 papers), do the work that does not need full text:
  Pass 0 themes from the shortlist abstracts, and the Point candidates list. Write reading notes and cards only from
  the converted text — drafting them from a preview and "checking later" is how unverified numbers get into cards.
- `paper_pdf` also writes `step3_missing_pdfs.md` (paywalled / broken / no DOI). Do not chase those: a paper without
  full text stays in the pipeline as `abstract-only`. Some fully open-access publishers (MDPI, for one) answer 403 to
  every automated client, so expect to lose papers you "should" have got. `fulltext-status` lists the Tier 1–2 papers
  that are still missing under **Worth fetching by hand**, with the file name to save each one as — tell the user
  about that list in the Finish report; dropping the PDFs in and re-running `pdf2md.sh` picks them up.
- A second `download` (after `--top-up`) fetches only the new candidates; earlier failures are not retried unless you
  pass `--retry-failed`. Downloads are slow — budget ~1 minute per candidate, mostly time-outs on paywalled hosts.

Each paper ends with an `access_level` of `full-text` (pdf2md), `full-text-plain` (pdftotext fallback — tables and
equations are degraded, so re-check any number you take from it), `pdf-only` (PDF fetched, nothing could convert it)
or `abstract-only`. pdf2md also drops a `{key}_meta.json` next to each markdown file; ignore those.
**Figures.** Text conversion loses what is drawn: pdftotext keeps no images and scrambles tables, and even pdf2md turns
tables into text. So every PDF also gets page images: `figures` renders each page that carries a figure or table caption
(a line starting "Fig. 3.", "FIGURE 2 |", "TABLE IV" …) at 130 dpi into the flat folder `step5_full_text/figure/` as
`{key}_p{NN}.png`, and indexes them with their captions in `figure/index.json`. Whole pages rather than crops, because
plots are usually vector graphics that no image extractor sees, and a whole page is always complete. When pdf2md
converts a paper it also delivers tight figure crops, saved to the same folder as `{key}_{name}` with the markdown links
rewritten. Both are local files under the gitignored `step5_full_text/` (~2-3 MB per paper).

`fulltext-status` also re-encodes every full text to UTF-8 with LF line ends, strips NUL bytes (they make `grep` treat
the file as binary), and says how many it fixed: a Latin-1 /
cp1252 file (seen on 11 of 17 full texts of one topic, converted elsewhere) makes `grep` print nothing without any
error, so every later lookup in it silently misses.

---

## 3. A7 — knowledge base

Turning the screened papers into the Point / Line / Plane / Body knowledge base is the most important step of stage A
and has its own reference: **[knowledge-passes.md](knowledge-passes.md)**. Read it when you reach this step (after the
full texts are in), not before — it is long and none of it is needed before then.

---

## 4. Depth levels

| | literature search | fulltext | knowledge base (A7) | use when |
|---|---|---|---|---|
| `quick` | the quick query set, no scope probe, no dense instance; snowball | none (abstracts only) | Pass 0, 1, 3 and a thin descriptive Body — no Lines | scouting a topic, checking the plumbing |
| `standard` (default) | the standard set + scope probe + dense instance; snowball | top 20 by composite | all passes | normal ideation |
| `deep` | the deep set + scope probe + dense instance; snowball | every Tier 1 paper, ≥ 20 | all passes | a topic you intend to publish on |

The literature search's depth rules are in [search/README.md](search/README.md#depth). `quick` cannot produce Lines,
and Lines are where gaps come from, so its ideas rest on much weaker evidence. Say this plainly whenever you deliver
ideas from a quick run.

---

## 5. Degraded paths

The skill must not stop because a service is down, but it must record what it fell back to, so the evidence base
stays auditable: the literature search writes caveats into its own files; full text writes
`step5_full_text/_access_log.md`.

| Situation | Fall back to |
|---|---|
| the literature search (a source down, a key missing, no S2 key, no SPECTER2 model, a snowball route skipped) | run `mcp_bridge.py preflight <RD>` first: the networked Units then take their degraded path at once; the `degraded` row of each Unit's card in [units.md](units.md) says what is recorded, and `search_caveats.json` collects it |
| `mcp_bridge.py` exits 4 (no `mcp` package) | run it with the interpreter `check_env.sh` reports; if the scholar server itself cannot be used, A2.s's manual path ([search/A2-search.md](search/A2-search.md#a2s)) |
| `paper_pdf` fails or finds nothing | `arxiv-pdfs`; then `WebFetch` of the arXiv HTML page; else leave the paper `abstract-only`. |
| `pdf2md.sh` exits 3 (no `PDF2MD_API_KEY`) or the service is down | `pdf2md.sh` already does this by itself (plain `pdftotext`, deliberately **without** `-layout`, which splices the two columns of a paper together line by line). Lower quality: equations and tables are lost. |
| fewer than 10 papers survive screening | continue, but label every gap and idea as preliminary and recommend a broader search. |
