#!/usr/bin/env python3
'''
MCP Server for downloading open-access PDFs from a research candidate list.

Given a candidate file such as `step3_tier1_candidates.json` (preferred) or the
`.md` table (produced by the Research Agent pipeline), this server extracts
`citation_key` + `doi` (+ title) records — reading the JSON directly when
available, falling back to scraping the markdown table — resolves each DOI to a
legal open-access PDF URL
(via Unpaywall, with arXiv / PubMed Central / OA-publisher fallbacks), and
downloads each PDF into a sibling `pdfs/` folder named `{citation_key}.pdf`.

Paywalled papers with no open-access copy are reported as failures — this
server never touches paywalled or grey-market sources.

Tools:
  - paper_pdf_parse_candidates : parse the markdown into citation_key/doi rows
  - paper_pdf_resolve_url      : resolve a single DOI to an OA PDF URL (no download)
  - paper_pdf_download         : the full workflow — parse, resolve, and download
'''

import asyncio
import json
import os
import re
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
import logging

# httpx logs every request URL at INFO, and several APIs (PubMed, IEEE) carry the API key as a query parameter,
# so INFO-level request logging writes credentials to stderr / any log file. Keep warnings and errors only.
# (Added in the ai-scientist-ideate copy; the original in forecasting_the_brain is unchanged.)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

mcp = FastMCP("paper_pdf_mcp")

# Unpaywall requires a contact email as a query param; it is free and needs no key. Set a real address as
# PAPER_PDF_UNPAYWALL_EMAIL (or SCHOLAR_CONTACT_EMAIL) in .env; the placeholder keeps the server starting, Unpaywall
# may refuse it, and the other routes (PMC, arXiv) still run.
UNPAYWALL_EMAIL = (os.environ.get("PAPER_PDF_UNPAYWALL_EMAIL") or os.environ.get("SCHOLAR_CONTACT_EMAIL")
                   or "research-agent@example.com")
UNPAYWALL_BASE = "https://api.unpaywall.org/v2"
NCBI_IDCONV = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
ARXIV_API = "http://export.arxiv.org/api/query"

# Browser-like UA — some publishers block default httpx/python UAs.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 paper_pdf_mcp/1.0"
)

HTTP_TIMEOUT = 60.0
DOWNLOAD_TIMEOUT = 180.0
MIN_PDF_BYTES = 1024  # anything smaller is almost certainly an error page
DEFAULT_CONCURRENCY = 4

# Known open-access publisher hosts where the DOI landing page often links a PDF.
OA_PUBLISHER_HOSTS = (
    "journals.plos.org",
    "frontiersin.org",
    "mdpi.com",
    "biomedcentral.com",
    "elifesciences.org",
    "peerj.com",
)


# ---------------------------------------------------------------------------
# Enums and Pydantic input models
# ---------------------------------------------------------------------------

class ResponseFormat(str, Enum):
    '''Output format for tool responses.'''
    MARKDOWN = "markdown"
    JSON = "json"


class ParseCandidatesInput(BaseModel):
    '''Input model for parsing a candidate markdown file.'''
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    md_path: str = Field(
        ...,
        description=(
            "Absolute path to the candidate file — either step3_tier1_candidates.json "
            "(preferred: full fields incl. title) or the .md table. When given a .md, a "
            "sibling .json is used automatically if present, so the .md is optional."
        ),
        min_length=1,
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' for human-readable or 'json' for machine-readable.",
    )


class ResolveUrlInput(BaseModel):
    '''Input model for resolving a single DOI to an open-access PDF URL.'''
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    doi: str = Field(
        ...,
        description="The DOI to resolve, e.g. '10.1212/wnl.0000000000001280' (with or without a leading 'https://doi.org/').",
        min_length=3,
    )

    @field_validator("doi")
    @classmethod
    def normalize_doi(cls, v: str) -> str:
        return _normalize_doi(v)


class DownloadInput(BaseModel):
    '''Input model for the full parse + resolve + download workflow.'''
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    md_path: str = Field(
        ...,
        description=(
            "Absolute path to the candidate file — step3_tier1_candidates.json (preferred) "
            "or the .md. PDFs are saved to a sibling 'pdfs/' folder unless output_dir is given."
        ),
        min_length=1,
    )
    output_dir: Optional[str] = Field(
        default=None,
        description=(
            "Optional absolute path for the output folder. Defaults to a 'pdfs/' "
            "directory alongside the markdown file."
        ),
    )
    only_keys: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional list of citation_keys to restrict the download to "
            "(e.g. ['BergeyEtAl2015', 'AmiriEtAl2026']). If omitted, all rows are processed."
        ),
        max_length=500,
    )
    overwrite: bool = Field(
        default=False,
        description="If false (default), skip papers whose {citation_key}.pdf already exists.",
    )
    concurrency: int = Field(
        default=DEFAULT_CONCURRENCY,
        description="Number of PDFs to download in parallel.",
        ge=1,
        le=8,
    )
    write_missing_report: bool = Field(
        default=True,
        description=(
            "If true (default), write a human-facing 'missing PDFs' markdown report "
            "next to the source file (step3_missing_pdfs.md), listing every paper that "
            "could not be downloaded, bucketed by recoverability with a remediation hint."
        ),
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' for human-readable or 'json' for machine-readable.",
    )


