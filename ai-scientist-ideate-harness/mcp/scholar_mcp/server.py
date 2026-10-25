#!/usr/bin/env python3
"""
MCP Server for academic literature search (scholar_mcp).

Wraps seven academic databases — Semantic Scholar, OpenAlex, PubMed, arXiv, Scopus,
IEEE Xplore, and Web of Science — behind a small set of high-level tools that return ALREADY-NORMALIZED,
ALREADY-PARSED records. The point of this server is to move the brittle parts (OpenAlex
inverted-index abstract reconstruction, PubMed XML parsing, DOI normalization, rate-limit
retries, DOI/title deduplication, snowball reference fetching) out of the LLM and into
deterministic code. The LLM keeps the *decisions* — which queries to run, which papers
to keep, how to cluster — while this server handles the *mechanics*.

Scopus, IEEE Xplore, Web of Science, and (optionally) PubMed and Semantic Scholar take API keys, read
from the environment or a `.env` beside this file:
  - SCOPUS_API_KEY   : Elsevier Scopus Search API (https://dev.elsevier.com)
  - IEEE_API_KEY     : IEEE Xplore Metadata API (https://developer.ieee.org)
  - WOS_API_KEY      : Clarivate Web of Science Expanded API (https://developer.clarivate.com)
  - PUBMED_API_KEY   : NCBI E-utilities key (optional; raises rate limit 3->10 req/s)
  - SEMANTIC_SCHOLAR_API_KEY : optional for search; recommendations are rate-limited without it
  - OPENALEX_API_KEY : optional; without it every client on the network shares one small daily budget
A source whose key is absent is skipped with a clear message in `source_errors` rather
than failing the whole search; the keyless sources (SS, OpenAlex, arXiv) always run.

Tools:
  - scholar_search        : one query against one-or-more sources -> normalized papers
  - scholar_dedup         : merge multiple search batches, dedup by DOI then fuzzy title
  - scholar_snowball      : fetch the reference list of a seed paper (Semantic Scholar)
  - scholar_recover_dois  : fill missing DOIs via Semantic Scholar lookup
  - scholar_recommend     : Semantic Scholar's embedding neighbours of seed papers (dense retrieval)
  - scholar_venues        : Scopus SNIP and SJR for up to 25 ISSNs

Every tool is read-only and returns JSON as a string.

Run (stdio transport, the default for local Claude Code use):
    python server.py
"""

from __future__ import annotations

import asyncio
import time
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
import logging

# httpx logs every request URL at INFO, and several APIs (PubMed, IEEE) carry the API key as a query parameter,
# so INFO-level request logging writes credentials to stderr / any log file. Keep warnings and errors only.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Server + constants
# ---------------------------------------------------------------------------

mcp = FastMCP("scholar_mcp")


def _load_dotenv() -> None:
    """Minimal .env loader: populate os.environ from a sibling/project `.env`
    WITHOUT overwriting already-set vars. Keeps API keys out of source while not
    requiring python-dotenv. Looks at the server dir and two parents up (project root)."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, ".env"),
        os.path.join(here, "..", "..", "..", ".env"),  # project root
    ]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = val
        except OSError:
            continue


_load_dotenv()

SEMANTIC_SCHOLAR_BASE = "https://api.semanticscholar.org/graph/v1"
SEMANTIC_SCHOLAR_RECS_BASE = "https://api.semanticscholar.org/recommendations/v1"
OPENALEX_BASE = "https://api.openalex.org"
OPENALEX_API_KEY = os.environ.get("OPENALEX_API_KEY")  # optional: a key has its own daily budget
PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ARXIV_BASE = "https://export.arxiv.org/api"
SCOPUS_BASE = "https://api.elsevier.com/content/search/scopus"
IEEE_BASE = "https://ieeexploreapi.ieee.org/api/v1/search/articles"
WOS_BASE = "https://api.clarivate.com/api/wos"  # Expanded API

# API keys (read from env / .env). Absent key -> that source is skipped, not fatal.
SCOPUS_API_KEY = os.environ.get("SCOPUS_API_KEY")
IEEE_API_KEY = os.environ.get("IEEE_API_KEY")
WOS_API_KEY = os.environ.get("WOS_API_KEY")
PUBMED_API_KEY = os.environ.get("PUBMED_API_KEY")  # optional; only raises rate limit
# Optional. Keyless Semantic Scholar answers 429 most days; with a key the search, the snowball and the recommendations
# get their own rate limit. Sent as the x-api-key header.
SEMANTIC_SCHOLAR_API_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")


def _s2_headers() -> Optional[dict]:
    return {"x-api-key": SEMANTIC_SCHOLAR_API_KEY} if SEMANTIC_SCHOLAR_API_KEY else None

# Sent to OpenAlex `mailto` (polite pool) and PubMed `email`. Override via env if you like.
CONTACT_EMAIL = os.environ.get("SCHOLAR_CONTACT_EMAIL", "research-agent@example.com")

DEFAULT_TIMEOUT = 30.0
DEFAULT_LIMIT = 25
USER_AGENT = "scholar_mcp/0.2 (Research Agent pipeline)"

# Fields requested from Semantic Scholar paper search.
SS_SEARCH_FIELDS = (
    "title,authors,year,abstract,externalIds,citationCount,journal,url"
)


# ---------------------------------------------------------------------------
# Enums + the canonical paper schema this server speaks
# ---------------------------------------------------------------------------


class Source(str, Enum):
    """The academic database to query."""

    SEMANTIC_SCHOLAR = "semantic_scholar"
    OPENALEX = "openalex"
    PUBMED = "pubmed"
    ARXIV = "arxiv"
    SCOPUS = "scopus"
    IEEE = "ieee"
    WOS = "wos"


# Sources that require an API key, mapped to the env var that supplies it. PubMed is
# deliberately NOT here: it works keyless (the key only lifts the rate limit).
_KEYED_SOURCES = {
    Source.SCOPUS: ("SCOPUS_API_KEY", lambda: SCOPUS_API_KEY),
    Source.IEEE: ("IEEE_API_KEY", lambda: IEEE_API_KEY),
    Source.WOS: ("WOS_API_KEY", lambda: WOS_API_KEY),
}


def _empty_paper() -> Dict[str, Any]:
    """The normalized record every adapter fills. Missing fields stay null,
    never absent — so downstream code can rely on the shape."""
    return {
        "title": None,
        "authors": [],
        "year": None,
        "journal": None,
        "doi": None,
        "url": None,
        "abstract": None,
        "citation_count": None,
        "sources_found_in": [],
        "semantic_scholar_id": None,
        "openalex_id": None,
        "pubmed_id": None,
        "arxiv_id": None,
        "scopus_id": None,
        "ieee_id": None,
        "wos_id": None,
    }


class Hits(list):
    """An adapter's papers plus `total`: how many records the database reports for the query (None when it does not
    say). PRISMA's identification box and the relevance check need it: 25 papers taken from 25 is a different search
    from 25 taken from 4,300."""
    total: Optional[int] = None


def _hits(papers, total) -> "Hits":
    h = Hits(papers)
    try:
        h.total = int(total) if total is not None else None
    except (TypeError, ValueError):
        h.total = None
    return h


# ---------------------------------------------------------------------------
# Shared helpers — HTTP, DOI normalization, title normalization
# ---------------------------------------------------------------------------


async def _paced_turn(clock: Path, gap: float) -> None:
    """Wait until `gap` seconds have passed since the last call recorded in `clock`, then record this one. The time
    lives in a lock-guarded file, so the spacing holds across every server process on the machine (parallel research
    dirs each start their own server)."""
    import fcntl
    while True:
        with open(clock, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.seek(0)
            try:
                last = float(fh.read().strip() or 0)
            except ValueError:
                last = 0.0
            wait = gap - (time.time() - last)
            if wait <= 0:
                fh.seek(0)
                fh.truncate()
                fh.write(f"{time.time():.3f}")
                return
        await asyncio.sleep(min(wait, gap))


# Semantic Scholar's key allows about one request a second across all its endpoints; the snowball's recommendations call
# came straight after other S2 calls and got 429 even with a key (s20: q363, q386, q000). Every S2 request waits its turn.
S2_GAP = 1.1
S2_CLOCK = Path(os.environ.get("TMPDIR", "/tmp")) / "ai-scientist-s2-clock"
S2_BACKOFF = (10.0, 30.0, 60.0)        # seconds to wait after a 429 with a key, unless the answer says Retry-After
S2_BACKOFF_KEYLESS = (3.0, 6.0, 9.0)   # keyless S2 answers 429 most days: fail fast rather than wait a minute per call


def _s2_backoff(attempt: int) -> float:
    b = S2_BACKOFF if SEMANTIC_SCHOLAR_API_KEY else S2_BACKOFF_KEYLESS
    return b[min(attempt, len(b) - 1)]


def _is_s2(url: str) -> bool:
    return url.startswith("https://api.semanticscholar.org")


def _retry_after(resp: httpx.Response, default: float) -> float:
    try:
        return max(default, float(resp.headers.get("Retry-After") or 0))
    except ValueError:
        return default


async def _s2_post(url: str, params: dict, body: dict) -> httpx.Response:
    """POST to Semantic Scholar: each attempt waits its turn on the shared clock; a 429 is waited out (`S2_BACKOFF`,
    or `Retry-After` when longer) up to len(S2_BACKOFF) times. Raises on the final failure."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **(_s2_headers() or {})}
    resp = None
    for attempt in range(len(S2_BACKOFF) + 1):
        await _paced_turn(S2_CLOCK, S2_GAP)
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, headers=headers) as client:
            resp = await client.post(url, params=params, json=body)
        if resp.status_code == 429 and attempt < len(S2_BACKOFF):
            await asyncio.sleep(_retry_after(resp, _s2_backoff(attempt)))
            continue
        break
    resp.raise_for_status()
    return resp


