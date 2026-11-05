#!/usr/bin/env python3
"""Tests for the PDF sources of mcp/paper_pdf_mcp (A6.d's download), offline: every request goes to a mock transport.

  python3 scripts/tests/fulltext/test_pdf_sources.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import httpx
except ImportError:                                  # the server's own dependency; without it there is nothing to test
    httpx = None

SERVER = Path(__file__).resolve().parents[3] / "mcp" / "paper_pdf_mcp"
PDF = b"%PDF-1.5" + b"x" * 2048
DOI = "10.3389/fnins.2018.00097"


def answer(request) -> "httpx.Response":
    u = str(request.url)
    if u.startswith("https://api.unpaywall.org/"):
        return httpx.Response(422, json={"message": "Please use your own email address in API calls."})
    if u.startswith("https://api.openalex.org/works/doi:"):
        return httpx.Response(200, json={"ids": {"pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/5835235"},
                                         "locations": [{"pdf_url": "https://publisher.example/blocked.pdf"}]})
    if "list-type=2" in u:
        return httpx.Response(200, text="<Key>metadata/PMC5835235.1.json</Key><Key>metadata/PMC5835235.2.json</Key>")
    if u.endswith("/metadata/PMC5835235.2.json"):
        return httpx.Response(200, json={"pdf_url": "s3://pmc-oa-opendata/PMC5835235.2/PMC5835235.2.pdf?md5=0"})
    if u == "https://pmc-oa-opendata.s3.amazonaws.com/PMC5835235.2/PMC5835235.2.pdf":
        return httpx.Response(200, content=PDF)
    if u.startswith("https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/"):
        return httpx.Response(200, json={"records": []})
    return httpx.Response(403, text="<html>forbidden</html>")


@unittest.skipIf(httpx is None, "httpx is not installed")
class PdfSources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(SERVER))
        try:
            import server
        except ImportError as e:                         # the server's `mcp` package lives in the skill's venv
            raise unittest.SkipTest(f"paper_pdf_mcp cannot load: {e}")
        cls.S = server

    def setUp(self):
        self.S._PMC_PDF.clear()
        self.S.UNPAYWALL_REFUSED = False

    def run_one(self, row):
        async def go():
            async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as c:
                return await self.S._download_one(c, row, tempfile.mkdtemp(), True)
        return asyncio.run(go())

    def test_an_open_paper_is_found_without_unpaywall(self):
        """Unpaywall refuses the placeholder email; OpenAlex's PMCID leads to the PMC Cloud Service's latest PDF."""
        r = self.run_one({"citation_key": "k", "doi": DOI})
        self.assertEqual((r["status"], r["source"]), ("downloaded", "openalex+pmc"))
        self.assertTrue(r["pdf_url"].endswith("/PMC5835235.2/PMC5835235.2.pdf"))
        self.assertTrue(self.S.UNPAYWALL_REFUSED)

    def test_a_failure_names_the_refused_email(self):
        self.S._PMC_PDF["PMC5835235"] = []                     # this time PMC has nothing either
        r = self.run_one({"citation_key": "k", "doi": DOI})
        self.assertEqual(r["status"], "failed")
        self.assertIn("openalex: HTTP 403", r["reason"])
        self.assertIn("set PAPER_PDF_UNPAYWALL_EMAIL", r["reason"])

    def test_the_doi_prefix_patterns_run_without_a_lookup(self):
        out = asyncio.run(self.S._candidates_from_doi_prefix(None, DOI))
        self.assertIn("https://www.frontiersin.org/articles/10.3389/fnins.2018.00097/pdf", [c["url"] for c in out])
        self.assertEqual(self.S._pmcid_from_url("https://www.ncbi.nlm.nih.gov/pmc/articles/5835235"), "PMC5835235")


if __name__ == "__main__":
    unittest.main(verbosity=1)