# ---------------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------------

def _normalize_doi(raw: str) -> str:
    '''Strip URL prefixes / backticks / whitespace and lowercase a DOI.'''
    v = raw.strip().strip("`").strip()
    v = re.sub(r"^https?://(dx\.)?doi\.org/", "", v, flags=re.IGNORECASE)
    v = re.sub(r"^doi:\s*", "", v, flags=re.IGNORECASE)
    return v.strip()


def _clean_cell(cell: str) -> str:
    '''Remove markdown emphasis/backticks/whitespace from a table cell.'''
    return cell.strip().strip("`").strip("*").strip()


def parse_candidate_markdown(md_text: str) -> List[Dict[str, Any]]:
    '''Parse markdown tables and return citation_key + doi rows.

    Handles the step3_tier1_candidates.md layout where multiple grouped tables
    share the header `| # | citation_key | track/lvl | missing criteria | year |
    domain | doi |`. Column order is read from each table's header row, so the
    parser is resilient to extra/reordered columns. Rows whose DOI cell is empty
    or '(none)' yield doi=None (still returned, so the caller can see them).

    Returns:
        List of dicts: {citation_key, doi, year, domain, track_lvl, group}
        Rows missing a citation_key are skipped. Duplicate citation_keys are
        de-duplicated (first occurrence wins).
    '''
    rows: List[Dict[str, Any]] = []
    seen_keys: set = set()
    current_group: Optional[str] = None
    header_cols: Optional[List[str]] = None

    for line in md_text.splitlines():
        stripped = line.strip()

        # Track the most recent section heading as the "group" label.
        if stripped.startswith("#"):
            current_group = stripped.lstrip("#").strip()
            header_cols = None
            continue

        if not stripped.startswith("|"):
            header_cols = None  # a non-table line ends the current table
            continue

        cells = [c.strip() for c in stripped.strip("|").split("|")]

        # A separator row like |---|---| — ignore.
        if all(set(c) <= {"-", ":", " "} and c for c in cells if c != ""):
            continue

        lowered = [c.lower() for c in cells]
        if "citation_key" in lowered and "doi" in lowered:
            header_cols = lowered
            continue

        if header_cols is None:
            continue  # data row with no header seen yet — skip

        record = dict(zip(header_cols, cells))
        key = _clean_cell(record.get("citation_key", ""))
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)

        doi_raw = _clean_cell(record.get("doi", ""))
        doi = None if (not doi_raw or doi_raw.lower() in ("(none)", "none", "-", "—")) else _normalize_doi(doi_raw)

        rows.append(
            {
                "citation_key": key,
                "doi": doi,
                "title": None,  # filled in later from the sibling .json if available
                "year": _clean_cell(record.get("year", "")) or None,
                "domain": _clean_cell(record.get("domain", "")) or None,
                "track_lvl": _clean_cell(record.get("track/lvl", "")) or None,
                "group": current_group,
            }
        )

    return rows


def _load_titles(md_path: str) -> Dict[str, str]:
    '''Load a {citation_key: title} map from the candidate .md's sibling .json.

    The candidate markdown (step3_tier1_candidates.md) carries no titles, but the
    machine-readable twin (step3_tier1_candidates.json) does, under
    candidates[].{citation_key,title}. Returns an empty map if the json is
    missing or unreadable — titles are a nice-to-have, never required.
    '''
    json_path = re.sub(r"\.md$", ".json", md_path, flags=re.IGNORECASE)
    if json_path == md_path or not os.path.isfile(json_path):
        return {}
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    # Find the list of candidate records, wherever it lives.
    records: List[Dict[str, Any]] = []
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict) and "citation_key" in v[0]:
                records = v
                break
    elif isinstance(data, list):
        records = [r for r in data if isinstance(r, dict)]

    titles: Dict[str, str] = {}
    for rec in records:
        key = rec.get("citation_key")
        title = rec.get("title")
        if key and title:
            titles[str(key).strip("`").strip()] = str(title).strip()
    return titles


def parse_candidates_with_titles(md_path: str, md_text: str) -> List[Dict[str, Any]]:
    '''Parse the candidate markdown and enrich each row with its title from the .json.'''
    rows = parse_candidate_markdown(md_text)
    titles = _load_titles(md_path)
    if titles:
        for r in rows:
            r["title"] = titles.get(r["citation_key"])
    return rows


def _candidate_records_from_json(data: Any) -> List[Dict[str, Any]]:
    '''Find the list of candidate records inside a parsed candidates JSON.'''
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict) and "citation_key" in v[0]:
                return v
    elif isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


