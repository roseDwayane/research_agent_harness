"""Open-access full-text sources (plan §4.3 fallback chain):

    arXiv HTML → arXiv PDF → PMC XML → Unpaywall OA PDF → publisher landing page (OA list)

Every attempt is logged; the first success wins.  PDFs are stored by sha256 in
``.cache/pdf`` so replay never re-downloads.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ...cache import Cache
from ...utils import sha256_bytes
from ..base import HttpClient
from .extract import Extraction, html_to_markdown, pdf_text_to_markdown, pdf_to_text, pmc_xml_to_markdown

OA_PUBLISHER_HOSTS = ("journals.plos.org", "frontiersin.org", "mdpi.com", "nature.com/ncomms", "nature.com/srep", "biomedcentral.com", "elifesciences.org", "peerj.com", "biorxiv.org", "medrxiv.org")


@dataclass
class Attempt:
    level: str
    status: str  # ok | http-404 | skipped | error:<msg> | too-short
    detail: str = ""


@dataclass
class FulltextResult:
    access_level: str = "abstract-only"  # full-text-html | full-text-pdf | partial-text-html | abstract-only
    source: str = "abstract-only"
    extraction: Extraction | None = None
    attempts: list[Attempt] = field(default_factory=list)
    pdf_sha256: str | None = None
    pmc_id: str | None = None


class FulltextFetcher:
    def __init__(self, http: HttpClient, cache: Cache, unpaywall_email: str | None = None, ncbi_api_key: str | None = None, min_chars: int = 8000, min_sections: int = 4):
        self.http = http
        self.cache = cache
        self.unpaywall_email = unpaywall_email
        self.ncbi_api_key = ncbi_api_key
        self.min_chars = min_chars
        self.min_sections = min_sections
        http.limiter.intervals.setdefault("arxiv.org", 3.1)
        http.limiter.intervals.setdefault("export.arxiv.org", 3.1)

    # ------------------------------------------------------------------ #
    def fetch(self, paper: dict[str, Any], prefer_published: bool = True) -> FulltextResult:
        res = FulltextResult()
        chain = []
        arxiv_id, doi, pmid, pmc = paper.get("arxiv_id"), paper.get("doi"), paper.get("pubmed_id"), paper.get("pmc_id")
        published_oa = bool(doi and prefer_published and any(h in (paper.get("url") or "") for h in OA_PUBLISHER_HOSTS))
        if published_oa:
            chain.append(("oa-publisher", lambda: self._publisher_html(doi)))
        if arxiv_id:
            chain.append(("arxiv-html", lambda: self._arxiv_html(arxiv_id)))
            chain.append(("arxiv-pdf", lambda: self._pdf(f"https://arxiv.org/pdf/{arxiv_id}")))
        chain.append(("pmc", lambda: self._pmc(pmc, pmid, doi, res)))
        if doi:
            chain.append(("unpaywall", lambda: self._unpaywall(doi)))
            if not published_oa:
                chain.append(("oa-publisher", lambda: self._publisher_html(doi)))
        for level, fn in chain:
            try:
                ext, access, src, pdf_sha = fn()
            except Exception as e:  # noqa: BLE001
                res.attempts.append(Attempt(level, f"error:{type(e).__name__}", str(e)[:200]))
                continue
            if ext is None:
                res.attempts.append(Attempt(level, "not-available", src))
                continue
            ext.finalize()
            if ext.char_count < 1500:
                res.attempts.append(Attempt(level, "too-short", f"{ext.char_count} chars"))
                continue
            res.attempts.append(Attempt(level, "ok", f"{ext.char_count} chars, {ext.section_count} sections"))
            res.extraction = ext
            res.access_level = access
            res.source = src
            res.pdf_sha256 = pdf_sha
            if ext.char_count < self.min_chars or ext.section_count < self.min_sections:
                ext.notes.append(f"quality check: {ext.char_count} chars / {ext.section_count} sections below expectation ({self.min_chars}/{self.min_sections})")
                if access == "full-text-html":
                    res.access_level = "partial-text-html"
            return res
        return res

    # ------------------------------------------------------------------ #
    def _arxiv_html(self, arxiv_id: str):
        r = self.http.get(f"https://arxiv.org/html/{arxiv_id}")
        if r.status == 404 or not r.ok or not r.text:
            return None, "", f"HTTP {r.status}", None
        md = html_to_markdown(r.text)
        return Extraction(text=md, method="arxiv-html"), "full-text-html", f"arXiv HTML ({arxiv_id})", None

    def _pdf(self, url: str):
        r = self.http.get(url, binary=True)
        if not r.ok or not r.body_bytes:
            return None, "", f"HTTP {r.status}", None
        data = r.body_bytes
        if not data.startswith(b"%PDF"):
            return None, "", "not a PDF", None
        sha = self.cache.put_blob(data)
        raw, method = pdf_to_text(data)
        md = pdf_text_to_markdown(raw)
        ext = Extraction(text=md, method=method, sha256=sha)
        return ext, "full-text-pdf", f"PDF ({url})", sha

    def _pmc(self, pmc: str | None, pmid: str | None, doi: str | None, res: FulltextResult):
        if not pmc:
            ident = pmid or doi
            if not ident:
                return None, "", "no PMID/DOI", None
            r = self.http.get("https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/", params={"ids": ident, "format": "json", "tool": "scholar-research", "email": self.unpaywall_email})
            if r.ok:
                recs = r.json().get("records") or []
                pmc = (recs[0] or {}).get("pmcid") if recs else None
        if not pmc:
            return None, "", "not in PMC", None
        res.pmc_id = pmc
        r = self.http.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi", params={"db": "pmc", "id": pmc.replace("PMC", ""), "retmode": "xml", "api_key": self.ncbi_api_key})
        if not r.ok or not r.text or "<body" not in r.text:
            return None, "", f"PMC XML unavailable ({r.status})", None
        md = pmc_xml_to_markdown(r.text)
        return Extraction(text=md, method="pmc-xml"), "full-text-html", f"PMC ({pmc})", None

    def _unpaywall(self, doi: str):
        if not self.unpaywall_email:
            return None, "", "UNPAYWALL_EMAIL not set", None
        r = self.http.get(f"https://api.unpaywall.org/v2/{doi}", params={"email": self.unpaywall_email})
        if not r.ok:
            return None, "", f"HTTP {r.status}", None
        loc = r.json().get("best_oa_location") or {}
        pdf_url = loc.get("url_for_pdf")
        if not pdf_url:
            return None, "", "no OA PDF", None
        return self._pdf(pdf_url)

    def _publisher_html(self, doi: str):
        r = self.http.get(f"https://doi.org/{doi}")
        if not r.ok or not r.text:
            return None, "", f"HTTP {r.status}", None
        if "application/pdf" in (r.headers.get("content-type") or ""):
            return None, "", "landing page is a PDF (handled by unpaywall path)", None
        md = html_to_markdown(r.text)
        low = md.lower()
        if not any(k in low for k in ("## introduction", "## methods", "## results", "## discussion", "# introduction", "# methods")):
            return None, "", "paywall/abstract stub", None
        return Extraction(text=md, method="html-generic"), "full-text-html", f"publisher ({r.url})", None
