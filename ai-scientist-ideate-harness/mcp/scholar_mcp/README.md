# scholar_mcp

A local [MCP](https://modelcontextprotocol.io) server that searches seven literature databases — **Semantic Scholar,
OpenAlex, PubMed, arXiv, Scopus, IEEE Xplore, Web of Science** — and returns already-parsed, normalised records. The
brittle mechanics (OpenAlex inverted-index abstracts, PubMed XML, DOI normalisation, retries, deduplication, reference
lists) live in code; the decisions (what to search, what to keep) stay with the skill.

The literature search of `ai-scientist-ideate` drives it through `scripts/mcp_bridge.py`, which records every answer under
`<research_dir>/_state/net/scholar/` and replays them offline with `IDEATE_REPLAY=1`. The server derives from the
scholar_mcp of the forecasting_the_brain project.

## Tools

| Tool | What it does | Used by | Key |
|---|---|---|---|
| `scholar_search` | one query → one or more sources → normalised papers (merged within the call); per source the records returned and the total the database reports (`returned`, `totals`) | A1.q probe, A2.s | per source (below) |
| `scholar_dedup` | merge batches: DOI, then fuzzy title + first author + year; optional stable ids | — (A2.m merges locally) | none |
| `scholar_recover_dois` | fill a missing DOI from Semantic Scholar (arXiv id first, then the title) | A2.m (arXiv records only) | optional S2 |
| `scholar_recommend` | Semantic Scholar's embedding neighbours (SPECTER) of seed papers | A2.s dense instance D1, A5 similar | S2 in practice |
| `scholar_abstracts` | the abstract S2 holds for each DOI / S2 id (one batch request, ≤ 500) | A3.b, records without an abstract | S2 in practice |
| `scholar_snowball` | a seed paper's reference list (Semantic Scholar) | A5, only when OpenAlex has no reference lists | optional S2 |
| `scholar_venues` | Scopus SNIP and SJR for up to 25 ISSNs (Elsevier Serial Title API) | A3.b | Scopus |

A3.b's citation data, A5's forward and backward routes and A4.b's Crossref entries are fetched by the Unit modules
themselves (`it_common.http_json`, recorded the same way); they need no server tool.

All tools are read-only and return a JSON string. A normalised paper:

```json
{
  "title": "...", "authors": ["..."], "year": 2024, "journal": "...",
  "doi": "10.xxx/yyy", "url": "...", "abstract": "...", "citation_count": 42,
  "sources_found_in": ["semantic_scholar", "openalex", "scopus"],
  "semantic_scholar_id": "...", "openalex_id": "W...", "pubmed_id": "...",
  "arxiv_id": "...", "scopus_id": "...", "ieee_id": "...", "wos_id": "WOS:...",
  "pmc_id": "PMC...", "volume": "...", "issue": "...", "pages": "...", "language": "eng"
}
```

`pmc_id`, `volume`, `issue`, `pages` and `language` are the bibliographic fields the archived engine kept per paper:
PubMed gives all five, OpenAlex its PMC id when it has one (the merge's OpenAlex enrichment adds the rest by DOI).

`scholar_search` also reports `sources_queried`, `sources_skipped` (a keyed source without its key) and
`source_errors` (a source that failed, including an inactive IEEE key; any key in a URL is replaced by `REDACTED`). A
missing key skips that source; it never fails the call.

## Query forms

The search step renders each query in the form a source parses and the server passes it through: Boolean for PubMed,
Scopus, IEEE and WoS; Boolean without truncation for OpenAlex (title + abstract search, relevance order); arXiv field
syntax (`all:`, `ti:`, `abs:` …) for arXiv; a short flat phrase for Semantic Scholar, which parses no Boolean.

## API keys

In the environment, or in `.env` beside `server.py` (gitignored; `../.env.example` lists the names). Never print or
commit them.

| Variable | Source | Needed for | Notes |
|---|---|---|---|
| `SCOPUS_API_KEY` | Scopus | Scopus search, `scholar_venues` | <https://dev.elsevier.com>. The standard view returns the first author only and no abstract; 25 records per page (the adapter pages). |
| `IEEE_API_KEY` | IEEE Xplore | IEEE search | <https://developer.ieee.org>. A new key answers `403 Developer Inactive` until IEEE activates it. |
| `WOS_API_KEY` | Web of Science | WoS search | Clarivate Expanded API. Terms inside `TS=(...)` are ANDed; ~2 requests/s and a yearly quota. |
| `PUBMED_API_KEY` | PubMed | optional | raises the rate limit from 3 to 10 requests/s |
| `SEMANTIC_SCHOLAR_API_KEY` | Semantic Scholar | optional | keyless recommendation calls are rate-limited most days |
| `OPENALEX_API_KEY` | OpenAlex | optional | without a key every client on the network shares one small daily budget; a free key (<https://openalex.org/settings/api>) has its own. The skill's own OpenAlex requests (A1.q's probe, A2.m's enrichment, A3.b, A5) read it too, from the environment or this `.env` |
| `SCHOLAR_CONTACT_EMAIL` | OpenAlex, PubMed | optional | polite-pool contact |

## Install and run

```bash
/opt/anaconda3/envs/drug/bin/python -m pip install -r requirements.txt
/opt/anaconda3/envs/drug/bin/python server.py          # starts a stdio server (Ctrl-C to stop)
/opt/anaconda3/envs/drug/bin/python _smoke_client.py   # lists the tools and runs one search
```

Point MCP clients straight at the interpreter. `conda run` buffers the child's stdout and breaks the stdio handshake.

## Register with Claude Code

The repo's `.mcp.json` registers this server as `scholar` (tools `mcp__scholar__scholar_search`, …). After editing it,
restart Claude Code or check with `/mcp`. Without the attached tools, `scripts/mcp_bridge.py` starts the server itself.

## Limits

- Semantic Scholar, OpenAlex, PubMed and arXiv need no key; polite-pool rate limits apply and the server retries once on
  429.
- IEEE's free tier and Scopus's standard view return 25 records per request, WoS Expanded 100; `limit` is clamped.
- Screening, citation-network analysis and every other judgement are not here: the server fetches, parses and
  normalises.