def parse_candidates_json(json_text: str) -> List[Dict[str, Any]]:
    '''Parse step3_tier1_candidates.json into the same row shape as the .md parser.

    The JSON twin carries the full fields directly (citation_key, doi, title,
    year, group, ...), so this is both simpler and more reliable than scraping
    the markdown table. Rows missing a citation_key are skipped; duplicates are
    de-duplicated (first wins). DOI '(none)'/empty becomes None.
    '''
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return []

    rows: List[Dict[str, Any]] = []
    seen: set = set()
    for rec in _candidate_records_from_json(data):
        key = str(rec.get("citation_key", "")).strip("`").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        doi_raw = str(rec.get("doi") or "").strip("`").strip()
        doi = None if (not doi_raw or doi_raw.lower() in ("(none)", "none", "-", "—")) else _normalize_doi(doi_raw)
        # group can be a label or a code; prefer an explicit human label if present.
        group = rec.get("group")
        rows.append(
            {
                "citation_key": key,
                "doi": doi,
                "title": (str(rec["title"]).strip() if rec.get("title") else None),
                "year": (str(rec["year"]).strip() if rec.get("year") else None),
                "domain": rec.get("application_domain") or rec.get("domain"),
                "track_lvl": (f"{rec.get('track')}/{rec.get('level')}" if rec.get("track") else None),
                "group": (str(group).strip() if group else None),
            }
        )
    return rows


def load_candidates(path: str) -> tuple[List[Dict[str, Any]], str]:
    '''Load candidate rows from a candidate file, preferring JSON.

    Accepts either the .json (parsed directly — full fields incl. title) or the
    .md (parsed, then titles merged from the sibling .json). When given a .md, a
    sibling .json is used in preference if it exists, so the .md is fully
    optional. Returns (rows, source_used) where source_used is 'json' or 'md'.
    '''
    # Direct JSON input.
    if path.lower().endswith(".json"):
        with open(path, "r", encoding="utf-8") as f:
            return parse_candidates_json(f.read()), "json"

    # Markdown input — prefer the sibling JSON if present.
    sibling_json = re.sub(r"\.md$", ".json", path, flags=re.IGNORECASE)
    if sibling_json != path and os.path.isfile(sibling_json):
        with open(sibling_json, "r", encoding="utf-8") as f:
            rows = parse_candidates_json(f.read())
        if rows:
            return rows, "json"

    # Fall back to scraping the markdown table.
    with open(path, "r", encoding="utf-8") as f:
        return parse_candidates_with_titles(path, f.read()), "md"


# ---------------------------------------------------------------------------
# DOI -> open-access PDF URL resolution
# ---------------------------------------------------------------------------

def _pmcid_from_url(url: str) -> Optional[str]:
    '''Extract a PMCxxxx id from a PMC article URL, if present.'''
    m = re.search(r"(PMC\d+)", url or "", flags=re.IGNORECASE)
    return m.group(1).upper() if m else None


def _direct_pdf_from_landing(doi: str, url: str) -> List[str]:
    '''Construct direct PDF URL(s) from a DOI / OA-publisher landing page.

    Unpaywall frequently reports is_oa=true but url_for_pdf=None, and gives only
    a bare https://doi.org/{doi} landing page (host_type=publisher) — so a host
    substring match misses it. These transforms are therefore keyed on the **DOI
    prefix** (reliable) as well as the landing host, and return *every* plausible
    direct-PDF URL so the downloader can try them in order (the _looks_like_pdf
    guard rejects any that resolve to HTML, so over-generating is safe).
    '''
    low = (url or "").lower()
    suffix = doi.split("/", 1)[1] if "/" in doi else doi
    out: List[str] = []

    # PLOS (10.1371) — Unpaywall lands on doi.org, so match on the DOI prefix too.
    if doi.startswith("10.1371/") or "journals.plos.org" in low:
        for journal in ("plosone", "ploscompbiol", "plosbiology", "plosmedicine"):
            out.append(f"https://journals.plos.org/{journal}/article/file?id={doi}&type=printable")
    # MDPI (10.3390) — /pdf landing handles the redirect.
    if doi.startswith("10.3390/") or "mdpi.com" in low:
        out.append(f"https://www.mdpi.com/{suffix}/pdf")
    # Nature / Springer-Nature article pages: /articles/{id} -> /articles/{id}.pdf
    if "nature.com/articles/" in low and not low.endswith(".pdf"):
        out.append(url.rstrip("/") + ".pdf")
    # Frontiers (10.3389) — /full -> /pdf.
    if doi.startswith("10.3389/") or "frontiersin.org" in low:
        if "frontiersin.org" in low:
            out.append(re.sub(r"/full/?$", "/pdf", url))
        out.append(f"https://www.frontiersin.org/articles/{doi}/pdf")
    # IOP (10.1088) — Biomed. Phys. Eng. Express etc. expose /pdf on the article path.
    if doi.startswith("10.1088/"):
        out.append(f"https://iopscience.iop.org/article/{doi}/pdf")
    # eLife (10.7554)
    if doi.startswith("10.7554/") or "elifesciences.org" in low:
        out.append(f"https://elifesciences.org/articles/{suffix}.pdf")
    # PeerJ (10.7717)
    if doi.startswith("10.7717/") or "peerj.com" in low:
        out.append(f"https://peerj.com/articles/{suffix.split('.')[-1]}.pdf")
    # Hindawi / Wiley-OA download.hindawi pattern (10.1155)
    if doi.startswith("10.1155/"):
        out.append(f"https://downloads.hindawi.com/journals/{suffix}.pdf")
    # JMIR (10.2196)
    if doi.startswith("10.2196/") or "jmir.org" in low:
        out.append(f"https://www.jmir.org/{suffix}/PDF" if "jmir.org" in low else url)

    # De-dupe while preserving order.
    seen: set = set()
    return [u for u in out if u and not (u in seen or seen.add(u))]


