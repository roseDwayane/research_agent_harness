# paper_pdf_mcp

An MCP server that reads a Research-Agent candidate list — `step3_tier1_candidates.json`
(preferred; full fields incl. title) or the `.md` table — extracts each paper's
`citation_key` + `doi` (+ title), and downloads the **open-access** PDF into a
sibling `pdfs/` folder named `{citation_key}.pdf`.

> `md_path` accepts either a `.json` or a `.md`. Given a `.md`, the sibling
> `.json` is used automatically if present, so the markdown file is optional —
> the pipeline now emits only the `.json`.

It only uses **legal open-access sources** — Unpaywall, Europe PMC, arXiv, and
known OA publishers (PLOS / MDPI / Nature). Paywalled papers with no OA copy are
reported as failures, never scraped from grey-market mirrors.

## Tools

| Tool | What it does |
|---|---|
| `paper_pdf_parse_candidates` | Parse the markdown into `citation_key` / `doi` rows. Read-only; use it to preview what will download or find rows with no DOI. |
| `paper_pdf_resolve_url` | Resolve a single DOI to its best OA PDF URL (no download). Use for debugging. |
| `paper_pdf_download` | The full workflow: parse → resolve → download all PDFs concurrently into `pdfs/`. |

### `paper_pdf_download` parameters

- `md_path` (required) — absolute path to the candidate markdown file.
- `output_dir` — defaults to a `pdfs/` folder next to the markdown file.
- `only_keys` — restrict to specific citation keys, e.g. `["BergeyEtAl2015"]`.
- `overwrite` — re-download existing files (default `false`; existing PDFs are skipped).
- `concurrency` — parallel downloads, 1–8 (default 4).
- `response_format` — `markdown` (default) or `json`.

## How resolution works

For each DOI the server collects an **ordered list of candidate PDF URLs** and
tries them top-down until one returns a real PDF (verified by the `%PDF-` magic
header), with retry-on-transient-error (429/5xx, timeouts):

1. **Unpaywall** — any `url_for_pdf`; PMC locations → Europe PMC render URL;
   PLOS/MDPI/Nature landing pages → constructed direct `.pdf`.
2. **NCBI PMC idconv** → Europe PMC render URL.
3. **arXiv API** (DOI lookup) → `arxiv.org/pdf/{id}`.
4. **IEEE Xplore** (for `10.1109/` DOIs) — scrape the article number from the
   DOI landing page → `stampPDF/getPDF.jsp?arnumber={N}`. Recovers IEEE
   gold/open-access PDFs that Unpaywall lists with no direct link (and several
   IEEE-OA articles Unpaywall mislabels as `is_oa=false`).

> NCBI's own `/pmc/articles/{id}/pdf/` endpoint now serves an anti-bot HTML
> interstitial, so all PMC routes go through `europepmc.org/articles/{id}?pdf=render`.

A paper fails when it is genuinely paywalled (`is_oa=false`), has no DOI, or its
only OA copy is behind a publisher page that blocks automated PDF access (e.g.
some IEEE/Elsevier gold-OA articles that Unpaywall lists with no direct PDF link).

## Configuration

`PAPER_PDF_UNPAYWALL_EMAIL` — contact email sent to the free Unpaywall API
(defaults to the maintainer's). No API key is required.

## Running

Registered in the repo's `.mcp.json` as the `paper_pdf` server:

```json
{
  "command": "conda",
  "args": ["run", "-n", "drug", "python",
           ".../tools/paper_pdf_mcp/server.py"]
}
```

Standalone smoke test:

```bash
conda run -n drug python tools/paper_pdf_mcp/server.py   # starts stdio MCP server
```

## Example

> Download all PDFs from `step3_tier1_candidates.md`.

calls `paper_pdf_download(md_path=".../step3_tier1_candidates.md")` → writes
`{session}/pdfs/{citation_key}.pdf` for every paper with a reachable OA copy and
returns a per-paper report.