async def _get(
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    retries: int = 2,
) -> httpx.Response:
    """GET with polite retries on 429/timeout. Raises on final failure. Semantic Scholar calls are paced
    (`S2_GAP`, shared by all processes) and back off longer on 429 (`S2_BACKOFF`).

    `headers` is merged onto the default User-Agent/Accept pair (caller wins), so
    sources that need auth headers (e.g. Scopus's X-ELS-APIKey) can pass them in."""
    last_exc: Optional[Exception] = None
    base_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        base_headers.update(headers)
    headers = base_headers
    s2 = _is_s2(url)
    for attempt in range(retries + 1):
        try:
            if s2:
                await _paced_turn(S2_CLOCK, S2_GAP)
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, headers=headers) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 429 and attempt < retries:
                    await asyncio.sleep(_retry_after(resp, _s2_backoff(attempt)) if s2 else 3.0 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp
        except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            last_exc = exc
            if attempt < retries:
                await asyncio.sleep(2.0 * (attempt + 1))
                continue
            raise
    # Unreachable, but keeps type checkers happy.
    raise last_exc  # type: ignore[misc]


def _normalize_doi(doi: Optional[str]) -> Optional[str]:
    """Lowercase, strip URL prefixes, return bare DOI or None."""
    if not doi:
        return None
    d = doi.strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    d = d.removeprefix("doi:").strip()
    return d or None


_TITLE_STOP = re.compile(r"[^\w\s]", re.UNICODE)


def _title_tokens(title: Optional[str]) -> set:
    """Normalized word set for fuzzy title matching."""
    if not title:
        return set()
    t = _TITLE_STOP.sub(" ", title.lower())
    return {w for w in t.split() if w}


def _last_name(author: Optional[str]) -> str:
    """Best-effort last token of an author name, lowercased."""
    if not author:
        return ""
    return author.strip().split()[-1].lower() if author.strip() else ""


# ---------------------------------------------------------------------------
# Source adapters — each returns a list of normalized paper dicts
# ---------------------------------------------------------------------------


async def _search_semantic_scholar(query: str, limit: int, year: Optional[str]) -> List[Dict[str, Any]]:
    params = {"query": query, "fields": SS_SEARCH_FIELDS, "limit": min(limit, 100)}
    if year:
        params["year"] = year
    resp = await _get(f"{SEMANTIC_SCHOLAR_BASE}/paper/search", params=params, headers=_s2_headers())
    data = resp.json()
    out: List[Dict[str, Any]] = []
    for item in data.get("data", []) or []:
        p = _empty_paper()
        ext = item.get("externalIds") or {}
        p["title"] = item.get("title")
        p["authors"] = [a.get("name") for a in (item.get("authors") or []) if a.get("name")]
        p["year"] = item.get("year")
        p["journal"] = (item.get("journal") or {}).get("name")
        p["doi"] = _normalize_doi(ext.get("DOI"))
        p["url"] = item.get("url")
        p["abstract"] = item.get("abstract")
        p["citation_count"] = item.get("citationCount")
        p["semantic_scholar_id"] = item.get("paperId")
        p["arxiv_id"] = ext.get("ArXiv")
        p["pubmed_id"] = str(ext["PubMed"]) if ext.get("PubMed") else None
        p["sources_found_in"] = [Source.SEMANTIC_SCHOLAR.value]
        out.append(p)
    return _hits(out, data.get("total"))


def _reconstruct_openalex_abstract(inv_index: Optional[dict]) -> Optional[str]:
    """OpenAlex stores abstracts as {word: [positions]}. Rebuild the text."""
    if not inv_index:
        return None
    positions: List[tuple] = []
    for word, idxs in inv_index.items():
        for i in idxs:
            positions.append((i, word))
    if not positions:
        return None
    positions.sort(key=lambda x: x[0])
    return " ".join(w for _, w in positions)


async def _search_openalex(query: str, limit: int, year: Optional[str]) -> List[Dict[str, Any]]:
    # Title+abstract search in OpenAlex's relevance order: full-text search sorted by citations returns mega-cited
    # off-topic surveys for any multi-word query.
    filters = [f"title_and_abstract.search:{query.replace(',', ' ').replace(':', ' ')}"]
    if year:
        parts = year.split("-")
        filters.append(f"from_publication_date:{parts[0]}-01-01")
        if len(parts) > 1 and parts[1]:
            filters.append(f"to_publication_date:{parts[1]}-12-31")   # the end of the range, not only its start
    params = {
        "filter": ",".join(filters),
        "per_page": min(limit, 200),
        "mailto": CONTACT_EMAIL,
    }
    if OPENALEX_API_KEY:
        params["api_key"] = OPENALEX_API_KEY
    resp = await _get(f"{OPENALEX_BASE}/works", params=params)
    data = resp.json()
    out: List[Dict[str, Any]] = []
    for item in data.get("results", []) or []:
        p = _empty_paper()
        ids = item.get("ids") or {}
        p["title"] = item.get("title")
        p["authors"] = [
            (a.get("author") or {}).get("display_name")
            for a in (item.get("authorships") or [])
            if (a.get("author") or {}).get("display_name")
        ]
        p["year"] = item.get("publication_year")
        p["journal"] = ((item.get("primary_location") or {}).get("source") or {}).get("display_name")
        p["doi"] = _normalize_doi(item.get("doi"))
        p["url"] = ids.get("doi") or item.get("id")
        p["abstract"] = _reconstruct_openalex_abstract(item.get("abstract_inverted_index"))
        p["citation_count"] = item.get("cited_by_count")
        oa_id = item.get("id") or ""
        p["openalex_id"] = oa_id.rsplit("/", 1)[-1] if oa_id else None
        pmid_url = ids.get("pmid") or ""
        p["pubmed_id"] = pmid_url.rsplit("/", 1)[-1] if pmid_url else None
        p["sources_found_in"] = [Source.OPENALEX.value]
        out.append(p)
    return _hits(out, (data.get("meta") or {}).get("count"))


async def _search_pubmed(query: str, limit: int, year: Optional[str]) -> List[Dict[str, Any]]:
    # Step 1: ESearch -> PMIDs
    esearch_params = {
        "db": "pubmed",
        "term": query,
        "retmax": min(limit, 100),
        "retmode": "json",
        "sort": "relevance",  # Best Match, stated rather than left to the E-utilities default
        "datetype": "pdat",
        "email": CONTACT_EMAIL,
    }
    if PUBMED_API_KEY:
        esearch_params["api_key"] = PUBMED_API_KEY
    if year:
        parts = year.split("-")
        esearch_params["mindate"] = parts[0]
        esearch_params["maxdate"] = parts[1] if len(parts) > 1 else parts[0]
    resp = await _get(f"{PUBMED_BASE}/esearch.fcgi", params=esearch_params)
    esr = resp.json().get("esearchresult") or {}
    idlist = esr.get("idlist") or []
    if not idlist:
        return _hits([], esr.get("count"))

    # Step 2: EFetch -> XML details
    efetch_params = {"db": "pubmed", "id": ",".join(idlist), "retmode": "xml", "email": CONTACT_EMAIL}
    if PUBMED_API_KEY:
        efetch_params["api_key"] = PUBMED_API_KEY
    resp = await _get(f"{PUBMED_BASE}/efetch.fcgi", params=efetch_params)
    return _hits(_parse_pubmed_xml(resp.text), esr.get("count"))


def _parse_pubmed_xml(xml_text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for art in root.findall(".//PubmedArticle"):
        p = _empty_paper()
        pmid_el = art.find(".//MedlineCitation/PMID")
        p["pubmed_id"] = pmid_el.text if pmid_el is not None else None

        title_el = art.find(".//Article/ArticleTitle")
        p["title"] = "".join(title_el.itertext()).strip() if title_el is not None else None

        # Abstract may have multiple labeled sections.
        abstract_parts = [
            "".join(ab.itertext()).strip()
            for ab in art.findall(".//Article/Abstract/AbstractText")
        ]
        p["abstract"] = " ".join(x for x in abstract_parts if x) or None

        authors: List[str] = []
        for au in art.findall(".//Article/AuthorList/Author"):
            fore = au.findtext("ForeName")
            last = au.findtext("LastName")
            if last:
                authors.append(f"{fore} {last}".strip() if fore else last)
            else:
                coll = au.findtext("CollectiveName")
                if coll:
                    authors.append(coll)
        p["authors"] = authors

        journal_el = art.find(".//Article/Journal/Title")
        p["journal"] = journal_el.text if journal_el is not None else None

        year_el = (
            art.find(".//Article/Journal/JournalIssue/PubDate/Year")
            or art.find(".//Article/ArticleDate/Year")
        )
        if year_el is not None and year_el.text and year_el.text.isdigit():
            p["year"] = int(year_el.text)

        for aid in art.findall(".//PubmedData/ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi":
                p["doi"] = _normalize_doi(aid.text)
        if p["pubmed_id"]:
            p["url"] = f"https://pubmed.ncbi.nlm.nih.gov/{p['pubmed_id']}/"
        p["sources_found_in"] = [Source.PUBMED.value]
        out.append(p)
    return out


_ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


ARXIV_GAP, ARXIV_BACKOFF = 3.5, 20.0       # seconds between arXiv calls; wait after a 429 before the one retry
# arXiv limits per client machine, so the spacing holds across every server process on it: the time of the last call
# lives in a lock-guarded file (several searches - parallel research dirs - each start their own server).
ARXIV_CLOCK = Path(os.environ.get("TMPDIR", "/tmp")) / "ai-scientist-arxiv-clock"


async def _arxiv_turn() -> None:
    await _paced_turn(ARXIV_CLOCK, ARXIV_GAP)


async def _arxiv_fetch(params: Dict[str, Any]) -> str:
    """Fetch the arXiv Atom feed with curl instead of httpx.

    arXiv's front end answers 406 to every *fresh* request made by httpx, whatever the
    headers, URL encoding or parameters, while curl gets 200 for the identical URL. Responses are cached per URL, so an
    httpx call only succeeds when curl has already fetched that exact URL - which made the failure look intermittent.
    Verified with a falsifiable test (httpx 406 -> curl 200 -> httpx 200 on a never-seen URL). What is fingerprinted is
    unknown; routing through curl sidesteps it. Falls back to httpx when curl is not installed.
    """
    import shutil
    from urllib.parse import urlencode

    url = f"{ARXIV_BASE}/query?{urlencode(params)}"
    if not shutil.which("curl"):
        return (await _get(f"{ARXIV_BASE}/query", params=params)).text
    for attempt in range(2):
        # arXiv asks for one request every 3 s per client and answers 429 to anything faster (two searches running
        # side by side were enough to get this machine blocked for a while): space the calls, back off on 429.
        await _arxiv_turn()
        proc = await asyncio.create_subprocess_exec(
            "curl", "-sS", "--fail", "--max-time", "40", "-A", USER_AGENT, url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode == 0:
            return out.decode("utf-8", errors="replace")
        msg = err.decode(errors="replace")
        if ("429" in msg or "error: 400" in msg) and attempt == 0:   # arXiv also answers 400 to a valid query when loaded
            await asyncio.sleep(ARXIV_BACKOFF)
            continue
        raise RuntimeError(f"arXiv request failed (curl exit {proc.returncode}): {msg[:160]}")


async def _search_arxiv(query: str, limit: int, year: Optional[str]) -> List[Dict[str, Any]]:
    # arXiv wants its own query syntax; turn a plain phrase into all:term AND all:term. A query that already carries
    # arXiv field prefixes (all: ti: abs: au: cat:) - the Boolean form the search step renders from the protocol's
    # axes - is passed through untouched (splitting it on spaces would break its brackets).
    if re.search(r"\b(all|ti|abs|au|cat|co|jr):", query):
        search_query = query
    else:
        terms = [t for t in re.split(r"\s+", query.strip()) if t]
        search_query = " AND ".join(f"all:{t}" for t in terms) if terms else f"all:{query}"
    if year:                       # the range in the query, so the results returned all fall inside it
        parts = year.split("-")
        lo, hi = parts[0], (parts[1] if len(parts) > 1 and parts[1] else "2999")
        search_query = f"({search_query}) AND submittedDate:[{lo}01010000 TO {hi}12312359]"
    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": min(limit, 50),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    xml_text = await _arxiv_fetch(params)
    out = _parse_arxiv_atom(xml_text)
    m = re.search(r"<opensearch:totalResults[^>]*>(\d+)<", xml_text)
    if year:
        parts = year.split("-")
        start, end = int(parts[0]), (int(parts[1]) if len(parts) > 1 and parts[1] else None)
        out = [p for p in out if p["year"] is None or (p["year"] >= start and (end is None or p["year"] <= end))]
    return _hits(out, m.group(1) if m else None)


def _parse_arxiv_atom(xml_text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for entry in root.findall("atom:entry", _ARXIV_NS):
        p = _empty_paper()
        id_el = entry.find("atom:id", _ARXIV_NS)
        if id_el is not None and id_el.text:
            m = re.search(r"abs/([^v]+)(v\d+)?$", id_el.text)
            p["arxiv_id"] = m.group(1) if m else id_el.text.rsplit("/", 1)[-1]
            p["url"] = id_el.text
        title_el = entry.find("atom:title", _ARXIV_NS)
        if title_el is not None and title_el.text:
            p["title"] = re.sub(r"\s+", " ", title_el.text).strip()
        summ_el = entry.find("atom:summary", _ARXIV_NS)
        if summ_el is not None and summ_el.text:
            p["abstract"] = re.sub(r"\s+", " ", summ_el.text).strip()
        pub_el = entry.find("atom:published", _ARXIV_NS)
        if pub_el is not None and pub_el.text:
            p["year"] = int(pub_el.text[:4])
        p["authors"] = [
            a.findtext("atom:name", default="", namespaces=_ARXIV_NS).strip()
            for a in entry.findall("atom:author", _ARXIV_NS)
            if a.findtext("atom:name", default="", namespaces=_ARXIV_NS).strip()
        ]
        doi_el = entry.find("arxiv:doi", _ARXIV_NS)
        if doi_el is not None and doi_el.text:
            p["doi"] = _normalize_doi(doi_el.text)
        p["journal"] = "arXiv"
        p["sources_found_in"] = [Source.ARXIV.value]
        out.append(p)
    return out


class _MissingKeyError(RuntimeError):
    """Raised by a keyed adapter when its API key env var is unset. Surfaced to the
    caller as a per-source message in `source_errors`, never as a hard failure."""


def _as_list(value: Any) -> List[Any]:
    """Scopus/IEEE return some fields as either a single object or a list depending on
    cardinality. Normalize to a list."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


async def _search_scopus(query: str, limit: int, year: Optional[str]) -> List[Dict[str, Any]]:
    """Elsevier Scopus Search API. Auth via X-ELS-APIKey header. The bare query is
    wrapped in TITLE-ABS-KEY(...) so it matches title/abstract/keywords like the other
    sources' relevance search, unless the caller already passed Scopus field syntax."""
    if not SCOPUS_API_KEY:
        raise _MissingKeyError("SCOPUS_API_KEY not set — Scopus skipped.")
    # If the query already uses Scopus field operators, pass it through untouched.
    if re.search(r"\b(TITLE-ABS-KEY|TITLE|ABS|KEY|AUTH|DOI)\s*\(", query, re.IGNORECASE):
        scopus_query = query
    else:
        scopus_query = f"TITLE-ABS-KEY({query})"
    if year:
        parts = year.split("-")
        lo = parts[0]
        hi = parts[1] if len(parts) > 1 else parts[0]
        years = " OR ".join(f"PUBYEAR IS {y}" for y in range(int(lo), int(hi) + 1)) if int(hi) - int(lo) <= 30 else None
        if years:
            scopus_query = f"({scopus_query}) AND ({years})"
    headers = {"X-ELS-APIKey": SCOPUS_API_KEY, "Accept": "application/json"}
    # The standard view caps a page at 25, so a larger limit pages through (start=25, 50, ...).
    entries, total, start = [], None, 0
    while start < limit:
        params = {
            "query": scopus_query,
            "count": min(limit - start, 25),  # Scopus standard view caps at 25/page
            "start": start,
            "sort": "relevancy",  # by citations, a 50-of-5,000 sample is the most cited, not the most relevant
            "view": "STANDARD",
        }
        resp = await _get(SCOPUS_BASE, params=params, headers=headers)
        results = (resp.json().get("search-results") or {})
        total = results.get("opensearch:totalResults", total)
        page = _as_list(results.get("entry"))
        entries += page
        start += 25
        if len(page) < 25 or (total is not None and str(total).isdigit() and start >= int(total)):
            break
    out: List[Dict[str, Any]] = []
    for item in entries:
        if item.get("error"):  # Scopus returns a single entry with 'error' on no-results
            continue
        p = _empty_paper()
        p["title"] = item.get("dc:title")
        creator = item.get("dc:creator")
        p["authors"] = [creator] if creator else []  # STANDARD view gives only first author
        cover = item.get("prism:coverDate") or ""
        if cover[:4].isdigit():
            p["year"] = int(cover[:4])
        p["journal"] = item.get("prism:publicationName")
        p["doi"] = _normalize_doi(item.get("prism:doi"))
        cc = item.get("citedby-count")
        p["citation_count"] = int(cc) if cc and str(cc).isdigit() else None
        sid = item.get("dc:identifier") or ""
        p["scopus_id"] = sid.split(":")[-1] if ":" in sid else (sid or None)
        # Prefer the Scopus record URL from the link list; fall back to DOI.
        for ln in _as_list(item.get("link")):
            if ln.get("@ref") == "scopus":
                p["url"] = ln.get("@href")
                break
        if not p["url"] and p["doi"]:
            p["url"] = f"https://doi.org/{p['doi']}"
        pmid = item.get("pubmed-id")
        p["pubmed_id"] = str(pmid) if pmid else None
        # STANDARD view omits abstracts; abstract stays None (recoverable via other sources on dedup).
        p["abstract"] = item.get("dc:description")
        p["sources_found_in"] = [Source.SCOPUS.value]
        out.append(p)
    return _hits(out, total)


async def _search_ieee(query: str, limit: int, year: Optional[str]) -> List[Dict[str, Any]]:
    """IEEE Xplore Metadata API. Auth via `apikey` query param. NOTE: a freshly issued
    key returns HTTP 403 'Developer Inactive' until IEEE activates it — that surfaces as
    a clean per-source error, not a crash."""
    if not IEEE_API_KEY:
        raise _MissingKeyError("IEEE_API_KEY not set — IEEE Xplore skipped.")
    params = {
        "apikey": IEEE_API_KEY,
        "format": "json",
        "querytext": query,
        "max_records": min(limit, 25),  # IEEE free tier caps at 25/request
        "start_record": 1,  # no sort_field: IEEE's default order is relevance
    }
    if year:
        parts = year.split("-")
        params["start_year"] = parts[0]
        params["end_year"] = parts[1] if len(parts) > 1 else parts[0]
    resp = await _get(IEEE_BASE, params=params)
    data = resp.json()
    out: List[Dict[str, Any]] = []
    for item in data.get("articles") or []:
        p = _empty_paper()
        p["title"] = item.get("title")
        p["authors"] = [
            a.get("full_name")
            for a in _as_list((item.get("authors") or {}).get("authors"))
            if a.get("full_name")
        ]
        py = item.get("publication_year")
        if py and str(py).isdigit():
            p["year"] = int(py)
        p["journal"] = item.get("publication_title")
        p["doi"] = _normalize_doi(item.get("doi"))
        p["url"] = item.get("html_url") or item.get("pdf_url")
        p["abstract"] = item.get("abstract")
        cc = item.get("citing_paper_count")
        p["citation_count"] = int(cc) if cc is not None and str(cc).isdigit() else None
        an = item.get("article_number")
        p["ieee_id"] = str(an) if an else None
        p["sources_found_in"] = [Source.IEEE.value]
        out.append(p)
    return _hits(out, data.get("total_records"))


async def _search_wos(query: str, limit: int, year: Optional[str]) -> List[Dict[str, Any]]:
    """Clarivate Web of Science Expanded API. Auth via X-ApiKey header. The bare query is
    wrapped in TS=(...) (topic: title/abstract/keywords) unless the caller already passed
    WoS field-tag syntax. Unlike the Starter API, the Expanded API returns full abstracts.
    Note: WoS relevance sorting requires the query to be field-tagged, which TS=() gives us."""
    if not WOS_API_KEY:
        raise _MissingKeyError("WOS_API_KEY not set — Web of Science skipped.")
    # If the query already uses WoS field tags (TS=, TI=, AU=, PY=, DO=...), pass through.
    if re.search(r"\b(TS|TI|AU|PY|DO|SO|IS|UT|AB)\s*=", query):
        wos_query = query
    else:
        wos_query = f"TS=({query})"
    if year:
        parts = year.split("-")
        span = f"{parts[0]}-{parts[1]}" if len(parts) > 1 else parts[0]
        wos_query = f"({wos_query}) AND PY=({span})"
    params = {
        "databaseId": "WOS",
        "usrQuery": wos_query,
        "count": min(limit, 100),  # Expanded API caps at 100/request
        "firstRecord": 1,
        "sortField": "RS+D",  # relevance, descending
    }
    headers = {"X-ApiKey": WOS_API_KEY, "Accept": "application/json"}
    resp = await _get(WOS_BASE, params=params, headers=headers)
    data = resp.json()
    recs = ((((data.get("Data") or {}).get("Records") or {}).get("records") or {}).get("REC")) or []
    out: List[Dict[str, Any]] = []
    for item in _as_list(recs):
        p = _empty_paper()
        static = item.get("static_data") or {}
        summary = static.get("summary") or {}
        dynamic = item.get("dynamic_data") or {}

        # Titles list carries both the item title and the source (journal) title.
        for t in _as_list((summary.get("titles") or {}).get("title")):
            if t.get("type") == "item":
                p["title"] = t.get("content")
            elif t.get("type") == "source":
                p["journal"] = t.get("content")

        yr = (summary.get("pub_info") or {}).get("pubyear")
        if yr and str(yr).isdigit():
            p["year"] = int(yr)

        p["authors"] = [
            n.get("display_name") or n.get("full_name")
            for n in _as_list((summary.get("names") or {}).get("name"))
            if n.get("role") == "author" and (n.get("display_name") or n.get("full_name"))
        ]

        # DOI / PMID live in dynamic_data.cluster_related.identifiers.
        idents = _as_list(((dynamic.get("cluster_related") or {}).get("identifiers") or {}).get("identifier"))
        for ident in idents:
            if ident.get("type") == "doi":
                p["doi"] = _normalize_doi(ident.get("value"))
            elif ident.get("type") == "pmid" and ident.get("value"):
                # WoS prefixes PMIDs as 'MEDLINE:12345678'.
                p["pubmed_id"] = str(ident["value"]).rsplit(":", 1)[-1]

        # Citation count: WOS silo entry in the times-cited list.
        silo = _as_list((((dynamic.get("citation_related") or {}).get("tc_list")) or {}).get("silo_tc"))
        for tc in silo:
            if tc.get("coll_id") == "WOS" and tc.get("local_count") is not None:
                p["citation_count"] = int(tc["local_count"])
                break

        # Abstract paragraphs: abstract_text.p is a string or a list of strings.
        abstract_obj = (((static.get("fullrecord_metadata") or {}).get("abstracts") or {}).get("abstract")) or {}
        paras = _as_list((abstract_obj.get("abstract_text") or {}).get("p"))
        p["abstract"] = " ".join(str(x) for x in paras if x) or None

        uid = item.get("UID") or ""
        p["wos_id"] = uid or None
        if p["doi"]:
            p["url"] = f"https://doi.org/{p['doi']}"
        elif uid:
            p["url"] = f"https://www.webofscience.com/wos/woscc/full-record/{uid}"
        p["sources_found_in"] = [Source.WOS.value]
        out.append(p)
    return _hits(out, (data.get("QueryResult") or {}).get("RecordsFound"))


_ADAPTERS = {
    Source.SEMANTIC_SCHOLAR: _search_semantic_scholar,
    Source.OPENALEX: _search_openalex,
    Source.PUBMED: _search_pubmed,
    Source.ARXIV: _search_arxiv,
    Source.SCOPUS: _search_scopus,
    Source.IEEE: _search_ieee,
    Source.WOS: _search_wos,
}


# ---------------------------------------------------------------------------
# Dedup logic (shared by scholar_search merge and scholar_dedup tool)
# ---------------------------------------------------------------------------


def _merge_two(into: Dict[str, Any], other: Dict[str, Any]) -> None:
    """Merge `other` into `into` in place. Prefer richest non-null metadata."""
    # Union sources.
    srcs = set(into.get("sources_found_in") or []) | set(other.get("sources_found_in") or [])
    into["sources_found_in"] = sorted(srcs)
    # Fill any null scalar field from the other record.
    for key in ("title", "year", "journal", "doi", "url", "abstract",
                "semantic_scholar_id", "openalex_id", "pubmed_id", "arxiv_id",
                "scopus_id", "ieee_id", "wos_id"):
        if not into.get(key) and other.get(key):
            into[key] = other[key]
    # Authors: keep the longer list.
    if len(other.get("authors") or []) > len(into.get("authors") or []):
        into["authors"] = other["authors"]
    # Citation count: keep the max (different sources lag differently).
    a, b = into.get("citation_count"), other.get("citation_count")
    if b is not None and (a is None or b > a):
        into["citation_count"] = b
    # Prefer a longer abstract.
    if other.get("abstract") and len(other["abstract"]) > len(into.get("abstract") or ""):
        into["abstract"] = other["abstract"]


def _dedup(papers: List[Dict[str, Any]], title_threshold: float = 0.85) -> List[Dict[str, Any]]:
    """Dedup by DOI (exact) then fuzzy title (Jaccard over word sets +
    same first-author last name + year within ±1)."""
    by_doi: Dict[str, Dict[str, Any]] = {}
    no_doi: List[Dict[str, Any]] = []

    for p in papers:
        doi = _normalize_doi(p.get("doi"))
        if doi:
            p["doi"] = doi
            if doi in by_doi:
                _merge_two(by_doi[doi], p)
            else:
                by_doi[doi] = dict(p)
        else:
            no_doi.append(dict(p))

    merged: List[Dict[str, Any]] = list(by_doi.values())

    # Fuzzy match DOI-less papers against the whole growing set.
    for cand in no_doi:
        cand_tokens = _title_tokens(cand.get("title"))
        cand_first = _last_name((cand.get("authors") or [None])[0])
        cand_year = cand.get("year")
        matched = False
        for existing in merged:
            ex_tokens = _title_tokens(existing.get("title"))
            if not cand_tokens or not ex_tokens:
                continue
            jacc = len(cand_tokens & ex_tokens) / len(cand_tokens | ex_tokens)
            ex_first = _last_name((existing.get("authors") or [None])[0])
            year_ok = (
                cand_year is None
                or existing.get("year") is None
                or abs(cand_year - existing["year"]) <= 1
            )
            name_ok = (not cand_first) or (not ex_first) or (cand_first == ex_first)
            if jacc >= title_threshold and year_ok and name_ok:
                _merge_two(existing, cand)
                matched = True
                break
        if not matched:
            merged.append(cand)
    return merged


# ---------------------------------------------------------------------------
# Pydantic input models
# ---------------------------------------------------------------------------


class SearchInput(BaseModel):
    """Input for scholar_search."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., description="Search phrase, e.g. 'closed-loop neurostimulation epilepsy'", min_length=2, max_length=2000)  # = it_frame.MAX_QUERY_CHARS; a rendered Boolean form runs to ~1-2k
    sources: List[Source] = Field(
        default_factory=lambda: [Source.SEMANTIC_SCHOLAR, Source.OPENALEX, Source.SCOPUS],
        description=(
            "Which databases to query. Default: Semantic Scholar + OpenAlex + Scopus. "
            "Options: 'semantic_scholar','openalex','pubmed','arxiv','scopus','ieee','wos'. "
            "'pubmed' for biomedical, 'arxiv' for CS/preprints, 'scopus' for broad indexed "
            "coverage, 'ieee' for engineering/CS conferences & journals, 'wos' for Web of "
            "Science Core Collection (curated, citation-authoritative). NOTE: WoS ANDs all "
            "query terms — long multi-word queries often return 0; keep WoS queries to 2-4 "
            "core terms or pass explicit WoS syntax like TS=(a OR b). "
            "scopus/ieee/wos require API keys (set in env); a keyless source is skipped "
            "with a note in source_errors rather than failing the search."
        ),
        max_length=7,
    )
    limit: int = Field(default=DEFAULT_LIMIT, description="Max results per source", ge=1, le=100)
    year: Optional[str] = Field(
        default=None,
        description="Year filter, format 'YYYY' or 'YYYY-YYYY' (e.g. '2019-2026'). Applies to all sources.",
        pattern=r"^\d{4}(-\d{4})?$",
    )
    found_via: Optional[str] = Field(
        default=None,
        description="Optional tag stamped onto every returned paper's 'found_via' field (e.g. 'Q1') for provenance.",
        max_length=40,
    )

    @field_validator("sources")
    @classmethod
    def _nonempty_sources(cls, v: List[Source]) -> List[Source]:
        if not v:
            raise ValueError("At least one source must be specified.")
        # De-dupe while preserving order.
        seen, out = set(), []
        for s in v:
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out


class DedupInput(BaseModel):
    """Input for scholar_dedup."""

    model_config = ConfigDict(extra="forbid")

    papers: List[Dict[str, Any]] = Field(
        ...,
        description="Flat list of normalized paper objects (as returned by scholar_search across multiple calls). Combine all batches into one list.",
        min_length=1,
    )
    assign_ids: bool = Field(
        default=True,
        description="If true, assign sequential 'id' fields (paper_001, paper_002, ...) to the deduped output.",
    )
    title_threshold: float = Field(
        default=0.85,
        description="Jaccard word-overlap threshold for fuzzy title dedup of DOI-less papers.",
        ge=0.5,
        le=1.0,
    )


class SnowballInput(BaseModel):
    """Input for scholar_snowball."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    paper_id: str = Field(
        ...,
        description="Seed paper identifier: a Semantic Scholar paperId, 'DOI:10.xxx/yyy', or 'ARXIV:2401.12345'.",
        min_length=3,
        max_length=200,
    )
    limit: int = Field(default=50, description="Max references to return", ge=1, le=100)


class RecommendInput(BaseModel):
    """Input for scholar_recommend."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    paper_ids: List[str] = Field(
        ..., description="Positive seed papers: Semantic Scholar paperIds or 'DOI:10.xxx/yyy' / 'ARXIV:2401.12345'.",
        min_length=1, max_length=50,
    )
    limit: int = Field(default=50, description="Max recommendations to return", ge=1, le=500)


class RecoverDoisInput(BaseModel):
    """Input for scholar_recover_dois."""

    model_config = ConfigDict(extra="forbid")

    papers: List[Dict[str, Any]] = Field(
        ...,
        description="Papers (some missing DOIs). Only those with doi==null and a title or arxiv_id are looked up; the rest pass through unchanged.",
        min_length=1,
    )


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------


_KEY_PARAM = re.compile(r"(?i)((?:api_?key|apikey|insttoken|token)=)[^&\s\"']+")


def _err(e: Exception) -> str:
    """The error as one line for `source_errors`, with any credential in a URL replaced by REDACTED."""
    return _KEY_PARAM.sub(r"\1REDACTED", _err_text(e))


def _err_text(e: Exception) -> str:
    if isinstance(e, _MissingKeyError):
        return f"Skipped: {e}"
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        body = (e.response.text or "")[:200]
        if code == 429:
            return "Error: Rate limit exceeded (429). Wait ~30s and retry, or reduce limit."
        if code == 404:
            return "Error: Not found (404). Check the identifier."
        if code == 403:
            # IEEE returns 403 'Developer Inactive' for keys awaiting activation.
            if "inactive" in body.lower():
                return ("Error: IEEE key not yet active (403 'Developer Inactive'). "
                        "New IEEE keys require activation by IEEE before use — try again "
                        "in a few days or check your developer.ieee.org dashboard.")
            return f"Error: Forbidden (403). Check API key / entitlements. {body}".strip()
        if code == 401:
            return f"Error: Unauthorized (401). API key invalid or missing. {body}".strip()
        return f"Error: API request failed with status {code}. {body}".strip()
    if isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out. Try again or reduce limit."
    return f"Error: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="scholar_search",
    annotations={
        "title": "Search Academic Databases",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def scholar_search(params: SearchInput) -> str:
    """Search one query across one or more academic databases and return normalized papers.

    Queries the selected sources concurrently, normalizes every record into a single
    schema, reconstructs OpenAlex inverted-index abstracts, parses PubMed XML, and
    merges records that the SAME call found in multiple sources (dedup across calls is a
    separate step — use scholar_dedup for that). Call it once per (query, source-set) and
    collect the batches, then dedup.

    Args:
        params (SearchInput):
            - query (str): the search phrase
            - sources (List[Source]): any of 'semantic_scholar','openalex','pubmed',
              'arxiv','scopus','ieee','wos' (scopus/ieee/wos need API keys; default is
              semantic_scholar+openalex+scopus)
            - limit (int): max results per source (1-100, default 25)
            - year (str|None): 'YYYY' or 'YYYY-YYYY'
            - found_via (str|None): provenance tag stamped onto each paper

    Returns:
        str: JSON with schema:
        {
          "query": str,
          "sources_queried": [str],                    # sources actually queried
          "sources_skipped": {source: reason},         # keyed sources with no API key set
          "source_errors": {source: error_string},     # sources that errored (incl. inactive keys)
          "count": int,                                 # papers after intra-call merge
          "papers": [ {                                 # normalized paper objects
              "title","authors":[str],"year","journal","doi","url","abstract",
              "citation_count","sources_found_in":[str],
              "semantic_scholar_id","openalex_id","pubmed_id","arxiv_id","scopus_id","ieee_id","wos_id",
              "found_via"                               # present iff found_via was given
          } ]
        }

    Examples:
        - "search Semantic Scholar + PubMed for closed-loop DBS, 2019-2026" ->
          sources=['semantic_scholar','pubmed'], year='2019-2026'
        - "search Scopus + IEEE for BCI decoders" -> sources=['scopus','ieee']
        - Don't use to dedup across multiple queries (use scholar_dedup).
    """
    try:
        tasks = [_ADAPTERS[s](params.query, params.limit, params.year) for s in params.sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_papers: List[Dict[str, Any]] = []
        source_errors: Dict[str, str] = {}
        sources_skipped: Dict[str, str] = {}
        totals: Dict[str, Optional[int]] = {}
        returned: Dict[str, int] = {}
        for src, res in zip(params.sources, results):
            if isinstance(res, _MissingKeyError):
                sources_skipped[src.value] = str(res)
            elif isinstance(res, Exception):
                source_errors[src.value] = _err(res)
            else:
                all_papers.extend(res)
                totals[src.value] = getattr(res, "total", None)
                returned[src.value] = len(res)

        merged = _dedup(all_papers)
        if params.found_via:
            for p in merged:
                p["found_via"] = params.found_via

        active_sources = [
            s.value for s in params.sources
            if s.value not in sources_skipped
        ]
        payload = {
            "query": params.query,
            "sources_queried": active_sources,
            "sources_skipped": sources_skipped,   # keyed sources with no API key configured
            "source_errors": source_errors,       # sources that errored (incl. inactive keys)
            "count": len(merged),
            "totals": totals,      # records the database reports for the query (None = not reported)
            "returned": returned,  # records it sent back, before the intra-call merge
            "papers": merged,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001 - top-level guard returns a clean message
        return _err(e)


@mcp.tool(
    name="scholar_dedup",
    annotations={
        "title": "Deduplicate Paper Collection",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def scholar_dedup(params: DedupInput) -> str:
    """Merge many search batches into one deduplicated collection (DOI + fuzzy title).

    Pure local computation, no network. Dedups by normalized DOI first, then by fuzzy
    title (Jaccard word overlap >= threshold AND same first-author last name AND year
    within +-1). Merges duplicates by keeping the richest metadata, the max citation
    count, the longest abstract, and the union of sources_found_in. Optionally assigns
    stable sequential ids. Feed it everything scholar_search returned across all your
    queries and sources.

    Args:
        params (DedupInput):
            - papers (List[dict]): combined flat list of normalized papers
            - assign_ids (bool): assign paper_001, paper_002, ... (default true)
            - title_threshold (float): fuzzy-title Jaccard cutoff (default 0.85)

    Returns:
        str: JSON with schema:
        {
          "input_count": int,
          "output_count": int,
          "duplicates_removed": int,
          "doi_coverage": "N/M (P%)",
          "papers": [ <normalized paper, with 'id' if assign_ids> ]
        }
    """
    try:
        merged = _dedup(params.papers, title_threshold=params.title_threshold)
        if params.assign_ids:
            for i, p in enumerate(merged, start=1):
                p["id"] = f"paper_{i:03d}"
                # Keep id first for readability when serialized.
                merged[i - 1] = {"id": p.pop("id"), **p}
        with_doi = sum(1 for p in merged if p.get("doi"))
        total = len(merged)
        pct = round(100 * with_doi / total) if total else 0
        payload = {
            "input_count": len(params.papers),
            "output_count": total,
            "duplicates_removed": len(params.papers) - total,
            "doi_coverage": f"{with_doi}/{total} ({pct}%)",
            "papers": merged,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        return _err(e)


@mcp.tool(
    name="scholar_snowball",
    annotations={
        "title": "Fetch Paper References (Snowball)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def scholar_snowball(params: SnowballInput) -> str:
    """Fetch the reference list of a seed paper via Semantic Scholar (backward snowball).

    Given a seed identifier, returns the papers it cites, normalized to the same schema
    as scholar_search. Use this on your top-cited seeds to catch foundational work that
    keyword queries missed. The caller decides which returned references are relevant and
    should be added (this tool does not filter).

    Args:
        params (SnowballInput):
            - paper_id (str): 'DOI:10.x/y', 'ARXIV:2401.12345', or a Semantic Scholar paperId
            - limit (int): max references (1-100, default 50)

    Returns:
        str: JSON with schema:
        {
          "seed": str,
          "count": int,
          "references": [ <normalized paper, found_via='snowball'> ]
        }
    """
    try:
        fields = "title,authors,year,abstract,externalIds,citationCount,journal,url"
        url = f"{SEMANTIC_SCHOLAR_BASE}/paper/{params.paper_id}/references"
        resp = await _get(url, params={"fields": fields, "limit": params.limit}, headers=_s2_headers())
        refs: List[Dict[str, Any]] = []
        for row in resp.json().get("data", []) or []:
            cited = row.get("citedPaper") or {}
            if not cited:
                continue
            p = _empty_paper()
            ext = cited.get("externalIds") or {}
            p["title"] = cited.get("title")
            p["authors"] = [a.get("name") for a in (cited.get("authors") or []) if a.get("name")]
            p["year"] = cited.get("year")
            p["journal"] = (cited.get("journal") or {}).get("name")
            p["doi"] = _normalize_doi(ext.get("DOI"))
            p["url"] = cited.get("url")
            p["abstract"] = cited.get("abstract")
            p["citation_count"] = cited.get("citationCount")
            p["semantic_scholar_id"] = cited.get("paperId")
            p["arxiv_id"] = ext.get("ArXiv")
            p["pubmed_id"] = str(ext["PubMed"]) if ext.get("PubMed") else None
            p["sources_found_in"] = [Source.SEMANTIC_SCHOLAR.value]
            p["found_via"] = "snowball"
            refs.append(p)
        return json.dumps(
            {"seed": params.paper_id, "count": len(refs), "references": refs},
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:  # noqa: BLE001
        return _err(e)


@mcp.tool(
    name="scholar_recover_dois",
    annotations={
        "title": "Recover Missing DOIs",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def scholar_recover_dois(params: RecoverDoisInput) -> str:
    """Fill missing DOIs by looking papers up on Semantic Scholar (by arXiv id, else title).

    Papers that already have a DOI pass through untouched. For each paper missing a DOI,
    tries ARXIV:{arxiv_id} first (exact), then a title search. Returns the same list with
    DOIs filled where found, plus a count of how many were recovered.

    Args:
        params (RecoverDoisInput):
            - papers (List[dict]): normalized papers, some with doi==null

    Returns:
        str: JSON with schema:
        {
          "input_count": int,
          "recovered": int,
          "doi_coverage": "N/M (P%)",
          "papers": [ <same papers, DOIs filled where found> ]
        }
    """
    try:
        papers = [dict(p) for p in params.papers]
        recovered = 0
        for p in papers:
            if _normalize_doi(p.get("doi")):
                continue
            doi = None
            if p.get("arxiv_id"):
                try:
                    resp = await _get(
                        f"{SEMANTIC_SCHOLAR_BASE}/paper/ARXIV:{p['arxiv_id']}",
                        params={"fields": "externalIds"},
                        headers=_s2_headers(),
                    )
                    doi = _normalize_doi((resp.json().get("externalIds") or {}).get("DOI"))
                except Exception:  # noqa: BLE001 - fall through to title search
                    doi = None
            if not doi and p.get("title"):
                try:
                    resp = await _get(
                        f"{SEMANTIC_SCHOLAR_BASE}/paper/search",
                        params={"query": p["title"], "fields": "externalIds,title", "limit": 1},
                        headers=_s2_headers(),
                    )
                    hits = resp.json().get("data", []) or []
                    if hits:
                        doi = _normalize_doi((hits[0].get("externalIds") or {}).get("DOI"))
                except Exception:  # noqa: BLE001
                    doi = None
            if doi:
                p["doi"] = doi
                recovered += 1
        with_doi = sum(1 for p in papers if p.get("doi"))
        total = len(papers)
        pct = round(100 * with_doi / total) if total else 0
        return json.dumps(
            {
                "input_count": total,
                "recovered": recovered,
                "doi_coverage": f"{with_doi}/{total} ({pct}%)",
                "papers": papers,
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:  # noqa: BLE001
        return _err(e)


@mcp.tool(
    name="scholar_recommend",
    annotations={"title": "Semantic Scholar recommendations (embedding neighbours of seed papers)",
                 "readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
)
async def scholar_recommend(params: RecommendInput) -> str:
    """Papers Semantic Scholar's embedding model (SPECTER) places nearest to the seed papers - the dense-retrieval
    route that finds papers written in other words. Needs SEMANTIC_SCHOLAR_API_KEY in
    practice (keyless calls are rate-limited most days). Results change over time: record them.

    Returns JSON {"seeds": [...], "count": int, "papers": [<normalized paper, found_via='dense'>]}."""
    try:
        url = f"{SEMANTIC_SCHOLAR_RECS_BASE}/papers"
        fields = "title,authors,year,abstract,externalIds,citationCount,journal,url"
        body = {"positivePaperIds": params.paper_ids, "negativePaperIds": []}
        resp = await _s2_post(url, {"fields": fields, "limit": params.limit}, body)
        out = []
        for item in resp.json().get("recommendedPapers") or []:
            p = _empty_paper()
            ext = item.get("externalIds") or {}
            p["title"] = item.get("title")
            p["authors"] = [a.get("name") for a in (item.get("authors") or []) if a.get("name")]
            p["year"] = item.get("year")
            p["journal"] = (item.get("journal") or {}).get("name")
            p["doi"] = _normalize_doi(ext.get("DOI"))
            p["url"] = item.get("url")
            p["abstract"] = item.get("abstract")
            p["citation_count"] = item.get("citationCount")
            p["semantic_scholar_id"] = item.get("paperId")
            p["arxiv_id"] = ext.get("ArXiv")
            p["pubmed_id"] = str(ext["PubMed"]) if ext.get("PubMed") else None
            p["sources_found_in"] = [Source.SEMANTIC_SCHOLAR.value]
            p["found_via"] = "dense"
            out.append(p)
        return json.dumps({"seeds": params.paper_ids, "count": len(out), "papers": out}, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        return _err(e)


class AbstractsInput(BaseModel):
    """Input for scholar_abstracts."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    paper_ids: List[str] = Field(
        ..., description="Semantic Scholar paperIds or 'DOI:10.xxx/yyy' / 'ARXIV:2401.12345'.", min_length=1, max_length=500,
    )


@mcp.tool(
    name="scholar_abstracts",
    annotations={"title": "Abstracts by identifier (Semantic Scholar batch)", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def scholar_abstracts(params: AbstractsInput) -> str:
    """The abstract Semantic Scholar holds for each identifier, in one batch request (up to 500) - screening fills the
    records that came without one. Paced and backed off like every S2 call; a publisher whose abstracts S2 may not
    show simply has none.

    Returns JSON {"abstracts": {input id: text}, "missing": [input id], "count": int}."""
    try:
        resp = await _s2_post(f"{SEMANTIC_SCHOLAR_BASE}/paper/batch", {"fields": "abstract"}, {"ids": params.paper_ids})
        rows = resp.json() or []
        found, missing = {}, []
        for pid, row in zip(params.paper_ids, rows):
            text = (row or {}).get("abstract")
            if text and str(text).strip():
                found[pid] = str(text).strip()
            else:
                missing.append(pid)
        missing += params.paper_ids[len(rows):]
        return json.dumps({"abstracts": found, "missing": missing, "count": len(found)}, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        return _err(e)


class VenuesInput(BaseModel):
    """Input for scholar_venues."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    issns: List[str] = Field(..., description="Print or electronic ISSNs, e.g. '1053-8119'", min_length=1, max_length=25)


@mcp.tool(
    name="scholar_venues",
    annotations={"title": "Venue metrics from Scopus (SNIP, SJR)", "readOnlyHint": True, "destructiveHint": False,
                 "idempotentHint": True, "openWorldHint": True},
)
async def scholar_venues(params: VenuesInput) -> str:
    """SNIP (source-normalised impact per paper: corrects for the field's citation habits) and SJR for up to 25
    venues, from the Elsevier Serial Title API (the venue part of screening's impact axis). Needs
    SCOPUS_API_KEY. Returns {"venues": {issn: {title, issn, eissn, snip, sjr}}, "missing": [issn]} - every input ISSN
    that matched a venue, by print or electronic ISSN."""
    try:
        if not SCOPUS_API_KEY:
            raise _MissingKeyError("SCOPUS_API_KEY not set")
        headers = {"X-ELS-APIKey": SCOPUS_API_KEY, "Accept": "application/json"}
        resp = await _get(f"{SCOPUS_BASE.rsplit('/content/', 1)[0]}/content/serial/title",
                          params={"issn": ",".join(params.issns), "view": "STANDARD"}, headers=headers)
        entries = (resp.json().get("serial-metadata-response") or {}).get("entry") or []
        venues: Dict[str, Any] = {}

        def first(lst_key, item_key, e):
            v = ((e.get(lst_key) or {}).get(item_key) or [{}])
            v = v[0] if isinstance(v, list) and v else (v if isinstance(v, dict) else {})
            try:
                return float(v.get("$"))
            except (TypeError, ValueError):
                return None
        for e in entries:
            rec = {"title": e.get("dc:title"), "issn": e.get("prism:issn"), "eissn": e.get("prism:eIssn"),
                   "snip": first("SNIPList", "SNIP", e), "sjr": first("SJRList", "SJR", e)}
            for want in params.issns:
                w = want.replace("-", "").upper()
                if w in {str(rec["issn"] or "").replace("-", "").upper(), str(rec["eissn"] or "").replace("-", "").upper()}:
                    venues[want] = rec
        return json.dumps({"venues": venues, "missing": [i for i in params.issns if i not in venues]}, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        return _err(e)


if __name__ == "__main__":
    mcp.run()