# Each resolver appends zero or more {"url", "source"} candidates. The
# downloader tries them in order until one yields a real PDF, so a 403 on the
# publisher copy can fall through to a PMC mirror, etc.

async def _candidates_from_unpaywall(client: httpx.AsyncClient, doi: str) -> List[Dict[str, str]]:
    '''Collect every plausible OA PDF URL from the Unpaywall record.

    For each OA location, in Unpaywall's own preference order, yield:
      - its explicit url_for_pdf (if any)
      - a Europe PMC render URL (if the location is a PMC article)
      - a constructed publisher PDF URL (PLOS/MDPI/Nature landing pages)
    NCBI's own /pdf/ endpoint now serves an anti-bot HTML page, so PMC always
    routes through europepmc.org instead.
    '''
    url = f"{UNPAYWALL_BASE}/{doi}"
    try:
        resp = await client.get(url, params={"email": UNPAYWALL_EMAIL})
        if resp.status_code != 200:
            return []
        data = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        return []

    if not data.get("is_oa"):
        return []

    locations = data.get("oa_locations") or []
    best = data.get("best_oa_location")
    if best and best not in locations:
        locations = [best] + locations

    out: List[Dict[str, str]] = []
    for loc in locations:
        loc_url = loc.get("url", "")
        if loc.get("url_for_pdf"):
            out.append({"url": loc["url_for_pdf"], "source": "unpaywall"})
        pmcid = _pmcid_from_url(loc_url)
        if pmcid:
            out.append({"url": f"https://europepmc.org/articles/{pmcid}?pdf=render", "source": "unpaywall+pmc"})
        for constructed in _direct_pdf_from_landing(doi, loc_url):
            out.append({"url": constructed, "source": "unpaywall+publisher"})
    # Last-resort: Unpaywall says is_oa but no PDF/PMC/publisher transform fired
    # for any location (host_type=publisher with a bare doi.org landing). Hand the
    # landing URL itself to the downloader — many OA hosts content-negotiate or
    # 302 a .pdf, and _looks_like_pdf rejects it if it's just HTML. Costs one GET.
    if not out:
        for loc in locations:
            loc_url = loc.get("url")
            if loc_url:
                out.append({"url": loc_url, "source": "unpaywall+landing"})
    return out


async def _candidates_from_pmc(client: httpx.AsyncClient, doi: str) -> List[Dict[str, str]]:
    '''Use the NCBI ID converter to find a PMC ID, then a Europe PMC PDF URL.'''
    try:
        resp = await client.get(
            NCBI_IDCONV, params={"ids": doi, "format": "json", "tool": "paper_pdf_mcp", "email": UNPAYWALL_EMAIL}
        )
        if resp.status_code != 200:
            return []
        records = resp.json().get("records") or []
    except (httpx.HTTPError, json.JSONDecodeError):
        return []
    out: List[Dict[str, str]] = []
    for rec in records:
        pmcid = rec.get("pmcid")
        if pmcid:
            out.append({"url": f"https://europepmc.org/articles/{pmcid}?pdf=render", "source": "pmc"})
    return out


async def _candidates_from_arxiv(client: httpx.AsyncClient, doi: str) -> List[Dict[str, str]]:
    '''Look up an arXiv record by DOI and return its PDF URL.'''
    try:
        resp = await client.get(ARXIV_API, params={"search_query": f"doi:{doi}", "max_results": 1})
        if resp.status_code != 200:
            return []
        m = re.search(r"abs/([0-9]+\.[0-9]+(v[0-9]+)?)", resp.text)
        if not m:
            return []
        return [{"url": f"https://arxiv.org/pdf/{m.group(1)}", "source": "arxiv"}]
    except httpx.HTTPError:
        return []


async def _candidates_from_ieee(client: httpx.AsyncClient, doi: str) -> List[Dict[str, str]]:
    '''For IEEE DOIs, scrape the article number and build the stampPDF URL.

    IEEE Xplore exposes the full PDF of gold/open-access articles at
    stampPDF/getPDF.jsp?arnumber={N}. Unpaywall lists these as OA but gives no
    direct PDF link, so we scrape the article number from the DOI landing page.
    Only fires for 10.1109/ DOIs. Paywalled IEEE articles return an HTML stub
    here, which the downloader's %PDF- check rejects — so this is safe to try.
    '''
    if not doi.startswith("10.1109/"):
        return []
    try:
        resp = await client.get(f"https://doi.org/{doi}", follow_redirects=True)
        if resp.status_code != 200:
            return []
        m = (
            re.search(r'"articleNumber":"(\d+)"', resp.text)
            or re.search(r"/document/(\d+)", resp.text)
            or re.search(r"arnumber=(\d+)", resp.text)
        )
        if not m:
            return []
        arn = m.group(1)
        return [{"url": f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={arn}", "source": "ieee"}]
    except httpx.HTTPError:
        return []


async def resolve_pdf_candidates(client: httpx.AsyncClient, doi: str) -> List[Dict[str, str]]:
    '''Resolve a DOI to an ordered, de-duplicated list of candidate OA PDF URLs.

    Aggregates Unpaywall (covers most OA, incl. publisher/PMC), then NCBI PMC
    idconv, then arXiv, then IEEE Xplore (for 10.1109/ DOIs). Each entry is
    {'url', 'source'}. The downloader tries them top-down until one returns a
    real PDF, so a 403 or HTML interstitial on one source falls through to the
    next. Empty list means no OA copy was found.
    '''
    candidates: List[Dict[str, str]] = []
    for resolver in (_candidates_from_unpaywall, _candidates_from_pmc, _candidates_from_arxiv, _candidates_from_ieee):
        candidates.extend(await resolver(client, doi))

    seen: set = set()
    deduped: List[Dict[str, str]] = []
    for c in candidates:
        if c["url"] not in seen:
            seen.add(c["url"])
            deduped.append(c)
    return deduped


async def resolve_pdf_url(client: httpx.AsyncClient, doi: str) -> Dict[str, Any]:
    '''Return the single best-guess OA PDF URL for a DOI (for the resolve tool).

    Returns {'pdf_url', 'source'} for the top candidate, or
    {'pdf_url': None, 'source': None, 'reason': ...} when none exist.
    '''
    candidates = await resolve_pdf_candidates(client, doi)
    if candidates:
        top = candidates[0]
        return {"pdf_url": top["url"], "source": top["source"], "alternatives": len(candidates) - 1}
    return {"pdf_url": None, "source": None, "reason": "no open-access copy found"}


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------

def _looks_like_pdf(content: bytes) -> bool:
    '''A real PDF starts with the %PDF- magic header.'''
    return content[:5] == b"%PDF-"


async def _try_fetch_pdf(client: httpx.AsyncClient, url: str, retries: int = 2) -> tuple[Optional[bytes], str]:
    '''Fetch a single URL and return (pdf_bytes, note). pdf_bytes is None on failure.

    Retries transient failures (HTTP 429/500/502/503/504, timeouts) with a short
    linear backoff. Permanent failures (403/404, or a non-PDF body) return
    immediately — retrying those just wastes time.
    '''
    note = "unknown"
    for attempt in range(retries + 1):
        try:
            resp = await client.get(url, timeout=DOWNLOAD_TIMEOUT, follow_redirects=True)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            note = f"HTTP {code}"
            if code in (429, 500, 502, 503, 504) and attempt < retries:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            return None, note
        except (httpx.TimeoutException, httpx.TransportError) as e:
            note = type(e).__name__
            if attempt < retries:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            return None, note
        except httpx.HTTPError as e:
            return None, type(e).__name__

        content = resp.content
        if len(content) < MIN_PDF_BYTES or not _looks_like_pdf(content):
            ct = resp.headers.get("content-type", "?")
            return None, f"not a PDF ({len(content)}B, {ct.split(';')[0]})"
        return content, "ok"
    return None, note


async def _download_one(
    client: httpx.AsyncClient,
    row: Dict[str, Any],
    output_dir: str,
    overwrite: bool,
) -> Dict[str, Any]:
    '''Resolve + download a single paper, trying each candidate URL in order.

    Returns a status dict (never raises): status is 'downloaded', 'skipped', or
    'failed'. On failure, 'reason' summarizes every candidate that was tried.
    '''
    key = row["citation_key"]
    doi = row.get("doi")
    out_path = os.path.join(output_dir, f"{key}.pdf")
    base = {"citation_key": key, "doi": doi, "title": row.get("title"), "path": out_path}

    if not overwrite and os.path.exists(out_path) and os.path.getsize(out_path) >= MIN_PDF_BYTES:
        return {**base, "status": "skipped", "reason": "already exists"}

    if not doi:
        return {**base, "status": "failed", "reason": "no DOI in candidate list"}

    candidates = await resolve_pdf_candidates(client, doi)
    if not candidates:
        return {**base, "status": "failed", "reason": "no open-access copy found"}

    attempts: List[str] = []
    for cand in candidates:
        content, note = await _try_fetch_pdf(client, cand["url"])
        if content is not None:
            os.makedirs(output_dir, exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(content)
            return {
                **base,
                "status": "downloaded",
                "source": cand["source"],
                "pdf_url": cand["url"],
                "bytes": len(content),
            }
        attempts.append(f"{cand['source']}: {note}")

    return {**base, "status": "failed", "reason": "all sources failed [" + "; ".join(attempts) + "]", "source": None}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )


def _format_download_markdown(output_dir: str, results: List[Dict[str, Any]]) -> str:
    n_dl = sum(1 for r in results if r["status"] == "downloaded")
    n_skip = sum(1 for r in results if r["status"] == "skipped")
    n_fail = sum(1 for r in results if r["status"] == "failed")
    lines = [
        "# PDF Download Report",
        "",
        f"**Output**: `{output_dir}`",
        f"**Total**: {len(results)} — ✅ {n_dl} downloaded, ⏭️ {n_skip} skipped, ❌ {n_fail} failed",
        "",
    ]
    if n_dl or n_skip:
        lines.append("## Succeeded")
        for r in results:
            if r["status"] == "downloaded":
                kb = r.get("bytes", 0) / 1024
                lines.append(f"- ✅ `{r['citation_key']}` — {kb:.0f} KB via {r.get('source')}")
            elif r["status"] == "skipped":
                lines.append(f"- ⏭️ `{r['citation_key']}` — {r['reason']}")
        lines.append("")
    if n_fail:
        lines.append("## Failed (no open-access PDF)")
        for r in results:
            if r["status"] == "failed":
                lines.append(f"- ❌ `{r['citation_key']}` — {r['reason']}")
        lines.append("")
    return "\n".join(lines)


# Failure buckets, in order of "how likely a human can recover it".
_FAIL_NO_DOI = "no_doi"
_FAIL_SOURCE_BROKEN = "source_broken"  # had an OA URL but it 403'd / 5xx'd
_FAIL_PAYWALL = "paywall"              # no OA copy exists at all


def _classify_failure(reason: str) -> str:
    '''Bucket a failure reason for the human-补齐 report.'''
    if "no DOI" in reason:
        return _FAIL_NO_DOI
    if "all sources failed" in reason:
        return _FAIL_SOURCE_BROKEN
    return _FAIL_PAYWALL  # "no open-access copy found"


def _remediation_hint(citation_key: str, doi: Optional[str], bucket: str) -> str:
    '''A short, actionable next-step a human can follow to obtain the PDF.'''
    if bucket == _FAIL_NO_DOI:
        return "no DOI in source — likely a clinical-trial registration or vendor white paper, not a journal article. Confirm it has a real paper before chasing a PDF."
    scholar = f"https://scholar.google.com/scholar?q={(doi or citation_key).replace(' ', '+')}"
    doi_link = f"https://doi.org/{doi}" if doi else "(no DOI)"
    if bucket == _FAIL_SOURCE_BROKEN:
        return (
            f"an OA copy was found but the publisher/mirror blocked or errored on the PDF. "
            f"Retry later, or fetch manually via {doi_link} (institutional proxy) or [Scholar]({scholar})."
        )
    # paywall
    return (
        f"no open-access copy. Try your institutional subscription via {doi_link}, "
        f"the author's preprint/ResearchGate, or [Scholar]({scholar})."
    )


def build_missing_report(results: List[Dict[str, Any]], md_path: str, output_dir: str) -> str:
    '''Produce a human-facing markdown report of every PDF that could not be downloaded.

    Groups failures into three buckets (source-broken → most recoverable,
    paywall, no-DOI) and gives a concrete remediation hint per paper so a human
    can fill the gaps after the automated pass.
    '''
    failed = [r for r in results if r["status"] == "failed"]
    n_total = len(results)
    n_ok = sum(1 for r in results if r["status"] in ("downloaded", "skipped"))

    buckets: Dict[str, List[Dict[str, Any]]] = {_FAIL_SOURCE_BROKEN: [], _FAIL_PAYWALL: [], _FAIL_NO_DOI: []}
    for r in failed:
        buckets[_classify_failure(r["reason"])].append(r)

    lines = [
        "# Missing PDFs — Manual Recovery List / 待人工補齊清單",
        "",
        f"> Source list: `{os.path.basename(md_path)}`",
        f"> PDFs saved to: `{output_dir}`",
        f"> **{n_ok}/{n_total} obtained automatically; {len(failed)} need manual recovery.**",
        "",
        "Buckets are ordered by how recoverable they are: **source-broken** papers "
        "*are* open-access (worth a retry / manual fetch); **paywall** papers need a "
        "subscription or author copy; **no-DOI** rows usually aren't journal articles at all.",
        "",
    ]

    section_titles = [
        (_FAIL_SOURCE_BROKEN, "🟡 OA but source broke (most recoverable) / 有 OA 但來源端壞掉"),
        (_FAIL_PAYWALL, "🔴 Paywalled — no OA copy / 付費牆,無 OA 版"),
        (_FAIL_NO_DOI, "⚪ No DOI in source / 來源無 DOI"),
    ]
    for bucket, section_label in section_titles:
        rows = buckets[bucket]
        if not rows:
            continue
        lines.append(f"## {section_label} ({len(rows)})")
        lines.append("")
        for r in rows:
            key = r["citation_key"]
            doi = r.get("doi")
            paper_title = r.get("title")
            lines.append(f"- [ ] **`{key}`** — DOI: `{doi or '(none)'}`")
            lines.append(f"  - title: {paper_title if paper_title else '_(title unavailable — see step3_tier1_candidates.json)_'}")
            lines.append(f"  - failure: {r['reason']}")
            lines.append(f"  - → {_remediation_hint(key, doi, bucket)}")
        lines.append("")

    if not failed:
        lines.append("✅ Nothing missing — every candidate PDF was obtained.")
    lines.append("")
    lines.append("---")
    lines.append("After manually placing a PDF, save it as `{citation_key}.pdf` in the folder above so `rsrch-C4-extract` picks it up.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="paper_pdf_parse_candidates",
    annotations={
        "title": "Parse Candidate Markdown",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def paper_pdf_parse_candidates(params: ParseCandidatesInput) -> str:
    '''Parse a candidate markdown file into citation_key + DOI rows.

    Reads a markdown file (e.g. step3_tier1_candidates.md) and extracts every
    paper from its grouped markdown tables. Use this to inspect what would be
    downloaded BEFORE running paper_pdf_download, or to see which candidates are
    missing a DOI.

    Args:
        params (ParseCandidatesInput): Validated parameters containing:
            - md_path (str): Absolute path to the candidate markdown file
            - response_format (ResponseFormat): 'markdown' or 'json'

    Returns:
        str: A report of parsed rows. JSON schema (response_format='json'):
        {
            "md_path": str,
            "total": int,                 # rows parsed
            "with_doi": int,              # rows that have a DOI
            "missing_doi": int,           # rows with no DOI
            "rows": [
                {
                    "citation_key": str,  # e.g. "BergeyEtAl2015"
                    "title": str | null,  # full paper title (from sibling .json)
                    "doi": str | null,    # normalized DOI or null
                    "year": str | null,
                    "domain": str | null,
                    "track_lvl": str | null,
                    "group": str | null   # section heading the row was under
                }
            ]
        }
        Error response: "Error: <message>"

    Examples:
        - Use when: "What papers are in step3_tier1_candidates.md?"
        - Use when: "Which candidates have no DOI?" -> response_format='json', filter doi==null
        - Don't use when: You want to actually download — use paper_pdf_download.
    '''
    try:
        if not os.path.isfile(params.md_path):
            return f"Error: File not found: {params.md_path}"
        rows, _src = load_candidates(params.md_path)
    except OSError as e:
        return f"Error: Could not read file: {e}"

    with_doi = sum(1 for r in rows if r["doi"])

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(
            {
                "md_path": params.md_path,
                "total": len(rows),
                "with_doi": with_doi,
                "missing_doi": len(rows) - with_doi,
                "rows": rows,
            },
            indent=2,
            ensure_ascii=False,
        )

    lines = [
        f"# Parsed Candidates: {os.path.basename(params.md_path)}",
        "",
        f"**Total**: {len(rows)} papers — {with_doi} with DOI, {len(rows) - with_doi} without",
        "",
        "| citation_key | title | doi | year |",
        "|---|---|---|---|",
    ]
    for r in rows:
        doi = r["doi"] or "_(none)_"
        title = (r.get("title") or "").replace("|", "\\|")
        lines.append(f"| `{r['citation_key']}` | {title} | {doi} | {r['year'] or ''} |")
    return "\n".join(lines)


@mcp.tool(
    name="paper_pdf_resolve_url",
    annotations={
        "title": "Resolve DOI to Open-Access PDF URL",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def paper_pdf_resolve_url(params: ResolveUrlInput) -> str:
    '''Resolve a single DOI to a legal open-access PDF URL (no download).

    Queries Unpaywall first, then PubMed Central, then arXiv. Use this to debug
    why a particular paper can or cannot be downloaded.

    Args:
        params (ResolveUrlInput): Validated parameters containing:
            - doi (str): The DOI (with or without https://doi.org/ prefix)

    Returns:
        str: JSON with schema:
        {
            "doi": str,
            "pdf_url": str | null,   # resolved OA PDF URL, or null if none
            "source": str | null,    # "unpaywall" | "pmc" | "arxiv" | null
            "reason": str            # present only when pdf_url is null
        }

    Examples:
        - Use when: "Can I get an OA PDF for 10.1212/wnl.0000000000001280?"
        - Don't use when: You want to download many papers — use paper_pdf_download.
    '''
    async with _client() as client:
        result = await resolve_pdf_url(client, params.doi)
    return json.dumps({"doi": params.doi, **result}, indent=2)


@mcp.tool(
    name="paper_pdf_download",
    annotations={
        "title": "Download Candidate PDFs",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def paper_pdf_download(params: DownloadInput, ctx: Context) -> str:
    '''Parse a candidate markdown file and download every paper's OA PDF.

    The complete workflow: parse the markdown -> resolve each DOI to an
    open-access PDF (Unpaywall + PMC + arXiv) -> download into the output folder
    as {citation_key}.pdf. Downloads run concurrently. Existing files are skipped
    unless overwrite=true. Paywalled papers with no OA copy are reported as
    failures, not errors — the tool always finishes and reports per-paper status.

    Args:
        params (DownloadInput): Validated parameters containing:
            - md_path (str): Absolute path to the candidate markdown file
            - output_dir (Optional[str]): Output folder (default: sibling 'pdfs/')
            - only_keys (Optional[List[str]]): Restrict to these citation_keys
            - overwrite (bool): Re-download existing files (default: false)
            - concurrency (int): Parallel downloads, 1-8 (default: 4)
            - write_missing_report (bool): Write step3_missing_pdfs.md (default: true)
            - response_format (ResponseFormat): 'markdown' or 'json'
        ctx (Context): Injected — used for progress reporting.

    Side effect:
        Unless write_missing_report=false, writes 'step3_missing_pdfs.md' next to
        the source file — a human-recovery checklist of every paper that could not
        be downloaded, bucketed by recoverability with a remediation hint each.

    Returns:
        str: A report. JSON schema (response_format='json'):
        {
            "output_dir": str,
            "total": int,
            "downloaded": int,
            "skipped": int,
            "failed": int,
            "results": [
                {
                    "citation_key": str,
                    "doi": str | null,
                    "path": str,                  # target file path
                    "status": "downloaded" | "skipped" | "failed",
                    "source": str | null,         # which resolver succeeded
                    "pdf_url": str,               # present on download/fail-after-resolve
                    "bytes": int,                 # present on downloaded
                    "reason": str                 # present on skipped/failed
                }
            ]
        }
        Error response (whole run could not start): "Error: <message>"

    Examples:
        - Use when: "Download all the PDFs from step3_tier1_candidates.md"
        - Use when: "Re-download just BergeyEtAl2015" -> only_keys=['BergeyEtAl2015'], overwrite=true
        - Don't use when: You only want to see the list — use paper_pdf_parse_candidates.
    '''
    try:
        if not os.path.isfile(params.md_path):
            return f"Error: File not found: {params.md_path}"
        rows, _src = load_candidates(params.md_path)
    except OSError as e:
        return f"Error: Could not read file: {e}"

    if params.only_keys:
        wanted = set(params.only_keys)
        rows = [r for r in rows if r["citation_key"] in wanted]

    if not rows:
        return "Error: No matching candidate rows found (check the file format or only_keys)."

    output_dir = params.output_dir or os.path.join(os.path.dirname(os.path.abspath(params.md_path)), "pdfs")
    os.makedirs(output_dir, exist_ok=True)

    semaphore = asyncio.Semaphore(params.concurrency)
    done_count = 0
    total = len(rows)

    async with _client() as client:
        async def worker(row: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal done_count
            async with semaphore:
                result = await _download_one(client, row, output_dir, params.overwrite)
            done_count += 1
            # NOTE: report_progress(progress, total=None, message=None). The status
            # string MUST go in `message`; passing it positionally lands it in `total`,
            # which FastMCP validates as a float and the whole gather() crashes on the
            # first call. Keyword args keep each field in its lane. Progress reporting
            # is best-effort telemetry — never let it abort the downloads.
            try:
                await ctx.report_progress(
                    progress=done_count,
                    total=total,
                    message=f"{done_count}/{total} — {result['citation_key']}: {result['status']}",
                )
            except Exception:
                pass
            return result

        results = await asyncio.gather(*(worker(r) for r in rows))

    # Write the human-facing "missing PDFs" report next to the source file.
    missing_report_path = None
    if params.write_missing_report:
        missing_report_path = os.path.join(
            os.path.dirname(os.path.abspath(params.md_path)), "step3_missing_pdfs.md"
        )
        report = build_missing_report(results, params.md_path, output_dir)
        try:
            with open(missing_report_path, "w", encoding="utf-8") as f:
                f.write(report)
        except OSError:
            missing_report_path = None  # non-fatal; download still succeeded

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(
            {
                "output_dir": output_dir,
                "total": len(results),
                "downloaded": sum(1 for r in results if r["status"] == "downloaded"),
                "skipped": sum(1 for r in results if r["status"] == "skipped"),
                "failed": sum(1 for r in results if r["status"] == "failed"),
                "missing_report": missing_report_path,
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
        )

    md = _format_download_markdown(output_dir, results)
    if missing_report_path:
        md += f"\n\n📋 Missing-PDF recovery list written to `{missing_report_path}`"
    return md


if __name__ == "__main__":
    mcp.run()
